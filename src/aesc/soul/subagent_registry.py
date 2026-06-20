"""Registry for tracking active subagents.

Provides visibility and control over running subagents:
- Track active subagents by task_tool_call_id
- Store output buffers for UI display
- Support killing subagents
- Enable jumping/intervention
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from aesc.soul.aescsoul import AescSoul
    from aesc.wire.message import Event


@dataclass
class SubagentSession:
    """Represents an active subagent session."""

    task_tool_call_id: str
    """The tool call ID of the parent Task that spawned this subagent."""

    agent_name: str
    """Name of the subagent (e.g., 'reconnaissance', 'exploitation')."""

    prompt: str
    """The prompt/task given to the subagent."""

    started_at: datetime = field(default_factory=datetime.now)
    """When the subagent was started."""

    soul: AescSoul | None = None
    """Reference to the running AescSoul instance."""

    task: asyncio.Task[Any] | None = None
    """The asyncio task running the subagent."""

    output_buffer: list[Event] = field(default_factory=list)
    """Buffer of events from the subagent for UI display."""

    status: str = "running"
    """Status: running, completed, failed, killed."""

    result: str | None = None
    """Final result from the subagent."""

    MAX_OUTPUT_BUFFER: int = 500
    """Maximum events to keep in buffer."""

    def append_event(self, event: Event) -> None:
        """Add an event to the output buffer."""
        self.output_buffer.append(event)
        # Trim buffer if too large
        if len(self.output_buffer) > self.MAX_OUTPUT_BUFFER:
            # Keep last half
            self.output_buffer = self.output_buffer[-(self.MAX_OUTPUT_BUFFER // 2) :]

    def mark_completed(self, result: str | None = None) -> None:
        """Mark subagent as completed."""
        self.status = "completed"
        self.result = result

    def mark_failed(self, error: str) -> None:
        """Mark subagent as failed."""
        self.status = "failed"
        self.result = f"Error: {error}"

    def mark_killed(self) -> None:
        """Mark subagent as killed."""
        self.status = "killed"
        self.result = "Killed by user"


class SubagentRegistry:
    """Singleton registry for tracking active subagents."""

    _instance: SubagentRegistry | None = None

    def __init__(self) -> None:
        self._sessions: dict[str, SubagentSession] = {}
        self._lock = asyncio.Lock()

    @classmethod
    def get_instance(cls) -> SubagentRegistry:
        """Get or create the singleton instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    async def register(
        self,
        task_tool_call_id: str,
        agent_name: str,
        prompt: str,
        soul: AescSoul | None = None,
        task: asyncio.Task[Any] | None = None,
    ) -> SubagentSession:
        """Register a new subagent session."""
        async with self._lock:
            session = SubagentSession(
                task_tool_call_id=task_tool_call_id,
                agent_name=agent_name,
                prompt=prompt,
                soul=soul,
                task=task,
            )
            self._sessions[task_tool_call_id] = session
            return session

    async def unregister(self, task_tool_call_id: str) -> SubagentSession | None:
        """Unregister a subagent session."""
        async with self._lock:
            return self._sessions.pop(task_tool_call_id, None)

    def get(self, task_tool_call_id: str) -> SubagentSession | None:
        """Get a subagent session by task tool call ID."""
        return self._sessions.get(task_tool_call_id)

    def get_all(self) -> list[SubagentSession]:
        """Get all active subagent sessions."""
        return list(self._sessions.values())

    def get_running(self) -> list[SubagentSession]:
        """Get all running subagent sessions."""
        return [s for s in self._sessions.values() if s.status == "running"]

    async def kill(self, task_tool_call_id: str) -> bool:
        """Kill a running subagent.

        This will:
        1. Call cancel() on the soul for cooperative cancellation
        2. Cancel the asyncio task if still running
        3. Mark the session as killed
        """
        session = self._sessions.get(task_tool_call_id)
        if session is None:
            return False

        if session.status != "running":
            return False  # Already finished

        # Request cooperative cancellation via soul
        if session.soul is not None:
            session.soul.cancel()

        # Force cancel the task if still running
        if session.task and not session.task.done():
            session.task.cancel()
            try:
                await asyncio.wait_for(
                    asyncio.shield(session.task),
                    timeout=2.0,  # Give it 2 seconds to clean up
                )
            except (TimeoutError, asyncio.CancelledError):
                pass  # Expected

        session.mark_killed()
        return True

    async def kill_all(self) -> int:
        """Kill all running subagents. Returns count of killed agents."""
        killed = 0
        for task_id in list(self._sessions.keys()):
            if await self.kill(task_id):
                killed += 1
        return killed

    def append_event(self, task_tool_call_id: str, event: Event) -> None:
        """Append an event to a subagent's output buffer."""
        session = self._sessions.get(task_tool_call_id)
        if session:
            session.append_event(event)

    def clear(self) -> None:
        """Clear all sessions (for testing)."""
        self._sessions.clear()


def get_registry() -> SubagentRegistry:
    """Get the singleton SubagentRegistry instance."""
    return SubagentRegistry.get_instance()
