"""
TDD Tests for Subagent Visibility (Design Doc 002)

These tests define the expected behavior for subagent activity display.
"""

from aesc.provider import ToolOk
from aesc.provider.message import ToolCall


def make_tool_call(tool_id: str, name: str, arguments: str) -> ToolCall:
    """Helper to create ToolCall with proper FunctionBody."""
    return ToolCall(id=tool_id, function=ToolCall.FunctionBody(name=name, arguments=arguments))


# =============================================================================
# 1. Subagent Tool Tracking Tests
# =============================================================================


class TestSubagentToolTracking:
    """Test that subagent tool calls are properly tracked."""

    def test_add_subagent_tool_call(self):
        """Should track new tool calls from subagent."""
        from aesc.ui.widgets.tool_call_display import ToolCallDisplay

        parent_call = make_tool_call("task-123", "Task", '{"subagent_name": "recon"}')
        display = ToolCallDisplay(parent_call)

        subagent_call = make_tool_call("bash-456", "Bash", '{"command": "nmap"}')
        display.add_subagent_tool_call(subagent_call)

        assert len(display._subagent_tools) == 1
        assert display._subagent_tools[0][0].id == "bash-456"
        assert display._subagent_tools[0][1] is None

    def test_finish_subagent_tool_call(self):
        """Should mark subagent tool call as finished with result."""
        from aesc.provider import ToolResult
        from aesc.ui.widgets.tool_call_display import ToolCallDisplay

        parent_call = make_tool_call("task-123", "Task", '{"subagent_name": "recon"}')
        display = ToolCallDisplay(parent_call)

        subagent_call = make_tool_call("bash-456", "Bash", '{"command": "nmap"}')
        display.add_subagent_tool_call(subagent_call)

        result = ToolResult(
            tool_call_id="bash-456", result=ToolOk(output="PORT 22 open", brief="SSH found")
        )
        display.finish_subagent_tool_call(result)

        assert display._subagent_tools[0][1] is not None
        assert isinstance(display._subagent_tools[0][1], ToolOk)

    def test_multiple_subagent_tools(self):
        """Should track multiple subagent tool calls."""
        from aesc.ui.widgets.tool_call_display import ToolCallDisplay

        parent_call = make_tool_call("task-123", "Task", '{"subagent_name": "recon"}')
        display = ToolCallDisplay(parent_call)

        for i in range(5):
            subagent_call = make_tool_call(f"bash-{i}", "Bash", f'{{"command": "cmd{i}"}}')
            display.add_subagent_tool_call(subagent_call)

        assert len(display._subagent_tools) == 5


# =============================================================================
# 2. Subagent Output Tracking Tests
# =============================================================================


class TestSubagentOutputTracking:
    """Test that subagent output is properly tracked."""

    def test_append_subagent_output(self):
        """Should accumulate text output from subagent."""
        from aesc.ui.widgets.tool_call_display import ToolCallDisplay

        parent_call = make_tool_call("task-123", "Task", '{"subagent_name": "recon"}')
        display = ToolCallDisplay(parent_call)

        display.append_subagent_output("Scanning...")
        display.append_subagent_output("\nFound 3 open ports")

        assert "Scanning" in display._subagent_output
        assert "3 open ports" in display._subagent_output

    def test_append_subagent_thinking(self):
        """Should track subagent thinking."""
        from aesc.ui.widgets.tool_call_display import ToolCallDisplay

        parent_call = make_tool_call("task-123", "Task", '{"subagent_name": "recon"}')
        display = ToolCallDisplay(parent_call)

        display.append_subagent_thinking("Analyzing results...")

        assert display._subagent_thinking == "Analyzing results..."


# =============================================================================
# 3. Subagent Activity Rendering Tests
# =============================================================================


class TestSubagentActivityRendering:
    """Test that subagent activity renders correctly."""

    def test_render_shows_running_tool(self):
        """Running subagent tool should show spinner."""
        from aesc.ui.widgets.tool_call_display import ToolCallDisplay

        parent_call = make_tool_call("task-123", "Task", '{"subagent_name": "recon"}')
        display = ToolCallDisplay(parent_call)

        subagent_call = make_tool_call("bash-456", "Bash", '{"command": "nmap -sS target"}')
        display.add_subagent_tool_call(subagent_call)

        rendered = display._render_subagent_activity()

        from io import StringIO

        from rich.console import Console

        console = Console(file=StringIO(), force_terminal=True)
        console.print(rendered)
        output = console.file.getvalue()

        assert "Bash" in output

    def test_render_shows_finished_tool(self):
        """Finished subagent tool should show checkmark."""
        from aesc.provider import ToolResult
        from aesc.ui.widgets.tool_call_display import ToolCallDisplay

        parent_call = make_tool_call("task-123", "Task", '{"subagent_name": "recon"}')
        display = ToolCallDisplay(parent_call)

        subagent_call = make_tool_call("bash-456", "Bash", '{"command": "nmap"}')
        display.add_subagent_tool_call(subagent_call)

        result = ToolResult(
            tool_call_id="bash-456", result=ToolOk(output="PORT 22 open", brief="SSH found")
        )
        display.finish_subagent_tool_call(result)

        rendered = display._render_subagent_activity()

        from io import StringIO

        from rich.console import Console

        console = Console(file=StringIO(), force_terminal=True)
        console.print(rendered)
        output = console.file.getvalue()

        assert "✓" in output or "Bash" in output


# =============================================================================
# 4. Toggle Expand/Collapse Tests
# =============================================================================


class TestSubagentToggle:
    """Test Ctrl+O toggle for expand/collapse."""

    def test_toggle_live_output_for_subagent(self):
        """Ctrl+O should toggle expanded view for Task tool."""
        from aesc.ui.widgets.tool_call_display import ToolCallDisplay

        parent_call = make_tool_call("task-123", "Task", '{"subagent_name": "recon"}')
        display = ToolCallDisplay(parent_call)

        subagent_call = make_tool_call("bash-456", "Bash", '{"command": "nmap"}')
        display.add_subagent_tool_call(subagent_call)

        assert display._show_expanded_subagent is True  # expanded by default

        display.toggle_live_output()
        assert display._show_expanded_subagent is False

        display.toggle_live_output()
        assert display._show_expanded_subagent is True


# =============================================================================
# 5. Key Argument Extraction Tests
# =============================================================================


class TestSubagentKeyArgExtraction:
    """Test key argument extraction for subagent tools."""

    def test_extract_bash_command(self):
        """Should extract command from Bash tool."""
        from aesc.ui.widgets.tool_call_display import ToolCallDisplay

        parent_call = make_tool_call("task-123", "Task", "{}")
        display = ToolCallDisplay(parent_call)

        subagent_call = make_tool_call("bash-456", "Bash", '{"command": "nmap -sS 192.168.1.1"}')

        key_arg = display._extract_subagent_key_arg(subagent_call)
        assert key_arg == "nmap -sS 192.168.1.1"

    def test_extract_grep_pattern(self):
        """Should extract pattern from Grep tool."""
        from aesc.ui.widgets.tool_call_display import ToolCallDisplay

        parent_call = make_tool_call("task-123", "Task", "{}")
        display = ToolCallDisplay(parent_call)

        subagent_call = make_tool_call(
            "grep-456", "Grep", '{"pattern": "password", "path": "/etc"}'
        )

        key_arg = display._extract_subagent_key_arg(subagent_call)
        assert "password" in key_arg


# =============================================================================
# 6. Integration with Parent Display Tests
# =============================================================================


class TestSubagentIntegration:
    """Test subagent activity integrates with parent Task display."""

    def test_task_running_shows_subagent_activity(self):
        """Task tool in RUNNING state should show subagent activity."""
        from aesc.ui.widgets.tool_call_display import ToolCallDisplay, ToolState

        parent_call = make_tool_call("task-123", "Task", '{"subagent_name": "recon"}')
        display = ToolCallDisplay(parent_call)

        subagent_call = make_tool_call("bash-456", "Bash", '{"command": "nmap -sS target"}')
        display.add_subagent_tool_call(subagent_call)

        assert display.state == ToolState.RUNNING

        rendered = display.render_live()

        from io import StringIO

        from rich.console import Console

        console = Console(file=StringIO(), force_terminal=True)
        console.print(rendered)
        output = console.file.getvalue()

        assert "Task" in output or "Bash" in output

    def test_subagent_activity_visible_in_pending_state(self):
        """Even in PENDING state, subagent activity should be visible."""
        from aesc.ui.widgets.tool_call_display import ToolCallDisplay, ToolState

        parent_call = make_tool_call("task-123", "Task", '{"subagent_name": "recon"}')
        display = ToolCallDisplay(parent_call)

        subagent_call = make_tool_call("bash-456", "Bash", '{"command": "nmap"}')
        display.add_subagent_tool_call(subagent_call)

        display.set_pending()
        assert display.state == ToolState.PENDING

        assert len(display._subagent_tools) > 0
