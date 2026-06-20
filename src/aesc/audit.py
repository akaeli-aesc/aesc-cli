"""Audit logging for aesc - tracks all tool executions for compliance and forensics."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from aesc.security.risk import RiskLevel
from aesc.share import get_share_dir
from aesc.utils.logging import logger


@dataclass
class AuditEntry:
    """A single audit log entry."""

    timestamp: str
    session_id: str
    tool_name: str
    tool_call_id: str
    command_summary: str  # Brief description (e.g., "nmap -sV 192.168.1.1")
    risk_level: str  # RiskLevel as string
    approval_type: Literal["auto", "yolo", "user_once", "user_session", "rejected"]
    result: Literal["success", "error", "timeout", "cancelled"]
    duration_ms: int = 0
    error_message: str | None = None

    def to_json(self) -> str:
        """Serialize to JSON line."""
        return json.dumps(asdict(self), ensure_ascii=False)

    @classmethod
    def from_json(cls, line: str) -> AuditEntry:
        """Deserialize from JSON line."""
        data = json.loads(line)
        return cls(**data)


class AuditLog:
    """Append-only audit log for tool executions.

    Format: JSON Lines (one JSON object per line)
    Location: ~/.aesc/audit.jsonl

    Usage:
        audit = AuditLog()
        audit.log_tool_start(session_id, "bash", "tool_123", "nmap -sV target", RiskLevel.HIGH, "user_once")
        audit.log_tool_end("tool_123", "success", duration_ms=1234)
    """

    def __init__(self, audit_file: Path | None = None):
        self._audit_file = audit_file or (get_share_dir() / "audit.jsonl")
        self._pending: dict[str, AuditEntry] = {}  # tool_call_id -> entry

        # Ensure audit directory exists
        self._audit_file.parent.mkdir(parents=True, exist_ok=True)

    def log_tool_start(
        self,
        session_id: str,
        tool_name: str,
        tool_call_id: str,
        command_summary: str,
        risk_level: RiskLevel,
        approval_type: Literal["auto", "yolo", "user_once", "user_session", "rejected"],
    ) -> None:
        """Log the start of a tool execution."""
        entry = AuditEntry(
            timestamp=datetime.now(UTC).isoformat(),
            session_id=session_id,
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            command_summary=_truncate(command_summary, 500),
            risk_level=risk_level.name if isinstance(risk_level, RiskLevel) else str(risk_level),
            approval_type=approval_type,
            result="success",  # Will be updated on end
        )

        # Store pending entry
        self._pending[tool_call_id] = entry

        # Log immediately if rejected
        if approval_type == "rejected":
            entry.result = "cancelled"
            self._write_entry(entry)
            del self._pending[tool_call_id]

    def log_tool_end(
        self,
        tool_call_id: str,
        result: Literal["success", "error", "timeout", "cancelled"],
        duration_ms: int = 0,
        error_message: str | None = None,
    ) -> None:
        """Log the completion of a tool execution."""
        if tool_call_id not in self._pending:
            logger.warning("Audit: tool_call_id {id} not found in pending", id=tool_call_id)
            return

        entry = self._pending.pop(tool_call_id)
        entry.result = result
        entry.duration_ms = duration_ms
        entry.error_message = _truncate(error_message, 200) if error_message else None

        self._write_entry(entry)

    def _write_entry(self, entry: AuditEntry) -> None:
        """Write entry to audit log (append-only)."""
        try:
            with open(self._audit_file, "a", encoding="utf-8") as f:
                f.write(entry.to_json() + "\n")
        except OSError as e:
            logger.error("Failed to write audit log: {error}", error=e)

    def get_session_entries(self, session_id: str) -> list[AuditEntry]:
        """Get all audit entries for a session."""
        entries = []
        if not self._audit_file.exists():
            return entries

        with open(self._audit_file, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = AuditEntry.from_json(line)
                    if entry.session_id == session_id:
                        entries.append(entry)
                except (json.JSONDecodeError, TypeError):
                    continue

        return entries

    def export_session_report(self, session_id: str) -> str:
        """Export session audit as markdown report."""
        entries = self.get_session_entries(session_id)

        if not entries:
            return f"# Audit Report\n\nNo entries found for session {session_id}"

        lines = [
            "# Audit Report",
            "",
            f"**Session ID:** {session_id}",
            f"**Generated:** {datetime.now(UTC).isoformat()}",
            f"**Total Commands:** {len(entries)}",
            "",
            "## Command History",
            "",
            "| Time | Tool | Command | Risk | Approval | Result | Duration |",
            "|------|------|---------|------|----------|--------|----------|",
        ]

        for entry in entries:
            time_short = (
                entry.timestamp.split("T")[1].split(".")[0]
                if "T" in entry.timestamp
                else entry.timestamp
            )
            cmd_short = (
                entry.command_summary[:40] + "..."
                if len(entry.command_summary) > 40
                else entry.command_summary
            )
            lines.append(
                f"| {time_short} | {entry.tool_name} | `{cmd_short}` | "
                f"{entry.risk_level} | {entry.approval_type} | {entry.result} | {entry.duration_ms}ms |"
            )

        # Summary stats
        success_count = sum(1 for e in entries if e.result == "success")
        error_count = sum(1 for e in entries if e.result == "error")
        rejected_count = sum(1 for e in entries if e.approval_type == "rejected")

        risk_counts = {}
        for entry in entries:
            risk_counts[entry.risk_level] = risk_counts.get(entry.risk_level, 0) + 1

        lines.extend(
            [
                "",
                "## Summary",
                "",
                f"- **Successful:** {success_count}",
                f"- **Errors:** {error_count}",
                f"- **Rejected:** {rejected_count}",
                "",
                "### Risk Distribution",
                "",
            ]
        )

        for risk, count in sorted(risk_counts.items()):
            lines.append(f"- {risk}: {count}")

        return "\n".join(lines)


def _truncate(s: str | None, max_len: int) -> str:
    """Truncate string to max length."""
    if s is None:
        return ""
    if len(s) <= max_len:
        return s
    return s[: max_len - 3] + "..."


# Global audit log instance
_audit_log: AuditLog | None = None


def get_audit_log() -> AuditLog:
    """Get the global audit log instance."""
    global _audit_log
    if _audit_log is None:
        _audit_log = AuditLog()
    return _audit_log
