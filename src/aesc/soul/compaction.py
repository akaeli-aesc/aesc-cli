from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from string import Template
from typing import TYPE_CHECKING, Protocol, runtime_checkable

import aesc.prompts as prompts
from aesc.llm import LLM
from aesc.provider import ContentPart, Message, TextPart, generate
from aesc.soul.message import system
from aesc.utils.logging import logger

# Token estimation: ~4 characters per token (conservative for English)
CHARS_PER_TOKEN = 4


def estimate_tokens(text: str) -> int:
    """Estimate token count from text length."""
    return len(text) // CHARS_PER_TOKEN


# Cache for message token counts - uses id(message) as key
# This avoids recalculating for the same message object
_message_token_cache: dict[int, int] = {}
_CACHE_MAX_SIZE = 1000


def estimate_message_tokens(message: Message) -> int:
    """Estimate token count for a message (cached by object id)."""
    msg_id = id(message)
    if msg_id in _message_token_cache:
        return _message_token_cache[msg_id]

    if isinstance(message.content, str):
        tokens = estimate_tokens(message.content)
    else:
        # For list of content parts, sum up text parts
        total = 0
        for part in message.content:
            if isinstance(part, TextPart):
                total += estimate_tokens(part.text)
            elif hasattr(part, "text"):
                total += estimate_tokens(str(part.text))
        tokens = total

    # Cache result (with size limit to prevent memory issues)
    if len(_message_token_cache) >= _CACHE_MAX_SIZE:
        # Simple eviction: clear oldest half
        keys = list(_message_token_cache.keys())[: _CACHE_MAX_SIZE // 2]
        for k in keys:
            _message_token_cache.pop(k, None)

    _message_token_cache[msg_id] = tokens
    return tokens


def estimate_messages_tokens(messages: Sequence[Message]) -> int:
    """Estimate total token count for a sequence of messages (uses cached per-message counts)."""
    return sum(estimate_message_tokens(m) for m in messages)


def clear_token_cache() -> None:
    """Clear the token estimation cache (call when messages are modified)."""
    _message_token_cache.clear()


@dataclass(slots=True)
class CompactionResult:
    """Result of a compaction operation with metadata."""

    messages: Sequence[Message]
    summary: str
    """A brief summary of what was compacted (first line)."""
    full_summary: str
    """The full compacted context text for expandable display."""
    original_token_estimate: int
    compacted_token_estimate: int
    compression_ratio: float
    """Ratio of compacted to original (lower is more compressed)."""


@runtime_checkable
class Compaction(Protocol):
    async def compact(self, messages: Sequence[Message], llm: LLM) -> Sequence[Message]:
        """
        Compact a sequence of messages into a new sequence of messages.

        Args:
            messages (Sequence[Message]): The messages to compact.
            llm (LLM): The LLM to use for compaction.

        Returns:
            Sequence[Message]: The compacted messages.

        Raises:
            ChatProviderError: When the chat provider returns an error.
        """
        ...


class CompactionError(Exception):
    """Raised when compaction fails validation."""

    pass


class SimpleCompaction(Compaction):
    # Preserve last 2 user/assistant exchanges for conversation continuity
    MAX_PRESERVED_MESSAGES = 2

    # Maximum tokens to preserve (prevents huge tool outputs from being kept)
    # Tuned for security tasks with large outputs (nmap, hydra, etc.)
    MAX_PRESERVED_TOKENS = 6000

    # Aggressively truncate old tool outputs beyond this age (in message count)
    MAX_TOOL_MESSAGES_FULL = 3  # Keep last 3 tool outputs in full
    TRUNCATE_OLD_TOOL_TO = 500  # Truncate older tool outputs to 500 chars

    # Warn if compression ratio is poor (compacted is >50% of original)
    WARN_COMPRESSION_RATIO = 0.5
    # Fail if compaction doesn't achieve at least 20% reduction
    FAIL_COMPRESSION_RATIO = 0.8

    # Critical patterns to never discard (security-focused)
    CRITICAL_PATTERNS = frozenset(
        {
            "flag",
            "root",
            "shell",
            "exploit",
            "vulnerability",
            "cve",
            "credential",
            "password",
            "ssh",
            "token",
            "key",
            "secret",
            "reverse shell",
            "privilege",
            "escalation",
            "backdoor",
        }
    )

    async def compact(self, messages: Sequence[Message], llm: LLM) -> Sequence[Message]:
        """Compact messages, returning just the messages (for backward compatibility)."""
        result = await self.compact_with_result(messages, llm)
        return result.messages

    async def compact_with_result(
        self,
        messages: Sequence[Message],
        llm: LLM,
        max_context_tokens: int | None = None,
    ) -> CompactionResult:
        """
        Compact messages with full result including validation metrics.

        Args:
            messages: Messages to compact.
            llm: LLM to use for compaction.
            max_context_tokens: Optional context limit for validation.

        Returns:
            CompactionResult with compacted messages and metrics.

        Raises:
            CompactionError: If compaction fails validation.
        """
        history = list(messages)
        original_token_estimate = estimate_messages_tokens(history)

        if not history:
            return CompactionResult(
                messages=history,
                summary="No messages to compact",
                full_summary="",
                original_token_estimate=0,
                compacted_token_estimate=0,
                compression_ratio=1.0,
            )

        preserve_start_index = len(history)
        n_preserved = 0
        preserved_tokens = 0

        for index in range(len(history) - 1, -1, -1):
            msg = history[index]
            msg_tokens = estimate_message_tokens(msg)

            # Check if adding this message would exceed token limit
            if preserved_tokens + msg_tokens > self.MAX_PRESERVED_TOKENS and n_preserved > 0:
                # Stop preserving - we have enough and would exceed limit
                preserve_start_index = index + 1
                break

            preserved_tokens += msg_tokens

            if msg.role in {"user", "assistant"}:
                n_preserved += 1
                if n_preserved == self.MAX_PRESERVED_MESSAGES:
                    preserve_start_index = index
                    break

        if n_preserved < self.MAX_PRESERVED_MESSAGES:
            return CompactionResult(
                messages=history,
                summary="Not enough messages to compact",
                full_summary="",
                original_token_estimate=original_token_estimate,
                compacted_token_estimate=original_token_estimate,
                compression_ratio=1.0,
            )

        to_compact = history[:preserve_start_index]
        to_preserve = history[preserve_start_index:]

        # If preserved messages are still too large, truncate tool outputs
        if estimate_messages_tokens(to_preserve) > self.MAX_PRESERVED_TOKENS:
            logger.warning("Preserved messages exceed token limit, truncating tool outputs")
            to_preserve = self._truncate_preserved_messages(to_preserve)

        if not to_compact:
            return CompactionResult(
                messages=to_preserve,
                summary="Nothing to compact (only preserved messages)",
                full_summary="",
                original_token_estimate=original_token_estimate,
                compacted_token_estimate=estimate_messages_tokens(to_preserve),
                compression_ratio=1.0,
            )

        # Pre-process: aggressively truncate old tool outputs before LLM summarization
        # This reduces the input to the compaction LLM call significantly
        to_compact = self._preprocess_for_compaction(to_compact)

        # Convert history to string for the compact prompt
        history_text = "\n\n".join(
            f"## Message {i + 1}\nRole: {msg.role}\nContent: {self._extract_content_text(msg)}"
            for i, msg in enumerate(to_compact)
        )

        # Build the compact prompt using string template
        compact_template = Template(prompts.COMPACT)
        compact_prompt = compact_template.substitute(CONTEXT=history_text)

        # Create input message for compaction
        compact_message = Message(role="user", content=compact_prompt)

        # Call generate to get the compacted context
        logger.debug("Compacting context...")
        result = await generate(
            chat_provider=llm.chat_provider,
            system_prompt="You are a helpful assistant that compacts conversation context.",
            tools=[],
            history=[compact_message],
        )
        if result.usage:
            logger.debug(
                "Compaction used {input} input tokens and {output} output tokens",
                input=result.usage.input,
                output=result.usage.output,
            )

        content: list[ContentPart] = [
            system("Previous context has been compacted. Here is the compaction output:")
        ]
        compacted_msg = result.message

        # Extract text content from the compaction result
        # Handle both string and list of ContentPart
        if isinstance(compacted_msg.content, str):
            compacted_text = compacted_msg.content
        else:
            # Extract text from all TextPart elements
            text_parts = []
            for part in compacted_msg.content:
                if isinstance(part, TextPart):
                    text_parts.append(part.text)
                elif hasattr(part, "text"):
                    text_parts.append(str(part.text))
            compacted_text = "\n".join(text_parts)

        # Ensure the compacted content is a clean TextPart
        # This avoids issues with nested structures that may not serialize properly
        if compacted_text.strip():
            content.append(TextPart(text=compacted_text))

        compacted_messages: list[Message] = [Message(role="assistant", content=content)]
        compacted_messages.extend(to_preserve)

        # Validation: estimate token counts and compression ratio
        compacted_token_estimate = estimate_messages_tokens(compacted_messages)
        compression_ratio = (
            compacted_token_estimate / original_token_estimate
            if original_token_estimate > 0
            else 1.0
        )

        # Build summary from the already-extracted compacted_text
        # Extract first line or first 100 chars as summary
        summary_text = compacted_text.split("\n")[0][:100]
        if len(summary_text) < len(compacted_text):
            summary_text += "..."

        # Log validation results
        logger.debug(
            "Compaction: {orig} -> {comp} tokens ({ratio:.1%} ratio)",
            orig=original_token_estimate,
            comp=compacted_token_estimate,
            ratio=compression_ratio,
        )

        # Warn if compression is poor
        if compression_ratio > self.WARN_COMPRESSION_RATIO:
            logger.warning(
                "Poor compaction ratio: {ratio:.1%} (>{warn:.0%})",
                ratio=compression_ratio,
                warn=self.WARN_COMPRESSION_RATIO,
            )

        # Fail if compaction made things larger
        if compression_ratio > self.FAIL_COMPRESSION_RATIO:
            raise CompactionError(
                f"Compaction increased size: {original_token_estimate} -> "
                f"{compacted_token_estimate} tokens ({compression_ratio:.1%})"
            )

        # Validate against max context if provided
        if max_context_tokens and compacted_token_estimate > max_context_tokens:
            raise CompactionError(
                f"Compacted result ({compacted_token_estimate} tokens) exceeds "
                f"context limit ({max_context_tokens} tokens)"
            )

        return CompactionResult(
            messages=compacted_messages,
            summary=summary_text,
            full_summary=compacted_text,  # Full text for expandable display
            original_token_estimate=original_token_estimate,
            compacted_token_estimate=compacted_token_estimate,
            compression_ratio=compression_ratio,
        )

    def _truncate_preserved_messages(self, messages: Sequence[Message]) -> list[Message]:
        """
        Truncate tool message content to fit within MAX_PRESERVED_TOKENS.

        Keeps user/assistant messages intact but truncates large tool outputs.
        """
        result = []
        total_tokens = 0
        target_tokens = self.MAX_PRESERVED_TOKENS

        for msg in messages:
            if msg.role in {"user", "assistant"}:
                # Keep user/assistant messages intact
                result.append(msg)
                total_tokens += estimate_message_tokens(msg)
            elif msg.role == "tool":
                # Truncate tool messages if needed
                msg_tokens = estimate_message_tokens(msg)
                remaining = target_tokens - total_tokens

                if msg_tokens <= remaining or remaining > 1000:
                    # Enough room or at least 1000 tokens remaining
                    result.append(msg)
                    total_tokens += msg_tokens
                else:
                    # Truncate the tool output
                    if isinstance(msg.content, str):
                        # Truncate string content
                        max_chars = remaining * CHARS_PER_TOKEN
                        truncated_content = msg.content[:max_chars] + "\n... [output truncated]"
                        result.append(
                            Message(
                                role=msg.role,
                                content=truncated_content,
                                tool_call_id=msg.tool_call_id,
                            )
                        )
                    else:
                        # For list content, truncate text parts
                        truncated_parts = []
                        chars_used = 0
                        max_chars = remaining * CHARS_PER_TOKEN
                        for part in msg.content:
                            if isinstance(part, TextPart):
                                if chars_used < max_chars:
                                    remaining_chars = max_chars - chars_used
                                    text = part.text[:remaining_chars]
                                    if len(part.text) > remaining_chars:
                                        text += "\n... [truncated]"
                                    truncated_parts.append(TextPart(text=text))
                                    chars_used += min(len(part.text), remaining_chars)
                            else:
                                truncated_parts.append(part)
                        result.append(
                            Message(
                                role=msg.role,
                                content=truncated_parts,
                                tool_call_id=msg.tool_call_id,
                            )
                        )
                    total_tokens += remaining
            else:
                result.append(msg)
                total_tokens += estimate_message_tokens(msg)

        return result

    def _preprocess_for_compaction(self, messages: Sequence[Message]) -> list[Message]:
        """
        Aggressively preprocess messages before sending to LLM for compaction.

        - Truncates old tool outputs (keeping only last MAX_TOOL_MESSAGES_FULL in full)
        - Preserves messages containing critical security patterns
        - Reduces input to compaction LLM significantly
        """
        result = []

        # Count tool messages from the end
        tool_indices = [i for i, m in enumerate(messages) if m.role == "tool"]
        recent_tool_indices = set(tool_indices[-self.MAX_TOOL_MESSAGES_FULL :])

        for i, msg in enumerate(messages):
            if msg.role == "tool":
                content_text = self._extract_content_text(msg)

                # Check for critical patterns - never truncate these
                has_critical = any(
                    pattern in content_text.lower() for pattern in self.CRITICAL_PATTERNS
                )

                if i in recent_tool_indices or has_critical:
                    # Keep recent tool outputs and critical ones in full
                    result.append(msg)
                else:
                    # Aggressively truncate old tool outputs
                    truncated = content_text[: self.TRUNCATE_OLD_TOOL_TO]
                    if len(content_text) > self.TRUNCATE_OLD_TOOL_TO:
                        omitted = len(content_text) - self.TRUNCATE_OLD_TOOL_TO
                        truncated += f"\n... [truncated {omitted} chars]"

                    result.append(
                        Message(
                            role=msg.role,
                            content=truncated,
                            tool_call_id=msg.tool_call_id,
                        )
                    )
            else:
                result.append(msg)

        return result

    def _extract_content_text(self, msg: Message) -> str:
        """Extract plain text content from a message."""
        if isinstance(msg.content, str):
            return msg.content

        text_parts = []
        for part in msg.content:
            if isinstance(part, TextPart):
                text_parts.append(part.text)
            elif hasattr(part, "text"):
                text_parts.append(str(part.text))
        return "\n".join(text_parts)

    def _contains_critical_content(self, text: str) -> bool:
        """Check if text contains critical security patterns."""
        text_lower = text.lower()
        return any(pattern in text_lower for pattern in self.CRITICAL_PATTERNS)


if TYPE_CHECKING:

    def type_check(simple: SimpleCompaction):
        _: Compaction = simple
