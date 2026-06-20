"""Compaction summary panel widget for displaying context compaction info.

Claude Code inspired design with unified theme.
"""

from __future__ import annotations

from rich.console import Group, RenderableType
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text

from .theme import (
    BORDER,
    INFO,
    SUCCESS,
    TEXT_DIM,
    TEXT_MUTED,
)


class CompactionPanel:
    """
    Collapsible panel showing compaction/session summary.

    Features:
    - Shows brief summary in collapsed state
    - Shows full session context when expanded (what the agent remembers)
    - Toggle with Ctrl+O
    - Different display for session restore vs auto-compaction
    """

    def __init__(
        self,
        summary: str,
        full_summary: str,
        original_tokens: int,
        compacted_tokens: int,
        compression_ratio: float,
        is_session_restore: bool = False,
    ):
        self.summary = summary
        self.full_summary = full_summary
        self.original_tokens = original_tokens
        self.compacted_tokens = compacted_tokens
        self.compression_ratio = compression_ratio
        self.is_session_restore = is_session_restore
        self.expanded = False

    def render(self) -> RenderableType:
        """Render the compaction panel."""
        if self.expanded:
            return self._render_expanded()
        return self._render_collapsed()

    def _render_collapsed(self) -> RenderableType:
        """Render collapsed view - just icon and brief message."""
        saved = self.original_tokens - self.compacted_tokens
        saved_pct = (1 - self.compression_ratio) * 100 if self.compression_ratio < 1 else 0

        text = Text()

        if self.is_session_restore:
            text.append("● ", style=INFO)
            text.append("Session restored", style=INFO)
            text.append(f"  {self.compacted_tokens:,} tokens", style=TEXT_MUTED)
        else:
            text.append("● ", style=INFO)
            text.append("Context compacted", style=TEXT_MUTED)
            text.append(f"  {saved:,} tokens saved ({saved_pct:.0f}%)", style=TEXT_DIM)

        text.append("  ctrl+o expand", style=TEXT_DIM)

        return text

    def _render_expanded(self) -> RenderableType:
        """Render expanded view with full session summary."""
        parts = []

        # Header - clean design
        header = Text()
        header.append("● ", style=INFO)
        if self.is_session_restore:
            header.append("Session Restored", style=f"{INFO} bold")
        else:
            header.append("Context Compacted", style=f"{INFO} bold")
        parts.append(header)

        # Metrics bar
        parts.append(Text(""))
        saved_pct = (1 - self.compression_ratio) * 100 if self.compression_ratio < 1 else 0

        metrics = Text()
        if self.is_session_restore:
            metrics.append("Restored: ", style=TEXT_DIM)
            metrics.append(f"{self.compacted_tokens:,} tokens", style=TEXT_MUTED)
        else:
            metrics.append("Original: ", style=TEXT_DIM)
            metrics.append(f"{self.original_tokens:,}", style=TEXT_MUTED)
            metrics.append(" → ", style=TEXT_DIM)
            metrics.append("Compacted: ", style=TEXT_DIM)
            metrics.append(f"{self.compacted_tokens:,}", style=TEXT_MUTED)
            metrics.append(f"  -{saved_pct:.0f}%", style=SUCCESS)
        parts.append(metrics)

        # Full summary content
        if self.full_summary:
            parts.append(Text(""))

            # Render the full summary - it's structured with XML-like tags
            # Try to render as markdown for better formatting
            try:
                # Clean up the summary for display
                display_text = self.full_summary

                # Limit length for display (but show significant amount)
                max_display = 3000
                if len(display_text) > max_display:
                    display_text = display_text[:max_display] + "\n\n... [truncated for display]"

                parts.append(Markdown(display_text))
            except Exception:
                # Fallback to plain text
                display_text = self.full_summary[:2000]
                if len(self.full_summary) > 2000:
                    display_text += "\n... [truncated]"
                parts.append(Text(display_text, style=TEXT_MUTED))

        # Collapse hint
        parts.append(Text(""))
        collapse = Text()
        collapse.append("ctrl+o", style=INFO)
        collapse.append(" collapse", style=TEXT_DIM)
        parts.append(collapse)

        return Panel.fit(
            Group(*parts),
            border_style=BORDER,
            padding=(0, 1),
        )

    def toggle_expanded(self) -> None:
        """Toggle between expanded and collapsed state."""
        self.expanded = not self.expanded
