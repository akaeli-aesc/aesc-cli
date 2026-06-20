"""Enhanced Prompt Bar - Professional 3-line input with status.

Layout (3-line design):
┌────────────────────────────────────────────────────────────────────────────┐
│ ◆ AESC ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ ◉2 agents  ●3 tools ━━ │
│ › [input field                                                           ] │
│ ↓:activity  ^H:help  ESC:stop                             ctx: 45% ██░░░░ │
└────────────────────────────────────────────────────────────────────────────┘

Features:
- Line 1: Brand + activity summary (running agents/tools)
- Line 2: Clean input with minimal prefix
- Line 3: Hints + context usage bar
"""

from __future__ import annotations

from rich.console import RenderableType
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.reactive import reactive
from textual.widgets import Input, Static

from aesc.ui.widgets.theme import BRAND_LIGHT, TEXT
from aesc.ui.widgets.theme import COLORS as THEME_COLORS

# Single source of truth: derive from the canonical theme palette (theme.py)
# so the prompt bar never drifts from the rest of the UI. Two prompt-bar-only
# accents are added on top.
COLORS = {
    **THEME_COLORS,
    "agent": BRAND_LIGHT,  # light purple - agents
    "highlight": TEXT,  # bright primary text - highlights
}


class StatusLine(Static):
    """Top line: Brand + activity indicators."""

    DEFAULT_CSS = """
    StatusLine {
        width: 100%;
        height: 1;
        padding: 0 1;
    }
    """

    agent_count: reactive[int] = reactive(0)
    tool_count: reactive[int] = reactive(0)
    is_thinking: reactive[bool] = reactive(False)
    current_task: reactive[str] = reactive("")

    def render(self) -> RenderableType:
        line = Text()

        # Brand section - AESC branding
        line.append("◆ ", style=f"{COLORS['brand']} bold")
        line.append("AESC", style=f"{COLORS['brand']} bold")
        line.append(" ", style=COLORS["dim"])

        # Current task (if any)
        if self.current_task:
            task_display = self.current_task[:40]
            if len(self.current_task) > 40:
                task_display += "…"
            line.append("› ", style=COLORS["dim"])
            line.append(task_display, style=COLORS["text"])
            line.append(" ", style=COLORS["dim"])

        # Fill with line — use actual terminal width if available
        used = len(line.plain)
        activity_width = 25  # Approximate space for activity indicators
        total_width = self.size.width if self.size.width > 0 else 60
        fill_width = max(1, total_width - used - activity_width)
        line.append("━" * fill_width, style=COLORS["brand_dim"])

        # Activity indicators (right side)
        if self.is_thinking:
            line.append(" ⠋ ", style=f"{COLORS['brand']} bold")

        if self.agent_count > 0:
            line.append(f" ◉{self.agent_count}", style=f"{COLORS['agent']} bold")
            if self.agent_count == 1:
                line.append(" agent", style=COLORS["dim"])
            else:
                line.append(" agents", style=COLORS["dim"])

        if self.tool_count > 0:
            line.append(f" ●{self.tool_count}", style=f"{COLORS['success']} bold")
            if self.tool_count == 1:
                line.append(" tool", style=COLORS["dim"])
            else:
                line.append(" tools", style=COLORS["dim"])

        if self.agent_count == 0 and self.tool_count == 0 and not self.is_thinking:
            line.append(" ready", style=COLORS["dim"])

        line.append(" ━━", style=COLORS["brand_dim"])

        return line


class HintLine(Static):
    """Bottom line: Model info + context usage (OpenCode style)."""

    DEFAULT_CSS = """
    HintLine {
        width: 100%;
        height: 1;
        padding: 0 1;
    }
    """

    context_percent: reactive[int] = reactive(0)
    has_activity: reactive[bool] = reactive(False)
    is_running: reactive[bool] = reactive(False)
    model_name: reactive[str] = reactive("")
    max_context: reactive[int] = reactive(0)

    def render(self) -> RenderableType:
        line = Text()

        # Model info (left side) - OpenCode style
        if self.model_name:
            # Clean model name for display (remove provider prefix)
            display_model = self.model_name
            if "/" in display_model:
                display_model = display_model.split("/")[-1]
            # Truncate long names
            if len(display_model) > 25:
                display_model = display_model[:22] + "..."

            line.append("● ", style=COLORS["brand"])
            line.append(display_model, style=COLORS["text"])

            if self.max_context > 0:
                ctx_k = self.max_context // 1000
                line.append(f" ({ctx_k}K)", style=COLORS["dim"])

            line.append("  ", style="")

        # Running indicator
        if self.is_running:
            line.append("◉ running", style=COLORS["info"])
            line.append("  ", style="")

        # Keyboard hints
        if self.has_activity:
            line.append("↓", style=COLORS["warning"])
            line.append(":activity  ", style=COLORS["dim"])

        line.append("/help", style=COLORS["dim"])

        if self.is_running:
            line.append("  ESC", style=COLORS["warning"])
            line.append(":stop", style=COLORS["dim"])

        # Calculate spacing for right-aligned context — use actual width
        used = len(line.plain)
        ctx_width = 12  # "XX% used"
        total_width = self.size.width if self.size.width > 0 else 75
        spacing = max(1, total_width - used - ctx_width)
        line.append(" " * spacing)

        # Context usage (right side) - OpenCode style "XX% used"
        if self.context_percent >= 80:
            pct_color = COLORS["error"]
        elif self.context_percent >= 60:
            pct_color = COLORS["warning"]
        else:
            pct_color = COLORS["success"]

        line.append("◈ ", style=pct_color)
        line.append(f"{self.context_percent}% used", style=COLORS["dim"])

        return line


class PromptLine(Static):
    """Middle line: Just the prompt symbol."""

    DEFAULT_CSS = """
    PromptLine {
        width: auto;
        height: 1;
        padding: 0 0 0 1;
    }
    """

    def render(self) -> RenderableType:
        line = Text()
        line.append("› ", style=f"{COLORS['brand']} bold")
        return line


class EnhancedPromptBar(Vertical):
    """Professional 3-line prompt bar with status and context."""

    DEFAULT_CSS = """
    EnhancedPromptBar {
        width: 100%;
        height: 3;
        dock: bottom;
        background: $surface;
        padding: 0;
    }

    EnhancedPromptBar > Horizontal {
        width: 100%;
        height: 1;
    }

    EnhancedPromptBar Input {
        width: 1fr;
        height: 1;
        border: none;
        background: transparent;
        padding: 0;
    }

    EnhancedPromptBar Input:focus {
        border: none;
    }
    """

    def __init__(
        self,
        prefix: str = "user",  # Not used in new design but kept for API compat
        placeholder: str = "Send a message...",
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._placeholder = placeholder
        self._status_line: StatusLine | None = None
        self._hint_line: HintLine | None = None
        self._input: Input | None = None

    def compose(self) -> ComposeResult:
        # Line 1: Status
        self._status_line = StatusLine()
        yield self._status_line

        # Line 2: Input (with prompt prefix)
        # Note: We use the basic Input here. The ChatInput class from textual_chat_app
        # will be assigned to chat_input in on_mount for key handling.
        from textual.containers import Horizontal

        with Horizontal():
            yield PromptLine()
            self._input = Input(placeholder=self._placeholder, id="prompt-input")
            yield self._input

        # Line 3: Hints + context
        self._hint_line = HintLine()
        yield self._hint_line

    @property
    def input(self) -> Input | None:
        return self._input

    @property
    def value(self) -> str:
        return self._input.value if self._input else ""

    @value.setter
    def value(self, val: str) -> None:
        if self._input:
            self._input.value = val

    def clear(self) -> None:
        if self._input:
            self._input.value = ""

    def focus_input(self) -> None:
        if self._input:
            self._input.focus()

    def update_activity(
        self,
        tool_count: int = 0,
        agent_count: int = 0,
        is_thinking: bool = False,
        current_task: str = "",
    ) -> None:
        """Update activity indicators."""
        if self._status_line:
            self._status_line.tool_count = tool_count
            self._status_line.agent_count = agent_count
            self._status_line.is_thinking = is_thinking
            self._status_line.current_task = current_task

        if self._hint_line:
            self._hint_line.has_activity = (tool_count + agent_count) > 0
            self._hint_line.is_running = is_thinking or (tool_count + agent_count) > 0

    def update_context(self, percent: int) -> None:
        """Update context usage percentage."""
        if self._hint_line:
            self._hint_line.context_percent = max(0, min(100, percent))

    def set_current_task(self, task: str) -> None:
        """Set the current task description."""
        if self._status_line:
            self._status_line.current_task = task

    def set_model_info(self, model_name: str, max_context: int = 0) -> None:
        """Set model name and context size for display."""
        if self._hint_line:
            self._hint_line.model_name = model_name
            self._hint_line.max_context = max_context
