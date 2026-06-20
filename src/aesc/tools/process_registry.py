"""Process Registry for tracking running commands.

Enables UI to monitor and kill running processes.
Supports both PTY-based (subprocess.Popen) and pipe-based (asyncio.subprocess.Process).
"""

from __future__ import annotations

import os
import signal
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class RunningProcess:
    """A running process tracked by the registry."""

    tool_call_id: str
    """The tool call ID that started this process."""
    command: str
    """The command being executed."""
    process: Any  # asyncio.subprocess.Process | subprocess.Popen
    """The subprocess handle (asyncio Process or Popen)."""
    pgid: int | None = None
    """Process group ID for PTY processes (enables killing entire command tree)."""
    started_at: datetime = field(default_factory=datetime.now)
    """When the process started."""
    output_buffer: list[str] = field(default_factory=lambda: [])
    """Accumulated output lines (limited to last N lines)."""

    MAX_OUTPUT_LINES: int = 100

    def append_output(self, line: str) -> None:
        """Append output line, keeping only the last MAX_OUTPUT_LINES."""
        self.output_buffer.append(line)
        if len(self.output_buffer) > self.MAX_OUTPUT_LINES:
            self.output_buffer = self.output_buffer[-self.MAX_OUTPUT_LINES :]

    @property
    def elapsed_seconds(self) -> float:
        """Seconds since process started."""
        return (datetime.now() - self.started_at).total_seconds()

    @property
    def is_running(self) -> bool:
        """Check if process is still running."""
        return self.process.returncode is None

    def kill(self) -> None:
        """Kill the process. Uses process group kill for PTY processes."""
        if not self.is_running:
            return
        # Try process group kill first (kills shell + all children)
        if self.pgid is not None:
            try:
                os.killpg(self.pgid, signal.SIGKILL)
                return
            except (ProcessLookupError, OSError):
                pass
        # Fallback: kill just the process
        try:
            self.process.kill()
        except (ProcessLookupError, OSError):
            pass


class ProcessRegistry:
    """
    Global registry of running processes.

    Singleton pattern - use get_registry() to access.
    """

    _instance: ProcessRegistry | None = None

    def __init__(self):
        self._processes: dict[str, RunningProcess] = {}
        self._listeners: list[Callable[[], None]] = []

    @classmethod
    def get_instance(cls) -> ProcessRegistry:
        """Get the singleton registry instance."""
        if cls._instance is None:
            cls._instance = ProcessRegistry()
        return cls._instance

    def register(
        self,
        tool_call_id: str,
        command: str,
        process: Any,
        pgid: int | None = None,
    ) -> RunningProcess:
        """Register a new running process.

        Args:
            tool_call_id: The tool call ID.
            command: The shell command.
            process: asyncio.subprocess.Process or subprocess.Popen.
            pgid: Process group ID for PTY processes (enables group kill).
        """
        rp = RunningProcess(
            tool_call_id=tool_call_id,
            command=command,
            process=process,
            pgid=pgid,
        )
        self._processes[tool_call_id] = rp
        self._notify_listeners()
        return rp

    def unregister(self, tool_call_id: str) -> None:
        """Unregister a process (called when it finishes)."""
        if tool_call_id in self._processes:
            del self._processes[tool_call_id]
            self._notify_listeners()

    def get(self, tool_call_id: str) -> RunningProcess | None:
        """Get a running process by tool call ID."""
        return self._processes.get(tool_call_id)

    def get_all(self) -> list[RunningProcess]:
        """Get all running processes, sorted by start time (oldest first)."""
        return sorted(
            self._processes.values(),
            key=lambda p: p.started_at,
        )

    def kill(self, tool_call_id: str) -> bool:
        """Kill a process by tool call ID. Returns True if killed."""
        rp = self._processes.get(tool_call_id)
        if rp and rp.is_running:
            rp.kill()
            return True
        return False

    def kill_all(self) -> int:
        """Kill all running processes. Returns count of killed processes."""
        killed = 0
        for rp in self._processes.values():
            if rp.is_running:
                rp.kill()
                killed += 1
        return killed

    def add_listener(self, callback: Callable[[], None]) -> None:
        """Add a listener to be notified when processes change."""
        self._listeners.append(callback)

    def remove_listener(self, callback: Callable[[], None]) -> None:
        """Remove a listener."""
        if callback in self._listeners:
            self._listeners.remove(callback)

    def _notify_listeners(self) -> None:
        """Notify all listeners of a change."""
        for listener in self._listeners:
            try:
                listener()
            except Exception:
                pass  # Don't let listener errors break the registry

    @property
    def count(self) -> int:
        """Number of running processes."""
        return len(self._processes)


def get_registry() -> ProcessRegistry:
    """Get the global process registry."""
    return ProcessRegistry.get_instance()
