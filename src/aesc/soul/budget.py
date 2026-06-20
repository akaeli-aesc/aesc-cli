"""Budget tracking for parallel agent execution.

Provides token, time, and depth limits to prevent runaway agent trees.
Budget is shared across all agents in a session.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


class BudgetExceeded(Exception):
    """Raised when budget limits are exceeded."""

    def __init__(self, reason: str, budget: Budget):
        self.reason = reason
        self.budget = budget
        super().__init__(f"Budget exceeded: {reason}")


class BudgetWarning(Exception):
    """Raised when approaching budget limits (>80%)."""

    def __init__(self, reason: str, percentage: float):
        self.reason = reason
        self.percentage = percentage
        super().__init__(f"Budget warning ({percentage:.0%}): {reason}")


@dataclass
class BudgetConfig:
    """Budget configuration - immutable limits."""

    # Token limits
    max_tokens: int = 500_000  # Total input+output tokens

    # Time limits
    max_time_seconds: int = 3600  # 1 hour default

    # Tree limits
    max_depth: int = 5  # Maximum agent tree depth
    max_parallel_agents: int = 10  # Maximum concurrent agents
    max_total_agents: int = 50  # Maximum total agents spawned

    # Warning thresholds (percentage)
    warning_threshold: float = 0.8  # Warn at 80%


@dataclass
class BudgetState:
    """Budget state - mutable tracking."""

    # Token tracking
    tokens_used: int = 0
    tokens_by_agent: dict[str, int] = field(default_factory=dict)

    # Time tracking
    start_time: float = field(default_factory=time.time)

    # Agent tracking
    current_depth: int = 0
    max_depth_reached: int = 0
    active_agents: int = 0
    total_agents_spawned: int = 0
    agent_tree: dict[str, list[str]] = field(default_factory=dict)  # parent -> children


class Budget:
    """
    Budget tracker for a session.

    Thread-safe using asyncio locks.
    Shared across all agents via Runtime.
    """

    def __init__(self, config: BudgetConfig | None = None):
        self.config = config or BudgetConfig()
        self.state = BudgetState()
        self._lock = asyncio.Lock()

    # ─────────────────────────────────────────────────────────────────────────
    # Status Queries
    # ─────────────────────────────────────────────────────────────────────────

    @property
    def elapsed_seconds(self) -> float:
        """Elapsed time since budget started."""
        return time.time() - self.state.start_time

    @property
    def tokens_remaining(self) -> int:
        """Remaining tokens."""
        return max(0, self.config.max_tokens - self.state.tokens_used)

    @property
    def time_remaining(self) -> float:
        """Remaining time in seconds."""
        return max(0, self.config.max_time_seconds - self.elapsed_seconds)

    @property
    def token_percentage(self) -> float:
        """Percentage of token budget used."""
        if self.config.max_tokens == 0:
            return 0.0
        return self.state.tokens_used / self.config.max_tokens

    @property
    def time_percentage(self) -> float:
        """Percentage of time budget used."""
        if self.config.max_time_seconds == 0:
            return 0.0
        return self.elapsed_seconds / self.config.max_time_seconds

    @property
    def depth_remaining(self) -> int:
        """Remaining tree depth."""
        return max(0, self.config.max_depth - self.state.current_depth)

    def to_dict(self) -> dict:
        """Export budget status as dict (for manifest)."""
        return {
            "config": {
                "max_tokens": self.config.max_tokens,
                "max_time_seconds": self.config.max_time_seconds,
                "max_depth": self.config.max_depth,
                "max_parallel_agents": self.config.max_parallel_agents,
                "max_total_agents": self.config.max_total_agents,
            },
            "state": {
                "tokens_used": self.state.tokens_used,
                "tokens_remaining": self.tokens_remaining,
                "elapsed_seconds": round(self.elapsed_seconds, 1),
                "time_remaining": round(self.time_remaining, 1),
                "current_depth": self.state.current_depth,
                "max_depth_reached": self.state.max_depth_reached,
                "active_agents": self.state.active_agents,
                "total_agents_spawned": self.state.total_agents_spawned,
            },
            "percentages": {
                "tokens": round(self.token_percentage * 100, 1),
                "time": round(self.time_percentage * 100, 1),
            },
        }

    # ─────────────────────────────────────────────────────────────────────────
    # Budget Operations
    # ─────────────────────────────────────────────────────────────────────────

    async def add_tokens(self, tokens: int, agent_id: str = "main") -> None:
        """
        Record token usage.

        Raises BudgetExceeded if over limit.
        Raises BudgetWarning if approaching limit.
        """
        async with self._lock:
            self.state.tokens_used += tokens
            self.state.tokens_by_agent[agent_id] = (
                self.state.tokens_by_agent.get(agent_id, 0) + tokens
            )

            # Check exceeded
            if self.state.tokens_used > self.config.max_tokens:
                raise BudgetExceeded(
                    f"Token limit exceeded: {self.state.tokens_used:,} / {self.config.max_tokens:,}",
                    self,
                )

            # Check warning
            if self.token_percentage >= self.config.warning_threshold:
                raise BudgetWarning(
                    f"Token budget at {self.token_percentage:.0%}", self.token_percentage
                )

    def check_time(self) -> None:
        """
        Check time budget.

        Raises BudgetExceeded if over limit.
        """
        if self.elapsed_seconds > self.config.max_time_seconds:
            raise BudgetExceeded(
                f"Time limit exceeded: {self.elapsed_seconds:.0f}s / {self.config.max_time_seconds}s",
                self,
            )

    async def can_spawn_agent(
        self, parent_id: str | None = None, depth: int = 0
    ) -> tuple[bool, str]:
        """
        Check if a new agent can be spawned.

        Returns (allowed, reason).
        """
        async with self._lock:
            # Check parallel limit
            if self.state.active_agents >= self.config.max_parallel_agents:
                return False, f"Max parallel agents reached ({self.config.max_parallel_agents})"

            # Check total limit
            if self.state.total_agents_spawned >= self.config.max_total_agents:
                return False, f"Max total agents reached ({self.config.max_total_agents})"

            # Check depth limit
            if depth >= self.config.max_depth:
                return False, f"Max depth reached ({self.config.max_depth})"

            # Check time
            if self.time_remaining <= 0:
                return False, "Time budget exhausted"

            # Check tokens (need at least some buffer)
            min_tokens_for_agent = 1000  # Minimum tokens to start an agent
            if self.tokens_remaining < min_tokens_for_agent:
                return (
                    False,
                    f"Insufficient tokens ({self.tokens_remaining} < {min_tokens_for_agent})",
                )

            return True, "OK"

    async def agent_started(
        self, agent_id: str, parent_id: str | None = None, depth: int = 0
    ) -> None:
        """Record agent start."""
        async with self._lock:
            self.state.active_agents += 1
            self.state.total_agents_spawned += 1
            self.state.current_depth = max(self.state.current_depth, depth)
            self.state.max_depth_reached = max(self.state.max_depth_reached, depth)

            # Track tree structure
            if parent_id:
                if parent_id not in self.state.agent_tree:
                    self.state.agent_tree[parent_id] = []
                self.state.agent_tree[parent_id].append(agent_id)

    async def agent_finished(self, agent_id: str) -> None:
        """Record agent completion."""
        async with self._lock:
            self.state.active_agents = max(0, self.state.active_agents - 1)

    # ─────────────────────────────────────────────────────────────────────────
    # Persistence
    # ─────────────────────────────────────────────────────────────────────────

    def save_to_manifest(self, manifest_path: Path) -> None:
        """Save budget state to manifest file."""
        import json

        manifest_path.parent.mkdir(parents=True, exist_ok=True)

        # Load existing manifest or create new
        if manifest_path.exists():
            try:
                manifest = json.loads(manifest_path.read_text())
            except (json.JSONDecodeError, OSError):
                manifest = {}
        else:
            manifest = {}

        # Update budget section
        manifest["budget"] = self.to_dict()

        # Write atomically
        tmp_path = manifest_path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(manifest, indent=2))
        tmp_path.rename(manifest_path)

    @classmethod
    def load_from_manifest(cls, manifest_path: Path) -> Budget:
        """Load budget state from manifest file."""
        import json

        budget = cls()

        if not manifest_path.exists():
            return budget

        try:
            manifest = json.loads(manifest_path.read_text())
            budget_data = manifest.get("budget", {})

            # Restore config
            config_data = budget_data.get("config", {})
            budget.config = BudgetConfig(
                max_tokens=config_data.get("max_tokens", budget.config.max_tokens),
                max_time_seconds=config_data.get(
                    "max_time_seconds", budget.config.max_time_seconds
                ),
                max_depth=config_data.get("max_depth", budget.config.max_depth),
                max_parallel_agents=config_data.get(
                    "max_parallel_agents", budget.config.max_parallel_agents
                ),
                max_total_agents=config_data.get(
                    "max_total_agents", budget.config.max_total_agents
                ),
            )

            # Restore state (partially - some state is runtime only)
            state_data = budget_data.get("state", {})
            budget.state.tokens_used = state_data.get("tokens_used", 0)
            budget.state.total_agents_spawned = state_data.get("total_agents_spawned", 0)
            budget.state.max_depth_reached = state_data.get("max_depth_reached", 0)

        except (json.JSONDecodeError, OSError, KeyError):
            pass  # Return default budget on error

        return budget


# ─────────────────────────────────────────────────────────────────────────────
# Convenience Functions
# ─────────────────────────────────────────────────────────────────────────────


def create_budget(
    max_tokens: int = 500_000,
    max_time_minutes: int = 60,
    max_depth: int = 5,
    max_parallel: int = 10,
) -> Budget:
    """Create a budget with common defaults."""
    return Budget(
        BudgetConfig(
            max_tokens=max_tokens,
            max_time_seconds=max_time_minutes * 60,
            max_depth=max_depth,
            max_parallel_agents=max_parallel,
        )
    )
