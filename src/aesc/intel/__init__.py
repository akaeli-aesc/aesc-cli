"""Intel module for standardized findings and intelligence sharing.

Provides:
- Manifest management for session state
- Standardized schemas for hosts, services, credentials, findings
- Real-time intel sharing between parallel agents
"""

from __future__ import annotations

from .manifest import Manifest, ManifestAgent, ManifestFindingsSummary
from .schemas import (
    Credential,
    Finding,
    FindingSeverity,
    Host,
    IntelType,
    Service,
)

__all__ = [
    # Manifest
    "Manifest",
    "ManifestAgent",
    "ManifestFindingsSummary",
    # Schemas
    "Host",
    "Service",
    "Credential",
    "Finding",
    "FindingSeverity",
    "IntelType",
]
