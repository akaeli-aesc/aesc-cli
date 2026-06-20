"""Tests for aesc.soul.approval module - Approval system with risk-based logic."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from aesc.security.risk import RiskAssessment, RiskLevel
from aesc.soul.approval import Approval


class TestApprovalInit:
    """Test Approval initialization."""

    def test_init_default(self):
        """Default initialization."""
        approval = Approval()
        assert approval._yolo is False
        assert len(approval._auto_approve_actions) == 0
        assert len(approval._approved_risk_levels) == 0

    def test_init_yolo(self):
        """Initialize with YOLO mode."""
        approval = Approval(yolo=True)
        assert approval._yolo is True

    def test_set_yolo(self):
        """Set YOLO mode after initialization."""
        approval = Approval()
        assert approval._yolo is False
        approval.set_yolo(True)
        assert approval._yolo is True
        approval.set_yolo(False)
        assert approval._yolo is False


class TestApprovalYoloMode:
    """Test YOLO mode behavior."""

    @pytest.mark.asyncio
    async def test_yolo_approves_everything(self):
        """YOLO mode approves all requests."""
        approval = Approval(yolo=True)

        # Mock the tool call context
        mock_tool_call = MagicMock()
        mock_tool_call.function.name = "Bash"
        mock_tool_call.id = "call_123"

        with patch("aesc.soul.approval.get_current_tool_call_or_none", return_value=mock_tool_call):
            result = await approval.request("Bash", "run_command", "rm -rf /")
            assert result is True

    @pytest.mark.asyncio
    async def test_yolo_approves_critical(self):
        """YOLO mode even approves CRITICAL risk commands."""
        approval = Approval(yolo=True)

        mock_tool_call = MagicMock()
        mock_tool_call.function.name = "Bash"
        mock_tool_call.id = "call_123"

        with patch("aesc.soul.approval.get_current_tool_call_or_none", return_value=mock_tool_call):
            result = await approval.request("Bash", "run_command", "sudo rm -rf /")
            assert result is True


class TestApprovalLegacyActions:
    """Test legacy action-based auto-approval."""

    @pytest.mark.asyncio
    async def test_auto_approve_action(self):
        """Actions in auto_approve_actions are approved."""
        approval = Approval()
        approval._auto_approve_actions.add("read_file")

        mock_tool_call = MagicMock()
        mock_tool_call.function.name = "ReadFile"
        mock_tool_call.id = "call_123"

        with patch("aesc.soul.approval.get_current_tool_call_or_none", return_value=mock_tool_call):
            result = await approval.request("ReadFile", "read_file", "/etc/passwd")
            assert result is True


class TestApprovalRiskBased:
    """Test risk-based approval logic."""

    @pytest.mark.asyncio
    async def test_safe_auto_approve_after_safe_approved(self):
        """SAFE actions auto-approve after SAFE level approved."""
        approval = Approval()
        approval._approved_risk_levels.add(RiskLevel.SAFE)

        mock_tool_call = MagicMock()
        mock_tool_call.function.name = "Grep"
        mock_tool_call.id = "call_123"

        with patch("aesc.soul.approval.get_current_tool_call_or_none", return_value=mock_tool_call):
            # Grep is SAFE risk
            result = await approval.request("Grep", "search", "pattern")
            assert result is True

    @pytest.mark.asyncio
    async def test_low_auto_approve_after_low_approved(self):
        """LOW actions auto-approve after LOW level approved."""
        approval = Approval()
        approval._approved_risk_levels.add(RiskLevel.LOW)

        mock_tool_call = MagicMock()
        mock_tool_call.function.name = "WebFetch"
        mock_tool_call.id = "call_123"

        with patch("aesc.soul.approval.get_current_tool_call_or_none", return_value=mock_tool_call):
            # WebFetch is LOW risk
            result = await approval.request("WebFetch", "fetch", "http://example.com")
            assert result is True

    @pytest.mark.asyncio
    async def test_safe_auto_approve_after_medium_approved(self):
        """SAFE actions auto-approve after MEDIUM level approved (higher approval covers lower)."""
        approval = Approval()
        approval._approved_risk_levels.add(RiskLevel.MEDIUM)

        mock_tool_call = MagicMock()
        mock_tool_call.function.name = "Read"
        mock_tool_call.id = "call_123"

        with patch("aesc.soul.approval.get_current_tool_call_or_none", return_value=mock_tool_call):
            # Read is SAFE risk
            result = await approval.request("Read", "read", "/tmp/file.txt")
            assert result is True

    @pytest.mark.asyncio
    async def test_medium_not_auto_approve_after_low(self):
        """MEDIUM actions do NOT auto-approve after only LOW approved."""
        approval = Approval()
        approval._approved_risk_levels.add(RiskLevel.LOW)

        mock_tool_call = MagicMock()
        mock_tool_call.function.name = "Write"
        mock_tool_call.id = "call_123"

        # Write is MEDIUM risk - need to handle the request
        async def approve_request():
            # Simulate user approval
            request = await approval.fetch_request()
            request.approve()

        with patch("aesc.soul.approval.get_current_tool_call_or_none", return_value=mock_tool_call):
            # Run approval request and response in parallel
            task = asyncio.create_task(approve_request())
            result = await approval.request("Write", "write", "/tmp/file.txt")
            await task
            # Should have been approved by user
            assert result is True


class TestApprovalHighCritical:
    """Test HIGH and CRITICAL approval behavior."""

    @pytest.mark.asyncio
    async def test_high_requires_approval_even_after_medium(self):
        """HIGH risk requires explicit approval after only MEDIUM approved."""
        approval = Approval()
        approval._approved_risk_levels.add(RiskLevel.MEDIUM)

        mock_tool_call = MagicMock()
        mock_tool_call.function.name = "Bash"
        mock_tool_call.id = "call_123"

        async def reject_request():
            request = await approval.fetch_request()
            assert request.risk_assessment.level == RiskLevel.HIGH
            request.reject()

        with patch("aesc.soul.approval.get_current_tool_call_or_none", return_value=mock_tool_call):
            task = asyncio.create_task(reject_request())
            # SSH is HIGH risk
            result = await approval.request("Bash", "run_command", "ssh user@server")
            await task
            assert result is False

    @pytest.mark.asyncio
    async def test_high_auto_approves_after_high_approved(self):
        """HIGH risk auto-approves after HIGH level approved for session."""
        approval = Approval()
        approval._approved_risk_levels.add(RiskLevel.HIGH)

        mock_tool_call = MagicMock()
        mock_tool_call.function.name = "Bash"
        mock_tool_call.id = "call_123"

        with patch("aesc.soul.approval.get_current_tool_call_or_none", return_value=mock_tool_call):
            # SSH is HIGH risk - should auto-approve since HIGH is approved
            result = await approval.request("Bash", "run_command", "ssh user@server")
            assert result is True

    @pytest.mark.asyncio
    async def test_critical_auto_approves_after_critical_approved(self):
        """CRITICAL risk auto-approves after CRITICAL level approved for session."""
        approval = Approval()
        approval._approved_risk_levels.add(RiskLevel.CRITICAL)

        mock_tool_call = MagicMock()
        mock_tool_call.function.name = "Bash"
        mock_tool_call.id = "call_123"

        with patch("aesc.soul.approval.get_current_tool_call_or_none", return_value=mock_tool_call):
            # sudo rm -rf / is CRITICAL risk - should auto-approve
            result = await approval.request("Bash", "run_command", "sudo rm -rf /")
            assert result is True


class TestApprovalResponses:
    """Test handling of different approval responses."""

    @pytest.mark.asyncio
    async def test_approve_once(self):
        """APPROVE response returns True but doesn't track risk level."""
        approval = Approval()

        mock_tool_call = MagicMock()
        mock_tool_call.function.name = "Write"
        mock_tool_call.id = "call_123"

        async def approve_once():
            request = await approval.fetch_request()
            request.approve()

        with patch("aesc.soul.approval.get_current_tool_call_or_none", return_value=mock_tool_call):
            task = asyncio.create_task(approve_once())
            result = await approval.request("Write", "write", "/tmp/test.txt")
            await task
            assert result is True
            # Risk level should NOT be tracked
            assert RiskLevel.MEDIUM not in approval._approved_risk_levels

    @pytest.mark.asyncio
    async def test_approve_for_session(self):
        """APPROVE_FOR_SESSION tracks risk level."""
        approval = Approval()

        mock_tool_call = MagicMock()
        mock_tool_call.function.name = "Write"
        mock_tool_call.id = "call_123"

        async def approve_for_session():
            request = await approval.fetch_request()
            request.approve_for_session()

        with patch("aesc.soul.approval.get_current_tool_call_or_none", return_value=mock_tool_call):
            task = asyncio.create_task(approve_for_session())
            result = await approval.request("Write", "write", "/tmp/test.txt")
            await task
            assert result is True
            # Risk level should be tracked
            assert RiskLevel.MEDIUM in approval._approved_risk_levels

    @pytest.mark.asyncio
    async def test_reject(self):
        """REJECT response returns False."""
        approval = Approval()

        mock_tool_call = MagicMock()
        mock_tool_call.function.name = "Bash"
        mock_tool_call.id = "call_123"

        async def reject():
            request = await approval.fetch_request()
            request.reject()

        with patch("aesc.soul.approval.get_current_tool_call_or_none", return_value=mock_tool_call):
            task = asyncio.create_task(reject())
            result = await approval.request("Bash", "run_command", "rm -rf /tmp")
            await task
            assert result is False


class TestApprovalRuntimeError:
    """Test that approval outside tool call raises error."""

    @pytest.mark.asyncio
    async def test_no_tool_call_raises(self):
        """Request outside tool call raises RuntimeError."""
        approval = Approval()

        with patch("aesc.soul.approval.get_current_tool_call_or_none", return_value=None):
            with pytest.raises(RuntimeError, match="Approval must be requested from a tool call"):
                await approval.request("Test", "action", "desc")


class TestApprovalFetchRequest:
    """Test fetch_request method."""

    @pytest.mark.asyncio
    async def test_fetch_request(self):
        """fetch_request returns queued request."""
        approval = Approval()

        mock_tool_call = MagicMock()
        mock_tool_call.function.name = "Test"
        mock_tool_call.id = "call_123"

        async def make_request():
            with patch(
                "aesc.soul.approval.get_current_tool_call_or_none", return_value=mock_tool_call
            ):
                # Will block until response
                task = asyncio.create_task(approval.request("Test", "action", "desc"))
                await asyncio.sleep(0.01)  # Let request queue
                return task

        request_task = await make_request()
        fetched = await approval.fetch_request()

        assert fetched.sender == "Test"
        assert fetched.action == "action"
        assert fetched.description == "desc"

        # Clean up
        fetched.reject()
        await request_task


class TestApprovalRiskAssessmentPassthrough:
    """Test that risk assessment is passed to ApprovalRequest."""

    @pytest.mark.asyncio
    async def test_risk_assessment_in_request(self):
        """ApprovalRequest contains risk assessment."""
        approval = Approval()

        mock_tool_call = MagicMock()
        mock_tool_call.function.name = "Bash"
        mock_tool_call.id = "call_123"

        async def check_request():
            request = await approval.fetch_request()
            assert request.risk_assessment is not None
            assert isinstance(request.risk_assessment, RiskAssessment)
            request.reject()

        with patch("aesc.soul.approval.get_current_tool_call_or_none", return_value=mock_tool_call):
            task = asyncio.create_task(check_request())
            await approval.request("Bash", "run_command", "ls -la")
            await task


class TestApprovalBacktickBypass:
    """SEC-1 regression: a dangerous command must not slip past risk gating because
    an inner backtick command-substitution truncated the assessed text."""

    # Payload that previously extracted as harmless `echo ` (LOW) and auto-approved.
    PAYLOAD = "echo `id` ; rm -rf / --no-preserve-root"

    async def _assert_not_auto_approved(self, approval: Approval, **request_kwargs) -> None:
        mock_tool_call = MagicMock()
        mock_tool_call.function.name = "Bash"
        mock_tool_call.id = "call_123"

        async def reject_manual_request():
            request = await approval.fetch_request()
            # The FULL command must have been assessed, not a truncated prefix.
            assert request.risk_assessment.level == RiskLevel.CRITICAL
            request.reject()

        with patch(
            "aesc.soul.approval.get_current_tool_call_or_none",
            return_value=mock_tool_call,
        ):
            task = asyncio.create_task(reject_manual_request())
            approved = await approval.request(
                "Bash",
                "run shell command",
                f"Run command `{self.PAYLOAD}`",
                **request_kwargs,
            )
            if approved:
                # Regression: auto-approved without ever prompting.
                task.cancel()
            else:
                await asyncio.wait_for(task, timeout=2.0)

        assert approved is False, "CRITICAL command was auto-approved (SEC-1 bypass)"

    @pytest.mark.asyncio
    async def test_structured_command_assessed_directly(self):
        """The bash tool passes command= so the assessor sees the real command."""
        approval = Approval()
        approval._approved_risk_levels.add(RiskLevel.LOW)  # "approve LOW for session"
        await self._assert_not_auto_approved(approval, command=self.PAYLOAD)

    @pytest.mark.asyncio
    async def test_description_fallback_not_truncated(self):
        """Defense-in-depth: even without command=, greedy extraction is not fooled."""
        approval = Approval()
        approval._approved_risk_levels.add(RiskLevel.LOW)
        await self._assert_not_auto_approved(approval)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
