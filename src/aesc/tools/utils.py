import os
import re
import string
from pathlib import Path

from aesc.provider import ToolError, ToolOk


def load_desc(path: Path, substitutions: dict[str, str] | None = None) -> str:
    """Load a tool description from a file, with optional substitutions."""
    description = path.read_text(encoding="utf-8")
    if substitutions:
        description = string.Template(description).substitute(substitutions)
    return description


def truncate_line(line: str, max_length: int, marker: str = "...") -> str:
    """
    Truncate a line if it exceeds `max_length`, preserving the beginning and the line break.
    The output may be longer than `max_length` if it is too short to fit the marker.
    """
    if len(line) <= max_length:
        return line

    # Find line breaks at the end of the line
    m = re.search(r"[\r\n]+$", line)
    linebreak = m.group(0) if m else ""
    end = marker + linebreak
    max_length = max(max_length, len(end))
    return line[: max_length - len(end)] + end


# Default output limits
DEFAULT_MAX_CHARS = 12_000
DEFAULT_MAX_LINE_LENGTH = 2000


def _get_max_chars() -> int:
    """Read AESC_TOOL_MAX_OUTPUT from environment, falling back to DEFAULT_MAX_CHARS."""
    raw = os.environ.get("AESC_TOOL_MAX_OUTPUT")
    if raw is not None:
        try:
            val = int(raw)
            return max(val, 500)  # floor: prevent absurdly low values
        except ValueError:
            pass
    return DEFAULT_MAX_CHARS


class ToolResultBuilder:
    """
    Builder for tool results with character and line limits.
    """

    def __init__(
        self,
        max_chars: int | None = None,
        max_line_length: int | None = DEFAULT_MAX_LINE_LENGTH,
    ):
        self.max_chars = max_chars if max_chars is not None else _get_max_chars()
        self.max_line_length = max_line_length
        self._marker = "[...truncated]"
        if max_line_length is not None:
            assert max_line_length > len(self._marker)
        self._buffer: list[str] = []
        self._n_chars = 0
        self._n_lines = 0
        self._truncation_happened = False
        self._total_chars_received = 0

    def write(self, text: str) -> int:
        """
        Write text to the output buffer.

        Returns:
            int: Number of characters actually written
        """
        self._total_chars_received += len(text)

        if self.is_full:
            return 0

        lines = text.splitlines(keepends=True)
        if not lines:
            return 0

        chars_written = 0

        for line in lines:
            if self.is_full:
                break

            original_line = line
            remaining_chars = self.max_chars - self._n_chars
            limit = (
                min(remaining_chars, self.max_line_length)
                if self.max_line_length is not None
                else remaining_chars
            )
            line = truncate_line(line, limit, self._marker)
            if line != original_line:
                self._truncation_happened = True

            self._buffer.append(line)
            chars_written += len(line)
            self._n_chars += len(line)
            if line.endswith("\n"):
                self._n_lines += 1

        return chars_written

    def _truncation_notice(self, tool_hint: str = "") -> str:
        """Build a descriptive truncation notice with pagination guidance."""
        shown = self._n_chars
        total = self._total_chars_received
        parts = [f"Output truncated: showing {shown:,} of {total:,} total chars."]
        if tool_hint:
            parts.append(tool_hint)
        else:
            parts.append("Use head, tail, grep, or sed to view specific sections of large output.")
        return " ".join(parts)

    def ok(self, message: str = "", *, brief: str = "", tool_hint: str = "") -> ToolOk:
        """Create a ToolOk result with the current output."""
        output = "".join(self._buffer)

        final_message = message
        if final_message and not final_message.endswith("."):
            final_message += "."
        if self._truncation_happened:
            truncation_msg = self._truncation_notice(tool_hint)
            if final_message:
                final_message += f" {truncation_msg}"
            else:
                final_message = truncation_msg

        return ToolOk(output=output, message=final_message, brief=brief)

    def error(self, message: str, *, brief: str, tool_hint: str = "") -> ToolError:
        """Create a ToolError result with the current output."""
        output = "".join(self._buffer)

        final_message = message
        if self._truncation_happened:
            truncation_msg = self._truncation_notice(tool_hint)
            if final_message:
                final_message += f" {truncation_msg}"
            else:
                final_message = truncation_msg

        return ToolError(output=output, message=final_message, brief=brief)

    @property
    def is_full(self) -> bool:
        """Check if output buffer is full due to character limit."""
        return self._n_chars >= self.max_chars

    @property
    def n_chars(self) -> int:
        """Get current character count."""
        return self._n_chars

    @property
    def n_lines(self) -> int:
        """Get current line count."""
        return self._n_lines

    @property
    def total_chars_received(self) -> int:
        """Total characters received including discarded overflow."""
        return self._total_chars_received


class ToolRejectedError(ToolError):
    def __init__(self):
        super().__init__(
            message=(
                "The tool call is rejected by the user. "
                "Please follow the new instructions from the user."
            ),
            brief="Rejected by user",
        )
