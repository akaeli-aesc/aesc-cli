"""Session manifest for tracking overall progress and state.

The manifest file sits at /results/{session_id}/manifest.json
and provides a real-time view of:
- Budget status
- Active/completed agents
- Findings summary
- Target information
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class ManifestAgent(BaseModel):
    """Agent entry in manifest."""

    id: str = Field(description="Agent ID (tool_call_id for subagents)")
    name: str = Field(description="Agent name")
    status: str = Field(default="running", description="running/completed/failed/killed")
    depth: int = Field(default=0, description="Tree depth (0 = main)")
    parent_id: str | None = Field(default=None, description="Parent agent ID")
    started_at: datetime = Field(default_factory=datetime.utcnow)
    finished_at: datetime | None = Field(default=None)
    prompt: str | None = Field(default=None, description="Task prompt (for subagents)")
    result_summary: str | None = Field(default=None, description="Brief result")


class ManifestFindingsSummary(BaseModel):
    """Findings count by severity."""

    critical: int = 0
    high: int = 0
    medium: int = 0
    low: int = 0
    info: int = 0

    @property
    def total(self) -> int:
        """Total findings count."""
        return self.critical + self.high + self.medium + self.low + self.info


class Manifest(BaseModel):
    """Session manifest - central state tracking."""

    # Session info
    session_id: str
    started_at: datetime = Field(default_factory=datetime.utcnow)
    last_updated: datetime = Field(default_factory=datetime.utcnow)

    # Targets
    targets: list[str] = Field(default_factory=list, description="Target IPs/ranges")
    scope: str | None = Field(default=None, description="Scope description")

    # Budget (synced from Budget object)
    budget: dict[str, Any] = Field(default_factory=dict)

    # Agents
    agents: list[ManifestAgent] = Field(default_factory=list)

    # Findings summary
    findings: ManifestFindingsSummary = Field(default_factory=ManifestFindingsSummary)

    # Intel counts
    intel_counts: dict[str, int] = Field(
        default_factory=lambda: {
            "hosts": 0,
            "services": 0,
            "credentials": 0,
        }
    )

    # Timeline (recent events)
    timeline: list[dict[str, Any]] = Field(default_factory=list, max_length=100)

    # ─────────────────────────────────────────────────────────────────────────
    # Agent Management
    # ─────────────────────────────────────────────────────────────────────────

    def add_agent(
        self,
        agent_id: str,
        name: str,
        depth: int = 0,
        parent_id: str | None = None,
        prompt: str | None = None,
    ) -> ManifestAgent:
        """Add a new agent to tracking."""
        agent = ManifestAgent(
            id=agent_id,
            name=name,
            depth=depth,
            parent_id=parent_id,
            prompt=prompt,
        )
        self.agents.append(agent)
        self._add_timeline_event(
            "agent_started",
            {
                "agent_id": agent_id,
                "name": name,
                "depth": depth,
            },
        )
        return agent

    def update_agent(
        self,
        agent_id: str,
        status: str | None = None,
        result_summary: str | None = None,
    ) -> None:
        """Update agent status."""
        for agent in self.agents:
            if agent.id == agent_id:
                if status:
                    agent.status = status
                    if status in ("completed", "failed", "killed"):
                        agent.finished_at = datetime.utcnow()
                if result_summary:
                    agent.result_summary = result_summary
                self._add_timeline_event(
                    "agent_updated",
                    {
                        "agent_id": agent_id,
                        "status": status,
                    },
                )
                break

    def get_agent(self, agent_id: str) -> ManifestAgent | None:
        """Get agent by ID."""
        for agent in self.agents:
            if agent.id == agent_id:
                return agent
        return None

    def get_active_agents(self) -> list[ManifestAgent]:
        """Get all running agents."""
        return [a for a in self.agents if a.status == "running"]

    # ─────────────────────────────────────────────────────────────────────────
    # Findings Management
    # ─────────────────────────────────────────────────────────────────────────

    def add_finding(self, severity: str) -> None:
        """Increment finding count for severity."""
        severity = severity.lower()
        if severity == "critical":
            self.findings.critical += 1
        elif severity == "high":
            self.findings.high += 1
        elif severity == "medium":
            self.findings.medium += 1
        elif severity == "low":
            self.findings.low += 1
        else:
            self.findings.info += 1

        self._add_timeline_event("finding_added", {"severity": severity})

    # ─────────────────────────────────────────────────────────────────────────
    # Intel Management
    # ─────────────────────────────────────────────────────────────────────────

    def increment_intel(self, intel_type: str) -> None:
        """Increment intel count."""
        if intel_type in self.intel_counts:
            self.intel_counts[intel_type] += 1
        else:
            self.intel_counts[intel_type] = 1

    def add_target(self, target: str) -> None:
        """Add a target to the list."""
        if target not in self.targets:
            self.targets.append(target)
            self._add_timeline_event("target_added", {"target": target})

    # ─────────────────────────────────────────────────────────────────────────
    # Timeline
    # ─────────────────────────────────────────────────────────────────────────

    def _add_timeline_event(self, event_type: str, data: dict[str, Any]) -> None:
        """Add event to timeline (keeps last 100)."""
        event = {
            "type": event_type,
            "timestamp": datetime.utcnow().isoformat(),
            **data,
        }
        self.timeline.append(event)
        # Keep only last 100 events
        if len(self.timeline) > 100:
            self.timeline = self.timeline[-100:]

    # ─────────────────────────────────────────────────────────────────────────
    # Persistence
    # ─────────────────────────────────────────────────────────────────────────

    def save(self, results_dir: Path) -> None:
        """Save manifest to results directory."""
        self.last_updated = datetime.utcnow()
        manifest_path = results_dir / "manifest.json"

        data = self.model_dump()
        # Convert datetime objects
        data["started_at"] = self.started_at.isoformat()
        data["last_updated"] = self.last_updated.isoformat()
        for agent in data["agents"]:
            agent["started_at"] = agent["started_at"].isoformat() if agent["started_at"] else None
            agent["finished_at"] = (
                agent["finished_at"].isoformat() if agent["finished_at"] else None
            )

        # Write atomically
        tmp_path = manifest_path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(data, indent=2))
        tmp_path.rename(manifest_path)

    @classmethod
    def load(cls, results_dir: Path, session_id: str) -> Manifest:
        """Load manifest from results directory or create new."""
        manifest_path = results_dir / "manifest.json"

        if manifest_path.exists():
            try:
                data = json.loads(manifest_path.read_text())

                # Parse datetime strings
                if "started_at" in data:
                    data["started_at"] = datetime.fromisoformat(data["started_at"])
                if "last_updated" in data:
                    data["last_updated"] = datetime.fromisoformat(data["last_updated"])

                for agent in data.get("agents", []):
                    if agent.get("started_at"):
                        agent["started_at"] = datetime.fromisoformat(agent["started_at"])
                    if agent.get("finished_at"):
                        agent["finished_at"] = datetime.fromisoformat(agent["finished_at"])

                return cls(**data)
            except (json.JSONDecodeError, OSError, ValueError):
                pass  # Fall through to create new

        # Create new manifest
        return cls(session_id=session_id)

    def to_summary(self) -> str:
        """Generate human-readable summary."""
        lines = [
            f"Session: {self.session_id}",
            f"Started: {self.started_at.strftime('%Y-%m-%d %H:%M:%S')}",
            f"Targets: {', '.join(self.targets) if self.targets else 'none'}",
            "",
            f"Agents: {len(self.get_active_agents())} running / {len(self.agents)} total",
            "",
            "Findings:",
            f"  Critical: {self.findings.critical}",
            f"  High: {self.findings.high}",
            f"  Medium: {self.findings.medium}",
            f"  Low: {self.findings.low}",
            f"  Info: {self.findings.info}",
            "",
            "Intel:",
            f"  Hosts: {self.intel_counts.get('hosts', 0)}",
            f"  Services: {self.intel_counts.get('services', 0)}",
            f"  Credentials: {self.intel_counts.get('credentials', 0)}",
        ]
        return "\n".join(lines)
