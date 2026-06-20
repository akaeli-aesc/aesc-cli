from __future__ import annotations

from contextvars import ContextVar
from typing import override

from aesc.provider import HandleResult, SimpleToolset, ToolCall
from aesc.utils.logging import logger

current_tool_call = ContextVar[ToolCall | None]("current_tool_call", default=None)


def get_current_tool_call_or_none() -> ToolCall | None:
    """
    Get the current tool call or None.
    Expect to be not None when called from a `__call__` method of a tool.
    """
    return current_tool_call.get()


class CustomToolset(SimpleToolset):
    @override
    def handle(self, tool_call: ToolCall) -> HandleResult:
        token = current_tool_call.set(tool_call)
        logger.debug(
            "Handling tool call: {tool_name} (id={tool_id})",
            tool_name=tool_call.function.name,
            tool_id=tool_call.id,
        )
        try:
            result = super().handle(tool_call)
            logger.debug(
                "Tool call completed: {tool_name} (id={tool_id})",
                tool_name=tool_call.function.name,
                tool_id=tool_call.id,
            )
            return result
        except Exception as e:
            logger.exception(
                "Tool call failed: {tool_name} (id={tool_id}): {error}",
                tool_name=tool_call.function.name,
                tool_id=tool_call.id,
                error=str(e),
            )
            raise
        finally:
            current_tool_call.reset(token)
