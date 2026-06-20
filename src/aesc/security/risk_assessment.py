"""Risk assessment system for security tool execution."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any


class RiskLevel(str, Enum):
    """Risk levels for tool execution."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class RiskAssessment:
    """Result of a risk assessment."""

    level: RiskLevel
    """Assessed risk level"""

    reasons: list[str]
    """Human-readable reasons for the risk level"""

    dangerous_patterns: list[str]
    """List of dangerous patterns detected in the command/parameters"""

    mitigation_suggestions: list[str] | None = None
    """Optional suggestions for mitigating the risk"""

    requires_extra_confirmation: bool = False
    """Whether this operation requires extra confirmation beyond normal approval"""


class SecurityRiskAssessor:
    """
    Assess risk levels for security tool executions.

    This helps operators understand the potential impact of operations before approval.
    Critical for preventing accidental damage during security testing.
    """

    # Base risk levels for tools
    TOOL_BASE_RISK: dict[str, RiskLevel] = {
        # Low risk - read-only operations
        "read": RiskLevel.LOW,
        "grep": RiskLevel.LOW,
        "glob": RiskLevel.LOW,
        "fetch": RiskLevel.LOW,
        "search": RiskLevel.LOW,
        "SetTodoList": RiskLevel.LOW,
        # Medium risk - network scanning (can be detected)
        "nmap": RiskLevel.MEDIUM,
        "gobuster": RiskLevel.MEDIUM,
        "nikto": RiskLevel.MEDIUM,
        "hydra": RiskLevel.HIGH,  # Brute force is more aggressive
        # High risk - active exploitation
        "sqlmap": RiskLevel.HIGH,
        "Bash": RiskLevel.HIGH,  # Can execute anything
        "write": RiskLevel.MEDIUM,
        "edit": RiskLevel.MEDIUM,
        # Critical - exploitation frameworks
        "metasploit": RiskLevel.CRITICAL,
        "msfconsole": RiskLevel.CRITICAL,
    }

    # Dangerous command patterns that escalate risk
    DANGEROUS_PATTERNS: list[tuple[str, str, RiskLevel]] = [
        # Destructive file operations
        (r"rm\s+-rf", "Recursive force deletion", RiskLevel.CRITICAL),
        (r"dd\s+.*of=/dev/", "Writing to device files", RiskLevel.CRITICAL),
        (r"mkfs\.", "Filesystem formatting", RiskLevel.CRITICAL),
        (r"fdisk|parted", "Disk partitioning", RiskLevel.CRITICAL),
        # Privilege escalation
        (r"\bsudo\b", "Privilege escalation", RiskLevel.HIGH),
        (r"\bdoas\b", "Privilege escalation", RiskLevel.HIGH),
        (r"chmod\s+[0-7]*7[0-7]*", "Making files world-writable", RiskLevel.HIGH),
        # Metasploit exploitation
        (r"exploit/", "Metasploit exploit module", RiskLevel.CRITICAL),
        (r"msfvenom", "Payload generation", RiskLevel.HIGH),
        (r"use\s+exploit", "Loading exploit module", RiskLevel.CRITICAL),
        # SQLMap aggressive options
        (r"--sql-shell", "SQL shell access", RiskLevel.CRITICAL),
        (r"--os-shell", "Operating system shell", RiskLevel.CRITICAL),
        (r"--os-cmd", "OS command execution", RiskLevel.CRITICAL),
        (r"--file-write", "File writing via SQL", RiskLevel.HIGH),
        (r"DROP\s+DATABASE", "Database destruction", RiskLevel.CRITICAL),
        (r"DROP\s+TABLE", "Table destruction", RiskLevel.HIGH),
        # Network attacks
        (r"--dos", "Denial of service", RiskLevel.CRITICAL),
        (r"-sS.*-T[45]", "Aggressive nmap scan", RiskLevel.MEDIUM),
        (r"hping3", "Packet crafting", RiskLevel.HIGH),
        # System modification
        (r">\s*/etc/", "Modifying system config", RiskLevel.CRITICAL),
        (r">\s*/dev/", "Device file manipulation", RiskLevel.CRITICAL),
        (r"crontab\s+-e", "Cron job modification", RiskLevel.HIGH),
        (r"/etc/passwd|/etc/shadow", "Password file access", RiskLevel.HIGH),
        # Network pivoting
        (r"ssh.*-D\s+\d+", "SSH SOCKS proxy", RiskLevel.MEDIUM),
        (r"proxychains", "Proxy chaining", RiskLevel.MEDIUM),
        # Credential attacks
        (r"--passwords|--wordlist", "Password attack", RiskLevel.HIGH),
        (r"hashcat|john", "Password cracking", RiskLevel.MEDIUM),
    ]

    # Target-specific risks
    SENSITIVE_TARGETS: list[tuple[str, str]] = [
        (r"127\.0\.0\.1|localhost", "Targeting localhost"),
        (r"192\.168\.", "Targeting private network"),
        (r"10\.", "Targeting private network"),
        (r"172\.(1[6-9]|2[0-9]|3[01])\.", "Targeting private network"),
        (r"production|prod", "Targeting production environment"),
    ]

    def assess(self, tool_name: str, params: dict[str, Any]) -> RiskAssessment:
        """
        Calculate risk level for a tool execution.

        Args:
            tool_name: Name of the tool being executed
            params: Parameters being passed to the tool

        Returns:
            RiskAssessment with level, reasons, and detected patterns
        """
        # Start with base risk for the tool
        base_risk = self.TOOL_BASE_RISK.get(tool_name, RiskLevel.MEDIUM)

        # Convert params to searchable text
        param_text = str(params)

        # Detect dangerous patterns
        detected_patterns: list[str] = []
        pattern_reasons: list[str] = []
        max_pattern_risk = RiskLevel.LOW

        for pattern, description, risk_level in self.DANGEROUS_PATTERNS:
            if re.search(pattern, param_text, re.IGNORECASE):
                detected_patterns.append(description)
                pattern_reasons.append(f"Detected: {description}")
                # Track highest risk level from patterns
                if self._compare_risk_levels(risk_level, max_pattern_risk) > 0:
                    max_pattern_risk = risk_level

        # Check for sensitive targets
        for pattern, description in self.SENSITIVE_TARGETS:
            if re.search(pattern, param_text, re.IGNORECASE):
                pattern_reasons.append(description)

        # Determine final risk level (higher of base or pattern-detected)
        final_risk = base_risk
        if self._compare_risk_levels(max_pattern_risk, base_risk) > 0:
            final_risk = max_pattern_risk

        # Build reasons list
        reasons = self._get_base_reasons(tool_name, params)
        reasons.extend(pattern_reasons)

        # Get mitigation suggestions for high/critical risks
        mitigation = None
        requires_extra = False
        if final_risk in (RiskLevel.HIGH, RiskLevel.CRITICAL):
            mitigation = self._get_mitigation_suggestions(tool_name, detected_patterns)
            requires_extra = final_risk == RiskLevel.CRITICAL

        return RiskAssessment(
            level=final_risk,
            reasons=reasons or ["Standard operation"],
            dangerous_patterns=detected_patterns,
            mitigation_suggestions=mitigation,
            requires_extra_confirmation=requires_extra,
        )

    def _compare_risk_levels(self, level1: RiskLevel, level2: RiskLevel) -> int:
        """
        Compare two risk levels.

        Returns:
            -1 if level1 < level2
             0 if level1 == level2
             1 if level1 > level2
        """
        order = [RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH, RiskLevel.CRITICAL]
        return order.index(level1) - order.index(level2)

    def _get_base_reasons(self, tool: str, params: dict[str, Any]) -> list[str]:
        """Get base reasons for a tool's risk level."""
        reasons: list[str] = []

        # Tool-specific reasons
        if tool == "metasploit":
            reasons.append("Metasploit can actively exploit targets")
        elif tool == "msfconsole":
            reasons.append("Metasploit console has full exploitation capabilities")
        elif tool == "sqlmap":
            reasons.append("SQLMap can modify database data")
        elif tool == "Bash":
            reasons.append("Bash commands have full system access")
            if "command" in params:
                reasons.append(f"Command: {params['command'][:100]}")
        elif tool == "hydra":
            reasons.append("Hydra performs brute-force attacks")
        elif tool == "nmap":
            reasons.append("Network scanning may alert intrusion detection")
        elif tool == "nikto":
            reasons.append("Web scanning generates significant traffic")

        return reasons

    def _get_mitigation_suggestions(self, tool: str, dangerous_patterns: list[str]) -> list[str]:
        """Get suggestions for mitigating identified risks."""
        suggestions: list[str] = []

        if "Recursive force deletion" in dangerous_patterns:
            suggestions.append("Review target paths carefully before approving")
            suggestions.append("Consider using -i flag for interactive confirmation")

        if "Privilege escalation" in dangerous_patterns:
            suggestions.append("Ensure you have authorization for privileged operations")

        if "Metasploit exploit module" in dangerous_patterns:
            suggestions.append("Verify target is in scope for testing")
            suggestions.append("Ensure exploit module is appropriate for the target")

        if "SQL shell access" in dangerous_patterns or "OS command execution" in dangerous_patterns:
            suggestions.append("Review scope of engagement before proceeding")
            suggestions.append("Consider less invasive testing methods first")

        if tool in ("metasploit", "msfconsole"):
            suggestions.append("Document all exploitation attempts")
            suggestions.append("Have rollback plan ready")

        if not suggestions:
            suggestions.append("Review command parameters carefully")
            suggestions.append("Ensure target is authorized for testing")

        return suggestions
