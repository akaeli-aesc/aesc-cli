"""
Base chat provider interface.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Sequence
from typing import TYPE_CHECKING, Any, Literal, Self

if TYPE_CHECKING:
    from aesc.provider.message import ContentPart, Message
    from aesc.provider.tool import Tool
    from aesc.provider.usage import TokenUsage


# Thinking effort levels
ThinkingEffort = Literal["off", "low", "medium", "high"]


class StreamedMessage(ABC):
    """Iterator over streamed message parts from a provider."""

    @abstractmethod
    def __aiter__(self) -> AsyncIterator[ContentPart]:
        """Iterate over message parts."""
        ...

    @abstractmethod
    async def __anext__(self) -> ContentPart:
        """Get next message part."""
        ...

    @property
    @abstractmethod
    def id(self) -> str | None:
        """Message/response ID from the provider."""
        ...

    @property
    @abstractmethod
    def usage(self) -> TokenUsage | None:
        """Token usage statistics."""
        ...


class ChatProvider(ABC):
    """Abstract base class for chat/LLM providers."""

    name: str = "base"

    @property
    @abstractmethod
    def model_name(self) -> str:
        """The model name being used."""
        ...

    @abstractmethod
    async def generate(
        self,
        system_prompt: str,
        tools: Sequence[Tool],
        history: Sequence[Message],
    ) -> StreamedMessage:
        """
        Generate a response given a system prompt, tools, and conversation history.

        Args:
            system_prompt: The system/developer prompt
            tools: Available tools the model can use
            history: Conversation history (user/assistant messages)

        Returns:
            StreamedMessage that can be iterated to get response parts
        """
        ...

    @abstractmethod
    def with_thinking(self, effort: ThinkingEffort) -> Self:
        """
        Return a new provider instance with the specified thinking effort.

        For Gemini 3, this enables reasoning_effort which is required for
        function calling to work properly (thought_signature).
        """
        ...

    @property
    def model_parameters(self) -> dict[str, Any]:
        """Get model parameters for tracing/logging."""
        return {}
