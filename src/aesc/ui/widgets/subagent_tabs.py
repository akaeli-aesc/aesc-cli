"""Subagent tabs widget for visualizing and controlling active subagents."""

from __future__ import annotations

from rich.console import RenderableType
from rich.text import Text
from textual.message import Message
from textual.reactive import reactive
from textual.widgets import Static


class SubagentTabSelected(Message):
    """Message sent when a subagent tab is selected."""

    def __init__(self, task_id: str, agent_name: str) -> None:
        super().__init__()
        self.task_id = task_id
        self.agent_name = agent_name


class SubagentTabs(Static):
    """Tab bar for subagents with main agent tab.

    Renders as a single line with clickable tabs.
    Uses Static + render() for simplicity and reliability.
    """

    DEFAULT_CSS = """
    SubagentTabs {
        width: 100%;
        height: 1;
        background: #1e1e2e;
        dock: top;
        padding: 0 1;
    }

    SubagentTabs.hidden {
        display: none;
    }
    """

    active_tab: reactive[str | None] = reactive(None)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._tabs: dict[str, dict] = {}  # task_id -> {name, status, index}

    def render(self) -> RenderableType:
        """Render the tab bar as a single line."""
        line = Text()

        # Main tab
        if self.active_tab is None:
            line.append(" [F1] Main ", style="bold white on #3a3a6a")
        else:
            line.append(" [F1] Main ", style="#888888 on #2a2a3a")

        # Subagent tabs
        for i, (task_id, info) in enumerate(self._tabs.items()):
            line.append(" ")

            # Status indicator
            status = info.get("status", "running")
            if status == "running":
                indicator = "●"
                status_style = "green"
            elif status == "completed":
                indicator = "✓"
                status_style = "blue"
            elif status == "failed" or status == "killed":
                indicator = "✗"
                status_style = "red"
            else:
                indicator = "○"
                status_style = "white"

            # Tab content
            fkey = f"F{i + 2}" if i < 8 else ""
            name = info.get("name", "agent")[:12]

            if self.active_tab == task_id:
                line.append(f"[{fkey}] {name} ", style="bold white on #3a3a6a")
                line.append(indicator, style=f"bold {status_style} on #3a3a6a")
            else:
                line.append(f"[{fkey}] {name} ", style="#888888 on #2a2a3a")
                line.append(indicator, style=f"{status_style} on #2a2a3a")

        return line

    def add_subagent(self, task_id: str, agent_name: str, status: str = "running") -> None:
        """Add a new subagent tab."""
        if task_id in self._tabs:
            # Update existing
            self._tabs[task_id]["status"] = status
            self.refresh()
            return

        self._tabs[task_id] = {
            "name": agent_name,
            "status": status,
            "index": len(self._tabs),
        }
        self.refresh()

    def remove_subagent(self, task_id: str) -> None:
        """Remove a subagent tab."""
        if task_id in self._tabs:
            del self._tabs[task_id]
            # Reindex remaining tabs
            for i, info in enumerate(self._tabs.values()):
                info["index"] = i
            self.refresh()

    def update_status(self, task_id: str, status: str) -> None:
        """Update a subagent's status."""
        if task_id in self._tabs:
            self._tabs[task_id]["status"] = status
            self.refresh()

    def select_tab(self, index: int) -> str | None:
        """Select a tab by index. Returns task_id or None for main."""
        if index == 0:
            # Main tab
            self._select_main()
            return None

        # Subagent tab (1-indexed for user, 0-indexed in dict)
        tabs = list(self._tabs.keys())
        if 0 < index <= len(tabs):
            task_id = tabs[index - 1]
            self._select_subagent(task_id)
            return task_id

        return None

    def _select_main(self) -> None:
        """Select the main tab."""
        self.active_tab = None
        self.refresh()
        self.post_message(SubagentTabSelected("", "main"))

    def _select_subagent(self, task_id: str) -> None:
        """Select a subagent tab."""
        self.active_tab = task_id
        self.refresh()
        if task_id in self._tabs:
            self.post_message(SubagentTabSelected(task_id, self._tabs[task_id]["name"]))

    def get_running_count(self) -> int:
        """Get count of running subagents."""
        return sum(1 for info in self._tabs.values() if info.get("status") == "running")

    def has_subagents(self) -> bool:
        """Check if there are any subagent tabs."""
        return len(self._tabs) > 0

    def clear(self) -> None:
        """Clear all subagent tabs."""
        self._tabs.clear()
        self._select_main()
