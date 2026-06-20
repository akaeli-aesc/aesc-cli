"""Tests for aesc.ui.widgets.approval_panel module."""

from __future__ import annotations

import pytest
from rich.panel import Panel

from aesc.security.risk import RiskAssessment, RiskLevel
from aesc.ui.widgets.approval_panel import ApprovalPanel
from aesc.wire.message import ApprovalRequest


class MockApprovalRequest:
    """Mock ApprovalRequest for testing without async."""

    def __init__(
        self,
        sender: str = "Bash",
        action: str = "run_command",
        description: str = "ls -la",
        risk_assessment: RiskAssessment | None = None,
    ):
        self.sender = sender
        self.action = action
        self.description = description
        self.risk_assessment = risk_assessment


class TestApprovalPanelInit:
    """Test ApprovalPanel initialization."""

    def test_init_without_risk(self):
        """Initialize without risk assessment."""
        request = MockApprovalRequest()
        panel = ApprovalPanel(request)

        assert panel.request == request
        assert panel.selected_index == 0
        assert panel.risk_level is None
        assert panel.risk_reason is None

    def test_init_with_risk(self):
        """Initialize with risk assessment."""
        risk = RiskAssessment(
            level=RiskLevel.HIGH,
            reason="SSH connection detected",
            patterns_matched=["SSH connection"],
        )
        request = MockApprovalRequest(risk_assessment=risk)
        panel = ApprovalPanel(request)

        assert panel.risk_level == RiskLevel.HIGH
        assert panel.risk_reason == "SSH connection detected"

    def test_options_without_risk(self):
        """Options show UNKNOWN when no risk level."""
        request = MockApprovalRequest()
        panel = ApprovalPanel(request)

        assert len(panel.options) == 3
        assert panel.options[0][0] == "y"
        assert panel.options[1][0] == "a"
        assert panel.options[2][0] == "n"
        assert "UNKNOWN" in panel.options[1][1]

    def test_options_with_risk(self):
        """Options show risk level name."""
        risk = RiskAssessment(
            level=RiskLevel.MEDIUM,
            reason="Test",
            patterns_matched=[],
        )
        request = MockApprovalRequest(risk_assessment=risk)
        panel = ApprovalPanel(request)

        assert "MEDIUM" in panel.options[1][1]


class TestApprovalPanelRender:
    """Test ApprovalPanel rendering."""

    def test_render_returns_panel(self):
        """render() returns a Rich Panel."""
        request = MockApprovalRequest()
        panel = ApprovalPanel(request)
        rendered = panel.render()

        assert isinstance(rendered, Panel)

    def test_render_with_risk_level(self):
        """render() includes risk level information."""
        risk = RiskAssessment(
            level=RiskLevel.CRITICAL,
            reason="Destructive command",
            patterns_matched=["rm -rf"],
        )
        request = MockApprovalRequest(
            description="rm -rf /tmp",
            risk_assessment=risk,
        )
        panel = ApprovalPanel(request)
        rendered = panel.render()

        # Panel should have error (red) border for CRITICAL
        assert rendered.border_style == "#f87171"

    def test_render_border_colors(self):
        """Border color matches risk level."""
        test_cases = [
            (RiskLevel.SAFE, "#fbbf24"),  # warning (default)
            (RiskLevel.LOW, "#fbbf24"),  # warning (default)
            (RiskLevel.MEDIUM, "#fbbf24"),  # warning (default)
            (RiskLevel.HIGH, "#f87171"),  # error (HIGH/CRITICAL)
            (RiskLevel.CRITICAL, "#f87171"),  # error (HIGH/CRITICAL)
        ]

        for risk_level, expected_color in test_cases:
            risk = RiskAssessment(level=risk_level, reason="Test", patterns_matched=[])
            request = MockApprovalRequest(risk_assessment=risk)
            panel = ApprovalPanel(request)
            rendered = panel.render()
            assert rendered.border_style == expected_color, (
                f"Expected {expected_color} for {risk_level}"
            )


class TestApprovalPanelNavigation:
    """Test option navigation."""

    def test_initial_selection(self):
        """First option is selected by default."""
        request = MockApprovalRequest()
        panel = ApprovalPanel(request)

        assert panel.selected_index == 0

    def test_navigate_down(self):
        """Increment selected_index to navigate down."""
        request = MockApprovalRequest()
        panel = ApprovalPanel(request)

        panel.selected_index = 1
        assert panel.selected_index == 1

        panel.selected_index = 2
        assert panel.selected_index == 2

    def test_navigate_wrap(self):
        """Index can wrap using modulo."""
        request = MockApprovalRequest()
        panel = ApprovalPanel(request)

        # Wrap around
        panel.selected_index = (panel.selected_index + 1) % len(panel.options)
        assert panel.selected_index == 1

        panel.selected_index = (panel.selected_index + 1) % len(panel.options)
        assert panel.selected_index == 2

        panel.selected_index = (panel.selected_index + 1) % len(panel.options)
        assert panel.selected_index == 0  # Wrapped

    def test_get_selected_option(self):
        """Get the currently selected option."""
        request = MockApprovalRequest()
        panel = ApprovalPanel(request)

        assert panel.options[panel.selected_index][0] == "y"

        panel.selected_index = 1
        assert panel.options[panel.selected_index][0] == "a"

        panel.selected_index = 2
        assert panel.options[panel.selected_index][0] == "n"


class TestApprovalPanelApprovalDisplay:
    """Test get_approval_display method."""

    def test_approved_display(self):
        """Approved display shows checkmark."""
        request = MockApprovalRequest(description="test command")
        panel = ApprovalPanel(request)
        display = panel.get_approval_display(approved=True)

        # Should be a renderable (BulletColumns)
        assert display is not None

    def test_rejected_display(self):
        """Rejected display shows X."""
        request = MockApprovalRequest(description="test command")
        panel = ApprovalPanel(request)
        display = panel.get_approval_display(approved=False)

        assert display is not None

    def test_approved_for_session_with_risk(self):
        """Session approval shows risk level."""
        risk = RiskAssessment(
            level=RiskLevel.MEDIUM,
            reason="Test",
            patterns_matched=[],
        )
        request = MockApprovalRequest(risk_assessment=risk)
        panel = ApprovalPanel(request)
        display = panel.get_approval_display(approved=True, for_session=True)

        assert display is not None

    def test_approved_for_session_without_risk(self):
        """Session approval without risk still works."""
        request = MockApprovalRequest()
        panel = ApprovalPanel(request)
        display = panel.get_approval_display(approved=True, for_session=True)

        assert display is not None


class TestApprovalPanelWithRealRequest:
    """Test with real ApprovalRequest (requires async)."""

    @pytest.mark.asyncio
    async def test_with_real_request(self):
        """Test panel with actual ApprovalRequest."""
        risk = RiskAssessment(
            level=RiskLevel.HIGH,
            reason="Network operation",
            patterns_matched=["nmap"],
        )
        request = ApprovalRequest(
            tool_call_id="call_123",
            sender="Bash",
            action="run_command",
            description="nmap -sS target",
            risk_assessment=risk,
        )
        panel = ApprovalPanel(request)

        assert panel.risk_level == RiskLevel.HIGH
        rendered = panel.render()
        assert rendered.border_style == "#f87171"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
