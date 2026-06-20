"""Risk assessment system for tool execution approval.

This module provides a robust risk-based approval system that:
1. Parses commands structurally (not just regex on raw strings)
2. Detects obfuscation and bypass attempts
3. Extracts targets (IPs, domains, ports) for future scope validation
4. Uses intent-based categorization for pentest context
5. Auto-approves actions based on hierarchical risk levels
"""

from __future__ import annotations

import os
import re
import shlex
from dataclasses import dataclass, field
from enum import Enum
from typing import NamedTuple


class RiskLevel(Enum):
    """Risk levels for tool execution, ordered from lowest to highest."""

    SAFE = ("safe", "green", "✓")  # Read-only, no side effects
    LOW = ("low", "cyan", "ℹ")  # Minor side effects, easily reversible
    MEDIUM = ("medium", "yellow", "⚠")  # Moderate impact, some irreversibility
    HIGH = ("high", "dark_orange", "⚡")  # Significant impact, network operations
    CRITICAL = ("critical", "red", "⛔")  # Destructive, irreversible, dangerous

    def __init__(self, name: str, color: str, icon: str):
        self._name = name
        self.color = color
        self.icon = icon

    @property
    def display_name(self) -> str:
        """Get display name for UI."""
        return self._name.upper()

    def __lt__(self, other: RiskLevel) -> bool:
        """Compare risk levels for ordering."""
        order = [
            RiskLevel.SAFE,
            RiskLevel.LOW,
            RiskLevel.MEDIUM,
            RiskLevel.HIGH,
            RiskLevel.CRITICAL,
        ]
        return order.index(self) < order.index(other)

    def __le__(self, other: RiskLevel) -> bool:
        return self == other or self < other

    def __gt__(self, other: RiskLevel) -> bool:
        return not self <= other

    def __ge__(self, other: RiskLevel) -> bool:
        return self == other or self > other


# =============================================================================
# Parsed Command Structure
# =============================================================================


@dataclass
class ParsedCommand:
    """Structured representation of a shell command."""

    raw: str
    tokens: list[str] = field(default_factory=list)
    base: str | None = None
    args: list[str] = field(default_factory=list)

    # Structural properties
    has_pipe: bool = False
    has_redirect: bool = False
    has_subshell: bool = False
    has_chain: bool = False
    has_backgrounding: bool = False

    # Parse status
    parse_error: bool = False
    obfuscation_flags: list[str] = field(default_factory=list)


@dataclass
class ExtractedTargets:
    """Targets extracted from a command for scope validation."""

    ips: list[str] = field(default_factory=list)
    domains: list[str] = field(default_factory=list)
    ports: list[int] = field(default_factory=list)


class RiskAssessment(NamedTuple):
    """Result of risk assessment."""

    level: RiskLevel
    reason: str  # Why this risk level was assigned
    patterns_matched: list[str]  # Which patterns triggered this assessment
    obfuscation_detected: list[str] = []  # Obfuscation tricks found
    extracted_targets: ExtractedTargets | None = None  # For future scope validation


# =============================================================================
# Obfuscation Detection Patterns
# =============================================================================

OBFUSCATION_PATTERNS: list[tuple[str, str]] = [
    # Base64 encoding
    (r"base64\s+(-d|--decode)", "base64_decode"),
    (r"echo\s+[A-Za-z0-9+/=]{10,}\s*\|\s*base64", "base64_pipe"),
    # Hex encoding
    (r"\\x[0-9a-fA-F]{2}", "hex_escape"),
    (r"\$'\\x[0-9a-fA-F]", "bash_hex_escape"),
    # Variable injection: ${var}m -> rm
    (r"\$\{[^}]*\}[a-z]", "variable_injection"),
    (r"\$[A-Z_]+[a-z]", "variable_concat"),
    # Quote splitting: "r""m" -> rm
    (r'["\'][a-z]["\']["\'][a-z]', "quote_splitting"),
    (r"'[a-z]''[a-z]'", "single_quote_split"),
    # eval/exec usage
    (r"\beval\s+", "eval_usage"),
    (r"\bexec\s+", "exec_usage"),
    # Path obfuscation (exclude URLs like http://)
    (r"/\./", "dot_path"),
    (r"(?<!:)//+", "double_slash"),  # Negative lookbehind to exclude ://
    (r"/bin/\.\./bin/", "path_traversal"),
    # Unicode/escape tricks
    (r"\\u[0-9a-fA-F]{4}", "unicode_escape"),
    (r"\$\(\s*printf", "printf_construct"),
]


# =============================================================================
# Intent-Based Command Categories (Pentest Context)
# =============================================================================

# Self-destructive: damages operator's machine - ALWAYS CRITICAL
SELF_DESTRUCTIVE_COMMANDS = {
    "patterns": [
        (r"\brm\s+(-[rf]+\s+)*(/|~|\$HOME)", "rm on home/root"),
        (r"\brm\s+.*--no-preserve-root", "rm no-preserve-root"),
        (r"\bdd\s+.*of=/dev/[sh]d[a-z]", "dd to disk"),
        (r"\bmkfs\.", "filesystem format"),
        (r"\bfdisk\s+/dev/", "disk partition"),
        (r":\s*\(\s*\)\s*\{.*:\s*\|.*&\s*\}", "fork bomb"),
        (r">\s*/dev/sd[a-z]", "write to disk device"),
        (r"\bchmod\s+(-R\s+)?777\s+/", "chmod 777 root"),
        (r"\bchown\s+-R\s+.*\s+/\s*$", "chown root"),
    ],
}

# Infrastructure affecting: affects operator's system - HIGH to CRITICAL
INFRASTRUCTURE_COMMANDS = {
    "systemctl": {"stop", "disable", "mask", "kill"},
    "service": {"stop", "restart"},
    "iptables": {"-F", "--flush", "-X", "-P DROP"},
    "ufw": {"disable", "reset"},
    "docker": {"rm", "rmi", "system prune", "stop"},
    "kubectl": {"delete"},
    "kill": {"-9", "-KILL"},
}

# Remote access / lateral movement - HIGH risk
REMOTE_ACCESS_COMMANDS = {"ssh", "scp", "sftp", "rsync"}

# Exploitation tools - expected in pentest, HIGH risk
EXPLOITATION_COMMANDS = {
    "msfconsole",
    "msfvenom",
    "metasploit",
    "hydra",
    "medusa",
    "ncrack",
    "hashcat",
    "john",
    "responder",
    "impacket-secretsdump",
    "crackmapexec",
    "mimikatz",
    "lazagne",
    "empire",
    "covenant",
    "sliver",
    "burpsuite",
    "sqlmap",
}

# Enumeration tools - expected in pentest, MEDIUM risk
ENUMERATION_COMMANDS = {
    "gobuster",
    "dirb",
    "dirbuster",
    "feroxbuster",
    "ffuf",
    "nikto",
    "wpscan",
    "droopescan",
    "enum4linux",
    "smbclient",
    "rpcclient",
    "ldapsearch",
    "snmpwalk",
    "onesixtyone",
}

# Recon tools - expected in pentest, LOW to MEDIUM risk
RECON_COMMANDS = {
    "nmap",
    "masscan",
    "rustscan",
    "dig",
    "nslookup",
    "host",
    "whois",
    "dnsrecon",
    "ping",
    "traceroute",
    "mtr",
    "whatweb",
    "wafw00f",
    "theHarvester",
    "recon-ng",
    "amass",
    "subfinder",
}

# Read-only commands - SAFE
READONLY_COMMANDS = {
    "ls",
    "pwd",
    "whoami",
    "date",
    "uptime",
    "uname",
    "df",
    "free",
    "ps",
    "top",
    "htop",
    "cat",
    "head",
    "tail",
    "less",
    "more",
    "grep",
    "find",
    "locate",
    "which",
    "whereis",
    "file",
    "stat",
    "wc",
    "sort",
    "uniq",
    "env",
    "printenv",
    "id",
    "groups",
}


# =============================================================================
# Risk Assessor
# =============================================================================


class RiskAssessor:
    """Robust risk assessment engine with parsing and obfuscation detection.

    Improvements over simple regex:
    1. Parses commands structurally using shlex
    2. Detects obfuscation/bypass attempts
    3. Extracts targets for future scope validation
    4. Intent-based categorization for pentest context
    """

    def _parse_command(self, cmd: str) -> ParsedCommand:
        """Parse command into structured form with obfuscation detection."""
        result = ParsedCommand(raw=cmd)

        # Detect obfuscation before parsing
        for pattern, flag in OBFUSCATION_PATTERNS:
            if re.search(pattern, cmd):
                result.obfuscation_flags.append(flag)

        # Structural analysis on raw string
        # Handle pipe carefully - don't match || as pipe
        pipe_check = re.sub(r"\|\|", "", cmd)
        result.has_pipe = "|" in pipe_check
        result.has_redirect = bool(re.search(r"[^<]>[^>]|>>|<[^<]|[12]>", cmd))
        result.has_subshell = bool(re.search(r"\$\(|`|\(\s*[a-z]", cmd))
        result.has_chain = bool(re.search(r"&&|\|\||;\s*[a-z]", cmd))
        result.has_backgrounding = cmd.rstrip().endswith("&") and not cmd.rstrip().endswith("&&")

        # Token parsing
        try:
            # Expand environment variables to catch $HOME tricks
            expanded = os.path.expandvars(cmd)
            tokens = shlex.split(expanded)

            if tokens:
                result.tokens = tokens
                # Get base command, handle path prefixes
                base = tokens[0]
                if "/" in base:
                    base = base.rsplit("/", 1)[-1]
                result.base = base
                result.args = tokens[1:]
        except ValueError:
            # Malformed quoting - suspicious
            result.parse_error = True

        return result

    def _extract_targets(self, cmd: str) -> ExtractedTargets:
        """Extract potential targets from command string."""
        targets = ExtractedTargets()

        # IP addresses (including CIDR)
        ip_pattern = r"\b(?:\d{1,3}\.){3}\d{1,3}(?:/\d{1,2})?\b"
        targets.ips = list(set(re.findall(ip_pattern, cmd)))

        # Domains / hosts
        #
        # Use a token-based approach to avoid common false positives like local
        # filenames in wordlists or URL paths (e.g., "paths.txt", "app.js").
        domain_pattern = r"^(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}$"
        false_positives = {"example.com", "test.local", "localhost.localdomain"}
        file_like_tlds = {
            "txt",
            "log",
            "json",
            "yaml",
            "yml",
            "md",
            "csv",
            "tsv",
            "xml",
            "html",
            "css",
            "js",
            "toml",
            "ini",
            "conf",
            "cfg",
            "lock",
            "py",
        }

        try:
            tokens = shlex.split(cmd)
        except ValueError:
            tokens = cmd.split()

        domains: set[str] = set()
        extra_ports: set[int] = set()

        for token in tokens:
            t = token.strip().strip(",;")
            if not t:
                continue

            # URLs: extract hostname and port (ignore path segments).
            if "://" in t:
                try:
                    from urllib.parse import urlsplit

                    parsed = urlsplit(t)
                    if parsed.hostname:
                        domains.add(parsed.hostname.lower())
                    if parsed.port and 1 <= int(parsed.port) <= 65535:
                        extra_ports.add(int(parsed.port))
                except Exception:
                    pass
                continue

            # SSH-style user@host
            hostpart = t.rsplit("@", 1)[-1]

            # Avoid treating local filesystem paths as domains
            if hostpart.startswith(("/", "./", "../", "~")):
                continue

            # If host/path without scheme, split first slash
            if "/" in hostpart:
                prefix = hostpart.split("/", 1)[0]
            else:
                prefix = hostpart

            # Strip common wrappers
            prefix = prefix.strip().strip("[](){}<>\"'")
            if not prefix:
                continue

            # host:port
            port: int | None = None
            if ":" in prefix:
                maybe_host, maybe_port = prefix.rsplit(":", 1)
                if maybe_port.isdigit():
                    port_int = int(maybe_port)
                    if 1 <= port_int <= 65535:
                        port = port_int
                        prefix = maybe_host
            if port is not None:
                extra_ports.add(port)

            candidate = prefix.strip().strip(".")
            if not candidate:
                continue

            # Domain candidate
            if re.fullmatch(domain_pattern, candidate):
                candidate_lower = candidate.lower()
                if candidate_lower in false_positives:
                    continue
                tld = candidate_lower.rsplit(".", 1)[-1]
                if tld in file_like_tlds:
                    continue
                domains.add(candidate_lower)

        targets.domains = sorted(domains)

        # Ports from common flag patterns
        port_patterns = [
            r"-p\s*(\d+(?:[-,]\d+)*)",  # nmap style
            r"--port[s]?\s*[=\s]?(\d+(?:[-,]\d+)*)",
            r":(\d+)(?:\s|$|/)",  # URL style host:port
        ]
        for pattern in port_patterns:
            matches = re.findall(pattern, cmd)
            for match in matches:
                for part in match.replace("-", ",").split(","):
                    if part.isdigit():
                        port = int(part)
                        if 1 <= port <= 65535:
                            targets.ports.append(port)
        targets.ports.extend(extra_ports)
        targets.ports = list(set(targets.ports))

        return targets

    def _check_self_destructive(self, cmd: str) -> tuple[bool, str]:
        """Check for self-destructive patterns."""
        for pattern, reason in SELF_DESTRUCTIVE_COMMANDS["patterns"]:
            if re.search(pattern, cmd, re.IGNORECASE):
                return True, reason
        return False, ""

    def _check_infrastructure(self, parsed: ParsedCommand) -> tuple[bool, str]:
        """Check for infrastructure-affecting commands."""
        if not parsed.base:
            return False, ""

        base = parsed.base.lower()
        if base in INFRASTRUCTURE_COMMANDS:
            dangerous_args = INFRASTRUCTURE_COMMANDS[base]
            args_str = " ".join(parsed.args)
            for arg in dangerous_args:
                if arg in args_str:
                    return True, f"{base} {arg}"
        return False, ""

    def _get_command_category(self, base: str) -> tuple[str, RiskLevel]:
        """Categorize command by intent and return base risk level."""
        base_lower = base.lower()

        if base_lower in READONLY_COMMANDS:
            return "readonly", RiskLevel.SAFE

        if base_lower in RECON_COMMANDS:
            return "recon", RiskLevel.LOW

        if base_lower in ENUMERATION_COMMANDS:
            return "enumeration", RiskLevel.MEDIUM

        if base_lower in REMOTE_ACCESS_COMMANDS:
            return "remote_access", RiskLevel.HIGH

        if base_lower in EXPLOITATION_COMMANDS:
            return "exploitation", RiskLevel.HIGH

        # Check with wildcards for impacket-* style tools
        for exploit_cmd in EXPLOITATION_COMMANDS:
            if exploit_cmd.endswith("*") and base_lower.startswith(exploit_cmd[:-1]):
                return "exploitation", RiskLevel.HIGH

        return "unknown", RiskLevel.LOW

    def assess_bash_command(self, command: str) -> RiskAssessment:
        """Assess risk level of a bash command.

        Uses structural parsing, obfuscation detection, and intent-based categorization.
        """
        parsed = self._parse_command(command)
        targets = self._extract_targets(command)
        patterns_matched: list[str] = []
        score = 0

        # =================================
        # Parse error is suspicious
        # =================================
        if parsed.parse_error:
            patterns_matched.append("Malformed syntax (parse error)")
            score += 2

        # =================================
        # Obfuscation detection - bump risk
        # =================================
        if parsed.obfuscation_flags:
            for flag in parsed.obfuscation_flags:
                patterns_matched.append(f"Obfuscation: {flag}")
            score += len(parsed.obfuscation_flags) * 2

        # =================================
        # Self-destructive patterns - CRITICAL
        # =================================
        is_destructive, destruct_reason = self._check_self_destructive(command)
        if is_destructive:
            patterns_matched.append(f"Self-destructive: {destruct_reason}")
            return RiskAssessment(
                level=RiskLevel.CRITICAL,
                reason=f"Self-destructive operation: {destruct_reason}",
                patterns_matched=patterns_matched,
                obfuscation_detected=parsed.obfuscation_flags,
                extracted_targets=targets,
            )

        # =================================
        # Infrastructure affecting
        # =================================
        is_infra, infra_reason = self._check_infrastructure(parsed)
        if is_infra:
            patterns_matched.append(f"Infrastructure: {infra_reason}")
            score += 4

        # =================================
        # Command categorization
        # =================================
        if parsed.base:
            category, base_level = self._get_command_category(parsed.base)
            patterns_matched.append(f"Category: {category}")
            # Map risk levels to score increments
            level_scores = {
                RiskLevel.SAFE: 0,
                RiskLevel.LOW: 1,
                RiskLevel.MEDIUM: 3,
                RiskLevel.HIGH: 5,
                RiskLevel.CRITICAL: 8,
            }
            score += level_scores[base_level]

        # =================================
        # Compound risk factors
        # =================================

        # Piping network command to shell
        if parsed.has_pipe and parsed.base in {"curl", "wget", "nc", "netcat"}:
            if re.search(r"\|\s*(ba)?sh|\|\s*python|\|\s*perl", command):
                patterns_matched.append("Pipe to shell from network")
                score += 4

        # Reverse shell patterns - always HIGH risk
        reverse_shell_patterns = [
            (r"bash\s+-i\s+.*>&\s*/dev/tcp", "bash reverse shell"),
            (r"nc\s+.*-e\s+(/bin/)?(ba)?sh", "netcat reverse shell"),
            (r"python.*socket.*connect.*exec", "python reverse shell"),
            (r"php\s+-r.*fsockopen", "php reverse shell"),
        ]
        for pattern, name in reverse_shell_patterns:
            if re.search(pattern, command, re.IGNORECASE):
                patterns_matched.append(f"Reverse shell: {name}")
                score += 5  # Reverse shells are HIGH risk
                break

        # Backgrounded tasks
        if parsed.has_backgrounding:
            patterns_matched.append("Backgrounded execution")
            score += 1

        # Chained commands increase complexity/risk
        if parsed.has_chain:
            patterns_matched.append("Chained commands")
            score += 1

        # Subshell execution
        if parsed.has_subshell:
            patterns_matched.append("Subshell execution")
            score += 1

        # =================================
        # Calculate final level
        # =================================
        if score <= 0:
            level = RiskLevel.SAFE
        elif score <= 2:
            level = RiskLevel.LOW
        elif score <= 4:
            level = RiskLevel.MEDIUM
        elif score <= 7:
            level = RiskLevel.HIGH
        else:
            level = RiskLevel.CRITICAL

        # Build reason message
        if patterns_matched:
            reason = patterns_matched[0]
        else:
            reason = "Unknown command"

        return RiskAssessment(
            level=level,
            reason=reason,
            patterns_matched=patterns_matched,
            obfuscation_detected=parsed.obfuscation_flags,
            extracted_targets=targets,
        )

    def assess_tool_call(self, tool_name: str, arguments: str | None) -> RiskAssessment:
        """Assess risk level of a tool call."""
        tool_lower = tool_name.lower()
        arg_str = arguments or ""

        # Bash tool - delegate to command assessment
        if tool_lower == "bash":
            command = self._extract_bash_command(arg_str)
            return self.assess_bash_command(command)

        # SSH tools - HIGH risk (lateral movement)
        if tool_lower.startswith("ssh"):
            targets = self._extract_targets(arg_str)
            return RiskAssessment(
                level=RiskLevel.HIGH,
                reason="SSH operation (lateral movement)",
                patterns_matched=["SSH tool"],
                extracted_targets=targets,
            )

        # Credential tools - HIGH risk
        if tool_lower.startswith("cred"):
            return RiskAssessment(
                level=RiskLevel.HIGH,
                reason="Credential operation",
                patterns_matched=["Credential tool"],
            )

        # File tools
        if tool_lower in ("readfile", "read"):
            return RiskAssessment(
                level=RiskLevel.SAFE,
                reason="Read-only file operation",
                patterns_matched=["File read"],
            )

        if tool_lower in ("writefile", "write"):
            # Check if writing to sensitive paths
            if any(path in arg_str for path in ["/etc/", "/bin/", "/usr/", "/sys/"]):
                return RiskAssessment(
                    level=RiskLevel.CRITICAL,
                    reason="Writing to system directory",
                    patterns_matched=["System path write"],
                )
            return RiskAssessment(
                level=RiskLevel.MEDIUM,
                reason="File write operation",
                patterns_matched=["File write"],
            )

        if tool_lower in ("strreplacefile", "edit"):
            return RiskAssessment(
                level=RiskLevel.MEDIUM,
                reason="File edit operation",
                patterns_matched=["File edit"],
            )

        # Search tools
        if tool_lower in ("grep", "glob", "find"):
            return RiskAssessment(
                level=RiskLevel.SAFE,
                reason="File search operation",
                patterns_matched=["Search operation"],
            )

        # Web tools
        if tool_lower in ("fetchurl", "webfetch", "searchweb", "websearch"):
            targets = self._extract_targets(arg_str)
            return RiskAssessment(
                level=RiskLevel.LOW,
                reason="Web request operation",
                patterns_matched=["Web operation"],
                extracted_targets=targets,
            )

        # MITRE ATT&CK tool
        if tool_lower == "mitreattack":
            return RiskAssessment(
                level=RiskLevel.SAFE,
                reason="MITRE ATT&CK lookup",
                patterns_matched=["Reference lookup"],
            )

        # Kali docs tool
        if tool_lower == "kalidocs":
            return RiskAssessment(
                level=RiskLevel.SAFE,
                reason="Documentation lookup",
                patterns_matched=["Reference lookup"],
            )

        # Task/Think tools
        if tool_lower in ("task", "think", "settodolist"):
            return RiskAssessment(
                level=RiskLevel.SAFE,
                reason="Agent internal operation",
                patterns_matched=["Internal tool"],
            )

        # Default: MEDIUM for unknown tools
        return RiskAssessment(
            level=RiskLevel.MEDIUM,
            reason=f"Unknown tool: {tool_name}",
            patterns_matched=["Unknown tool"],
        )

    def _extract_bash_command(self, arguments: str) -> str:
        """Extract bash command from tool arguments."""
        # Try to extract from JSON-like format: {"command": "..."}
        match = re.search(r'"command"\s*:\s*"([^"]+)"', arguments)
        if match:
            return match.group(1)

        # Try single quotes
        match = re.search(r"'command'\s*:\s*'([^']+)'", arguments)
        if match:
            return match.group(1)

        # Common human-readable format: Run command `...`. Match greedily to the
        # final backtick so an inner command substitution (e.g. `id`) does not
        # truncate the extracted command and under-rate its risk.
        match = re.search(r"`(.+)`", arguments, re.DOTALL)
        if match:
            return match.group(1)

        # Fallback: use entire argument string
        return arguments.strip()
