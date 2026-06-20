"""Visual enhancements for security operations."""

from __future__ import annotations

import re
from enum import Enum
from typing import NamedTuple


class SecurityPhase(str, Enum):
    """Security testing phases."""

    RECON = "reconnaissance"
    ENUM = "enumeration"
    VULN = "vulnerability"
    EXPLOIT = "exploitation"
    POST = "post-exploitation"
    REPORT = "reporting"
    UNKNOWN = "unknown"


class SeverityLevel(NamedTuple):
    """Severity level with display info."""

    name: str
    color: str
    icon: str


# Security tool icons - only core Kali tools
SECURITY_TOOL_ICONS: dict[str, str] = {
    # Core security tools (most commonly used in Kali)
    "nmap": "🔍",  # Network scanning
    "gobuster": "📂",  # Directory enumeration
    "nikto": "🕷️",  # Web vulnerability scanner
    "sqlmap": "💉",  # SQL injection testing
    "metasploit": "🎯",  # Exploitation framework
    "msfconsole": "🎯",  # Metasploit console
    "hydra": "🐉",  # Password brute force
    # Default
    "bash": "💻",
    "default": "🔧",
}

# Severity levels with colors and icons
SEVERITY_LEVELS: dict[str, SeverityLevel] = {
    "critical": SeverityLevel("CRITICAL", "bright_red", "🔴"),
    "high": SeverityLevel("HIGH", "red", "🟠"),
    "medium": SeverityLevel("MEDIUM", "yellow", "🟡"),
    "low": SeverityLevel("LOW", "blue", "🔵"),
    "info": SeverityLevel("INFO", "grey50", "⚪"),
    "success": SeverityLevel("SUCCESS", "green", "🟢"),
}

# Quick access to severity colors
SEVERITY_COLORS: dict[str, str] = {level: info.color for level, info in SEVERITY_LEVELS.items()}

# Patterns for security-relevant content
PATTERNS = {
    # Network identifiers
    "ipv4": re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
    "ipv6": re.compile(r"\b(?:[0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}\b"),
    "port": re.compile(r"\b(\d+)/(tcp|udp)\b", re.IGNORECASE),
    "mac": re.compile(r"\b(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}\b"),
    # URLs and domains
    "url": re.compile(r"https?://[^\s]+"),
    "domain": re.compile(
        r"\b(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,}\b", re.IGNORECASE
    ),
    # Security keywords
    "critical": re.compile(r"\b(critical|cve-\d{4}-\d{4,7})\b", re.IGNORECASE),
    "high": re.compile(r"\b(high|severe|dangerous)\b", re.IGNORECASE),
    "medium": re.compile(r"\b(medium|moderate|warning)\b", re.IGNORECASE),
    "low": re.compile(r"\b(low|minor|notice)\b", re.IGNORECASE),
    "vuln": re.compile(
        r"\b(vulnerability|vulnerable|exploit|backdoor|injection|xss|csrf)\b", re.IGNORECASE
    ),
    "success": re.compile(
        r"\b(success|successful|open|accessible|found|exploited)\b", re.IGNORECASE
    ),
    "fail": re.compile(r"\b(failed|failure|closed|filtered|denied|error)\b", re.IGNORECASE),
    # Common security indicators
    "cve": re.compile(r"\bCVE-\d{4}-\d{4,7}\b", re.IGNORECASE),
    "cvss": re.compile(r"\bCVSS[:\s]*(\d+\.?\d*)\b", re.IGNORECASE),
}

# Phase detection patterns - simplified for core tools only
PHASE_PATTERNS: dict[SecurityPhase, list[re.Pattern[str]]] = {
    SecurityPhase.RECON: [
        re.compile(r"\b(nmap|scan|discover)\b", re.IGNORECASE),
    ],
    SecurityPhase.ENUM: [
        re.compile(r"\b(gobuster|enum|enumerate)\b", re.IGNORECASE),
    ],
    SecurityPhase.VULN: [
        re.compile(r"\b(nikto|vulnerability|vuln)\b", re.IGNORECASE),
    ],
    SecurityPhase.EXPLOIT: [
        re.compile(r"\b(metasploit|msfconsole|sqlmap|exploit)\b", re.IGNORECASE),
    ],
    SecurityPhase.POST: [
        re.compile(r"\b(hydra|brute|password|crack)\b", re.IGNORECASE),
    ],
}


def get_tool_icon(tool_name: str, command: str = "") -> str:
    """
    Get icon for a security tool.

    Args:
        tool_name: Name of the tool (e.g., "Bash", "nmap")
        command: The actual command being executed (for Bash tool detection)

    Returns:
        Icon string (emoji) for the tool
    """
    tool_lower = tool_name.lower()

    # For Bash tool, detect security tool from command first
    if tool_lower == "bash" and command:
        # Extract first word (the actual command)
        first_word = command.strip().split()[0] if command.strip() else ""
        # Remove sudo/doas prefix if present
        if first_word in ("sudo", "doas"):
            parts = command.strip().split()
            first_word = parts[1] if len(parts) > 1 else ""

        # Check if it's a known security tool
        for tool, icon in SECURITY_TOOL_ICONS.items():
            if tool in first_word.lower():
                return icon

    # Direct tool name match
    if tool_lower in SECURITY_TOOL_ICONS:
        return SECURITY_TOOL_ICONS[tool_lower]

    # Default icon
    return SECURITY_TOOL_ICONS["default"]


def get_severity_badge(severity: str) -> str:
    """
    Get colored severity badge.

    Args:
        severity: Severity level (critical, high, medium, low, info)

    Returns:
        Formatted severity badge with color markup
    """
    severity_lower = severity.lower()
    if severity_lower not in SEVERITY_LEVELS:
        severity_lower = "info"

    level = SEVERITY_LEVELS[severity_lower]
    return f"{level.icon} [{level.color}]{level.name}[/{level.color}]"


def detect_security_phase(command: str) -> SecurityPhase:
    """
    Detect security testing phase from command.

    Args:
        command: The command being executed

    Returns:
        Detected security phase
    """
    for phase, patterns in PHASE_PATTERNS.items():
        for pattern in patterns:
            if pattern.search(command):
                return phase

    return SecurityPhase.UNKNOWN


def colorize_security_text(text: str) -> str:
    """
    Add color markup to security-relevant text.

    Detects and colorizes:
    - IP addresses (cyan)
    - Ports (yellow)
    - URLs (blue)
    - CVEs (red)
    - Severity keywords (severity-based colors)
    - Success/failure indicators (green/red)

    Args:
        text: Plain text to colorize

    Returns:
        Text with Rich markup for coloring
    """
    result = text

    # CVE identifiers (highest priority - do first)
    result = PATTERNS["cve"].sub(r"[red]\g<0>[/red]", result)

    # IP addresses
    result = PATTERNS["ipv4"].sub(r"[cyan]\g<0>[/cyan]", result)
    result = PATTERNS["ipv6"].sub(r"[cyan]\g<0>[/cyan]", result)

    # Ports (e.g., "80/tcp")
    result = PATTERNS["port"].sub(r"[yellow]\g<0>[/yellow]", result)

    # URLs
    result = PATTERNS["url"].sub(r"[blue]\g<0>[/blue]", result)

    # Severity keywords
    result = PATTERNS["critical"].sub(r"[bright_red]\g<0>[/bright_red]", result)
    result = PATTERNS["high"].sub(r"[red]\g<0>[/red]", result)
    result = PATTERNS["medium"].sub(r"[yellow]\g<0>[/yellow]", result)
    result = PATTERNS["low"].sub(r"[blue]\g<0>[/blue]", result)

    # Success/failure indicators
    result = PATTERNS["success"].sub(r"[green]\g<0>[/green]", result)
    result = PATTERNS["fail"].sub(r"[red]\g<0>[/red]", result)

    # Vulnerability keywords
    result = PATTERNS["vuln"].sub(r"[yellow]\g<0>[/yellow]", result)

    return result


def format_security_command(tool_name: str, command: str, max_length: int = 60) -> str:
    """
    Format a security command for display with icon and colorization.

    Args:
        tool_name: Name of the tool
        command: The command being executed
        max_length: Maximum length before truncation

    Returns:
        Formatted command string with Rich markup
    """
    icon = get_tool_icon(tool_name, command)

    # Truncate if too long
    display_cmd = command
    if len(command) > max_length:
        display_cmd = command[: max_length - 3] + "..."

    # Colorize the command
    colored_cmd = colorize_security_text(display_cmd)

    return f"{icon} {colored_cmd}"
