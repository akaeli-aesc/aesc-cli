from __future__ import annotations

import asyncio
import uuid
from collections.abc import Sequence
from enum import Enum
from typing import TYPE_CHECKING, Any, NamedTuple

from aesc.provider import ContentPart, ToolCall, ToolCallPart, ToolOk, ToolResult

if TYPE_CHECKING:
    from aesc.soul import StatusSnapshot


class StepBegin(NamedTuple):
    n: int


class StepInterrupted:
    pass


class CompactionBegin:
    """
    Indicates that a compaction just began.
    This event must be sent during a step, which means, between `StepBegin` and `StepInterrupted`.
    And, there must be a `CompactionEnd` directly following this event.
    """

    pass


class CompactionEnd(NamedTuple):
    """
    Indicates that a compaction just ended.
    This event must be sent directly after a `CompactionBegin` event.

    Includes summary data for UI display.
    """

    summary: str = ""
    """Brief summary of the compacted conversation (first line)."""
    full_summary: str = ""
    """Full compacted context for expandable display."""
    original_tokens: int = 0
    """Estimated token count before compaction."""
    compacted_tokens: int = 0
    """Estimated token count after compaction."""
    compression_ratio: float = 1.0
    """Ratio of compacted to original (lower is more compressed)."""
    is_session_restore: bool = False
    """True if this is from a session restore rather than auto-compaction."""


class StatusUpdate(NamedTuple):
    status: StatusSnapshot


class SubagentEvent(NamedTuple):
    task_tool_call_id: str
    event: Event


class ToolOutputChunk(NamedTuple):
    """Streaming output from a running tool (e.g., bash command output)."""

    tool_call_id: str
    chunk: str
    is_stderr: bool = False


class RetryWait(NamedTuple):
    """Indicates the agent is waiting to retry after a rate limit or transient error."""

    attempt: int
    """Current retry attempt number."""
    wait_seconds: float
    """How long we're waiting before retrying."""
    reason: str
    """Why we're retrying (e.g., 'rate_limit', 'server_error')."""


type ControlFlowEvent = (
    StepBegin | StepInterrupted | CompactionBegin | CompactionEnd | StatusUpdate | RetryWait
)
type Event = (
    ControlFlowEvent
    | ContentPart
    | ToolCall
    | ToolCallPart
    | ToolResult
    | SubagentEvent
    | ToolOutputChunk
)


class ApprovalResponse(Enum):
    APPROVE = "approve"
    APPROVE_FOR_SESSION = "approve_for_session"
    REJECT = "reject"


class ApprovalRequest:
    def __init__(
        self,
        tool_call_id: str,
        sender: str,
        action: str,
        description: str,
        risk_assessment: Any | None = None,  # RiskAssessment from aesc.security.risk
    ):
        self.id = str(uuid.uuid4())
        self.tool_call_id = tool_call_id
        self.sender = sender
        self.action = action
        self.description = description
        self.risk_assessment = risk_assessment
        self._future: asyncio.Future[ApprovalResponse] | None = None

    def __repr__(self) -> str:
        return (
            f"ApprovalRequest(id={self.id}, tool_call_id={self.tool_call_id}, "
            f"sender={self.sender}, action={self.action}, description={self.description})"
        )

    def _ensure_future(self) -> asyncio.Future[ApprovalResponse]:
        """Ensure the future is created in the current event loop."""
        if self._future is None:
            self._future = asyncio.Future[ApprovalResponse]()
        return self._future

    async def wait(self) -> ApprovalResponse:
        """
        Wait for the request to be resolved or cancelled.

        Returns:
            ApprovalResponse: The response to the approval request.
        """
        return await self._ensure_future()

    def resolve(self, response: ApprovalResponse) -> None:
        """
        Resolve the approval request with the given response.
        This will cause the `wait()` method to return the response.

        Safe to call multiple times - subsequent calls are ignored.
        """
        future = self._ensure_future()
        if not future.done():
            future.set_result(response)

    def approve(self) -> None:
        """Approve this request (one-time)."""
        self.resolve(ApprovalResponse.APPROVE)

    def approve_for_session(self) -> None:
        """Approve this request and similar ones for the session."""
        self.resolve(ApprovalResponse.APPROVE_FOR_SESSION)

    def reject(self) -> None:
        """Reject this request."""
        self.resolve(ApprovalResponse.REJECT)

    @property
    def resolved(self) -> bool:
        """Whether the request is resolved."""
        return self._future is not None and self._future.done()


type WireMessage = Event | ApprovalRequest


def serialize_event(event: Event) -> dict[str, Any]:
    """
    Convert an event message into a JSON-serializable dictionary.
    """
    match event:
        case StepBegin():
            return {"type": "step_begin", "payload": {"n": event.n}}
        case StepInterrupted():
            return {"type": "step_interrupted"}
        case CompactionBegin():
            return {"type": "compaction_begin"}
        case CompactionEnd():
            return {"type": "compaction_end"}
        case StatusUpdate():
            return {
                "type": "status_update",
                "payload": {"context_usage": event.status.context_usage},
            }
        case ContentPart():
            return {
                "type": "content_part",
                "payload": event.model_dump(mode="json", exclude_none=True),
            }
        case ToolCall():
            return {
                "type": "tool_call",
                "payload": event.model_dump(mode="json", exclude_none=True),
            }
        case ToolCallPart():
            return {
                "type": "tool_call_part",
                "payload": event.model_dump(mode="json", exclude_none=True),
            }
        case ToolResult():
            return {
                "type": "tool_result",
                "payload": serialize_tool_result(event),
            }
        case SubagentEvent():
            return {
                "type": "subagent_event",
                "payload": {
                    "task_tool_call_id": event.task_tool_call_id,
                    "event": serialize_event(event.event),
                },
            }
        case ToolOutputChunk():
            return {
                "type": "tool_output_chunk",
                "payload": {
                    "tool_call_id": event.tool_call_id,
                    "chunk": event.chunk,
                    "is_stderr": event.is_stderr,
                },
            }
        case RetryWait():
            return {
                "type": "retry_wait",
                "payload": {
                    "attempt": event.attempt,
                    "wait_seconds": event.wait_seconds,
                    "reason": event.reason,
                },
            }
        case _:
            # Fallback for any unhandled event types - log and return a minimal representation
            # This prevents returning None which causes "params": null in JSON-RPC
            return {
                "type": "unknown",
                "payload": {"repr": repr(event)[:200]},
            }


def serialize_approval_request(request: ApprovalRequest) -> dict[str, Any]:
    """
    Convert an ApprovalRequest into a JSON-serializable dictionary.
    """
    result = {
        "id": request.id,
        "tool_call_id": request.tool_call_id,
        "sender": request.sender,
        "action": request.action,
        "description": request.description,
    }

    # Include risk assessment if available
    if request.risk_assessment is not None:
        result["risk"] = serialize_risk_assessment(request.risk_assessment)

    return result


def serialize_risk_assessment(assessment: Any) -> dict[str, Any]:
    """
    Convert a RiskAssessment into a JSON-serializable dictionary.
    """
    # Import here to avoid circular imports
    from aesc.security.risk import RiskAssessment

    if not isinstance(assessment, RiskAssessment):
        return {}

    result = {
        "level": assessment.level.value[0],  # "safe", "low", "medium", "high", "critical"
        "level_display": assessment.level.display_name,  # "SAFE", "LOW", etc.
        "color": assessment.level.color,  # For UI styling
        "icon": assessment.level.icon,  # "✓", "ℹ", "⚠", "⚡", "⛔"
        "reason": assessment.reason,
        "patterns_matched": assessment.patterns_matched,
    }

    if assessment.obfuscation_detected:
        result["obfuscation_detected"] = assessment.obfuscation_detected

    if assessment.extracted_targets is not None:
        targets = assessment.extracted_targets
        result["targets"] = {
            "ips": targets.ips,
            "domains": targets.domains,
            "ports": targets.ports,
        }

    return result


def serialize_tool_result(result: ToolResult) -> dict[str, Any]:
    if isinstance(result.result, ToolOk):
        ok = True
        result_data = {
            "output": _serialize_tool_output(result.result.output),
            "message": result.result.message,
            "brief": result.result.brief,
        }
    else:
        ok = False
        result_data = {
            "output": result.result.output,
            "message": result.result.message,
            "brief": result.result.brief,
        }
    return {
        "tool_call_id": result.tool_call_id,
        "ok": ok,
        "result": result_data,
    }


def _serialize_tool_output(
    output: str | ContentPart | Sequence[ContentPart],
) -> str | list[Any] | dict[str, Any]:
    if isinstance(output, str):
        return output
    elif isinstance(output, ContentPart):
        return output.model_dump(mode="json", exclude_none=True)
    else:  # Sequence[ContentPart]
        return [part.model_dump(mode="json", exclude_none=True) for part in output]
