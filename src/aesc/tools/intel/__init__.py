"""Intel tools for sharing discoveries between parallel agents.

These tools enable coordination through the shared results folder:
- WriteHost: Record discovered hosts
- WriteService: Record discovered services
- WriteCredential: Record found credentials
- ReadIntel: Read all intelligence from other agents
- QueryIntel: Query specific intel with filters
"""

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, override

from pydantic import BaseModel, Field

from aesc.intel.schemas import (
    Credential,
    Finding,
    FindingSeverity,
    Host,
    IntelIndex,
    Service,
)
from aesc.provider import CallableTool2, ToolError, ToolOk, ToolReturnType
from aesc.session import Session


def _get_intel_dir(session: Session) -> Path:
    """Get the intel directory for the session."""
    intel_dir = session.results_dir / "intel"
    intel_dir.mkdir(parents=True, exist_ok=True)
    return intel_dir


def _update_index(intel_dir: Path, intel_type: str, item_id: str) -> None:
    """Update the intel index with a new item."""
    index_file = intel_dir / "index.json"

    if index_file.exists():
        try:
            index_data = json.loads(index_file.read_text())
        except (json.JSONDecodeError, OSError):
            index_data = {}
    else:
        index_data = {}

    # Update counts
    count_key = f"{intel_type}_count"
    index_data[count_key] = index_data.get(count_key, 0) + 1

    # Add to ID list
    list_key = f"{intel_type}_ids"
    if list_key not in index_data:
        index_data[list_key] = []
    if item_id not in index_data[list_key]:
        index_data[list_key].append(item_id)

    index_data["last_updated"] = datetime.utcnow().isoformat()

    # Write atomically
    tmp_file = index_file.with_suffix(".tmp")
    tmp_file.write_text(json.dumps(index_data, indent=2))
    tmp_file.rename(index_file)


# ─────────────────────────────────────────────────────────────────────────────
# WriteHost Tool
# ─────────────────────────────────────────────────────────────────────────────


class WriteHostParams(BaseModel):
    ip: str = Field(description="IP address of the host")
    hostname: str | None = Field(default=None, description="Hostname if known")
    os: str | None = Field(default=None, description="Operating system")
    os_version: str | None = Field(default=None, description="OS version")
    ports: list[int] = Field(default_factory=list, description="Open ports discovered")
    tags: list[str] = Field(default_factory=list, description="Tags for categorization")
    discovery_method: str | None = Field(
        default=None, description="How it was discovered (nmap, arp, etc.)"
    )


class WriteHost(CallableTool2[WriteHostParams]):
    """Record a discovered host to the shared intel folder."""

    name: str = "WriteHost"
    description: str = (
        "Record a discovered host to share with other agents. "
        "Use this when you discover a new host through scanning or enumeration."
    )
    params: type[WriteHostParams] = WriteHostParams

    def __init__(self, session: Session, agent_name: str = "main", **kwargs: Any):
        super().__init__(**kwargs)
        self._session = session
        self._agent_name = agent_name

    @override
    async def __call__(self, params: WriteHostParams) -> ToolReturnType:
        intel_dir = _get_intel_dir(self._session)
        hosts_dir = intel_dir / "hosts"
        hosts_dir.mkdir(exist_ok=True)

        # Create host object
        host = Host(
            ip=params.ip,
            hostname=params.hostname,
            os=params.os,
            os_version=params.os_version,
            ports=params.ports,
            tags=params.tags,
            discovery_method=params.discovery_method,
            discovered_by=self._agent_name,
        )

        # Save to file (use IP as filename, sanitized)
        safe_ip = params.ip.replace(".", "_").replace(":", "_")
        host_file = hosts_dir / f"{safe_ip}.json"

        # Merge with existing if present
        if host_file.exists():
            try:
                existing = json.loads(host_file.read_text())
                # Merge ports
                existing_ports = set(existing.get("ports", []))
                host.ports = list(existing_ports.union(set(params.ports)))
                # Merge tags
                existing_tags = set(existing.get("tags", []))
                host.tags = list(existing_tags.union(set(params.tags)))
                # Keep earlier discovery time
                if "discovered_at" in existing:
                    host.discovered_at = datetime.fromisoformat(existing["discovered_at"])
            except (json.JSONDecodeError, OSError):
                pass

        host_file.write_text(json.dumps(host.to_file_dict(), indent=2))
        _update_index(intel_dir, "hosts", params.ip)

        return ToolOk(
            output=f"Host {params.ip} recorded with {len(host.ports)} ports",
            brief=f"Recorded host {params.ip}",
        )


# ─────────────────────────────────────────────────────────────────────────────
# WriteService Tool
# ─────────────────────────────────────────────────────────────────────────────


class WriteServiceParams(BaseModel):
    host: str = Field(description="Host IP address")
    port: int = Field(description="Port number")
    protocol: str = Field(default="tcp", description="Protocol (tcp/udp)")
    service: str | None = Field(default=None, description="Service name (http, ssh, etc.)")
    product: str | None = Field(default=None, description="Product name")
    version: str | None = Field(default=None, description="Version string")
    state: str = Field(default="open", description="Port state")
    vulnerabilities: list[str] = Field(default_factory=list, description="CVE IDs if known")
    tags: list[str] = Field(default_factory=list, description="Tags")


class WriteService(CallableTool2[WriteServiceParams]):
    """Record a discovered service to the shared intel folder."""

    name: str = "WriteService"
    description: str = (
        "Record a discovered service to share with other agents. "
        "Use this when you identify a service running on a port."
    )
    params: type[WriteServiceParams] = WriteServiceParams

    def __init__(self, session: Session, agent_name: str = "main", **kwargs: Any):
        super().__init__(**kwargs)
        self._session = session
        self._agent_name = agent_name

    @override
    async def __call__(self, params: WriteServiceParams) -> ToolReturnType:
        intel_dir = _get_intel_dir(self._session)
        services_dir = intel_dir / "services"
        services_dir.mkdir(exist_ok=True)

        service_id = Service.make_id(params.host, params.port, params.protocol)

        service = Service(
            id=service_id,
            host=params.host,
            port=params.port,
            protocol=params.protocol,
            service=params.service,
            product=params.product,
            version=params.version,
            state=params.state,
            vulnerabilities=params.vulnerabilities,
            tags=params.tags,
            discovered_by=self._agent_name,
        )

        # Save to file
        safe_id = service_id.replace(":", "_").replace("/", "_")
        service_file = services_dir / f"{safe_id}.json"
        service_file.write_text(json.dumps(service.to_file_dict(), indent=2))
        _update_index(intel_dir, "services", service_id)

        svc_name = params.service or "unknown"
        return ToolOk(
            output=f"Service {svc_name} on {params.host}:{params.port} recorded",
            brief=f"Recorded {svc_name}:{params.port}",
        )


# ─────────────────────────────────────────────────────────────────────────────
# WriteCredential Tool
# ─────────────────────────────────────────────────────────────────────────────


class WriteCredentialParams(BaseModel):
    username: str | None = Field(default=None, description="Username")
    secret: str = Field(description="The credential value (password, hash, key)")
    secret_type: str = Field(default="password", description="Type: password, hash, key, token")
    target: str | None = Field(default=None, description="Target system/service")
    source: str = Field(description="Where credential was found")
    valid: bool | None = Field(default=None, description="Whether verified valid")
    privileged: bool = Field(default=False, description="High-privilege account")


class WriteCredential(CallableTool2[WriteCredentialParams]):
    """Record a discovered credential to the shared intel folder."""

    name: str = "WriteCredential"
    description: str = (
        "Record a discovered credential to share with other agents. "
        "Use this when you find usernames, passwords, hashes, or keys."
    )
    params: type[WriteCredentialParams] = WriteCredentialParams

    def __init__(self, session: Session, agent_name: str = "main", **kwargs: Any):
        super().__init__(**kwargs)
        self._session = session
        self._agent_name = agent_name

    @override
    async def __call__(self, params: WriteCredentialParams) -> ToolReturnType:
        from aesc.intel.schemas import CredentialType

        intel_dir = _get_intel_dir(self._session)
        creds_dir = intel_dir / "credentials"
        creds_dir.mkdir(exist_ok=True)

        cred_id = str(uuid.uuid4())[:8]

        # Map string type to enum
        try:
            cred_type = CredentialType(params.secret_type)
        except ValueError:
            cred_type = CredentialType.PASSWORD

        credential = Credential(
            id=cred_id,
            type=cred_type,
            username=params.username,
            secret=params.secret,
            target=params.target,
            source=params.source,
            valid=params.valid,
            privileged=params.privileged,
            discovered_by=self._agent_name,
        )

        cred_file = creds_dir / f"{cred_id}.json"
        cred_file.write_text(json.dumps(credential.to_file_dict(), indent=2))
        _update_index(intel_dir, "credentials", cred_id)

        user_display = params.username or "unknown"
        return ToolOk(
            output=f"Credential for {user_display} recorded (ID: {cred_id})",
            brief=f"Recorded cred: {user_display}",
        )


# ─────────────────────────────────────────────────────────────────────────────
# ReadIntel Tool
# ─────────────────────────────────────────────────────────────────────────────


class ReadIntelParams(BaseModel):
    intel_type: str | None = Field(
        default=None,
        description="Type to read: 'hosts', 'services', 'credentials', or None for all",
    )
    limit: int = Field(default=50, description="Maximum items to return")


class ReadIntel(CallableTool2[ReadIntelParams]):
    """Read intelligence discovered by all agents."""

    name: str = "ReadIntel"
    description: str = (
        "Read intelligence from the shared folder discovered by all agents. "
        "Use this to see what other agents have found - hosts, services, credentials."
    )
    params: type[ReadIntelParams] = ReadIntelParams

    def __init__(self, session: Session, **kwargs: Any):
        super().__init__(**kwargs)
        self._session = session

    @override
    async def __call__(self, params: ReadIntelParams) -> ToolReturnType:
        intel_dir = _get_intel_dir(self._session)

        result_parts = []

        types_to_read = (
            [params.intel_type] if params.intel_type else ["hosts", "services", "credentials"]
        )

        for intel_type in types_to_read:
            type_dir = intel_dir / intel_type
            if not type_dir.exists():
                continue

            items = []
            for item_file in sorted(type_dir.glob("*.json"))[: params.limit]:
                try:
                    item = json.loads(item_file.read_text())
                    items.append(item)
                except (json.JSONDecodeError, OSError):
                    continue

            if items:
                result_parts.append(f"## {intel_type.upper()} ({len(items)})")
                for item in items:
                    if intel_type == "hosts":
                        ports_str = ",".join(map(str, item.get("ports", [])))
                        result_parts.append(
                            f"- {item['ip']}: {item.get('os', 'unknown OS')} "
                            f"[ports: {ports_str or 'none'}]"
                        )
                    elif intel_type == "services":
                        result_parts.append(
                            f"- {item['host']}:{item['port']}/{item['protocol']}: "
                            f"{item.get('service', '?')} {item.get('version', '')}"
                        )
                    elif intel_type == "credentials":
                        result_parts.append(
                            f"- {item.get('username', '?')}@{item.get('target', '?')}: "
                            f"{item['type']} (valid: {item.get('valid', '?')})"
                        )
                result_parts.append("")

        if not result_parts:
            return ToolOk(output="No intelligence found yet.", brief="No intel")

        output = "\n".join(result_parts)
        return ToolOk(output=output, brief=f"Found intel in {len(types_to_read)} categories")


# ─────────────────────────────────────────────────────────────────────────────
# Exports
# ─────────────────────────────────────────────────────────────────────────────

__all__ = [
    "WriteHost",
    "WriteService",
    "WriteCredential",
    "ReadIntel",
]
