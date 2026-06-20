"""Decision panel widget for human-in-the-loop responses to subagent decisions.

Claude Code inspired design with unified theme.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.console import Group, RenderableType
from rich.panel import Panel
from rich.text import Text

from .theme import (
    BRAND,
    INFO,
    SUCCESS,
    TEXT,
    TEXT_DIM,
    TEXT_MUTED,
    WARNING,
)

if TYPE_CHECKING:
    from aesc.tools.results.schemas import Decision


class DecisionPanel:
    """
    Decision panel for responding to subagent decision requests.

    Key features:
    - Shows question, context, and available options
    - Option selection with keyboard (1/2/3/4 or A/B/C/D)
    - Arrow indicator (→) for selected option
    - Shows recommended option if available
    - DISAPPEARS after user makes a choice
    """

    def __init__(self, decision: Decision):
        self.decision = decision
        self.selected_index = 0

        # Find recommended option index
        if decision.recommended:
            for i, opt in enumerate(decision.options):
                if opt.id == decision.recommended:
                    self.selected_index = i
                    break

    @property
    def options(self) -> list[tuple[str, str, str]]:
        """Return options as (key, title, description) tuples."""
        result = []
        for i, opt in enumerate(self.decision.options):
            # Use A/B/C/D or 1/2/3/4 depending on option count
            if len(self.decision.options) <= 4:
                key = chr(ord("A") + i)  # A, B, C, D
            else:
                key = str(i + 1)  # 1, 2, 3, 4, ...
            result.append((key, opt.title, opt.description))
        return result

    def render(self) -> Panel:
        """Render the decision panel with unified theme."""
        parts = []

        # Header - clean design
        header = Text()
        header.append("● ", style=INFO)
        header.append("Decision required", style="bold")
        header.append("  from ", style=TEXT_DIM)
        header.append(self.decision.source_agent, style=BRAND)
        parts.append(header)
        parts.append(Text(""))

        # Question - prominent
        question = Text()
        question.append(self.decision.question, style=f"{TEXT} bold")
        parts.append(question)
        parts.append(Text(""))

        # Context (truncated if too long)
        context = self.decision.context
        if len(context) > 300:
            context = context[:297] + "..."
        parts.append(Text(context, style=TEXT_MUTED))
        parts.append(Text(""))

        # Options - clean list
        for i, (key, title, description) in enumerate(self.options):
            opt = self.decision.options[i]
            is_recommended = opt.id == self.decision.recommended

            line = Text()
            if i == self.selected_index:
                line.append("▸ ", style=f"{BRAND} bold")
                line.append(f"{key}", style=f"{INFO} bold")
                line.append(f"  {title}", style=f"{TEXT} bold")
                if is_recommended:
                    line.append(" ★", style=WARNING)
            else:
                line.append("  ", style="")
                line.append(f"{key}", style=TEXT_DIM)
                line.append(f"  {title}", style=TEXT_MUTED)
                if is_recommended:
                    line.append(" ★", style=WARNING)
            parts.append(line)

            if description and i == self.selected_index:
                desc = Text()
                desc.append("     ", style="")
                desc.append(description, style=TEXT_MUTED)
                parts.append(desc)

        # Recommendation reason
        if self.decision.recommendation_reason:
            parts.append(Text(""))
            rec = Text()
            rec.append("Recommended: ", style=TEXT_DIM)
            rec.append(self.decision.recommendation_reason, style=TEXT_MUTED)
            parts.append(rec)

        # Key hints - inline
        parts.append(Text(""))
        hints = Text()
        keys = "/".join(k for k, _, _ in self.options)
        hints.append(f"{keys}", style=INFO)
        hints.append(" or ", style=TEXT_DIM)
        hints.append("↑↓", style=INFO)
        hints.append(" + ", style=TEXT_DIM)
        hints.append("enter", style=INFO)
        parts.append(hints)

        return Panel.fit(
            Group(*parts),
            border_style=INFO,
            padding=(0, 1),
        )

    def get_selected_option_id(self) -> str:
        """Get the ID of the currently selected option."""
        if 0 <= self.selected_index < len(self.decision.options):
            return self.decision.options[self.selected_index].id
        return self.decision.options[0].id if self.decision.options else ""

    def get_decision_display(self, chosen_id: str) -> RenderableType:
        """
        Get display to show AFTER user makes choice.

        Format: ● Chose [option_title]: <question summary>
        """
        chosen_opt = None
        for opt in self.decision.options:
            if opt.id == chosen_id:
                chosen_opt = opt
                break

        chosen_title = chosen_opt.title if chosen_opt else chosen_id
        question_short = self.decision.question
        if len(question_short) > 60:
            question_short = question_short[:57] + "..."

        result = Text()
        result.append("● ", style=SUCCESS)
        result.append(f"{chosen_title}", style=INFO)
        result.append("  ", style="")
        result.append(question_short, style=TEXT_MUTED)
        return result
