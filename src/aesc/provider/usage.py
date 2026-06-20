"""
Token usage tracking.
"""

from dataclasses import dataclass


@dataclass(slots=True)
class TokenUsage:
    """Token usage statistics from a provider."""

    input_other: int = 0
    output: int = 0
    input_cache_read: int = 0
    input_cache_write: int = 0

    @property
    def input(self) -> int:
        """Total input tokens."""
        return self.input_other + self.input_cache_read + self.input_cache_write

    @property
    def total(self) -> int:
        """Total tokens used."""
        return self.input + self.output
