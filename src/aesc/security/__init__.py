"""Security-specific utilities and constants for AESC."""

from aesc.security.risk_assessment import (
    RiskAssessment,
    RiskLevel,
    SecurityRiskAssessor,
)
from aesc.security.visual import (
    SECURITY_TOOL_ICONS,
    SEVERITY_COLORS,
    SecurityPhase,
    colorize_security_text,
    detect_security_phase,
    get_severity_badge,
    get_tool_icon,
)

__all__ = [
    # Risk assessment
    "RiskAssessment",
    "RiskLevel",
    "SecurityRiskAssessor",
    # Visual utilities
    "SECURITY_TOOL_ICONS",
    "SEVERITY_COLORS",
    "SecurityPhase",
    "colorize_security_text",
    "detect_security_phase",
    "get_severity_badge",
    "get_tool_icon",
]
