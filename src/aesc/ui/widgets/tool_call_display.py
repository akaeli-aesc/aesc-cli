"""Modern tool call display widget - Claude Code inspired design.

Design principles:
- Clean, minimal aesthetic with subtle indicators
- IN/OUT labels for input/output sections
- Muted color palette (no harsh reds/greens)
- Collapsible sections with smooth transitions
- Clear visual hierarchy
"""

from __future__ import annotations

from enum import Enum, auto
from typing import TYPE_CHECKING

from rich.console import Group, RenderableType
from rich.spinner import Spinner
from rich.text import Text

from aesc.provider import ToolCall, ToolOk
from aesc.tools import extract_key_argument

if TYPE_CHECKING:
    from aesc.provider import ToolReturnType


# Modern color palette - softer, more professional
COLORS = {
    "brand": "#a855f7",  # Purple - brand accent
    "success": "#4ade80",  # Soft green
    "error": "#f87171",  # Soft red
    "warning": "#fbbf24",  # Soft amber
    "running": "#60a5fa",  # Soft blue
    "muted": "#71717a",  # Zinc-500
    "dim": "#52525b",  # Zinc-600
    "text": "#d4d4d8",  # Zinc-300
    "label": "#a1a1aa",  # Zinc-400 for IN/OUT labels
}

# Display width limits
MAX_KEY_ARG_WIDTH = 60  # Truncation width for key argument in descriptions
MAX_CMD_WIDTH = 80  # Truncation width for command displays
MAX_LINE_WIDTH = 100  # Truncation width for output lines

# Output truncation settings
MAX_OUTPUT_LINES = 100  # Maximum lines to show in expanded output
MAX_OUTPUT_CHARS = 10000  # Maximum characters to show
HEAD_LINES = 40  # Lines to show from start
TAIL_LINES = 20  # Lines to show from end


def truncate_output(
    output: str, max_lines: int = MAX_OUTPUT_LINES, max_chars: int = MAX_OUTPUT_CHARS
) -> str:
    """
    Truncate large output showing head + tail with elided middle.

    Shows first HEAD_LINES and last TAIL_LINES with "... [N lines omitted] ..." in between.
    Also respects max_chars limit.

    Args:
        output: The output string to truncate.
        max_lines: Maximum total lines to show.
        max_chars: Maximum total characters to show.

    Returns:
        Truncated output with omission message if needed.
    """
    if not output:
        return output

    # First check character limit
    if len(output) > max_chars:
        # Truncate by characters, preserving end
        head_chars = max_chars * 2 // 3  # 2/3 for head
        tail_chars = max_chars // 3  # 1/3 for tail
        omitted = len(output) - max_chars
        output = (
            output[:head_chars]
            + f"\n... [{omitted:,} characters omitted] ...\n"
            + output[-tail_chars:]
        )

    # Then check line limit
    lines = output.split("\n")
    if len(lines) <= max_lines:
        return output

    # Guard: if the output is no longer than head+tail, eliding would yield a
    # negative omit count and MORE lines than the input — return it unchanged.
    if len(lines) <= HEAD_LINES + TAIL_LINES:
        return output

    # Show head + tail with omission message
    omitted_lines = len(lines) - HEAD_LINES - TAIL_LINES
    truncated = (
        "\n".join(lines[:HEAD_LINES])
        + f"\n... [{omitted_lines:,} lines omitted] ...\n"
        + "\n".join(lines[-TAIL_LINES:])
    )
    return truncated


class ToolState(Enum):
    """Tool execution state for display purposes."""

    PENDING = auto()  # Tool call received, waiting for approval or starting
    APPROVED = auto()  # Approved, about to execute
    RUNNING = auto()  # Currently executing
    FINISHED = auto()  # Execution complete


class ToolCallDisplay:
    """
    Professional tool call visualization with collapsible output.

    States:
    - Pending: Shows "⋯ <tool> (<key_arg>)" - waiting for approval
    - Approved: Shows "✓ Approved: <description>" - brief confirmation
    - Running: Shows "⟳ Running <tool>..." with spinner and live output (collapsed)
    - Complete (collapsed): Shows "✓ <tool> (<key_arg>) - <brief>" with expand hint
    - Complete (expanded): Shows full output
    """

    def __init__(self, tool_call: ToolCall):
        self.tool_call = tool_call
        self.tool_name = tool_call.function.name

        # Extract key argument from tool call
        # tool_call.function.arguments is a JSON string (may be None during streaming)
        try:
            extracted = extract_key_argument(tool_call.function.arguments, self.tool_name)
            self.key_arg = extracted if extracted else ""
        except (ValueError, KeyError, AttributeError, TypeError):
            # Fallback: try to parse arguments dict
            import json

            try:
                if isinstance(tool_call.function.arguments, str):
                    args = json.loads(tool_call.function.arguments)
                else:
                    args = tool_call.function.arguments
                # Simple fallback: use first value (with safe access)
                if args:
                    values_list = list(args.values())
                    self.key_arg = str(values_list[0]) if values_list else ""
                else:
                    self.key_arg = ""
            except (json.JSONDecodeError, ValueError, IndexError, TypeError):
                self.key_arg = ""

        self.result: ToolReturnType | None = None
        # Start RUNNING - changes to PENDING only if approval requested
        self.state = ToolState.RUNNING
        self.finished = False
        self.expanded = False  # Collapsed by default
        self._spinner = Spinner("dots", text="")
        self._running_spinner = Spinner("dots", text="")
        self._frame_count = 0  # For manual spinner animation

        # Timing
        import time

        self._start_time = time.time()

        # Live output streaming
        self._live_output: str = ""
        self._show_live_output = True  # Expanded by default - show real-time output

        # Subagent tracking (for Task tool)
        self._subagent_tools: list[tuple[ToolCall, ToolReturnType | None]] = []
        self._subagent_output: str = ""
        self._subagent_thinking: str = ""
        self._subagent_live_outputs: dict[str, str] = {}  # Live output per tool_call_id
        self._subagent_tool_start: dict[str, float] = {}  # Start time per subagent tool
        self._subagent_render_cache: dict[str, Text] = {}  # Cache finished tool renders
        self._show_expanded_subagent = True  # Show all subagent tools by default
        self._subagent_name: str | None = None  # Name of the delegated subagent
        self._subagent_launching: bool = False  # True during subagent cold start

    def set_subagent_name(self, name: str) -> None:
        """Set the subagent name for Task tool display."""
        self._subagent_name = name

    def set_subagent_launching(self, launching: bool) -> None:
        """Set whether the subagent is in cold start phase."""
        self._subagent_launching = launching

    def render_live(self) -> RenderableType:
        """
        Render based on current state - Claude Code inspired design.

        - PENDING: "△ Tool  Description" - waiting for approval (amber)
        - RUNNING: "● Tool  Description" with spinner (blue)
        """
        if self.state == ToolState.RUNNING:
            return self._render_running()

        # PENDING state - waiting for approval
        import time

        # Calculate elapsed time
        elapsed = time.time() - self._start_time
        elapsed_str = self._format_elapsed(elapsed)

        # Build clean header: △ Bash  Command description
        parts = []
        header = Text()
        header.append("△ ", style=f"{COLORS['warning']} bold")
        header.append(f"{self.tool_name}", style="bold")
        header.append("  ", style="")

        # Add description/key_arg
        if self.key_arg:
            desc = (
                self.key_arg[:MAX_KEY_ARG_WIDTH] + "..."
                if len(self.key_arg) > MAX_KEY_ARG_WIDTH
                else self.key_arg
            )
            header.append(desc, style=COLORS["muted"])
        else:
            header.append("Waiting for approval", style=COLORS["muted"])
        parts.append(header)

        # Show input section with IN label (like Claude Code)
        if self.key_arg and self.tool_name == "Bash":
            in_section = Text()
            in_section.append("  IN   ", style=f"{COLORS['label']}")
            in_section.append(self.key_arg[:MAX_LINE_WIDTH], style=COLORS["text"])
            if len(self.key_arg) > 100:
                in_section.append("...", style=COLORS["dim"])
            parts.append(in_section)

        # Approval hint - subtle, not screaming
        hint = Text()
        hint.append("       ", style="")  # Indent
        hint.append("y", style=f"{COLORS['success']}")
        hint.append("·approve  ", style=COLORS["dim"])
        hint.append("n", style=f"{COLORS['error']}")
        hint.append("·reject  ", style=COLORS["dim"])
        hint.append("a", style=f"{COLORS['brand']}")
        hint.append("·all", style=COLORS["dim"])
        parts.append(hint)

        # Show subagent activity if Task tool
        if self._subagent_tools or self._subagent_output:
            parts.append(self._render_subagent_activity())

        return Group(*parts)

    def _format_elapsed(self, elapsed: float) -> str:
        """Format elapsed time in a clean way."""
        if elapsed < 60:
            return f"{int(elapsed)}s"
        elif elapsed < 3600:
            mins = int(elapsed // 60)
            secs = int(elapsed % 60)
            return f"{mins}m {secs}s"
        else:
            hours = int(elapsed // 3600)
            mins = int((elapsed % 3600) // 60)
            return f"{hours}h {mins}m"

    def set_pending(self) -> None:
        """Mark tool as waiting for approval."""
        self.state = ToolState.PENDING

    def set_running(self) -> None:
        """Mark tool as actively running (after approval or when no approval needed)."""
        self.state = ToolState.RUNNING

    def update_key_arg(self, arguments: str | None) -> None:
        """Update key_arg from tool call arguments (called when arguments become available)."""
        if self.key_arg:
            return  # Already have key_arg

        if not arguments:
            return

        try:
            extracted = extract_key_argument(arguments, self.tool_name)
            if extracted:
                self.key_arg = extracted
        except Exception:
            pass  # Keep existing (empty) key_arg

    def append_live_output(self, output: str) -> None:
        """Append streaming output from tool execution.

        The buffer is limited to prevent memory issues with long-running commands.
        Only the last MAX_OUTPUT_CHARS are kept.
        """
        self._live_output += output
        # Limit buffer size to prevent unbounded growth
        if len(self._live_output) > MAX_OUTPUT_CHARS * 2:
            # Keep last MAX_OUTPUT_CHARS
            self._live_output = "... [output truncated]\n" + self._live_output[-MAX_OUTPUT_CHARS:]

    def toggle_live_output(self) -> None:
        """Toggle live output expansion while running.

        For Task tools (with subagent activity), this toggles expanded subagent view.
        For other tools, this toggles live command output.
        """
        if self._subagent_tools or self._subagent_output:
            # Task tool - toggle expanded subagent view
            self._show_expanded_subagent = not self._show_expanded_subagent
        else:
            # Regular tool - toggle live output
            self._show_live_output = not self._show_live_output

    def render_complete(self) -> RenderableType:
        """
        Render after tool completes - Claude Code inspired design.

        Clean format:
        ● Bash  Command description  (2s)
          IN   command --flag
          OUT  output result...
        """
        import time

        self.state = ToolState.FINISHED
        success = isinstance(self.result, ToolOk) if self.result else False

        # Try to extract key_arg if still empty
        if not self.key_arg and self.tool_call.function.arguments:
            self.update_key_arg(self.tool_call.function.arguments)

        parts = []

        # Header: ● Bash  Description  (2s)
        header = Text()
        if success:
            header.append("● ", style=f"{COLORS['success']}")
        else:
            header.append("● ", style=f"{COLORS['error']}")

        header.append(f"{self.tool_name}", style="bold")
        header.append("  ", style="")

        # Add brief description
        if self.result:
            brief = getattr(self.result, "brief", "") or ""
            if brief:
                desc = (
                    brief[:MAX_KEY_ARG_WIDTH] + "..." if len(brief) > MAX_KEY_ARG_WIDTH else brief
                )
                header.append(desc, style=COLORS["muted"])
            elif self.key_arg:
                desc = (
                    self.key_arg[:MAX_KEY_ARG_WIDTH] + "..."
                    if len(self.key_arg) > MAX_KEY_ARG_WIDTH
                    else self.key_arg
                )
                header.append(desc, style=COLORS["muted"])

        # Elapsed time - subtle, right after description
        elapsed = time.time() - self._start_time
        if elapsed >= 1.0:  # Only show if >= 1 second
            header.append(f"  ({self._format_elapsed(elapsed)})", style=COLORS["dim"])
        parts.append(header)

        # IN section - show input for relevant tools
        show_in = (
            self.tool_name in ("Bash", "Read", "Write", "Grep", "Glob", "Task") and self.key_arg
        )
        if show_in:
            in_line = Text()
            in_line.append("  IN   ", style=COLORS["label"])
            cmd_display = (
                self.key_arg[:MAX_CMD_WIDTH] + "..."
                if len(self.key_arg) > MAX_CMD_WIDTH
                else self.key_arg
            )
            in_line.append(cmd_display, style=COLORS["text"])
            parts.append(in_line)

        # OUT section
        if self.result:
            output = getattr(self.result, "output", "") or ""
            message = getattr(self.result, "message", "") or ""

            if self.expanded:
                # Expanded: show full output
                if not success and message:
                    clean_msg = self._sanitize_error_msg(message)[:200]
                    err_line = Text()
                    err_line.append("  OUT  ", style=COLORS["label"])
                    err_line.append(clean_msg, style=COLORS["error"])
                    parts.append(err_line)

                if output.strip():
                    out_line = Text()
                    out_line.append("  OUT  ", style=COLORS["label"])
                    truncated = truncate_output(output)
                    # Show first part inline, rest indented
                    out_lines = truncated.split("\n")
                    out_line.append(out_lines[0][:100], style=COLORS["text"])
                    parts.append(out_line)
                    # Additional lines
                    for line in out_lines[1:20]:  # Limit to 20 lines
                        indent_line = Text()
                        indent_line.append("       ", style="")  # Align with OUT
                        indent_line.append(line[:100], style=COLORS["dim"])
                        parts.append(indent_line)
                    if len(out_lines) > 20:
                        more_line = Text()
                        more_line.append(
                            f"       ... {len(out_lines) - 20} more lines", style=COLORS["dim"]
                        )
                        parts.append(more_line)

                # Collapse hint
                hint = Text()
                hint.append("       ", style="")
                hint.append("Ctrl+O to collapse", style=COLORS["dim"])
                parts.append(hint)
            else:
                # Collapsed: show brief output preview
                content = output.strip() or self._sanitize_error_msg(message)
                if content:
                    out_line = Text()
                    out_line.append("  OUT  ", style=COLORS["label"])
                    # Show first line preview
                    first_line = content.split("\n")[0]
                    if len(first_line) > 60:
                        first_line = first_line[:60] + "..."
                    out_line.append(
                        first_line, style=COLORS["text"] if success else COLORS["error"]
                    )
                    parts.append(out_line)

                    # Expand hint if more content
                    has_more = content.count("\n") > 0 or len(content) > 60
                    if has_more:
                        hint = Text()
                        hint.append("       ", style="")
                        hint.append("Ctrl+O to expand", style=COLORS["dim"])
                        parts.append(hint)

        return Group(*parts)

    def toggle_expanded(self) -> None:
        """Toggle between collapsed and expanded state."""
        self.expanded = not self.expanded

    # --- Subagent support (for Task tool) ---

    def add_subagent_tool_call(self, tool_call: ToolCall) -> None:
        """Track a new tool call from a subagent."""
        import time

        self._subagent_tools.append((tool_call, None))
        self._subagent_tool_start[tool_call.id] = time.time()

    def finish_subagent_tool_call(self, result: ToolReturnType) -> None:
        """Mark a subagent tool call as finished with result."""
        # Find the matching tool call by id and update its result
        for i, (tc, _) in enumerate(self._subagent_tools):
            if tc.id == result.tool_call_id:
                self._subagent_tools[i] = (tc, result.result)
                break

    def update_subagent_tool_args(self, tool_call_part) -> None:
        """Update streaming arguments for the last subagent tool call."""
        if not self._subagent_tools:
            return

        # Get the last (most recent) tool call
        last_tc, result = self._subagent_tools[-1]
        if result is not None:
            return  # Already finished, don't update

        # Append arguments to the last tool call
        if tool_call_part.arguments_part:
            if last_tc.function.arguments is None:
                last_tc.function.arguments = tool_call_part.arguments_part
            else:
                last_tc.function.arguments += tool_call_part.arguments_part

    def append_subagent_output(self, text: str) -> None:
        """Append streaming text from subagent."""
        self._subagent_output += text

    def append_subagent_thinking(self, thought: str) -> None:
        """Append thinking from subagent."""
        self._subagent_thinking = thought  # Replace with latest thought

    def append_subagent_tool_output(self, chunk) -> None:
        """Append streaming output from a subagent's tool (e.g., Bash output).

        This enables real-time visibility of subagent tool execution.
        """
        tool_call_id = chunk.tool_call_id
        if tool_call_id not in self._subagent_live_outputs:
            self._subagent_live_outputs[tool_call_id] = ""
        self._subagent_live_outputs[tool_call_id] += chunk.chunk

    def _extract_subagent_key_arg(self, tool_call: ToolCall) -> str:
        """Extract the most relevant argument from a subagent tool call for display."""
        import json

        tool_name = tool_call.function.name
        args_str = tool_call.function.arguments

        if not args_str:
            return ""

        try:
            args = json.loads(args_str) if isinstance(args_str, str) else args_str
        except (json.JSONDecodeError, TypeError):
            return ""

        if not args:
            return ""

        # Tool-specific key argument extraction
        if tool_name == "Bash":
            return args.get("command", "")
        elif tool_name in ("Read", "Write"):
            return args.get("file_path", args.get("path", ""))
        elif tool_name == "Grep":
            pattern = args.get("pattern", "")
            path = args.get("path", "")
            return f"{pattern} in {path}" if path else pattern
        elif tool_name == "Glob":
            return args.get("pattern", "")
        elif tool_name == "MitreAttack":
            return args.get("query", args.get("technique_id", ""))
        elif tool_name == "KaliDocs":
            return args.get("tool", args.get("query", ""))
        elif tool_name == "Think":
            thought = args.get("thought", "")
            return thought[:100] + "..." if len(thought) > 100 else thought
        elif tool_name == "Task":
            return args.get("subagent_name", args.get("description", ""))
        elif tool_name == "FetchURL":
            return args.get("url", "")
        elif tool_name == "SearchWeb":
            return args.get("query", "")
        else:
            # Generic: return first string value
            for v in args.values():
                if isinstance(v, str) and v:
                    return v[:80]
            return ""

    def _render_running(self) -> RenderableType:
        """
        Render while tool is actively executing - Claude Code style.

        ● Bash  Running command...
          IN   command --flag
          OUT  live output streaming...
        """
        import time

        parts = []

        elapsed = time.time() - self._start_time
        elapsed_str = self._format_elapsed(elapsed)

        # Spinner animation
        spinner_frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        spinner_char = spinner_frames[self._frame_count % len(spinner_frames)]
        self._frame_count += 1

        # Header: ● Bash  Description
        header = Text()
        header.append(f"{spinner_char} ", style=f"{COLORS['running']}")
        header.append(f"{self.tool_name}", style="bold")
        header.append("  ", style="")

        # Description - show subagent name for Task tools
        if self.tool_name == "Task" and self._subagent_name:
            header.append(f"→ {self._subagent_name}", style=COLORS["brand"])
            if self.key_arg:
                desc = (
                    self.key_arg[:MAX_KEY_ARG_WIDTH] + "..."
                    if len(self.key_arg) > MAX_KEY_ARG_WIDTH
                    else self.key_arg
                )
                header.append(f"  {desc}", style=COLORS["muted"])
        elif self.key_arg:
            desc = (
                self.key_arg[:MAX_KEY_ARG_WIDTH] + "..."
                if len(self.key_arg) > MAX_KEY_ARG_WIDTH
                else self.key_arg
            )
            header.append(desc, style=COLORS["muted"])
        else:
            header.append("Running...", style=COLORS["muted"])

        # Elapsed time
        if elapsed >= 1.0:
            header.append(f"  ({elapsed_str})", style=COLORS["dim"])
        parts.append(header)

        # IN section (for Bash, show command)
        if self.tool_name == "Bash" and self.key_arg:
            in_line = Text()
            in_line.append("  IN   ", style=COLORS["label"])
            cmd_display = (
                self.key_arg[:MAX_CMD_WIDTH] + "..."
                if len(self.key_arg) > MAX_CMD_WIDTH
                else self.key_arg
            )
            in_line.append(cmd_display, style=COLORS["text"])
            parts.append(in_line)

        # Show subagent activity (for Task tool) — including launch state
        if self._subagent_tools or self._subagent_output or self._subagent_launching:
            parts.append(self._render_subagent_activity())

        # Live output streaming
        if self._live_output:
            lines = self._live_output.strip().split("\n")
            if self._show_live_output:
                # Expanded: show last 15 lines
                max_lines = 15
                display_lines = lines[-max_lines:] if len(lines) > max_lines else lines

                out_line = Text()
                out_line.append("  OUT  ", style=COLORS["label"])
                if len(lines) > max_lines:
                    out_line.append(
                        f"... {len(lines) - max_lines} lines above", style=COLORS["dim"]
                    )
                    parts.append(out_line)
                    for line in display_lines:
                        l = Text()
                        l.append("       ", style="")
                        l.append(line[:100], style=COLORS["text"])
                        parts.append(l)
                else:
                    out_line.append(
                        display_lines[0][:100] if display_lines else "", style=COLORS["text"]
                    )
                    parts.append(out_line)
                    for line in display_lines[1:]:
                        l = Text()
                        l.append("       ", style="")
                        l.append(line[:100], style=COLORS["text"])
                        parts.append(l)

                hint = Text()
                hint.append("       ", style="")
                hint.append("Ctrl+O to collapse", style=COLORS["dim"])
                parts.append(hint)
            else:
                # Collapsed: show last 2 lines
                display_lines = lines[-2:] if len(lines) > 2 else lines
                out_line = Text()
                out_line.append("  OUT  ", style=COLORS["label"])
                out_line.append(
                    display_lines[-1][:60] if display_lines else "", style=COLORS["text"]
                )
                parts.append(out_line)

                if len(lines) > 2:
                    hint = Text()
                    hint.append("       ", style="")
                    hint.append("Ctrl+O to expand", style=COLORS["dim"])
                    parts.append(hint)

        return Group(*parts)

    @staticmethod
    def _sanitize_error_msg(msg: str) -> str:
        """Strip raw JSON/bytes bodies from an error message for clean display."""
        for marker in (" - b'{", ' - b"', "\n{", '\n"error"'):
            if marker in msg:
                msg = msg[: msg.index(marker)]
                break
        return msg.strip()

    def _render_subagent_activity(self) -> RenderableType:
        """Render nested subagent tool calls with visual hierarchy.

        Features:
        - Summary line with completed/failed counts
        - Cached renders for finished tools (perf)
        - Elapsed time per tool
        - Clean error display (no raw JSON)
        """
        import time as _time

        lines: list[Text] = []

        # Show launch spinner during subagent cold start
        if self._subagent_launching and not self._subagent_tools:
            spinner_frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
            spinner = spinner_frames[self._frame_count % len(spinner_frames)]
            name = self._subagent_name or "subagent"
            launch_line = Text()
            launch_line.append(f"    {spinner} ", style=COLORS["running"])
            launch_line.append(f"Launching {name}...", style=COLORS["muted"])
            lines.append(launch_line)
            return Group(*lines)

        expanded = self._show_expanded_subagent
        # Determine how many tools to show
        if expanded:
            tools_to_show = self._subagent_tools
            arg_limit = 200
        else:
            tools_to_show = self._subagent_tools[-3:]  # Compact: only last 3
            arg_limit = 80

        # Show subagent tool calls
        for tool_call, result in tools_to_show:
            # Use cached render for finished tools (they never change)
            if result is not None and tool_call.id in self._subagent_render_cache:
                lines.append(self._subagent_render_cache[tool_call.id])
                continue

            tool_name = tool_call.function.name
            key_arg = self._extract_subagent_key_arg(tool_call)

            if result is None:
                # Still running — animated indicator
                line = Text()
                line.append("    ○ ", style=COLORS["running"])
                line.append(f"{tool_name}", style="bold")
                if key_arg:
                    display_arg = (
                        key_arg[:arg_limit] + "..." if len(key_arg) > arg_limit else key_arg
                    )
                    line.append(f"  {display_arg}", style=COLORS["muted"])
                # Show running elapsed
                start = self._subagent_tool_start.get(tool_call.id)
                if start:
                    elapsed = _time.time() - start
                    if elapsed >= 1.0:
                        line.append(f"  ({self._format_elapsed(elapsed)})", style=COLORS["dim"])
                lines.append(line)

                # Show live output
                live_output = self._subagent_live_outputs.get(tool_call.id, "")
                if live_output:
                    output_lines = live_output.strip().split("\n")
                    max_lines = 5 if expanded else 2
                    for out_line in output_lines[-max_lines:]:
                        l = Text()
                        l.append("      OUT  ", style=COLORS["label"])
                        l.append(out_line[:80], style=COLORS["text"])
                        lines.append(l)
            else:
                # Finished — cached after first render
                success = isinstance(result, ToolOk)
                line = Text()
                line.append("    ● ", style=COLORS["success"] if success else COLORS["error"])
                line.append(f"{tool_name}", style="bold")

                brief = getattr(result, "brief", "") or ""
                message = getattr(result, "message", "") or ""

                if key_arg:
                    disp_limit = arg_limit if expanded else 60
                    display_arg = (
                        key_arg[:disp_limit] + "..." if len(key_arg) > disp_limit else key_arg
                    )
                    line.append(f"  {display_arg}", style=COLORS["muted"])
                elif not success and message:
                    # Show clean error summary inline
                    clean = self._sanitize_error_msg(message)[:80]
                    line.append(f"  {clean}", style=COLORS["error"])
                elif brief:
                    brief_limit = 100 if expanded else 50
                    display_brief = (
                        brief[:brief_limit] + "..." if len(brief) > brief_limit else brief
                    )
                    line.append(f"  {display_brief}", style=COLORS["muted"])

                # Elapsed time for finished tool
                start = self._subagent_tool_start.get(tool_call.id)
                if start:
                    elapsed = _time.time() - start
                    if elapsed >= 1.0:
                        line.append(f"  ({self._format_elapsed(elapsed)})", style=COLORS["dim"])

                lines.append(line)

                # In expanded mode, show output (but NOT for errors — already shown inline)
                if expanded and success:
                    out = getattr(result, "output", "") or ""
                    if out and isinstance(out, str):
                        for out_line in out.strip().split("\n")[:3]:
                            l = Text()
                            l.append("      OUT  ", style=COLORS["label"])
                            l.append(out_line[:80], style=COLORS["text"])
                            lines.append(l)

                # Cache this finished tool's render
                self._subagent_render_cache[tool_call.id] = line

        # Summary counter with failed count
        total = len(self._subagent_tools)
        if total > 0:
            running = sum(1 for _, r in self._subagent_tools if r is None)
            failed = sum(
                1 for _, r in self._subagent_tools if r is not None and not isinstance(r, ToolOk)
            )
            completed = total - running
            summary = Text()
            summary.append("    ", style="")
            summary.append(f"{completed}/{total}", style=COLORS["muted"])
            summary.append(" tools completed", style=COLORS["dim"])
            if failed > 0:
                summary.append(f"  {failed} failed", style=COLORS["error"])
            if running > 0:
                summary.append(f", {running} running", style=COLORS["running"])
            lines.insert(0, summary)

        # Show how many tools were hidden
        if not expanded and len(self._subagent_tools) > 3:
            hidden = len(self._subagent_tools) - 3
            hidden_line = Text()
            hidden_line.append(f"    ... {hidden} more above", style=COLORS["dim"])
            lines.insert(1 if total > 0 else 0, hidden_line)

        # Show subagent thinking - collapsible style
        if self._subagent_thinking:
            thought = self._subagent_thinking
            thought_limit = 200 if expanded else 100
            thought = thought[:thought_limit] + "..." if len(thought) > thought_limit else thought
            think_line = Text()
            think_line.append("    Thinking ", style=COLORS["brand"])
            think_line.append("∨", style=COLORS["dim"])
            lines.append(think_line)
            thought_text = Text()
            thought_text.append("      ", style="")
            thought_text.append(thought, style=COLORS["muted"])
            lines.append(thought_text)

        # Show subagent text output
        output_limit = 5 if expanded else 2
        if self._subagent_output:
            for raw_line in self._subagent_output.strip().split("\n")[-output_limit:]:
                line_limit = 120 if expanded else 60
                raw_line = raw_line[:line_limit] + "..." if len(raw_line) > line_limit else raw_line
                l = Text()
                l.append("    ", style="")
                l.append(raw_line, style=COLORS["text"])
                lines.append(l)

        # Toggle hint
        if self._subagent_tools:
            hint = Text()
            hint.append("    ", style="")
            if expanded:
                hint.append("Ctrl+O to collapse", style=COLORS["dim"])
            else:
                hint.append("Ctrl+O to expand", style=COLORS["dim"])
            lines.append(hint)

        return Group(*lines) if lines else Text("")
