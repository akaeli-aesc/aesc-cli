"""
Anthropic chat provider.
"""

from __future__ import annotations

import copy
import json
from collections.abc import AsyncIterator, Mapping, Sequence
from typing import TYPE_CHECKING, Any, Literal, Self, TypedDict, cast

from anthropic import (
    AnthropicError,
    AsyncAnthropic,
    AsyncStream,
    omit,
)
from anthropic import (
    APIConnectionError as AnthropicAPIConnectionError,
)
from anthropic import (
    APIStatusError as AnthropicAPIStatusError,
)
from anthropic import (
    APITimeoutError as AnthropicAPITimeoutError,
)
from anthropic import (
    AuthenticationError as AnthropicAuthenticationError,
)
from anthropic import (
    PermissionDeniedError as AnthropicPermissionDeniedError,
)
from anthropic import (
    RateLimitError as AnthropicRateLimitError,
)
from anthropic.lib.streaming import MessageStopEvent
from anthropic.types import (
    Base64ImageSourceParam,
    CacheControlEphemeralParam,
    ContentBlockParam,
    ImageBlockParam,
    MessageDeltaEvent,
    MessageParam,
    MessageStartEvent,
    RawContentBlockDeltaEvent,
    RawContentBlockStartEvent,
    RawMessageStreamEvent,
    TextBlockParam,
    ThinkingBlockParam,
    ThinkingConfigParam,
    ToolChoiceParam,
    ToolParam,
    ToolResultBlockParam,
    ToolUseBlockParam,
    URLImageSourceParam,
    Usage,
)
from anthropic.types import (
    Message as AnthropicMessage,
)
from anthropic.types.tool_result_block_param import Content as ToolResultContent

from aesc.provider.base import ChatProvider, StreamedMessage, ThinkingEffort
from aesc.provider.errors import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    ChatProviderError,
)
from aesc.provider.message import (
    ImageURLPart,
    Message,
    StreamedMessagePart,
    TextPart,
    ThinkPart,
    ToolCall,
    ToolCallPart,
)
from aesc.provider.tool import Tool
from aesc.provider.usage import TokenUsage

if TYPE_CHECKING:

    def type_check(anthropic: AnthropicProvider):
        _: ChatProvider = anthropic


type BetaFeatures = Literal["interleaved-thinking-2025-05-14"]


class AnthropicProvider(ChatProvider):
    """
    Chat provider backed by Anthropic's Messages API.
    """

    name = "anthropic"

    class GenerationKwargs(TypedDict, total=False):
        max_tokens: int | None
        temperature: float | None
        top_k: int | None
        top_p: float | None
        thinking: ThinkingConfigParam | None
        tool_choice: ToolChoiceParam | None
        beta_features: list[BetaFeatures] | None
        extra_headers: Mapping[str, str] | None

    def __init__(
        self,
        *,
        model: str,
        api_key: str | None = None,
        base_url: str | None = None,
        stream: bool = True,
        default_max_tokens: int,
        **client_kwargs: Any,
    ):
        self._model = model
        self._stream = stream
        self._client = AsyncAnthropic(api_key=api_key, base_url=base_url, **client_kwargs)
        self._generation_kwargs: AnthropicProvider.GenerationKwargs = {
            "max_tokens": default_max_tokens,
            "beta_features": ["interleaved-thinking-2025-05-14"],
        }

    @property
    def model_name(self) -> str:
        return self._model

    async def generate(
        self,
        system_prompt: str,
        tools: Sequence[Tool],
        history: Sequence[Message],
    ) -> AnthropicStreamedMessage:
        system = (
            [
                TextBlockParam(
                    text=system_prompt,
                    type="text",
                    cache_control=CacheControlEphemeralParam(type="ephemeral"),
                )
            ]
            if system_prompt
            else omit
        )
        messages: list[MessageParam] = [message_to_anthropic(m) for m in history]
        anthropic_tools: list[ToolParam] = [tool_to_anthropic(t) for t in tools]

        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "system": system,
            "stream": self._stream,
            **self._generation_kwargs,
        }
        if anthropic_tools:
            kwargs["tools"] = anthropic_tools

        # The SDK has no `beta_features` parameter; passing it raises TypeError on
        # every call. Translate beta flags into the `anthropic-beta` header. The
        # only flag (interleaved-thinking) is only meaningful with extended
        # thinking enabled, so emit it only then.
        beta_features = kwargs.pop("beta_features", None)
        if beta_features and kwargs.get("thinking"):
            existing_headers = kwargs.get("extra_headers") or {}
            kwargs["extra_headers"] = {
                **existing_headers,
                "anthropic-beta": ", ".join(beta_features),
            }

        try:
            if self._stream:
                manager = self._client.messages.stream(**kwargs)
                return AnthropicStreamedMessage(manager, stream=True)
            else:
                response = await self._client.messages.create(**kwargs)
                return AnthropicStreamedMessage(response, stream=False)
        except AnthropicError as exc:
            raise _convert_error(exc) from exc

    def with_thinking(self, effort: ThinkingEffort) -> Self:
        new_self = copy.copy(self)
        if effort == "off":
            new_self._generation_kwargs.pop("thinking", None)
        else:
            # mapping ThinkingEffort to budget_tokens
            budget = 4096 if effort == "low" else 16384 if effort == "medium" else 32768
            new_self._generation_kwargs["thinking"] = {"type": "enabled", "budget_tokens": budget}
            # Anthropic requires temperature to be 1.0 when thinking is enabled
            new_self._generation_kwargs["temperature"] = 1.0
        return new_self

    def with_generation_kwargs(self, **kwargs: Any) -> Self:
        new_self = copy.copy(self)
        new_self._generation_kwargs = cast(
            AnthropicProvider.GenerationKwargs, {**self._generation_kwargs, **kwargs}
        )
        return new_self


class AnthropicStreamedMessage(StreamedMessage):
    def __init__(
        self,
        response: AsyncStream[RawMessageStreamEvent] | AnthropicMessage,
        stream: bool = True,
    ):
        self._id: str | None = None
        self._usage: Usage | None = None
        if stream:
            self._iter = self._convert_stream_response(
                cast(AsyncStream[RawMessageStreamEvent], response)
            )
        else:
            self._iter = self._convert_non_stream_response(cast(AnthropicMessage, response))

    def __aiter__(self) -> AsyncIterator[StreamedMessagePart]:
        return self

    async def __anext__(self) -> StreamedMessagePart:
        return await self._iter.__anext__()

    @property
    def id(self) -> str | None:
        return self._id

    @property
    def usage(self) -> TokenUsage | None:
        if self._usage:
            return TokenUsage(
                input_other=self._usage.input_tokens,
                output=self._usage.output_tokens,
                # Anthropic doesn't expose more details in Usage object for now
            )
        return None

    async def _convert_non_stream_response(
        self,
        message: AnthropicMessage,
    ) -> AsyncIterator[StreamedMessagePart]:
        self._id = message.id
        self._usage = message.usage
        for block in message.content:
            match block.type:
                case "text":
                    yield TextPart(text=block.text)
                case "thinking":
                    yield ThinkPart(think=block.thinking, encrypted=block.signature)
                case "tool_use":
                    yield ToolCall(
                        id=block.id,
                        function=ToolCall.FunctionBody(
                            name=block.name, arguments=json.dumps(block.input)
                        ),
                    )
                case _:
                    continue

    async def _convert_stream_response(
        self,
        manager: AsyncStream[RawMessageStreamEvent],
    ) -> AsyncIterator[StreamedMessagePart]:
        try:
            async with manager as stream:
                async for event in stream:
                    if isinstance(event, MessageStartEvent):
                        self._id = event.message.id
                    elif isinstance(event, RawContentBlockStartEvent):
                        block = event.content_block
                        match block.type:
                            case "text":
                                yield TextPart(text=block.text)
                            case "thinking":
                                yield ThinkPart(think=block.thinking)
                            case "tool_use":
                                yield ToolCall(
                                    id=block.id,
                                    function=ToolCall.FunctionBody(name=block.name, arguments=""),
                                )
                    elif isinstance(event, RawContentBlockDeltaEvent):
                        delta = event.delta
                        match delta.type:
                            case "text_delta":
                                yield TextPart(text=delta.text)
                            case "thinking_delta":
                                yield ThinkPart(think=delta.thinking)
                            case "input_json_delta":
                                yield ToolCallPart(arguments_part=delta.partial_json)
                            case "signature_delta":
                                yield ThinkPart(think="", encrypted=delta.signature)
                    elif isinstance(event, MessageDeltaEvent):
                        self._usage = cast(Usage, event.usage)
                    elif isinstance(event, MessageStopEvent):
                        continue
        except AnthropicError as exc:
            raise _convert_error(exc) from exc


def tool_to_anthropic(tool: Tool) -> ToolParam:
    return {
        "name": tool.name,
        "description": tool.description,
        "input_schema": tool.parameters,
    }


def message_to_anthropic(message: Message) -> MessageParam:
    role = message.role
    content = message.content

    if role == "system":
        return MessageParam(
            role="user",
            content=[TextBlockParam(type="text", text=f"<system>{content}</system>")],
        )
    elif role == "tool":
        block = _tool_result_message_to_block(message)
        return MessageParam(role="user", content=[block])

    assert role in ("user", "assistant")
    blocks: list[ContentBlockParam] = []
    if isinstance(content, str):
        blocks.append(TextBlockParam(type="text", text=content))
    else:
        for part in content:
            if isinstance(part, TextPart):
                blocks.append(TextBlockParam(type="text", text=part.text))
            elif isinstance(part, ImageURLPart):
                blocks.append(_image_url_part_to_anthropic(part))
            elif isinstance(part, ThinkPart):
                if part.encrypted is not None:
                    blocks.append(
                        ThinkingBlockParam(
                            type="thinking", thinking=part.think, signature=part.encrypted
                        )
                    )
            else:
                continue
    for tool_call in message.tool_calls or []:
        if tool_call.function.arguments:
            try:
                parsed_arguments = json.loads(tool_call.function.arguments)
            except json.JSONDecodeError as exc:
                raise ChatProviderError("Tool call arguments must be valid JSON.") from exc
            if not isinstance(parsed_arguments, dict):
                raise ChatProviderError("Tool call arguments must be a JSON object.")
            tool_input = cast(dict[str, object], parsed_arguments)
        else:
            tool_input = {}
        blocks.append(
            ToolUseBlockParam(
                type="tool_use",
                id=tool_call.id,
                name=tool_call.function.name,
                input=tool_input,
            )
        )
    return MessageParam(role=role, content=blocks)


def _tool_result_message_to_block(message: Message) -> ToolResultBlockParam:
    if message.tool_call_id is None:
        raise ChatProviderError("Tool response is missing `tool_call_id`")

    content: str | Sequence[ToolResultContent]
    if isinstance(message.content, str):
        content = message.content
    else:
        content_blocks: list[ToolResultContent] = []
        for part in message.content:
            if isinstance(part, TextPart):
                if part.text:
                    content_blocks.append(TextBlockParam(type="text", text=part.text))
            elif isinstance(part, ImageURLPart):
                content_blocks.append(_image_url_part_to_anthropic(part))
            else:
                raise ChatProviderError(
                    f"Anthropic API does not support {type(part)} in tool result"
                )
        content = content_blocks

    return ToolResultBlockParam(
        type="tool_result",
        tool_use_id=message.tool_call_id,
        content=content,
    )


def _image_url_part_to_anthropic(part: ImageURLPart) -> ImageBlockParam:
    url = part.image_url.url
    if url.startswith("data:"):
        res = url[5:].split(";base64,", 1)
        if len(res) != 2:
            raise ChatProviderError(f"Invalid data URL for image: {url}")
        media_type, data = res
        if media_type not in ("image/png", "image/jpeg", "image/gif", "image/webp"):
            raise ChatProviderError(
                f"Unsupported media type for base64 image: {media_type}, url: {url}"
            )
        return ImageBlockParam(
            type="image",
            source=Base64ImageSourceParam(
                type="base64",
                data=data,
                media_type=media_type,
            ),
        )
    else:
        return ImageBlockParam(
            type="image",
            source=URLImageSourceParam(type="url", url=url),
        )


def _convert_error(error: AnthropicError) -> ChatProviderError:
    if isinstance(error, AnthropicAPIStatusError):
        return APIStatusError(error.status_code, str(error))
    if isinstance(error, AnthropicAuthenticationError):
        return APIStatusError(getattr(error, "status_code", 401), str(error))
    if isinstance(error, AnthropicPermissionDeniedError):
        return APIStatusError(getattr(error, "status_code", 403), str(error))
    if isinstance(error, AnthropicRateLimitError):
        return APIStatusError(getattr(error, "status_code", 429), str(error))
    if isinstance(error, AnthropicAPIConnectionError):
        return APIConnectionError(str(error))
    if isinstance(error, AnthropicAPITimeoutError):
        return APITimeoutError(str(error))
    return ChatProviderError(f"Anthropic error: {error}")
