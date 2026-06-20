"""Activity Bar - Compact status line showing running agents and tools.

Shows below the prompt:
- Collapsed: "● 2 agents, 3 tools running" (single line)
- Expanded: Full list with navigation, kill, inspect

Navigation:
- Down arrow: Enter/expand the bar
- Up/Down: Navigate items when expanded
- Enter: Inspect selected item
- k: Kill selected item
- Escape/Tab: Collapse and return to prompt
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from rich.console import Group, RenderableType
from rich.text import Text
from textual.widgets import Static

from .theme import (
    BRAND,
    BRAND_LIGHT,
    ERROR,
    INFO,
    SUCCESS,
    TEXT,
    TEXT_DIM,
    TEXT_MUTED,
    WARNING,
)

if TYPE_CHECKING:
    from aesc.soul.subagent_registry import SubagentSession
    from aesc.tools.process_registry import RunningProcess


@dataclass
class ActivityItem:
    """Unified representation of running activity."""

    id: str
    type: str  # "agent" or "tool"
    name: str
    status: str  # "running", "completed", "failed"
    started_at: datetime
    detail: str = ""
    output_preview: list[str] | None = None

    @property
    def elapsed_seconds(self) -> float:
        return (datetime.now() - self.started_at).total_seconds()


def format_elapsed(seconds: float) -> str:
    """Format elapsed time as human-readable string."""
    if seconds < 60:
        return f"{int(seconds)}s"
    elif seconds < 3600:
        mins = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{mins}m{secs}s"
    else:
        hours = int(seconds // 3600)
        mins = int((seconds % 3600) // 60)
        return f"{hours}h{mins}m"


class ActivityBar(Static):
    """
    Compact activity bar showing running agents and tools.

    Features:
    - Single-line collapsed view: "▶ 2 agents, 3 tools"
    - Expandable with arrow down
    - Navigate with arrows, kill with k, inspect with Enter
    - Shows both subagents and bash commands
    """

    # CSS is defined in textual_chat_app.py for consistency
    DEFAULT_CSS = ""

    def __init__(
        self,
        on_kill_process: Callable[[str], None] | None = None,
        on_kill_agent: Callable[[str], None] | None = None,
        on_inspect: Callable[[str, str], None] | None = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._items: list[ActivityItem] = []
        self._selected_index: int = 0
        self._expanded: bool = False
        self._focused: bool = False
        self._on_kill_process = on_kill_process
        self._on_kill_agent = on_kill_agent
        self._on_inspect = on_inspect

    def update_activity(
        self,
        processes: list[RunningProcess] | None = None,
        subagents: list[SubagentSession] | None = None,
    ) -> None:
        """Update the activity list from processes and subagents."""
        self._items = []

        # Add subagents (all, not just running - user may want to see completed too)
        if subagents:
            for sa in subagents:
                self._items.append(
                    ActivityItem(
                        id=sa.task_tool_call_id,
                        type="agent",
                        name=sa.agent_name,
                        status=sa.status,
                        started_at=sa.started_at,
                        detail=sa.prompt[:50] + "..." if len(sa.prompt) > 50 else sa.prompt,
                    )
                )

        # Add running processes
        if processes:
            for proc in processes:
                self._items.append(
                    ActivityItem(
                        id=proc.tool_call_id,
                        type="tool",
                        name="bash",
                        status="running",
                        started_at=proc.started_at,
                        detail=proc.command[:50] + "..."
                        if len(proc.command) > 50
                        else proc.command,
                        output_preview=proc.output_buffer[-3:] if proc.output_buffer else None,
                    )
                )

        # Sort by start time (newest first)
        self._items.sort(key=lambda x: x.started_at, reverse=True)

        # Keep selection in bounds
        if self._items:
            self._selected_index = min(self._selected_index, len(self._items) - 1)
        else:
            self._selected_index = 0
            self._expanded = False

        # Show/hide based on activity
        if not self._items:
            self.add_class("no-activity")
            self.remove_class("collapsed")
        else:
            self.remove_class("no-activity")
            # Start collapsed when items appear
            if not self._expanded:
                self.add_class("collapsed")
            else:
                self.remove_class("collapsed")

        # Refresh content only (layout=False avoids expensive full recalculation)
        try:
            self.refresh()
        except Exception:
            pass  # Widget may not be mounted yet

    @property
    def is_expanded(self) -> bool:
        return self._expanded

    @property
    def is_focused(self) -> bool:
        return self._focused

    def set_focused(self, focused: bool) -> None:
        """Set focus state."""
        self._focused = focused
        if focused and self._items:
            self._expanded = True
        self.refresh()

    def expand(self) -> None:
        """Expand the activity bar."""
        if self._items:
            self._expanded = True
            self._focused = True
            self.remove_class("collapsed")
            self.refresh()

    def collapse(self) -> None:
        """Collapse the activity bar."""
        self._expanded = False
        self._focused = False
        if self._items:
            self.add_class("collapsed")
        self.refresh()

    def toggle_expand(self) -> None:
        """Toggle expanded state."""
        if self._expanded:
            self.collapse()
        else:
            self.expand()

    def select_next(self) -> None:
        """Select next item."""
        if self._items and self._selected_index < len(self._items) - 1:
            self._selected_index += 1
            self.refresh()

    def select_prev(self) -> None:
        """Select previous item."""
        if self._items and self._selected_index > 0:
            self._selected_index -= 1
            self.refresh()

    def kill_selected(self) -> bool:
        """Kill the selected item. Returns True if action taken."""
        if not self._items or self._selected_index >= len(self._items):
            return False

        item = self._items[self._selected_index]
        if item.type == "agent" and self._on_kill_agent:
            self._on_kill_agent(item.id)
            return True
        elif item.type == "tool" and self._on_kill_process:
            self._on_kill_process(item.id)
            return True
        return False

    def inspect_selected(self) -> None:
        """Inspect the selected item."""
        if not self._items or self._selected_index >= len(self._items):
            return

        item = self._items[self._selected_index]
        if self._on_inspect:
            self._on_inspect(item.id, item.type)

    @property
    def has_activity(self) -> bool:
        """Check if there's any activity."""
        return len(self._items) > 0

    @property
    def agent_count(self) -> int:
        """Count of running agents."""
        return sum(1 for i in self._items if i.type == "agent")

    @property
    def tool_count(self) -> int:
        """Count of running tools."""
        return sum(1 for i in self._items if i.type == "tool")

    def render(self) -> RenderableType:
        """Render the activity bar."""
        if not self._items:
            return Text("")

        # Collapsed view - single line summary
        if not self._expanded:
            line = Text()
            line.append("● ", style=BRAND)

            parts = []
            if self.agent_count > 0:
                parts.append(f"{self.agent_count} agent{'s' if self.agent_count > 1 else ''}")
            if self.tool_count > 0:
                parts.append(f"{self.tool_count} tool{'s' if self.tool_count > 1 else ''}")

            line.append(", ".join(parts) + " running", style=SUCCESS)
            line.append("  ↓ expand", style=TEXT_DIM)
            return line

        # Expanded view
        parts = []

        # Header - cleaner design
        header = Text()
        header.append("Activity ", style=f"{BRAND} bold")
        header.append(f"({len(self._items)}) ", style=TEXT_MUTED)
        header.append("  ", style="")
        header.append("↑↓", style=BRAND)
        header.append(" nav  ", style=TEXT_DIM)
        header.append("k", style=ERROR)
        header.append(" kill  ", style=TEXT_DIM)
        header.append("enter", style=BRAND)
        header.append(" inspect  ", style=TEXT_DIM)
        header.append("esc", style=WARNING)
        header.append(" close", style=TEXT_DIM)
        parts.append(header)

        # Items (show up to 8)
        visible_items = self._items[:8]
        for i, item in enumerate(visible_items):
            is_selected = i == self._selected_index and self._focused

            line = Text()

            # Selection indicator
            if is_selected:
                line.append("▸ ", style=f"{BRAND} bold")
            else:
                line.append("  ")

            # Type icon - dots for consistency
            if item.type == "agent":
                line.append("● ", style=BRAND_LIGHT)
            else:
                line.append("● ", style=INFO)

            # Elapsed time
            elapsed = format_elapsed(item.elapsed_seconds)
            line.append(f"{elapsed:>5} ", style=TEXT_MUTED)

            # Name/command
            style = "bold" if is_selected else ""
            if item.type == "agent":
                line.append(f"{item.name}: ", style=f"{BRAND_LIGHT} {style}")
                line.append(item.detail[:40], style=style if style else TEXT)
            else:
                line.append(item.detail[:55], style=style if style else TEXT)

            parts.append(line)

            # Show output preview for selected tool
            if is_selected and item.output_preview:
                for out_line in item.output_preview[-2:]:
                    preview = Text()
                    preview.append("     │ ", style=TEXT_DIM)
                    display = out_line.rstrip()[:60]
                    preview.append(display, style=TEXT_MUTED)
                    parts.append(preview)

        if len(self._items) > 8:
            more = Text()
            more.append(f"  ... and {len(self._items) - 8} more", style=TEXT_DIM)
            parts.append(more)

        return Group(*parts)
