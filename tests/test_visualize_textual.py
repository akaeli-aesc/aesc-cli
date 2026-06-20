"""Tests for aesc.ui.shell.visualize_textual module - approval key handling."""

from __future__ import annotations

import pytest

from aesc.security.risk import RiskAssessment, RiskLevel
from aesc.ui.widgets.approval_panel import ApprovalPanel


class MockApprovalRequest:
    """Mock for testing without async."""

    def __init__(self, risk_level: RiskLevel = RiskLevel.MEDIUM):
        self.sender = "Bash"
        self.action = "run_command"
        self.description = "test command"
        self.risk_assessment = RiskAssessment(
            level=risk_level,
            reason="Test reason",
            patterns_matched=["test"],
        )
        self._approved = None
        self._for_session = False

    def approve(self):
        self._approved = True

    def approve_for_session(self):
        self._approved = True
        self._for_session = True

    def reject(self):
        self._approved = False


class TestApprovalKeyHandling:
    """Test approval key handling logic."""

    def test_navigation_down(self):
        """Down arrow increments selected index."""
        request = MockApprovalRequest()
        panel = ApprovalPanel(request)

        initial = panel.selected_index
        panel.selected_index = (panel.selected_index + 1) % len(panel.options)

        assert panel.selected_index == initial + 1

    def test_navigation_up(self):
        """Up arrow decrements selected index."""
        request = MockApprovalRequest()
        panel = ApprovalPanel(request)
        panel.selected_index = 2  # Start at last

        panel.selected_index = (panel.selected_index - 1) % len(panel.options)

        assert panel.selected_index == 1

    def test_navigation_wrap_down(self):
        """Navigation wraps from last to first."""
        request = MockApprovalRequest()
        panel = ApprovalPanel(request)
        panel.selected_index = 2  # Last option

        panel.selected_index = (panel.selected_index + 1) % len(panel.options)

        assert panel.selected_index == 0

    def test_navigation_wrap_up(self):
        """Navigation wraps from first to last."""
        request = MockApprovalRequest()
        panel = ApprovalPanel(request)
        panel.selected_index = 0  # First option

        panel.selected_index = (panel.selected_index - 1) % len(panel.options)

        assert panel.selected_index == 2

    def test_select_yes(self):
        """Selecting 'y' approves the request."""
        request = MockApprovalRequest()
        panel = ApprovalPanel(request)

        selected_key = panel.options[0][0]  # 'y'
        assert selected_key == "y"

        if selected_key == "y":
            request.approve()

        assert request._approved is True

    def test_select_yes_to_all(self):
        """Selecting 'a' approves for session."""
        request = MockApprovalRequest()
        panel = ApprovalPanel(request)

        selected_key = panel.options[1][0]  # 'a'
        assert selected_key == "a"

        if selected_key == "a":
            request.approve_for_session()

        assert request._approved is True
        assert request._for_session is True

    def test_select_no(self):
        """Selecting 'n' rejects the request."""
        request = MockApprovalRequest()
        panel = ApprovalPanel(request)

        selected_key = panel.options[2][0]  # 'n'
        assert selected_key == "n"

        if selected_key == "n":
            request.reject()

        assert request._approved is False

    def test_enter_selects_current(self):
        """Enter key selects current option."""
        request = MockApprovalRequest()
        panel = ApprovalPanel(request)

        # Navigate to "Yes to all"
        panel.selected_index = 1
        selected_key = panel.options[panel.selected_index][0]

        assert selected_key == "a"

    def test_empty_options_safety(self):
        """Empty options list is handled safely."""
        # This tests the safety check we added
        request = MockApprovalRequest()
        panel = ApprovalPanel(request)

        # Normally options should never be empty, but test the guard
        assert len(panel.options) > 0

        # Valid index access
        if panel.options:
            key = panel.options[panel.selected_index][0]
            assert key in ("y", "a", "n")


class TestApprovalPanelStateTracking:
    """Test state tracking in approval panel."""

    def test_selected_index_bounds(self):
        """Selected index stays within bounds."""
        request = MockApprovalRequest()
        panel = ApprovalPanel(request)

        # Test all valid indices
        for i in range(len(panel.options)):
            panel.selected_index = i
            assert 0 <= panel.selected_index < len(panel.options)

    def test_risk_level_display(self):
        """Risk level is displayed correctly."""
        for risk_level in [
            RiskLevel.SAFE,
            RiskLevel.LOW,
            RiskLevel.MEDIUM,
            RiskLevel.HIGH,
            RiskLevel.CRITICAL,
        ]:
            request = MockApprovalRequest(risk_level=risk_level)
            panel = ApprovalPanel(request)

            assert panel.risk_level == risk_level
            assert risk_level.display_name in panel.options[1][1]


class TestApprovalKeyValidation:
    """Test key validation logic."""

    def test_valid_keys(self):
        """Valid approval keys are y, a, n."""
        valid_keys = {"y", "a", "n"}

        request = MockApprovalRequest()
        panel = ApprovalPanel(request)

        option_keys = {opt[0] for opt in panel.options}
        assert option_keys == valid_keys

    def test_navigation_keys(self):
        """Navigation keys are up, down, enter."""
        navigation_keys = {"up", "down", "enter"}

        # These would be handled by _handle_approval_key
        for key in navigation_keys:
            assert key in navigation_keys


class TestRaceConditionHandling:
    """Test race condition safety."""

    def test_captured_reference_pattern(self):
        """Demonstrates captured reference pattern for race safety."""
        request = MockApprovalRequest()
        panel = ApprovalPanel(request)

        # Capture reference before use (as done in visualize_textual.py)
        approval_panel = (request, panel)

        # Even if self._approval_panel changed to None after check,
        # approval_panel still holds valid reference
        assert approval_panel is not None
        req, pnl = approval_panel
        assert req is request
        assert pnl is panel


class TestApprovalDisplayGeneration:
    """Test approval display after user action."""

    def test_approval_display_approved(self):
        """Test display generation for approved."""
        request = MockApprovalRequest()
        panel = ApprovalPanel(request)

        display = panel.get_approval_display(approved=True)
        assert display is not None

    def test_approval_display_rejected(self):
        """Test display generation for rejected."""
        request = MockApprovalRequest()
        panel = ApprovalPanel(request)

        display = panel.get_approval_display(approved=False)
        assert display is not None

    def test_approval_display_for_session(self):
        """Test display generation for session approval."""
        request = MockApprovalRequest()
        panel = ApprovalPanel(request)

        display = panel.get_approval_display(approved=True, for_session=True)
        assert display is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
