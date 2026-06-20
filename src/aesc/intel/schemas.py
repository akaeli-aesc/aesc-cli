"""Standardized intel schemas for agent communication.

Enterprise-grade formats for sharing discovered intelligence
between parallel agents via the shared results folder.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class IntelType(str, Enum):
    """Types of intelligence that can be shared."""

    HOST = "host"
    SERVICE = "service"
    CREDENTIAL = "credential"
    FINDING = "finding"
    ARTIFACT = "artifact"


class FindingSeverity(str, Enum):
    """Finding severity levels (aligned with CVSS)."""

    CRITICAL = "critical"  # CVSS 9.0-10.0
    HIGH = "high"  # CVSS 7.0-8.9
    MEDIUM = "medium"  # CVSS 4.0-6.9
    LOW = "low"  # CVSS 0.1-3.9
    INFO = "info"  # Informational


# ─────────────────────────────────────────────────────────────────────────────
# Core Intel Schemas
# ─────────────────────────────────────────────────────────────────────────────


class Host(BaseModel):
    """Discovered host information."""

    ip: str = Field(description="IP address")
    hostname: str | None = Field(default=None, description="Hostname if resolved")
    mac: str | None = Field(default=None, description="MAC address if on same network")
    os: str | None = Field(default=None, description="Operating system")
    os_version: str | None = Field(default=None, description="OS version")

    # Discovery metadata
    discovered_by: str = Field(description="Agent that discovered this host")
    discovered_at: datetime = Field(default_factory=datetime.utcnow)
    discovery_method: str | None = Field(
        default=None, description="How it was discovered (nmap, arp, etc.)"
    )

    # Status
    is_alive: bool = Field(default=True, description="Host responds to probes")
    last_seen: datetime = Field(default_factory=datetime.utcnow)

    # Tags for categorization
    tags: list[str] = Field(default_factory=list)

    # References
    ports: list[int] = Field(default_factory=list, description="Open ports discovered")
    services: list[str] = Field(default_factory=list, description="Service IDs on this host")

    def to_file_dict(self) -> dict[str, Any]:
        """Convert to dict for file storage."""
        data = self.model_dump()
        data["discovered_at"] = self.discovered_at.isoformat()
        data["last_seen"] = self.last_seen.isoformat()
        return data


class Service(BaseModel):
    """Discovered service information."""

    id: str = Field(description="Unique service ID: {host}:{port}/{protocol}")
    host: str = Field(description="Host IP")
    port: int = Field(description="Port number")
    protocol: str = Field(default="tcp", description="Protocol (tcp/udp)")

    # Service identification
    service: str | None = Field(default=None, description="Service name (http, ssh, etc.)")
    product: str | None = Field(default=None, description="Product name")
    version: str | None = Field(default=None, description="Version string")
    extra_info: str | None = Field(default=None, description="Additional info from banner")

    # State
    state: str = Field(default="open", description="Port state (open/filtered/closed)")

    # Discovery metadata
    discovered_by: str = Field(description="Agent that discovered this service")
    discovered_at: datetime = Field(default_factory=datetime.utcnow)

    # Security info
    vulnerabilities: list[str] = Field(default_factory=list, description="CVE IDs")
    ssl_info: dict[str, Any] | None = Field(default=None, description="SSL/TLS certificate info")

    # Tags
    tags: list[str] = Field(default_factory=list)

    @classmethod
    def make_id(cls, host: str, port: int, protocol: str = "tcp") -> str:
        """Generate service ID."""
        return f"{host}:{port}/{protocol}"

    def to_file_dict(self) -> dict[str, Any]:
        """Convert to dict for file storage."""
        data = self.model_dump()
        data["discovered_at"] = self.discovered_at.isoformat()
        return data


class CredentialType(str, Enum):
    """Types of credentials."""

    PASSWORD = "password"
    HASH = "hash"
    KEY = "key"
    TOKEN = "token"
    CERTIFICATE = "certificate"


class Credential(BaseModel):
    """Discovered or obtained credential."""

    id: str = Field(description="Unique credential ID")
    type: CredentialType = Field(description="Credential type")

    # Identity
    username: str | None = Field(default=None)
    domain: str | None = Field(default=None)
    email: str | None = Field(default=None)

    # Secret (should be handled carefully)
    secret: str = Field(description="The credential value")
    secret_format: str | None = Field(
        default=None, description="Format (plaintext, ntlm, sha256, etc.)"
    )

    # Scope
    target: str | None = Field(default=None, description="Target system/service")
    scope: str | None = Field(default=None, description="What this grants access to")

    # Validation
    valid: bool | None = Field(default=None, description="Whether credential was verified")
    validated_at: datetime | None = Field(default=None)
    validated_by: str | None = Field(default=None)

    # Discovery
    source: str = Field(description="Where credential was found")
    discovered_by: str = Field(description="Agent that found this")
    discovered_at: datetime = Field(default_factory=datetime.utcnow)

    # Risk
    privileged: bool = Field(default=False, description="High-privilege account")

    def to_file_dict(self) -> dict[str, Any]:
        """Convert to dict for file storage."""
        data = self.model_dump()
        data["type"] = self.type.value
        data["discovered_at"] = self.discovered_at.isoformat()
        if self.validated_at:
            data["validated_at"] = self.validated_at.isoformat()
        return data


class Finding(BaseModel):
    """Security finding or vulnerability."""

    id: str = Field(description="Unique finding ID")
    type: str = Field(description="Finding type (vulnerability, misconfiguration, exposure, etc.)")
    title: str = Field(description="Short descriptive title")
    description: str = Field(description="Detailed description")

    # Severity
    severity: FindingSeverity = Field(description="Severity level")
    cvss_score: float | None = Field(default=None, ge=0, le=10)
    cvss_vector: str | None = Field(default=None)

    # Target
    target: str = Field(description="Affected target (IP, URL, etc.)")
    service: str | None = Field(default=None, description="Affected service ID")

    # Evidence
    evidence: str | None = Field(default=None, description="Proof of finding")
    screenshots: list[str] = Field(default_factory=list, description="Screenshot paths")
    artifacts: list[str] = Field(default_factory=list, description="Related artifact paths")

    # Classification
    cve_ids: list[str] = Field(default_factory=list, description="CVE identifiers")
    cwe_ids: list[str] = Field(default_factory=list, description="CWE identifiers")
    mitre_techniques: list[str] = Field(
        default_factory=list, description="MITRE ATT&CK technique IDs"
    )

    # Exploitation
    exploitable: bool = Field(default=False)
    exploited: bool = Field(default=False)
    exploit_info: str | None = Field(default=None)

    # Recommendations
    remediation: str | None = Field(default=None)
    next_steps: list[str] = Field(default_factory=list)

    # Discovery
    discovered_by: str = Field(description="Agent that found this")
    discovered_at: datetime = Field(default_factory=datetime.utcnow)
    tool_used: str | None = Field(default=None, description="Tool that identified this")

    # Status
    status: str = Field(
        default="new", description="Finding status (new/confirmed/false_positive/remediated)"
    )

    def to_file_dict(self) -> dict[str, Any]:
        """Convert to dict for file storage."""
        data = self.model_dump()
        data["severity"] = self.severity.value
        data["discovered_at"] = self.discovered_at.isoformat()
        return data


# ─────────────────────────────────────────────────────────────────────────────
# Index Schema (for quick lookups)
# ─────────────────────────────────────────────────────────────────────────────


class IntelIndex(BaseModel):
    """Index file for quick intel lookups."""

    last_updated: datetime = Field(default_factory=datetime.utcnow)

    # Counts
    hosts_count: int = 0
    services_count: int = 0
    credentials_count: int = 0
    findings_count: int = 0

    # Severity breakdown
    findings_by_severity: dict[str, int] = Field(
        default_factory=lambda: {
            "critical": 0,
            "high": 0,
            "medium": 0,
            "low": 0,
            "info": 0,
        }
    )

    # Quick access lists
    hosts: list[str] = Field(default_factory=list, description="All host IPs")
    targets: list[str] = Field(default_factory=list, description="All targets")

    def to_file_dict(self) -> dict[str, Any]:
        """Convert to dict for file storage."""
        data = self.model_dump()
        data["last_updated"] = self.last_updated.isoformat()
        return data
