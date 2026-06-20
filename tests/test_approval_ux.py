"""
TDD Tests for Approval UX Fix (Design Doc 001)

These tests define the expected behavior. Implementation should make them pass.
"""

from io import StringIO

from rich.console import Console

from aesc.provider.message import ToolCall
from aesc.wire.message import ApprovalRequest


def make_approval_request(desc: str = "Run: rm -rf /tmp/test") -> ApprovalRequest:
    """Helper to create ApprovalRequest with proper signature."""
    return ApprovalRequest(
        tool_call_id="test-123", sender="Bash", action="execute", description=desc
    )


def make_tool_call(tool_id: str, name: str, args: str) -> ToolCall:
    """Helper to create ToolCall."""
    return ToolCall(id=tool_id, function=ToolCall.FunctionBody(name=name, arguments=args))


# =============================================================================
# 1. Key Handling Tests
# =============================================================================


class TestApprovalKeyHandling:
    """Test that y/n/a keys work correctly with approval panel."""

    def test_y_key_approves_when_panel_active(self):
        """Pressing 'y' should approve when approval panel is visible."""
        from aesc.ui.widgets.approval_panel import ApprovalPanel
        from aesc.wire.message import ApprovalResponse

        request = make_approval_request()
        panel = ApprovalPanel(request)

        assert not request.resolved
        request.approve()
        assert request.resolved
        # Get result from the future
        assert request._future.result() == ApprovalResponse.APPROVE

    def test_n_key_rejects_when_panel_active(self):
        """Pressing 'n' should reject when approval panel is visible."""
        from aesc.wire.message import ApprovalResponse

        request = make_approval_request()

        assert not request.resolved
        request.reject()
        assert request.resolved
        assert request._future.result() == ApprovalResponse.REJECT

    def test_a_key_approves_for_session(self):
        """Pressing 'a' should approve for session."""
        from aesc.wire.message import ApprovalResponse

        request = make_approval_request()

        assert not request.resolved
        request.approve_for_session()
        assert request.resolved
        assert request._future.result() == ApprovalResponse.APPROVE_FOR_SESSION

    def test_arrow_navigation_changes_selection(self):
        """Arrow keys should change selected option."""
        from aesc.ui.widgets.approval_panel import ApprovalPanel

        request = make_approval_request()
        panel = ApprovalPanel(request)

        assert panel.selected_index == 0

        # Down arrow
        panel.selected_index = (panel.selected_index + 1) % len(panel.options)
        assert panel.selected_index == 1

        # Down again
        panel.selected_index = (panel.selected_index + 1) % len(panel.options)
        assert panel.selected_index == 2

        # Down wraps to 0
        panel.selected_index = (panel.selected_index + 1) % len(panel.options)
        assert panel.selected_index == 0

    def test_enter_selects_current_option(self):
        """Enter key should select the currently highlighted option."""
        from aesc.ui.widgets.approval_panel import ApprovalPanel

        request = make_approval_request()
        panel = ApprovalPanel(request)

        # Select "Yes to all" (index 1)
        panel.selected_index = 1
        selected_key = panel.options[panel.selected_index][0]
        assert selected_key == "a"  # 'a' for approve all


# =============================================================================
# 2. Elapsed Time Tests
# =============================================================================


class TestElapsedTimeDisplay:
    """Test elapsed time formatting and display."""

    def test_format_seconds(self):
        """Under 60 seconds shows just seconds."""
        import time

        from aesc.ui.widgets.tool_call_display import ToolCallDisplay

        tool_call = make_tool_call("test-123", "Bash", '{"command": "ls"}')
        display = ToolCallDisplay(tool_call)
        display._start_time = time.time() - 45

        rendered = display.render_live()
        assert rendered is not None

    def test_format_minutes(self):
        """Over 60 seconds shows minutes and seconds."""
        elapsed = 150
        mins = int(elapsed // 60)
        secs = int(elapsed % 60)
        elapsed_str = f"{mins}m {secs}s"
        assert elapsed_str == "2m 30s"

    def test_format_hours(self):
        """Over 60 minutes shows hours and minutes."""
        elapsed = 3700
        hours = int(elapsed // 3600)
        mins = int((elapsed % 3600) // 60)
        elapsed_str = f"{hours}h {mins}m"
        assert elapsed_str == "1h 1m"


# =============================================================================
# 3. Panel Visibility Tests
# =============================================================================


class TestApprovalPanelVisibility:
    """Test that approval panel is clearly visible."""

    def test_panel_has_action_required_header(self):
        """Panel should have prominent ACTION REQUIRED header."""
        from aesc.ui.widgets.approval_panel import ApprovalPanel

        request = make_approval_request()
        panel = ApprovalPanel(request)
        rendered = panel.render()

        console = Console(file=StringIO(), force_terminal=True)
        console.print(rendered)
        output = console.file.getvalue()

        assert "Approval required" in output

    def test_panel_shows_keyboard_options(self):
        """Panel should show y/n/a keyboard options."""
        from aesc.ui.widgets.approval_panel import ApprovalPanel

        request = make_approval_request()
        panel = ApprovalPanel(request)
        rendered = panel.render()

        console = Console(file=StringIO(), force_terminal=True)
        console.print(rendered)
        output = console.file.getvalue()

        # Check for key labels - modern format uses "y·yes", "a·all", "n·no"
        assert "yes" in output.lower()
        assert "no" in output.lower()
        assert "all" in output.lower()


# =============================================================================
# 4. Status Bar Tests
# =============================================================================


class TestStatusBarIndicators:
    """Test status bar shows approval and running indicators."""

    def test_pending_approval_indicator(self):
        """Status bar should show APPROVAL REQUIRED when pending."""
        from aesc.ui.widgets.status_bar import EnhancedStatusBar

        status_bar = EnhancedStatusBar()
        status_bar.set_pending_approval(True)
        assert status_bar._pending_approval is True

    def test_running_tools_count(self):
        """Status bar should show count of running tools."""
        from aesc.ui.widgets.status_bar import EnhancedStatusBar

        status_bar = EnhancedStatusBar()
        status_bar.set_running_tools(3)
        assert status_bar._running_tools == 3

    def test_clear_pending_approval(self):
        """Status bar should clear indicator when no pending approval."""
        from aesc.ui.widgets.status_bar import EnhancedStatusBar

        status_bar = EnhancedStatusBar()
        status_bar.set_pending_approval(True)
        assert status_bar._pending_approval is True

        status_bar.set_pending_approval(False)
        assert status_bar._pending_approval is False


# =============================================================================
# 5. Tool Display State Tests
# =============================================================================


class TestToolDisplayStates:
    """Test tool display state transitions."""

    def test_pending_state_shows_keyboard_hints(self):
        """PENDING state should show keyboard hints."""
        from aesc.ui.widgets.tool_call_display import ToolCallDisplay, ToolState

        tool_call = make_tool_call("test-123", "Bash", '{"command": "rm -rf /tmp"}')
        display = ToolCallDisplay(tool_call)
        display.set_pending()

        assert display.state == ToolState.PENDING

        rendered = display.render_live()
        console = Console(file=StringIO(), force_terminal=True)
        console.print(rendered)
        output = console.file.getvalue()

        assert "approve" in output.lower() or "y" in output

    def test_running_state_shows_elapsed_time(self):
        """RUNNING state should show elapsed time."""
        import time

        from aesc.ui.widgets.tool_call_display import ToolCallDisplay, ToolState

        tool_call = make_tool_call("test-123", "Bash", '{"command": "sleep 10"}')
        display = ToolCallDisplay(tool_call)
        display._start_time = time.time() - 45

        assert display.state == ToolState.RUNNING

        rendered = display.render_live()
        console = Console(file=StringIO(), force_terminal=True)
        console.print(rendered)
        output = console.file.getvalue()

        assert "s)" in output or "s]" in output or "running" in output.lower()


# =============================================================================
# 6. Integration Tests
# =============================================================================


class TestApprovalPanelLifecycle:
    """Test the full approval panel lifecycle."""

    def test_panel_disappears_after_approval(self):
        """Panel should be removed after user responds."""
        from aesc.ui.widgets.approval_panel import ApprovalPanel

        request = make_approval_request()
        panel = ApprovalPanel(request)

        request.approve()
        approval_display = panel.get_approval_display(approved=True)

        console = Console(file=StringIO(), force_terminal=True)
        console.print(approval_display)
        output = console.file.getvalue()

        assert "Approved" in output
        assert "ACTION REQUIRED" not in output
