"""Loading Indicator - Animated spinner with status message.

Shows current activity with animated spinner, elapsed time, and cancel hint.
Claude Code inspired design with unified theme.

Usage:
    indicator = LoadingIndicator()
    indicator.set_task("Processing request...")
    indicator.clear()  # When done
"""

from datetime import datetime
from enum import Enum

from rich.console import RenderableType
from rich.text import Text
from textual.widgets import Static

from .theme import (
    BRAND,
    INFO,
    SPINNER_FRAMES,
    TEXT_MUTED,
    WARNING,
)


class StreamingState(Enum):
    """Current streaming/processing state."""

    IDLE = 0
    THINKING = 1  # LLM is generating response
    TOOL_RUNNING = 2  # Tool/command is executing
    WAITING_APPROVAL = 3  # Waiting for user approval


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


class LoadingIndicator(Static):
    """
    Animated loading indicator showing current task.

    Display format:
        ⠋ Thinking...  (2s)
        ⠙ Running nmap -sV 192.168.1.1  (5s, esc to cancel)
    """

    DEFAULT_CSS = """
    LoadingIndicator {
        width: 100%;
        height: 1;
        background: $surface;
        padding: 0 1;
    }

    LoadingIndicator.hidden {
        display: none;
    }
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._state = StreamingState.IDLE
        self._task_name: str = ""
        self._started_at: datetime | None = None
        self._spinner_frame: int = 0
        self._timer_handle = None

    def on_mount(self) -> None:
        """Start the spinner animation timer."""
        self._start_animation()

    def _start_animation(self) -> None:
        """Start spinner animation (updates every 200ms — sufficient for smooth spinners)."""
        if self._timer_handle is None:
            self._timer_handle = self.set_interval(0.2, self._advance_spinner)

    def _advance_spinner(self) -> None:
        """Advance spinner frame and refresh only when active (not idle)."""
        if self._state != StreamingState.IDLE:
            self._spinner_frame = (self._spinner_frame + 1) % len(SPINNER_FRAMES)
            self.refresh()

    def set_thinking(self) -> None:
        """Show thinking/processing state."""
        self._state = StreamingState.THINKING
        self._task_name = "Thinking..."
        self._started_at = datetime.now()
        self.remove_class("hidden")
        self.refresh()

    def set_tool_running(self, tool_name: str, command: str = "") -> None:
        """Show tool execution state."""
        self._state = StreamingState.TOOL_RUNNING
        if command:
            # Truncate long commands
            display_cmd = command[:60] + "..." if len(command) > 60 else command
            self._task_name = f"{tool_name}: {display_cmd}"
        else:
            self._task_name = f"Running {tool_name}..."
        self._started_at = datetime.now()
        self.remove_class("hidden")
        self.refresh()

    def set_waiting_approval(self) -> None:
        """Show waiting for approval state."""
        self._state = StreamingState.WAITING_APPROVAL
        self._task_name = "Waiting for approval..."
        self._started_at = datetime.now()
        self.remove_class("hidden")
        self.refresh()

    def clear(self) -> None:
        """Clear the indicator (task complete)."""
        self._state = StreamingState.IDLE
        self._task_name = ""
        self._started_at = None
        self.add_class("hidden")
        self.refresh()

    @property
    def elapsed_seconds(self) -> float:
        """Get elapsed time since task started."""
        if self._started_at is None:
            return 0.0
        return (datetime.now() - self._started_at).total_seconds()

    @property
    def is_active(self) -> bool:
        """Check if indicator is showing activity."""
        return self._state != StreamingState.IDLE

    def render(self) -> RenderableType:
        """Render the loading indicator."""
        if self._state == StreamingState.IDLE:
            return Text("")

        line = Text()

        # Spinner
        spinner = SPINNER_FRAMES[self._spinner_frame]

        # Color based on state - using unified theme colors
        if self._state == StreamingState.THINKING:
            line.append(f"{spinner} ", style=BRAND)
            line.append(self._task_name, style=BRAND)
        elif self._state == StreamingState.TOOL_RUNNING:
            line.append(f"{spinner} ", style=INFO)
            line.append(self._task_name, style=INFO)
        elif self._state == StreamingState.WAITING_APPROVAL:
            line.append(f"{spinner} ", style=WARNING)
            line.append(self._task_name, style=f"{WARNING} bold")

        # Elapsed time - subtle
        elapsed_str = format_elapsed(self.elapsed_seconds)
        line.append(f"  ({elapsed_str}", style=TEXT_MUTED)

        # Cancel hint for long-running tasks
        if self._state == StreamingState.TOOL_RUNNING and self.elapsed_seconds > 2:
            line.append(", esc to cancel", style=TEXT_MUTED)

        line.append(")", style=TEXT_MUTED)

        return line
