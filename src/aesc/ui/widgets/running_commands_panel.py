"""Running Commands Panel - Shows active commands with inspect/kill functionality.

Displays running commands below the prompt area with:
- Navigation with arrow keys (when focused)
- Kill with 'k' key
- Inspect output by selecting a command
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from rich.console import Group, RenderableType
from rich.text import Text
from textual.widgets import Static

if TYPE_CHECKING:
    from aesc.tools.process_registry import RunningProcess


def format_elapsed(seconds: float) -> str:
    """Format elapsed time as human-readable string."""
    if seconds < 60:
        return f"{int(seconds)}s"
    elif seconds < 3600:
        mins = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{mins}m {secs}s"
    else:
        hours = int(seconds // 3600)
        mins = int((seconds % 3600) // 60)
        return f"{hours}h {mins}m"


def truncate_command(cmd: str, max_len: int = 60) -> str:
    """Truncate command string for display."""
    if len(cmd) <= max_len:
        return cmd
    return cmd[: max_len - 3] + "..."


class RunningCommandsPanel(Static):
    """
    Panel showing running commands with navigation and kill support.

    Features:
    - Shows up to 5 most recent running commands
    - Arrow keys navigate between commands
    - 'k' key kills selected command
    - Shows command, elapsed time, and brief output preview

    The panel appears below the chat input when commands are running.
    """

    # CSS is defined in TextualChatApp.CSS for consistent styling
    DEFAULT_CSS = ""

    def __init__(
        self,
        on_kill: Callable[[str], None] | None = None,
        on_inspect: Callable[[str], None] | None = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._processes: list[RunningProcess] = []
        self._selected_index: int = 0
        self._on_kill = on_kill
        self._on_inspect = on_inspect
        self._expanded_tool_call_id: str | None = None  # For expanded output view

    def update_processes(self, processes: list[RunningProcess]) -> None:
        """Update the list of running processes."""
        self._processes = processes

        # Keep selection in bounds
        if self._processes:
            self._selected_index = min(self._selected_index, len(self._processes) - 1)
        else:
            self._selected_index = 0
            self._expanded_tool_call_id = None

        # Hide/show based on process count
        if not self._processes:
            self.add_class("hidden")
        else:
            self.remove_class("hidden")

        self.refresh()

    def select_next(self) -> None:
        """Select next command."""
        if self._processes and self._selected_index < len(self._processes) - 1:
            self._selected_index += 1
            self.refresh()

    def select_prev(self) -> None:
        """Select previous command."""
        if self._processes and self._selected_index > 0:
            self._selected_index -= 1
            self.refresh()

    def kill_selected(self) -> bool:
        """Kill the selected command. Returns True if killed."""
        if not self._processes:
            return False

        if 0 <= self._selected_index < len(self._processes):
            proc = self._processes[self._selected_index]
            if self._on_kill:
                self._on_kill(proc.tool_call_id)
                return True
        return False

    def toggle_expanded(self) -> None:
        """Toggle expanded output view for selected command."""
        if not self._processes:
            return

        if 0 <= self._selected_index < len(self._processes):
            proc = self._processes[self._selected_index]
            if self._expanded_tool_call_id == proc.tool_call_id:
                self._expanded_tool_call_id = None
            else:
                self._expanded_tool_call_id = proc.tool_call_id
            self.refresh()

    def inspect_selected(self) -> None:
        """Inspect the selected command (show full output)."""
        if not self._processes:
            return

        if 0 <= self._selected_index < len(self._processes):
            proc = self._processes[self._selected_index]
            if self._on_inspect:
                self._on_inspect(proc.tool_call_id)

    @property
    def has_processes(self) -> bool:
        """Check if there are any running processes."""
        return len(self._processes) > 0

    @property
    def selected_tool_call_id(self) -> str | None:
        """Get the tool call ID of the selected process."""
        if self._processes and 0 <= self._selected_index < len(self._processes):
            return self._processes[self._selected_index].tool_call_id
        return None

    def render(self) -> RenderableType:
        """Render the panel."""
        if not self._processes:
            return Text("")

        parts = []

        # Header
        header = Text()
        header.append("Running Commands ", style="bold cyan")
        header.append(f"({len(self._processes)})", style="grey50")
        header.append("  [", style="dim")
        header.append("\u2191\u2193", style="cyan")
        header.append(" navigate  ", style="dim")
        header.append("k", style="red bold")
        header.append(" kill  ", style="dim")
        header.append("Enter", style="cyan")
        header.append(" inspect]", style="dim")
        parts.append(header)

        # Command list
        for i, proc in enumerate(self._processes[-5:]):  # Show last 5
            actual_idx = len(self._processes) - 5 + i if len(self._processes) > 5 else i
            is_selected = actual_idx == self._selected_index
            is_expanded = proc.tool_call_id == self._expanded_tool_call_id

            line = Text()

            # Selection indicator
            if is_selected:
                line.append("\u25b6 ", style="cyan bold")
            else:
                line.append("  ", style="dim")

            # Elapsed time
            elapsed = format_elapsed(proc.elapsed_seconds)
            line.append(f"[{elapsed:>6}] ", style="yellow")

            # Command (truncated)
            cmd_display = truncate_command(proc.command, 50)
            style = "bold" if is_selected else ""
            line.append(cmd_display, style=style)

            parts.append(line)

            # Show expanded output if selected and expanded
            if is_expanded and proc.output_buffer:
                # Show last 3 lines of output
                for out_line in proc.output_buffer[-3:]:
                    out_text = Text()
                    out_text.append("         ", style="dim")  # Indent
                    display_line = out_line.rstrip()[:70]
                    if len(out_line.rstrip()) > 70:
                        display_line += "..."
                    out_text.append(display_line, style="grey50")
                    parts.append(out_text)

        return Group(*parts)
