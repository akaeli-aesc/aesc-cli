"""Professional Status Bar - Claude Code inspired design with unified theme."""

from rich.text import Text
from textual.widgets import Static

from .theme import (
    INFO,
    TEXT_DIM,
    TEXT_MUTED,
    WARNING,
)


class EnhancedStatusBar(Static):
    """
    Professional status bar following Kimi-CLI pattern.

    Pattern: Right-aligned, grey50, minimal
    Format: "context: 42% | tools: 3 | model: gpt-4o"

    Enhanced: Shows prominent approval indicator when waiting for user input.
    """

    DEFAULT_CSS = """
    EnhancedStatusBar {
        width: 100%;
        height: 1;
        background: $background;
        color: $text;
        padding: 0 1;
        dock: bottom;
    }
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._status = None
        self._pending_approval = False
        self._running_tools = 0

    def render(self) -> Text:
        """Render clean status bar with unified theme colors."""
        result = Text()

        # Show approval indicator - subtle but visible
        if self._pending_approval:
            result.append("● ", style=WARNING)
            result.append("Approval required ", style=WARNING)
            result.append("y·n·a ", style=TEXT_MUTED)
            result.append("│ ", style=TEXT_DIM)

        # Show running tools indicator - subtle
        if self._running_tools > 0:
            result.append("● ", style=INFO)
            result.append(f"{self._running_tools} running ", style=TEXT_MUTED)
            result.append("│ ", style=TEXT_DIM)

        if not self._status:
            return result

        # Build status parts
        parts = []

        # Context usage
        if hasattr(self._status, "context_usage") and self._status.context_usage:
            parts.append(f"context: {self._status.context_usage:.1%}")

        # Tools used (if available)
        if hasattr(self._status, "tools_used") and self._status.tools_used:
            parts.append(f"tools: {self._status.tools_used}")

        # Model (if available)
        if hasattr(self._status, "model") and self._status.model:
            parts.append(f"model: {self._status.model}")

        # Join with separator - using muted text
        status_text = " │ ".join(parts)
        result.append(status_text, style=TEXT_MUTED)

        return result

    def update(self, status) -> None:
        """Update status and refresh display."""
        self._status = status
        self.refresh()

    def set_pending_approval(self, pending: bool) -> None:
        """Set whether there's a pending approval request."""
        if self._pending_approval != pending:
            self._pending_approval = pending
            self.refresh()

    def set_running_tools(self, count: int) -> None:
        """Set the number of running tools."""
        if self._running_tools != count:
            self._running_tools = count
            self.refresh()
