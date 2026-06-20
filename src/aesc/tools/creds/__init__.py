"""Credential Management Tools.

Store and retrieve credentials discovered during an engagement.

Security model: credentials live in memory for the duration of the session so the
agent can reuse them — there is no at-rest encryption, and the in-memory copy is
plaintext by necessity. The on-disk session copy (``creds.json``) is always
redacted. Storing a credential and revealing plaintext secrets are gated behind
the approval system; masked search/list/delete are not.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any, ClassVar

from pydantic import BaseModel, Field

from aesc.provider import CallableTool2, ToolOk, ToolReturnType
from aesc.soul.approval import Approval
from aesc.soul.runtime import BuiltinSystemPromptArgs
from aesc.tools.utils import ToolRejectedError
from aesc.utils.logging import logger


# Global credential store
class CredentialStore:
    """In-memory credential store with optional persistence."""

    def __init__(self, results_dir: Path | None = None):
        self._creds: list[dict] = []
        # Persist (redacted) to the session results dir when available, else a
        # user-scoped path. The old `/results` default only existed inside the
        # container image and silently no-op'd on a normal host.
        if results_dir is not None:
            self._persist_path = results_dir / "creds.json"
        else:
            self._persist_path = Path.home() / ".aesc" / "creds.json"

    def add(
        self,
        cred_type: str,
        username: str,
        secret: str,
        host: str | None = None,
        port: int | None = None,
        source: str | None = None,
        notes: str | None = None,
    ) -> dict:
        """Add a credential to the store."""
        cred = {
            "id": len(self._creds) + 1,
            "type": cred_type,
            "username": username,
            "secret": secret,
            "host": host,
            "port": port,
            "source": source,
            "notes": notes,
            "added_at": datetime.now().isoformat(),
        }
        self._creds.append(cred)
        self._save()
        return cred

    def search(
        self,
        host: str | None = None,
        username: str | None = None,
        cred_type: str | None = None,
    ) -> list[dict]:
        """Search credentials by criteria."""
        results = self._creds

        if host:
            results = [c for c in results if c.get("host") == host]
        if username:
            results = [c for c in results if c.get("username") == username]
        if cred_type:
            results = [c for c in results if c.get("type") == cred_type]

        return results

    def list_all(self) -> list[dict]:
        """List all stored credentials."""
        return self._creds.copy()

    def get_by_id(self, cred_id: int) -> dict | None:
        """Get credential by ID."""
        for cred in self._creds:
            if cred.get("id") == cred_id:
                return cred
        return None

    def delete(self, cred_id: int) -> bool:
        """Delete credential by ID."""
        for i, cred in enumerate(self._creds):
            if cred.get("id") == cred_id:
                self._creds.pop(i)
                self._save()
                return True
        return False

    def _save(self) -> None:
        """Persist credentials to disk."""
        try:
            self._persist_path.parent.mkdir(parents=True, exist_ok=True)
            # Mask secrets in saved file
            safe_creds = []
            for cred in self._creds:
                safe_cred = cred.copy()
                # Keep first 3 chars of secret for identification
                if safe_cred.get("secret"):
                    secret = safe_cred["secret"]
                    safe_cred["secret_preview"] = secret[:3] + "***" if len(secret) > 3 else "***"
                    safe_cred["secret"] = "***REDACTED***"
                safe_creds.append(safe_cred)

            with open(self._persist_path, "w") as f:
                json.dump(safe_creds, f, indent=2)
        except Exception as e:
            logger.debug("Failed to persist credentials (non-critical): {error}", error=str(e))


# Global store instance (keyed by session ID for isolation)
_cred_stores: dict[str, CredentialStore] = {}


def get_cred_store(
    session_id: str | None = None,
    results_dir: Path | None = None,
) -> CredentialStore:
    """Get or create the credential store for a session."""
    global _cred_stores

    # Use session ID as key, or "default" for backward compatibility
    key = session_id or "default"

    if key not in _cred_stores:
        _cred_stores[key] = CredentialStore(results_dir=results_dir)

    return _cred_stores[key]


# =============================================================================
# Tool Parameter Models
# =============================================================================


class CredStoreParams(BaseModel):
    """Parameters for storing a credential."""

    cred_type: str = Field(description="Type: 'password', 'ssh_key', 'hash', 'token', 'api_key'")
    username: str = Field(description="Username or account name")
    secret: str = Field(description="Password, key content, hash, or token")
    host: str | None = Field(default=None, description="Associated host/IP (optional)")
    port: int | None = Field(default=None, description="Associated port (optional)")
    source: str | None = Field(
        default=None, description="Where this credential was found (e.g., '/etc/shadow')"
    )
    notes: str | None = Field(default=None, description="Additional notes")


class CredSearchParams(BaseModel):
    """Parameters for searching credentials."""

    host: str | None = Field(default=None, description="Filter by host")
    username: str | None = Field(default=None, description="Filter by username")
    cred_type: str | None = Field(default=None, description="Filter by type")


class CredListParams(BaseModel):
    """Parameters for listing credentials (none required)."""

    # Gemini 3 requires at least one field for OBJECT type schemas
    show_secrets: bool = Field(default=False, description="Show credential secrets in output")


class CredDeleteParams(BaseModel):
    """Parameters for deleting a credential."""

    cred_id: int = Field(description="Credential ID to delete")


# =============================================================================
# Credential Tools
# =============================================================================


class CredStore(CallableTool2[CredStoreParams]):
    """Store a discovered credential."""

    name: ClassVar[str] = "CredStore"
    description: ClassVar[str] = """Store a discovered credential for later use.

Types:
- password: Plain text password
- ssh_key: SSH private key content
- hash: Password hash (NTLM, SHA, etc.)
- token: API token or session token
- api_key: API key

Example: CredStore(cred_type="password", username="admin", secret="P@ssw0rd",
         host="10.0.0.5", source="/etc/shadow")
"""
    params: ClassVar[type[CredStoreParams]] = CredStoreParams

    def __init__(
        self,
        builtin_args: BuiltinSystemPromptArgs,
        approval: Approval,
        **kwargs: Any,
    ):
        super().__init__(**kwargs)
        self._session_id = builtin_args.AESC_SESSION_ID
        self._results_dir = builtin_args.AESC_RESULTS_DIR
        self._approval = approval

    async def __call__(self, params: CredStoreParams) -> ToolReturnType:
        target = f"@{params.host}" if params.host else ""
        if not await self._approval.request(
            self.name,
            "store credential",
            f"Store {params.cred_type} for {params.username}{target}",
        ):
            return ToolRejectedError()

        store = get_cred_store(self._session_id, self._results_dir)

        cred = store.add(
            cred_type=params.cred_type,
            username=params.username,
            secret=params.secret,
            host=params.host,
            port=params.port,
            source=params.source,
            notes=params.notes,
        )

        # Build display (mask secret)
        display_secret = params.secret[:3] + "***" if len(params.secret) > 3 else "***"

        output = [
            f"Credential stored (ID: {cred['id']})",
            f"  Type: {params.cred_type}",
            f"  User: {params.username}",
            f"  Secret: {display_secret}",
        ]
        if params.host:
            output.append(f"  Host: {params.host}")
        if params.source:
            output.append(f"  Source: {params.source}")

        return ToolOk(
            output="\n".join(output),
            brief=f"Stored: {params.username}@{params.host or 'unknown'}",
        )


class CredSearch(CallableTool2[CredSearchParams]):
    """Search stored credentials."""

    name: ClassVar[str] = "CredSearch"
    description: ClassVar[str] = """Search for stored credentials by host, username, or type.

Examples:
- Find creds for host: CredSearch(host="10.0.0.5")
- Find by user: CredSearch(username="admin")
- Find SSH keys: CredSearch(cred_type="ssh_key")
"""
    params: ClassVar[type[CredSearchParams]] = CredSearchParams

    def __init__(self, builtin_args: BuiltinSystemPromptArgs, **kwargs: Any):
        super().__init__(**kwargs)
        self._session_id = builtin_args.AESC_SESSION_ID
        self._results_dir = builtin_args.AESC_RESULTS_DIR

    async def __call__(self, params: CredSearchParams) -> ToolReturnType:
        store = get_cred_store(self._session_id, self._results_dir)

        results = store.search(
            host=params.host,
            username=params.username,
            cred_type=params.cred_type,
        )

        if not results:
            return ToolOk(
                output="No credentials found matching criteria.",
                brief="No matches",
            )

        lines = [f"Found {len(results)} credential(s):", "─" * 40]
        for cred in results:
            secret_preview = cred.get("secret", "")[:3] + "***"
            host = cred.get("host", "N/A")
            lines.append(
                f"  [{cred['id']}] {cred['type']}: {cred['username']}:{secret_preview} @ {host}"
            )
            if cred.get("source"):
                lines.append(f"       Source: {cred['source']}")

        return ToolOk(
            output="\n".join(lines),
            brief=f"{len(results)} credential(s) found",
        )


class CredList(CallableTool2[CredListParams]):
    """List all stored credentials."""

    name: ClassVar[str] = "CredList"
    description: ClassVar[str] = "List all credentials stored during the engagement."
    params: ClassVar[type[CredListParams]] = CredListParams

    def __init__(
        self,
        builtin_args: BuiltinSystemPromptArgs,
        approval: Approval,
        **kwargs: Any,
    ):
        super().__init__(**kwargs)
        self._session_id = builtin_args.AESC_SESSION_ID
        self._results_dir = builtin_args.AESC_RESULTS_DIR
        self._approval = approval

    async def __call__(self, params: CredListParams) -> ToolReturnType:
        store = get_cred_store(self._session_id, self._results_dir)
        creds = store.list_all()

        if not creds:
            return ToolOk(
                output="No credentials stored yet.\nUse CredStore to add discovered credentials.",
                brief="No credentials",
            )

        # Revealing plaintext secrets is a sensitive operation — gate it.
        reveal = params.show_secrets
        if reveal and not await self._approval.request(
            self.name,
            "reveal credential secrets",
            f"Reveal plaintext secrets for {len(creds)} stored credential(s)",
        ):
            return ToolRejectedError()

        lines = [f"Stored Credentials ({len(creds)}):", "─" * 50]

        # Group by host
        by_host: dict[str, list] = {}
        for cred in creds:
            host = cred.get("host") or "Unknown"
            if host not in by_host:
                by_host[host] = []
            by_host[host].append(cred)

        for host, host_creds in by_host.items():
            lines.append(f"\n[{host}]")
            for cred in host_creds:
                secret = cred.get("secret", "")
                secret_display = secret if reveal else (secret[:3] + "***")
                cred_line = f"  [{cred['id']}] {cred['type']}: {cred['username']}:{secret_display}"
                lines.append(cred_line)

        lines.append(f"\nSaved to: {self._results_dir}/creds.json (secrets redacted)")

        return ToolOk(
            output="\n".join(lines),
            brief=f"{len(creds)} credential(s)",
        )


class CredDelete(CallableTool2[CredDeleteParams]):
    """Delete a stored credential."""

    name: ClassVar[str] = "CredDelete"
    description: ClassVar[str] = "Delete a stored credential by its ID."
    params: ClassVar[type[CredDeleteParams]] = CredDeleteParams

    def __init__(self, builtin_args: BuiltinSystemPromptArgs, **kwargs: Any):
        super().__init__(**kwargs)
        self._session_id = builtin_args.AESC_SESSION_ID
        self._results_dir = builtin_args.AESC_RESULTS_DIR

    async def __call__(self, params: CredDeleteParams) -> ToolReturnType:
        store = get_cred_store(self._session_id, self._results_dir)

        if store.delete(params.cred_id):
            return ToolOk(
                output=f"Credential {params.cred_id} deleted.",
                brief=f"Deleted #{params.cred_id}",
            )
        else:
            return ToolOk(
                output=f"Credential {params.cred_id} not found.",
                brief="Not found",
            )


__all__ = [
    "CredStore",
    "CredSearch",
    "CredList",
    "CredDelete",
    "get_cred_store",
]
