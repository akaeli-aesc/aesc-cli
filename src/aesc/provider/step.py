"""
Generate and step functions for agent execution.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from loguru import logger

from aesc.provider.base import ChatProvider
from aesc.provider.errors import APIEmptyResponseError, ChatProviderError
from aesc.provider.message import (
    ContentPart,
    Message,
    StreamedMessagePart,
    TextPart,
    ThinkPart,
    ToolCall,
)
from aesc.provider.tool import Tool, ToolResult, ToolResultFuture, Toolset
from aesc.provider.usage import TokenUsage

logger.disable("aesc.provider")

# Callback type
type Callback[T, R] = Callable[[T], R] | Callable[[T], asyncio.Future[R]]


async def callback[T, R](cb: Callback[T, R], arg: T) -> R:
    """Execute a callback, handling both sync and async callbacks."""
    result = cb(arg)
    if asyncio.iscoroutine(result) or isinstance(result, asyncio.Future):
        return await result
    return result


@dataclass(frozen=True, slots=True)
class GenerateResult:
    """The result of a generation."""

    id: str | None
    """The ID of the generated message."""
    message: Message
    """The generated message."""
    usage: TokenUsage | None
    """The token usage of the generated message."""


async def generate(
    chat_provider: ChatProvider,
    system_prompt: str,
    tools: Sequence[Tool],
    history: Sequence[Message],
    *,
    on_message_part: Callback[[StreamedMessagePart], None] | None = None,
    on_tool_call: Callback[[ToolCall], None] | None = None,
) -> GenerateResult:
    """
    Generate one message based on the given context.
    Parts of the message will be streamed to the specified callbacks if provided.

    Returns:
        GenerateResult with the generated message and token usage.

    Raises:
        APIConnectionError, APITimeoutError, APIStatusError, APIEmptyResponseError,
        ChatProviderError, asyncio.CancelledError
    """
    message = Message(role="assistant", content=[])
    pending_part: StreamedMessagePart | None = None
    current_thought_signature: str | None = None

    logger.trace("Generating with history: {history}", history=history)
    stream = await chat_provider.generate(system_prompt, tools, history)

    async for part in stream:
        logger.trace("Received part: {part}", part=part)

        # Track thought_signature from ThinkPart
        if isinstance(part, ThinkPart) and part.encrypted:
            current_thought_signature = part.encrypted

        # Apply thought_signature to ToolCalls
        if isinstance(part, ToolCall) and current_thought_signature and not part.thought_signature:
            part.thought_signature = current_thought_signature

        if on_message_part:
            await callback(
                on_message_part, part.model_copy(deep=True) if hasattr(part, "model_copy") else part
            )

        if pending_part is None:
            pending_part = part
        elif not pending_part.merge_in_place(part):
            _message_append(message, pending_part)
            if isinstance(pending_part, ToolCall) and on_tool_call:
                await callback(on_tool_call, pending_part)
            pending_part = part

    # End of message
    if pending_part is not None:
        _message_append(message, pending_part)
        if isinstance(pending_part, ToolCall) and on_tool_call:
            await callback(on_tool_call, pending_part)

    if not message.content and not message.tool_calls:
        raise APIEmptyResponseError()

    return GenerateResult(
        id=stream.id,
        message=message,
        usage=stream.usage,
    )


def _message_append(message: Message, part: StreamedMessagePart) -> None:
    """Append a part to a message."""
    match part:
        case ContentPart():
            if isinstance(message.content, str):
                message.content = [TextPart(text=message.content)]
            message.content.append(part)
        case ToolCall():
            if message.tool_calls is None:
                message.tool_calls = []
            message.tool_calls.append(part)
        case _:
            # May be an orphaned ToolCallPart
            return


@dataclass(frozen=True, slots=True)
class StepResult:
    """The result of one agent step."""

    id: str | None
    """The ID of the generated message."""

    message: Message
    """The message generated in this step."""

    usage: TokenUsage | None
    """The token usage in this step."""

    tool_calls: list[ToolCall]
    """All the tool calls generated in this step."""

    _tool_result_futures: dict[str, ToolResultFuture]
    """The futures of the results of the spawned tool calls."""

    async def tool_results(self) -> list[ToolResult]:
        """All the tool results returned by corresponding tool calls."""
        if not self._tool_result_futures:
            return []

        try:
            results: list[ToolResult] = []
            for tool_call in self.tool_calls:
                future = self._tool_result_futures.pop(tool_call.id)
                result = await future
                results.append(result)
            return results
        finally:
            for future in self._tool_result_futures.values():
                future.cancel()
            await asyncio.gather(*self._tool_result_futures.values(), return_exceptions=True)


async def step(
    chat_provider: ChatProvider,
    system_prompt: str,
    toolset: Toolset,
    history: Sequence[Message],
    *,
    on_message_part: Callback[[StreamedMessagePart], None] | None = None,
    on_tool_result: Callable[[ToolResult], None] | None = None,
) -> StepResult:
    """
    Run one agent "step". Generates LLM response and handles tool calls.

    The message history will NOT be modified.

    Raises:
        APIConnectionError, APITimeoutError, APIStatusError, APIEmptyResponseError,
        ChatProviderError, asyncio.CancelledError
    """
    tool_calls: list[ToolCall] = []
    tool_result_futures: dict[str, ToolResultFuture] = {}

    def future_done_callback(future: ToolResultFuture):
        if on_tool_result:
            try:
                result = future.result()
                on_tool_result(result)
            except asyncio.CancelledError:
                return

    async def on_tool_call(tool_call: ToolCall):
        tool_calls.append(tool_call)
        result = toolset.handle(tool_call)

        if isinstance(result, ToolResult):
            future = ToolResultFuture()
            future.add_done_callback(future_done_callback)
            future.set_result(result)
            tool_result_futures[tool_call.id] = future
        else:
            result.add_done_callback(future_done_callback)
            tool_result_futures[tool_call.id] = result

    try:
        result = await generate(
            chat_provider,
            system_prompt,
            toolset.tools,
            history,
            on_message_part=on_message_part,
            on_tool_call=on_tool_call,
        )
    except (ChatProviderError, asyncio.CancelledError):
        for future in tool_result_futures.values():
            future.remove_done_callback(future_done_callback)
            future.cancel()
        await asyncio.gather(*tool_result_futures.values(), return_exceptions=True)
        raise

    return StepResult(
        result.id,
        result.message,
        result.usage,
        tool_calls,
        tool_result_futures,
    )
