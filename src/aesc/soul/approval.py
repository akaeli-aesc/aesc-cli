from __future__ import annotations

import asyncio

from aesc.security.risk import RiskAssessor, RiskLevel
from aesc.soul.toolset import get_current_tool_call_or_none
from aesc.utils.logging import logger
from aesc.wire.message import ApprovalRequest, ApprovalResponse


class Approval:
    def __init__(self, yolo: bool = False):
        self._request_queue = asyncio.Queue[ApprovalRequest]()
        self._yolo = yolo
        self._auto_approve_actions: set[str] = set()
        """Set of action names that should automatically be approved."""

        # Risk-based approval tracking
        self._risk_assessor = RiskAssessor()
        self._approved_risk_levels: set[RiskLevel] = set()
        """Set of risk levels that have been approved for this session."""

    def set_yolo(self, yolo: bool) -> None:
        self._yolo = yolo

    async def request(
        self,
        sender: str,
        action: str,
        description: str,
        *,
        command: str | None = None,
    ) -> bool:
        """
        Request approval for the given action with risk-based auto-approval.

        Risk-based logic:
        - If user approved SAFE level, auto-approve all SAFE actions
        - If user approved LOW level, auto-approve SAFE and LOW actions
        - If user approved MEDIUM level, auto-approve SAFE, LOW, and MEDIUM actions
        - HIGH and CRITICAL always require explicit approval each time

        Args:
            sender (str): The name of the sender (tool name).
            action (str): The action to request approval for.
                This is used to identify the action for auto-approval.
            description (str): The description of the action (command/arguments).

        Returns:
            bool: True if the action is approved, False otherwise.

        Raises:
            RuntimeError: If the approval is requested from outside a tool call.
        """
        tool_call = get_current_tool_call_or_none()
        if tool_call is None:
            raise RuntimeError("Approval must be requested from a tool call.")

        logger.debug(
            "{tool_name} ({tool_call_id}) requesting approval: {action} {description}",
            tool_name=tool_call.function.name,
            tool_call_id=tool_call.id,
            action=action,
            description=description,
        )

        # YOLO mode: approve everything
        if self._yolo:
            return True

        # Legacy action-based auto-approval
        if action in self._auto_approve_actions:
            return True

        # Risk-based assessment. When the caller supplies the structured shell
        # command (bash tool), assess it directly. Re-parsing the human-readable
        # description string can truncate the command (e.g. at an inner backtick
        # substitution) and under-rate its risk, bypassing approval. See SEC-1.
        if command is not None:
            risk_assessment = self._risk_assessor.assess_bash_command(command)
        else:
            risk_assessment = self._risk_assessor.assess_tool_call(sender, description)

        logger.debug(
            "Risk assessment: level={level}, reason={reason}",
            level=risk_assessment.level.display_name,
            reason=risk_assessment.reason,
        )

        # Auto-approve if risk level already approved for session
        # All levels (including CRITICAL) can be auto-approved if same or higher approved
        for approved_level in self._approved_risk_levels:
            if risk_assessment.level <= approved_level:
                logger.debug(
                    "Auto-approving {lvl} (user approved {approved})",
                    lvl=risk_assessment.level.display_name,
                    approved=approved_level.display_name,
                )
                return True

        # Create approval request with risk information
        request = ApprovalRequest(
            tool_call.id,
            sender,
            action,
            description,
            risk_assessment=risk_assessment,  # Pass risk info to UI
        )
        self._request_queue.put_nowait(request)
        response = await request.wait()

        logger.debug("Received approval response: {response}", response=response)

        match response:
            case ApprovalResponse.APPROVE:
                # One-time approval - don't track risk level
                return True

            case ApprovalResponse.APPROVE_FOR_SESSION:
                # Track risk level for auto-approval
                self._approved_risk_levels.add(risk_assessment.level)
                logger.info(
                    "User approved {level} risk level for session",
                    level=risk_assessment.level.display_name,
                )
                return True

            case ApprovalResponse.REJECT:
                return False

    async def fetch_request(self) -> ApprovalRequest:
        """
        Fetch an approval request from the queue. Intended to be called by the soul.
        """
        return await self._request_queue.get()
