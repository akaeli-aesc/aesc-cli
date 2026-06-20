"""
OpenAI-compatible chat provider with Gemini 3 support.
"""

from __future__ import annotations

import copy
import uuid
from collections.abc import AsyncIterator, Sequence
from typing import Any, Self

import openai
from loguru import logger
from openai import AsyncOpenAI, AsyncStream, OpenAIError
from openai.types import CompletionUsage
from openai.types.chat import (
    ChatCompletion,
    ChatCompletionChunk,
    ChatCompletionToolParam,
)

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

# Reasoning effort mapping for OpenAI/Gemini
REASONING_EFFORT_MAP = {
    "off": None,
    "low": "low",
    "medium": "medium",
    "high": "high",
}


class OpenAIProvider(ChatProvider):
    """
    OpenAI-compatible chat provider with Gemini 3 support.

    Handles:
    - Standard OpenAI chat completions
    - Gemini 3's thought_signature for function calls
    - Streaming and non-streaming modes

    Example:
        >>> provider = OpenAIProvider(
        ...     model="gemini-3-flash-preview",
        ...     base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        ...     api_key="your-api-key"
        ... )
    """

    name = "openai"

    def __init__(
        self,
        *,
        model: str,
        api_key: str | None = None,
        base_url: str | None = None,
        stream: bool = True,
        **client_kwargs: Any,
    ):
        self.model = model
        self.stream = stream
        self.client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            **client_kwargs,
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
    ) -> OpenAIStreamedMessage:
        """Generate a response using the OpenAI-compatible API."""
        messages: list[dict[str, Any]] = []

        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        # Convert messages to OpenAI format with thought_signature support
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

        if self.stream:
            kwargs["stream_options"] = {"include_usage": True}

        # Add reasoning_effort for Gemini 3 / o1 / o3 models
        if self._reasoning_effort:
            kwargs["reasoning_effort"] = self._reasoning_effort

        try:
            response = await self.client.chat.completions.create(**kwargs)
            return OpenAIStreamedMessage(response, stream=self.stream)
        except OpenAIError as e:
            raise _convert_error(e) from e

    def with_thinking(self, effort: ThinkingEffort) -> Self:
        """Return a new provider with the specified thinking effort."""
        new_self = copy.copy(self)
        new_self._reasoning_effort = REASONING_EFFORT_MAP.get(effort)
        return new_self

    @property
    def model_parameters(self) -> dict[str, Any]:
        """Get model parameters for tracing/logging."""
        params: dict[str, Any] = {"base_url": str(self.client.base_url)}
        if self._reasoning_effort:
            params["reasoning_effort"] = self._reasoning_effort
        return params


class OpenAIStreamedMessage(StreamedMessage):
    """Streamed message from OpenAI-compatible API with Gemini 3 support."""

    def __init__(
        self,
        response: ChatCompletion | AsyncStream[ChatCompletionChunk],
        stream: bool = True,
    ):
        self._stream = stream
        if stream:
            self._iter = self._convert_stream_response(response)
        else:
            self._iter = self._convert_non_stream_response(response)
        self._id: str | None = None
        self._usage: CompletionUsage | None = None

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
            cached = 0
            other_input = self._usage.prompt_tokens
            if (
                self._usage.prompt_tokens_details
                and self._usage.prompt_tokens_details.cached_tokens
            ):
                cached = self._usage.prompt_tokens_details.cached_tokens
                other_input -= cached
            return TokenUsage(
                input_other=other_input,
                output=self._usage.completion_tokens,
                input_cache_read=cached,
            )
        return None

    async def _convert_non_stream_response(
        self,
        response: ChatCompletion,
    ) -> AsyncIterator[ContentPart]:
        """Convert a non-streaming response to message parts."""
        self._id = response.id
        self._usage = response.usage

        message = response.choices[0].message

        # Extract Gemini 3 thought_signature from extra_content
        thought_signature = _extract_thought_signature(message)

        # Yield thought_signature as ThinkPart first (so it's captured in Message)
        if thought_signature:
            yield ThinkPart(think="", encrypted=thought_signature)

        if message.content:
            yield TextPart(text=message.content)

        if message.tool_calls:
            for tool_call in message.tool_calls:
                yield ToolCall(
                    id=tool_call.id or str(uuid.uuid4()),
                    function=ToolCall.FunctionBody(
                        name=tool_call.function.name,
                        arguments=tool_call.function.arguments or "",
                    ),
                    thought_signature=thought_signature,
                )

    async def _convert_stream_response(
        self,
        response: AsyncStream[ChatCompletionChunk],
    ) -> AsyncIterator[ContentPart]:
        """Convert a streaming response to message parts."""
        accumulated_thought_signature: str | None = None

        try:
            async for chunk in response:
                if chunk.id:
                    self._id = chunk.id
                if chunk.usage:
                    self._usage = chunk.usage

                if not chunk.choices:
                    continue

                delta = chunk.choices[0].delta

                # Check for thought_signature in extra_content (Gemini 3)
                if ts := _extract_thought_signature(delta):
                    if ts != accumulated_thought_signature:
                        accumulated_thought_signature = ts
                        yield ThinkPart(think="", encrypted=ts)

                # Convert text content
                if delta.content:
                    yield TextPart(text=delta.content)

                # Convert tool calls
                for tool_call in delta.tool_calls or []:
                    if not tool_call.function:
                        continue

                    # Also check for thought_signature in the tool_call itself
                    if ts := _extract_thought_signature(tool_call):
                        if ts != accumulated_thought_signature:
                            accumulated_thought_signature = ts
                            yield ThinkPart(think="", encrypted=ts)

                    if tool_call.function.name:
                        yield ToolCall(
                            id=tool_call.id or str(uuid.uuid4()),
                            function=ToolCall.FunctionBody(
                                name=tool_call.function.name,
                                arguments=tool_call.function.arguments or "",
                            ),
                            thought_signature=accumulated_thought_signature,
                        )
                    elif tool_call.function.arguments:
                        yield ToolCallPart(arguments_part=tool_call.function.arguments)

        except OpenAIError as e:
            raise _convert_error(e) from e


def _extract_thought_signature(obj: Any) -> str | None:
    """Extract Gemini 3's thought_signature from a response object."""
    if ts := _extract_thought_signature_internal(obj):
        logger.debug("Extracted thought_signature: {ts}", ts=ts[:20] + "..." if ts else None)
        return ts
    return None


def _extract_thought_signature_internal(obj: Any) -> str | None:
    """Internal helper to extract Gemini 3's thought_signature from a response object."""
    # Try direct attribute
    if hasattr(obj, "extra_content") and obj.extra_content:
        google_data = obj.extra_content.get("google", {})
        if ts := google_data.get("thought_signature"):
            return ts

    # Try model_extra (pydantic)
    if hasattr(obj, "model_extra") and obj.model_extra:
        if "extra_content" in obj.model_extra:
            google_data = obj.model_extra["extra_content"].get("google", {})
            if ts := google_data.get("thought_signature"):
                return ts
        if "google" in obj.model_extra:
            if ts := obj.model_extra["google"].get("thought_signature"):
                return ts

    # Try _extra_content
    if hasattr(obj, "_extra_content") and obj._extra_content:
        google_data = obj._extra_content.get("google", {})
        if ts := google_data.get("thought_signature"):
            return ts

    # Check tool_calls (Gemini 3 often puts it here)
    if hasattr(obj, "tool_calls") and obj.tool_calls:
        for tc in obj.tool_calls:
            if ts := _extract_thought_signature_internal(tc):
                return ts

    # Try dict access
    if isinstance(obj, dict):
        if "extra_content" in obj:
            google_data = obj["extra_content"].get("google", {})
            if ts := google_data.get("thought_signature"):
                return ts
        if "tool_calls" in obj and isinstance(obj["tool_calls"], list):
            for tc in obj["tool_calls"]:
                if ts := _extract_thought_signature_internal(tc):
                    return ts

    return None


def _tool_to_openai(tool: Tool) -> ChatCompletionToolParam:
    """Convert a Tool to OpenAI tool format."""
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters,
        },
    }


def _convert_error(error: OpenAIError) -> ChatProviderError:
    """Convert OpenAI errors to our error types."""
    if isinstance(error, openai.APIStatusError):
        return APIStatusError(error.status_code, error.message)
    elif isinstance(error, openai.APIConnectionError):
        return APIConnectionError(error.message)
    elif isinstance(error, openai.APITimeoutError):
        return APITimeoutError(error.message)
    else:
        return ChatProviderError(f"Error: {error}")
