"""
LiteLLM-based chat provider for broad model support.

This provider uses LiteLLM as a backend to support 100+ LLM providers
including OpenAI, Anthropic, Google, Cohere, Replicate, and many more.
"""

from __future__ import annotations

import asyncio
import copy
import os
import time
import uuid
import warnings
from collections.abc import AsyncIterator, Sequence
from typing import Any, Self

from loguru import logger

# ---------------------------------------------------------------------------
# Module-level rate control (shared across ALL LiteLLMProvider instances)
# ---------------------------------------------------------------------------
# Caps concurrent in-flight API calls to prevent quota exhaustion when
# multiple subagents fire requests simultaneously.
MAX_CONCURRENT_API_CALLS = 4
MIN_REQUEST_INTERVAL_S = 0.5  # minimum gap between consecutive requests

_api_semaphore: asyncio.Semaphore | None = None
_rate_lock: asyncio.Lock | None = None
_last_request_time: float = 0.0


def _get_rate_controls() -> tuple[asyncio.Semaphore, asyncio.Lock]:
    """Lazily initialise rate-control primitives (must be called inside event loop)."""
    global _api_semaphore, _rate_lock
    if _api_semaphore is None:
        _api_semaphore = asyncio.Semaphore(MAX_CONCURRENT_API_CALLS)
    if _rate_lock is None:
        _rate_lock = asyncio.Lock()
    return _api_semaphore, _rate_lock


# Suppress Pydantic serialization warnings from LiteLLM internals.
# These occur when LiteLLM serializes responses from newer model APIs
# (e.g. Gemini 3 Flash Preview) that have different field counts than
# LiteLLM's schema expects. The warnings are harmless but confuse users.
warnings.filterwarnings("ignore", message=r"Pydantic serializer warnings")
warnings.filterwarnings("ignore", message=r"PydanticSerializationUnexpectedValue")

try:
    import litellm
    from litellm import acompletion, completion
    from litellm.types.utils import Choices, ModelResponse
    from litellm.types.utils import Message as LiteLLMMessage

    LITELLM_AVAILABLE = True

    # Monkey-patch LiteLLM to fix global location URL construction
    # Bug: LiteLLM uses {location}-aiplatform.googleapis.com but for 'global'
    # it should be aiplatform.googleapis.com (without location prefix)
    try:
        from litellm.llms.vertex_ai import common_utils as vertex_common_utils

        _original_get_vertex_url = vertex_common_utils._get_vertex_url

        def _patched_get_vertex_url(
            mode,
            model: str,
            stream,
            vertex_project,
            vertex_location,
            vertex_api_version,
        ):
            """Patched version that correctly handles 'global' location."""
            # Handle global location specially — LiteLLM generates
            # 'global-aiplatform.googleapis.com' which doesn't exist.
            if vertex_location == "global":
                # Determine publisher from model name
                publisher = "google"
                if "kimi" in model:
                    publisher = "kimi"

                endpoint = "generateContent"
                if stream is True:
                    endpoint = "streamGenerateContent"
                    url = f"https://aiplatform.googleapis.com/{vertex_api_version}/projects/{vertex_project}/locations/global/publishers/{publisher}/models/{model}:{endpoint}?alt=sse"
                else:
                    url = f"https://aiplatform.googleapis.com/{vertex_api_version}/projects/{vertex_project}/locations/global/publishers/{publisher}/models/{model}:{endpoint}"
                return url, endpoint

            # For non-global locations, use original function
            return _original_get_vertex_url(
                mode, model, stream, vertex_project, vertex_location, vertex_api_version
            )

        vertex_common_utils._get_vertex_url = _patched_get_vertex_url
        logger.info("Applied LiteLLM patch for Vertex AI global location support")
    except Exception as e:
        logger.warning(f"Failed to apply LiteLLM global location patch: {e}")

    # Patch Bedrock configs to enable tool use for all models.
    # LiteLLM blocks tools for some Bedrock models, but the Converse API
    # actually supports them (verified via boto3 directly).

    # Step 1: Register models so supports_function_calling returns True
    _BEDROCK_TOOL_MODELS = [
        "moonshotai.kimi-k2.5",
        "moonshot.kimi-k2-thinking",
        "qwen.qwen3-coder-next",
        "qwen.qwen3-next-80b-a3b",
        "qwen.qwen3-32b-v1:0",
        "deepseek.v3.2",
        "minimax.minimax-m2",
        "minimax.minimax-m2.1",
        "zai.glm-4.7",
        "zai.glm-4.7-flash",
        "nvidia.nemotron-nano-3-30b",
        "openai.gpt-oss-120b-1:0",
        "openai.gpt-oss-20b-1:0",
        "mistral.mistral-large-3-675b-instruct",
        "mistral.devstral-2-123b",
        "mistral.ministral-3-14b-instruct",
        "mistral.ministral-3-8b-instruct",
    ]
    try:
        for _m in _BEDROCK_TOOL_MODELS:
            litellm.register_model(
                {
                    f"bedrock/{_m}": {
                        "max_tokens": 131072,
                        "input_cost_per_token": 0.0000005,
                        "output_cost_per_token": 0.000002,
                        "litellm_provider": "bedrock",
                        "mode": "chat",
                        "supports_function_calling": True,
                    }
                }
            )
        logger.info("Registered Bedrock models for tool use support")
    except Exception as e:
        logger.warning(f"Failed to register Bedrock tool models: {e}")

    # Step 2: Patch config routing to force Converse API for models that
    # default to InvokeModel (which doesn't support tools).
    try:
        from litellm.llms.bedrock.common_utils import (
            get_bedrock_chat_config as _orig_get_bedrock_chat_config,
        )

        # Try multiple import paths (changed across LiteLLM versions)
        _ConverseConfig = None
        for _mod_path, _cls_name in [
            ("litellm.llms.bedrock.chat.converse_transformation", "AmazonConverseConfig"),
            ("litellm.llms.bedrock.chat.converse_handler", "AmazonConverseConfig"),
            ("litellm.llms.bedrock.chat.converse_handler", "BedrockConverseLLM"),
        ]:
            try:
                _mod = __import__(_mod_path, fromlist=[_cls_name])
                _ConverseConfig = getattr(_mod, _cls_name)
                logger.debug(f"Converse config class: {_mod_path}.{_cls_name}")
                break
            except (ImportError, AttributeError):
                continue

        _FORCE_CONVERSE_PREFIXES = ("qwen.", "deepseek.", "zai.", "nvidia.", "mistral.", "openai.")

        if _ConverseConfig is not None:

            def _patched_get_bedrock_chat_config(model: str):
                if any(model.startswith(p) for p in _FORCE_CONVERSE_PREFIXES):
                    return _ConverseConfig()
                return _orig_get_bedrock_chat_config(model)

            from litellm.llms.bedrock import common_utils as _bedrock_common

            _bedrock_common.get_bedrock_chat_config = _patched_get_bedrock_chat_config
            logger.info("Applied Bedrock Converse API routing patch")
        else:
            logger.warning("Could not find Converse config class — Bedrock routing patch skipped")
    except Exception as e:
        logger.warning(f"Failed to apply Bedrock routing patch: {e}")

except ImportError:
    logger.warning("LiteLLM not available - install with: pip install litellm")
    LITELLM_AVAILABLE = False

from aesc.provider.base import ChatProvider, StreamedMessage, ThinkingEffort
from aesc.provider.errors import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    ChatProviderError,
)
from aesc.provider.message import (
    ContentPart,
    Message,
    TextPart,
    ThinkPart,
    ToolCall,
    ToolCallPart,
)
from aesc.provider.tool import Tool
from aesc.provider.usage import TokenUsage


class LiteLLMProvider(ChatProvider):
    """
    LiteLLM-based chat provider supporting 100+ LLM providers.

    Supports models from:
    - OpenAI (gpt-4, gpt-3.5-turbo, etc.)
    - Anthropic (claude-3, claude-2, etc.)
    - Google (gemini-pro, palm, etc.)
    - Cohere (command, command-nightly, etc.)
    - Replicate (llama-2, codellama, etc.)
    - Hugging Face (any model)
    - And many more...

    Example:
        >>> provider = LiteLLMProvider(
        ...     model="gpt-4",
        ...     api_key="your-api-key"
        ... )
        >>> # Or use any other provider:
        >>> provider = LiteLLMProvider(
        ...     model="claude-3-sonnet-20240229",
        ...     api_key="your-anthropic-key"
        ... )
    """

    name = "litellm"

    def __init__(
        self,
        *,
        model: str,
        api_key: str | None = None,
        base_url: str | None = None,
        stream: bool = True,
        **kwargs: Any,
    ):
        if not LITELLM_AVAILABLE:
            raise ImportError(
                "LiteLLM is required but not available. Install with: pip install litellm"
            )

        self.model = model
        self.stream = stream
        self.api_key = api_key
        self.base_url = base_url
        self.kwargs = kwargs

        # Set up LiteLLM configuration
        if api_key:
            # LiteLLM automatically detects provider from model name
            # and uses appropriate environment variables
            if "gpt" in model.lower() or "openai" in model.lower():
                os.environ["OPENAI_API_KEY"] = api_key
            elif "claude" in model.lower() or "anthropic" in model.lower():
                os.environ["ANTHROPIC_API_KEY"] = api_key
            elif "gemini" in model.lower() or "google" in model.lower():
                os.environ["GOOGLE_API_KEY"] = api_key
            elif "command" in model.lower() or "cohere" in model.lower():
                os.environ["COHERE_API_KEY"] = api_key

        if base_url and not model.startswith("bedrock/"):
            # For custom endpoints (skip for Bedrock — boto3 handles endpoints)
            os.environ["OPENAI_API_BASE"] = base_url

        # Vertex AI uses GCP credentials - copy env vars to LiteLLM expected names
        if model.startswith("vertex_ai/"):
            # LiteLLM expects VERTEXAI_PROJECT and VERTEXAI_LOCATION
            if project := os.getenv("VERTEX_PROJECT"):
                os.environ["VERTEXAI_PROJECT"] = project
            if location := os.getenv("VERTEX_LOCATION"):
                os.environ["VERTEXAI_LOCATION"] = location
            logger.info(
                f"Vertex AI configured: project={os.getenv('VERTEXAI_PROJECT')}, "
                f"location={os.getenv('VERTEXAI_LOCATION')}"
            )

        self._reasoning_effort: str | None = None

    @property
    def model_name(self) -> str:
        return self.model

    async def generate(
        self,
        system_prompt: str,
        tools: Sequence[Tool],
        history: Sequence[Message],
    ) -> LiteLLMStreamedMessage:
        """Generate a response using LiteLLM.

        Rate-controlled: concurrent calls are capped at MAX_CONCURRENT_API_CALLS
        and requests are spaced at least MIN_REQUEST_INTERVAL_S apart to prevent
        quota exhaustion when multiple subagents run in parallel.
        """
        global _last_request_time

        messages: list[dict[str, Any]] = []

        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        # Convert messages to OpenAI format
        for msg in history:
            messages.append(msg.to_openai_format())

        # Prepare tool definitions
        tools_param = [_tool_to_openai(tool) for tool in tools] if tools else None

        # Build request kwargs
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": self.stream,
        }

        if tools_param:
            kwargs["tools"] = tools_param
            # Bedrock Converse API supports tools for all models, but LiteLLM
            # metadata doesn't list them as supported for newer models (Qwen,
            # DeepSeek, MiniMax). Force-allow the parameter.
            if self.model.startswith("bedrock/"):
                kwargs["allowed_openai_params"] = ["tools", "tool_choice"]

        if self.stream:
            kwargs["stream_options"] = {"include_usage": True}

        # Add reasoning_effort for compatible models
        if self._reasoning_effort:
            kwargs["reasoning_effort"] = self._reasoning_effort

        # Pass Vertex AI project/location explicitly — LiteLLM ignores
        # VERTEXAI_LOCATION env var for Anthropic models on Vertex AI.
        if self.model.startswith("vertex_ai/"):
            if project := os.getenv("VERTEXAI_PROJECT") or os.getenv("VERTEX_PROJECT"):
                kwargs["vertex_project"] = project
            if (
                location := os.getenv("VERTEXAI_LOCATION")
                or os.getenv("VERTEX_LOCATION")
                or os.getenv("GOOGLE_CLOUD_LOCATION")
            ):
                kwargs["vertex_location"] = location

        # Non-streaming generateContent to the Vertex *global* endpoint hangs when
        # tools are present (streaming works fine). Force streaming internally and
        # let LiteLLMStreamedMessage accumulate it for the non-streaming caller.
        if (
            not self.stream
            and tools_param
            and self.model.startswith("vertex_ai/")
            and kwargs.get("vertex_location") == "global"
        ):
            kwargs["stream"] = True
            kwargs["stream_options"] = {"include_usage": True}
            logger.debug("Vertex global+tools: forcing streaming (non-stream hangs)")

        # Add any additional kwargs
        kwargs.update(self.kwargs)

        # Acquire rate-control primitives
        semaphore, rate_lock = _get_rate_controls()

        # Retry logic for rate limit errors
        max_retries = 3
        retry_delay = 5  # Start with 5 seconds
        last_error = None

        for attempt in range(max_retries):
            # --- Rate control: cap concurrent calls + enforce minimum gap ---
            async with semaphore:
                async with rate_lock:
                    now = time.monotonic()
                    elapsed = now - _last_request_time
                    if elapsed < MIN_REQUEST_INTERVAL_S:
                        await asyncio.sleep(MIN_REQUEST_INTERVAL_S - elapsed)
                    _last_request_time = time.monotonic()

                try:
                    response = await acompletion(**kwargs)
                    return LiteLLMStreamedMessage(response, stream=kwargs["stream"])
                except Exception as e:
                    last_error = e
                    error_str = str(e).lower()

                    # Check if it's a rate limit error
                    is_rate_limit = any(
                        indicator in error_str
                        for indicator in [
                            "rate limit",
                            "ratelimit",
                            "429",
                            "resource_exhausted",
                            "quota exceeded",
                            "too many requests",
                        ]
                    )

                    if is_rate_limit and attempt < max_retries - 1:
                        # Exponential backoff: 5s → 15s → 45s
                        current_delay = retry_delay * (3**attempt)
                        logger.warning(
                            f"Rate limit hit (attempt {attempt + 1}/{max_retries}). "
                            f"Retrying in {current_delay}s..."
                        )
                        await asyncio.sleep(current_delay)
                        continue
                    else:
                        # Not a rate limit error, or out of retries
                        raise _convert_error(e) from e

        # If we get here, all retries failed
        raise _convert_error(last_error) from last_error

    def with_thinking(self, effort: ThinkingEffort) -> Self:
        """Return a new provider with the specified thinking effort."""
        new_self = copy.copy(self)
        # Map thinking effort to reasoning_effort for compatible models
        effort_map = {
            "off": None,
            "low": "low",
            "medium": "medium",
            "high": "high",
        }
        new_self._reasoning_effort = effort_map.get(effort)
        return new_self

    @property
    def model_parameters(self) -> dict[str, Any]:
        """Get model parameters for tracing/logging."""
        params: dict[str, Any] = {"model": self.model}
        if self.base_url:
            params["base_url"] = self.base_url
        if self._reasoning_effort:
            params["reasoning_effort"] = self._reasoning_effort
        return params


class LiteLLMStreamedMessage(StreamedMessage):
    """Streamed message from LiteLLM."""

    # Separator used by LiteLLM to embed thought signatures in tool call IDs
    THOUGHT_SIGNATURE_SEPARATOR = "__thought__"

    def __init__(
        self,
        response: Any,  # LiteLLM response object
        stream: bool = True,
    ):
        self._stream = stream
        if stream:
            self._iter = self._convert_stream_response(response)
        else:
            self._iter = self._convert_non_stream_response(response)
        self._id: str | None = None
        self._usage: dict | None = None

    def __aiter__(self) -> AsyncIterator[ContentPart]:
        return self

    async def __anext__(self) -> ContentPart:
        return await self._iter.__anext__()

    @property
    def id(self) -> str | None:
        return self._id

    @property
    def usage(self) -> TokenUsage | None:
        if self._usage:
            return TokenUsage(
                input_other=self._usage.get("prompt_tokens", 0),
                output=self._usage.get("completion_tokens", 0),
                input_cache_read=self._usage.get("cached_tokens", 0),
            )
        return None

    def _extract_thought_signature(self, tool_call: Any) -> str | None:
        """Extract thought_signature from a tool call.

        LiteLLM embeds thought signatures in two ways:
        1. In provider_specific_fields dict
        2. Encoded in the tool call ID using __thought__ separator
        """
        thought_signature = None

        # Method 1: Check provider_specific_fields
        if hasattr(tool_call, "provider_specific_fields") and tool_call.provider_specific_fields:
            thought_signature = tool_call.provider_specific_fields.get("thought_signature")

        # Method 2: Check if embedded in ID
        if not thought_signature and hasattr(tool_call, "id") and tool_call.id:
            if self.THOUGHT_SIGNATURE_SEPARATOR in tool_call.id:
                parts = tool_call.id.split(self.THOUGHT_SIGNATURE_SEPARATOR, 1)
                if len(parts) == 2:
                    thought_signature = parts[1]

        return thought_signature

    def _clean_tool_call_id(self, tool_call_id: str) -> str:
        """Remove thought signature from tool call ID if embedded."""
        if self.THOUGHT_SIGNATURE_SEPARATOR in tool_call_id:
            return tool_call_id.split(self.THOUGHT_SIGNATURE_SEPARATOR, 1)[0]
        return tool_call_id

    async def _convert_non_stream_response(
        self,
        response: ModelResponse,
    ) -> AsyncIterator[ContentPart]:
        """Convert a non-streaming response to message parts.

        Handles reasoning/thinking content from different providers:
        - reasoning_content: LiteLLM standardized field for thinking
        - thinking_blocks: Anthropic-specific structured thinking
        """
        self._id = response.id
        if hasattr(response, "usage") and response.usage:
            self._usage = {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
            }

        if response.choices and len(response.choices) > 0:
            choice = response.choices[0]
            message = choice.message

            # Check for reasoning_content (LiteLLM standardized thinking field)
            if hasattr(message, "reasoning_content") and message.reasoning_content:
                yield ThinkPart(think=message.reasoning_content)

            # Check for thinking_blocks (Anthropic format)
            if hasattr(message, "thinking_blocks") and message.thinking_blocks:
                for block in message.thinking_blocks:
                    if isinstance(block, dict) and block.get("thinking"):
                        yield ThinkPart(
                            think=block["thinking"],
                            encrypted=block.get("signature"),
                        )

            # Regular text content
            if hasattr(message, "content") and message.content:
                content = message.content
                # Filter malformed thinking that leaked into content
                if not self._is_malformed_thinking(content):
                    yield TextPart(text=content)
                else:
                    thinking = self._extract_thinking_from_malformed(content)
                    if thinking:
                        yield ThinkPart(think=thinking)

            if hasattr(message, "tool_calls") and message.tool_calls:
                for tool_call in message.tool_calls:
                    thought_sig = self._extract_thought_signature(tool_call)
                    tool_id = tool_call.id or str(uuid.uuid4())
                    clean_id = self._clean_tool_call_id(tool_id)

                    yield ToolCall(
                        id=clean_id,
                        function=ToolCall.FunctionBody(
                            name=tool_call.function.name,
                            arguments=tool_call.function.arguments or "",
                        ),
                        thought_signature=thought_sig,
                    )

    async def _convert_stream_response(
        self,
        response: Any,  # AsyncIterator from LiteLLM
    ) -> AsyncIterator[ContentPart]:
        """Convert a streaming response to message parts.

        Handles reasoning/thinking content from different providers:
        - reasoning_content: LiteLLM standardized field for thinking
        - provider_specific_fields.thinking_blocks: Anthropic thinking
        - Gemini thought patterns in content (fallback detection)
        """
        try:
            async for chunk in response:
                if hasattr(chunk, "id") and chunk.id:
                    self._id = chunk.id

                if hasattr(chunk, "usage") and chunk.usage:
                    self._usage = {
                        "prompt_tokens": chunk.usage.prompt_tokens,
                        "completion_tokens": chunk.usage.completion_tokens,
                    }

                if not hasattr(chunk, "choices") or not chunk.choices:
                    continue

                choice = chunk.choices[0]
                if not hasattr(choice, "delta"):
                    continue

                delta = choice.delta

                # Check for reasoning_content (LiteLLM standardized thinking field)
                # This is the proper way to get thinking from Claude, Gemini, DeepSeek, etc.
                if hasattr(delta, "reasoning_content") and delta.reasoning_content:
                    yield ThinkPart(think=delta.reasoning_content)

                # Check for thinking_blocks in provider_specific_fields (Anthropic format)
                if hasattr(delta, "provider_specific_fields") and delta.provider_specific_fields:
                    thinking_blocks = delta.provider_specific_fields.get("thinking_blocks", [])
                    for block in thinking_blocks:
                        if isinstance(block, dict) and block.get("thinking"):
                            yield ThinkPart(
                                think=block["thinking"],
                                encrypted=block.get("signature"),
                            )

                # Convert text content
                if hasattr(delta, "content") and delta.content:
                    content = delta.content
                    # Filter out malformed thinking markers that some providers emit
                    # (e.g., Gemini via LiteLLM sometimes emits raw Thought{} blocks)
                    if not self._is_malformed_thinking(content):
                        yield TextPart(text=content)
                    else:
                        # Extract the thinking content and yield as ThinkPart
                        thinking = self._extract_thinking_from_malformed(content)
                        if thinking:
                            yield ThinkPart(think=thinking)

                # Convert tool calls with thought_signature support
                if hasattr(delta, "tool_calls") and delta.tool_calls:
                    for tool_call in delta.tool_calls:
                        if hasattr(tool_call, "function") and tool_call.function:
                            if hasattr(tool_call.function, "name") and tool_call.function.name:
                                thought_sig = self._extract_thought_signature(tool_call)
                                tool_id = tool_call.id or str(uuid.uuid4())
                                clean_id = self._clean_tool_call_id(tool_id)

                                yield ToolCall(
                                    id=clean_id,
                                    function=ToolCall.FunctionBody(
                                        name=tool_call.function.name,
                                        arguments=tool_call.function.arguments or "",
                                    ),
                                    thought_signature=thought_sig,
                                )
                            elif (
                                hasattr(tool_call.function, "arguments")
                                and tool_call.function.arguments
                            ):
                                yield ToolCallPart(arguments_part=tool_call.function.arguments)

        except Exception as e:
            raise _convert_error(e) from e

    def _is_malformed_thinking(self, content: str) -> bool:
        """Detect malformed thinking markers from providers that don't properly structure thinking.

        Some providers (notably Gemini via LiteLLM) emit raw thinking in formats like:
        - call:default_api:Thought{thought:...}
        - Thought{thought:...}
        - <ctrl##> control characters

        These should be parsed as thinking, not displayed as text.
        """
        if not content:
            return False
        # Check for Gemini-style malformed thinking patterns
        malformed_patterns = [
            "call:default_api:Thought{",
            "Thought{thought:",
            "<ctrl46>",
            "<ctrl",
        ]
        return any(pattern in content for pattern in malformed_patterns)

    def _extract_thinking_from_malformed(self, content: str) -> str | None:
        """Extract actual thinking text from malformed thinking markers."""
        import re

        # Try to extract content from Thought{thought:...} pattern
        # Handle nested braces and control characters
        match = re.search(r"Thought\{thought:([^}]*(?:\{[^}]*\}[^}]*)*)\}", content, re.DOTALL)
        if match:
            thinking = match.group(1)
            # Clean up control characters
            thinking = re.sub(r"<ctrl\d+>", "", thinking)
            return thinking.strip() if thinking.strip() else None
        return None


def _tool_to_openai(tool: Tool) -> dict[str, Any]:
    """Convert a Tool to OpenAI tool format."""
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters,
        },
    }


def _strip_raw_body(msg: str) -> str:
    """Strip raw JSON/bytes response bodies that LiteLLM embeds in error messages."""
    for marker in (" - b'{", ' - b"', "\n{", '\n"error"'):
        if marker in msg:
            msg = msg[: msg.index(marker)]
            break
    if len(msg) > 200:
        msg = msg[:200] + "..."
    return msg.strip()


def _convert_error(error: Exception) -> ChatProviderError:
    """Convert various errors to our error types."""
    error_msg = _strip_raw_body(str(error))
    lower = error_msg.lower()

    if any(kw in lower for kw in ("rate limit", "ratelimit", "429", "resource_exhausted", "quota")):
        return APIStatusError(429, error_msg)
    elif "timeout" in lower:
        return APITimeoutError(error_msg)
    elif "connection" in lower:
        return APIConnectionError(error_msg)
    elif "401" in error_msg or "unauthorized" in lower:
        return APIStatusError(401, error_msg)
    elif "404" in error_msg or "not found" in lower:
        return APIStatusError(404, error_msg)
    else:
        return ChatProviderError(f"LiteLLM Error: {error_msg}")
