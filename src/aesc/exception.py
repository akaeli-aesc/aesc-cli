from __future__ import annotations


class AescCLIException(Exception):
    """Base exception class for AESC."""

    pass


class ConfigError(AescCLIException):
    """Configuration error."""

    pass


class AgentSpecError(AescCLIException):
    """Agent specification error."""

    pass
