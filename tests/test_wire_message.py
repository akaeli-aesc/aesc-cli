"""Tests for aesc.wire.message module - ApprovalRequest, ApprovalResponse, and serialization."""

from __future__ import annotations

import asyncio

import pytest

from aesc.wire.message import (
    ApprovalRequest,
    ApprovalResponse,
    CompactionBegin,
    CompactionEnd,
    StepBegin,
    StepInterrupted,
    serialize_approval_request,
    serialize_event,
)


class TestApprovalResponse:
    """Test ApprovalResponse enum."""

    def test_approval_response_values(self):
        """ApprovalResponse has correct values."""
        assert ApprovalResponse.APPROVE.value == "approve"
        assert ApprovalResponse.APPROVE_FOR_SESSION.value == "approve_for_session"
        assert ApprovalResponse.REJECT.value == "reject"

    def test_approval_response_is_enum(self):
        """ApprovalResponse is an enum."""
        assert len(ApprovalResponse) == 3


class TestApprovalRequest:
    """Test ApprovalRequest class."""

    def test_creation(self):
        """Create an ApprovalRequest."""
        request = ApprovalRequest(
            tool_call_id="call_123",
            sender="Bash",
            action="run_command",
            description="rm -rf /tmp/test",
        )
        assert request.tool_call_id == "call_123"
        assert request.sender == "Bash"
        assert request.action == "run_command"
        assert request.description == "rm -rf /tmp/test"
        assert request.id is not None  # Auto-generated UUID
        assert request.risk_assessment is None

    def test_creation_with_risk_assessment(self):
        """Create an ApprovalRequest with risk assessment."""
        from aesc.security.risk import RiskAssessment, RiskLevel

        risk = RiskAssessment(
            level=RiskLevel.HIGH,
            reason="High risk command",
            patterns_matched=["pattern1"],
        )
        request = ApprovalRequest(
            tool_call_id="call_456",
            sender="Bash",
            action="run_command",
            description="nmap -sS target",
            risk_assessment=risk,
        )
        assert request.risk_assessment is not None
        assert request.risk_assessment.level == RiskLevel.HIGH

    def test_unique_ids(self):
        """Each request gets a unique ID."""
        request1 = ApprovalRequest("call_1", "Test", "action", "desc")
        request2 = ApprovalRequest("call_2", "Test", "action", "desc")
        assert request1.id != request2.id

    def test_repr(self):
        """Test string representation."""
        request = ApprovalRequest("call_123", "Bash", "run", "ls -la")
        repr_str = repr(request)
        assert "ApprovalRequest" in repr_str
        assert "call_123" in repr_str
        assert "Bash" in repr_str

    def test_resolved_property_initially_false(self):
        """Request is not resolved initially."""
        request = ApprovalRequest("call_1", "Test", "action", "desc")
        assert request.resolved is False

    @pytest.mark.asyncio
    async def test_approve(self):
        """Test approve() method."""
        request = ApprovalRequest("call_1", "Test", "action", "desc")
        request.approve()
        assert request.resolved is True

    @pytest.mark.asyncio
    async def test_approve_for_session(self):
        """Test approve_for_session() method."""
        request = ApprovalRequest("call_1", "Test", "action", "desc")
        request.approve_for_session()
        assert request.resolved is True

    @pytest.mark.asyncio
    async def test_reject(self):
        """Test reject() method."""
        request = ApprovalRequest("call_1", "Test", "action", "desc")
        request.reject()
        assert request.resolved is True

    @pytest.mark.asyncio
    async def test_resolve_idempotent(self):
        """Calling resolve multiple times is safe (no exception)."""
        request = ApprovalRequest("call_1", "Test", "action", "desc")
        request.approve()
        # Second call should be ignored, not raise
        request.approve()
        request.reject()
        request.approve_for_session()
        assert request.resolved is True

    @pytest.mark.asyncio
    async def test_wait_returns_response(self):
        """wait() returns the response after resolution."""
        request = ApprovalRequest("call_1", "Test", "action", "desc")

        async def approve_after_delay():
            await asyncio.sleep(0.01)
            request.approve()

        task = asyncio.create_task(approve_after_delay())
        response = await request.wait()
        assert response == ApprovalResponse.APPROVE
        await task

    @pytest.mark.asyncio
    async def test_wait_approve_for_session(self):
        """wait() returns APPROVE_FOR_SESSION."""
        request = ApprovalRequest("call_1", "Test", "action", "desc")

        async def approve_after_delay():
            await asyncio.sleep(0.01)
            request.approve_for_session()

        task = asyncio.create_task(approve_after_delay())
        response = await request.wait()
        assert response == ApprovalResponse.APPROVE_FOR_SESSION
        await task

    @pytest.mark.asyncio
    async def test_wait_reject(self):
        """wait() returns REJECT."""
        request = ApprovalRequest("call_1", "Test", "action", "desc")

        async def reject_after_delay():
            await asyncio.sleep(0.01)
            request.reject()

        task = asyncio.create_task(reject_after_delay())
        response = await request.wait()
        assert response == ApprovalResponse.REJECT
        await task


class TestSerializeApprovalRequest:
    """Test serialization of ApprovalRequest."""

    def test_serialize_basic(self):
        """Serialize a basic request."""
        request = ApprovalRequest(
            tool_call_id="call_123",
            sender="Bash",
            action="run_command",
            description="ls -la",
        )
        data = serialize_approval_request(request)
        assert data["id"] == request.id
        assert data["tool_call_id"] == "call_123"
        assert data["sender"] == "Bash"
        assert data["action"] == "run_command"
        assert data["description"] == "ls -la"


class TestSerializeEvent:
    """Test event serialization."""

    def test_serialize_step_begin(self):
        """Serialize StepBegin event."""
        event = StepBegin(n=5)
        data = serialize_event(event)
        assert data["type"] == "step_begin"
        assert data["payload"]["n"] == 5

    def test_serialize_step_interrupted(self):
        """Serialize StepInterrupted event."""
        event = StepInterrupted()
        data = serialize_event(event)
        assert data["type"] == "step_interrupted"

    def test_serialize_compaction_begin(self):
        """Serialize CompactionBegin event."""
        event = CompactionBegin()
        data = serialize_event(event)
        assert data["type"] == "compaction_begin"

    def test_serialize_compaction_end(self):
        """Serialize CompactionEnd event."""
        event = CompactionEnd()
        data = serialize_event(event)
        assert data["type"] == "compaction_end"


class TestStepEvents:
    """Test step event namedtuples."""

    def test_step_begin(self):
        """StepBegin has step number."""
        step = StepBegin(n=1)
        assert step.n == 1

    def test_step_begin_tuple(self):
        """StepBegin is a namedtuple."""
        step = StepBegin(n=3)
        assert step[0] == 3

    def test_step_interrupted(self):
        """StepInterrupted is instantiable."""
        event = StepInterrupted()
        assert event is not None

    def test_compaction_begin(self):
        """CompactionBegin is instantiable."""
        event = CompactionBegin()
        assert event is not None

    def test_compaction_end(self):
        """CompactionEnd is instantiable."""
        event = CompactionEnd()
        assert event is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
