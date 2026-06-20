"""Modern approval dialog - Claude Code inspired design."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.console import Group, RenderableType
from rich.panel import Panel
from rich.text import Text

if TYPE_CHECKING:
    from aesc.wire.message import ApprovalRequest

# Colors from theme
COLORS = {
    "brand": "#a855f7",
    "success": "#4ade80",
    "error": "#f87171",
    "warning": "#fbbf24",
    "muted": "#71717a",
    "text": "#d4d4d8",
    "dim": "#52525b",
}


class ApprovalPanel:
    """
    Modern approval dialog - minimal and professional.

    Clean design without alarming symbols.
    """

    def __init__(self, request: ApprovalRequest):
        self.request = request
        self.selected_index = 0

        # Get risk info if available
        self.risk_level = None
        self.risk_reason = None
        if request.risk_assessment:
            self.risk_level = request.risk_assessment.level
            self.risk_reason = request.risk_assessment.reason

        # Build options
        risk_name = self.risk_level.display_name if self.risk_level else "UNKNOWN"
        self.options = [
            ("y", "Yes"),
            ("a", f"Yes to all ({risk_name})"),
            ("n", "No"),
        ]

    def render(self) -> Panel:
        """Render clean approval panel."""
        parts = []

        # Simple header - no alarming symbols
        header = Text()
        header.append("● ", style=COLORS["warning"])
        header.append("Approval required", style="bold")
        parts.append(header)
        parts.append(Text(""))

        # Description - clean
        desc = Text()
        desc.append(self.request.description, style=COLORS["text"])
        parts.append(desc)

        # Risk level - subtle
        if self.risk_level:
            parts.append(Text(""))
            risk_line = Text()
            risk_line.append("Risk: ", style=COLORS["dim"])
            risk_line.append(self.risk_level.display_name, style=self.risk_level.color)
            if self.risk_reason:
                risk_line.append(f"  {self.risk_reason}", style=COLORS["muted"])
            parts.append(risk_line)

        parts.append(Text(""))

        # Options - clean inline format
        opts = Text()
        opts.append("  ", style="")
        opts.append("y", style=COLORS["success"])
        opts.append("·yes  ", style=COLORS["dim"])
        opts.append("a", style=COLORS["brand"])
        opts.append("·all  ", style=COLORS["dim"])
        opts.append("n", style=COLORS["error"])
        opts.append("·no", style=COLORS["dim"])
        parts.append(opts)

        # Subtle border
        border_color = COLORS["warning"]
        if self.risk_level and self.risk_level.display_name in ("HIGH", "CRITICAL"):
            border_color = COLORS["error"]

        return Panel.fit(
            Group(*parts),
            border_style=border_color,
            padding=(0, 1),
        )

    def get_approval_display(self, approved: bool, for_session: bool = False) -> RenderableType:
        """Display after user makes choice."""
        parts = []

        header = Text()
        if approved:
            header.append("● ", style=COLORS["success"])
            if for_session and self.risk_level:
                header.append(
                    f"Approved up to {self.risk_level.display_name}", style=COLORS["success"]
                )
            else:
                header.append("Approved", style=COLORS["success"])
        else:
            header.append("● ", style=COLORS["error"])
            header.append("Rejected", style=COLORS["error"])

        header.append("  ", style="")
        header.append(self.request.description[:50], style=COLORS["muted"])

        return header
