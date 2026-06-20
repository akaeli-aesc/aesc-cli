"""SSH Tools for Lateral Movement.

Provides secure SSH capabilities for penetration testing:
- SSHConnect: Establish SSH connections
- SSHExec: Execute commands on remote hosts
- SSHSessions: List active sessions
- SSHDisconnect: Close SSH sessions
- SSHUpload: Upload files to remote hosts
- SSHDownload: Download files from remote hosts
- SSHPortForward: Set up port forwarding/pivoting
"""

import asyncio
import os
from pathlib import Path
from typing import Any, ClassVar

from pydantic import BaseModel, Field

from aesc.provider import CallableTool2, ToolOk, ToolReturnType
from aesc.soul.approval import Approval
from aesc.tools.utils import ToolResultBuilder, load_desc


class SSHSession:
    """Represents an active SSH connection."""

    def __init__(
        self,
        session_id: str,
        host: str,
        port: int,
        username: str,
        conn: Any,  # asyncssh.SSHClientConnection
    ):
        self.session_id = session_id
        self.host = host
        self.port = port
        self.username = username
        self.conn = conn
        self.forwards: list[dict] = []  # Active port forwards

    @property
    def display_name(self) -> str:
        return f"{self.username}@{self.host}:{self.port}"

    def is_connected(self) -> bool:
        """Check if connection is still alive."""
        try:
            return self.conn is not None and not self.conn.is_closed()
        except Exception:
            return False


class SessionManager:
    """Manages SSH sessions across the engagement."""

    def __init__(self):
        self._sessions: dict[str, SSHSession] = {}
        self._counter = 0
        self._lock = asyncio.Lock()

    async def create_session(
        self,
        host: str,
        port: int,
        username: str,
        password: str | None = None,
        key_path: str | None = None,
        key_passphrase: str | None = None,
        timeout: int = 10,
        verify_host_key: bool = True,
    ) -> SSHSession:
        """Create a new SSH session."""
        import asyncssh

        # Build connection options
        connect_opts: dict[str, Any] = {
            "host": host,
            "port": port,
            "username": username,
            "connect_timeout": timeout,
        }
        if not verify_host_key:
            # Host-key verification disabled (opt-in via insecure). MITM-exposed.
            connect_opts["known_hosts"] = None
        # Otherwise leave known_hosts unset so asyncssh verifies against the
        # user's ~/.ssh/known_hosts (secure default).

        if key_path:
            # Key-based auth
            key_path_obj = Path(key_path).expanduser()
            if not key_path_obj.exists():
                raise FileNotFoundError(f"SSH key not found: {key_path}")
            connect_opts["client_keys"] = [str(key_path_obj)]
            if key_passphrase:
                connect_opts["passphrase"] = key_passphrase
        elif password:
            # Password auth
            connect_opts["password"] = password
        else:
            # Try default keys
            connect_opts["client_keys"] = None  # Use default ~/.ssh/id_*

        # Connect
        conn = await asyncssh.connect(**connect_opts)

        # Generate session ID
        async with self._lock:
            self._counter += 1
            session_id = f"ssh_{self._counter}"

        session = SSHSession(
            session_id=session_id,
            host=host,
            port=port,
            username=username,
            conn=conn,
        )

        self._sessions[session_id] = session
        return session

    def get_session(self, session_id: str) -> SSHSession | None:
        """Get session by ID."""
        return self._sessions.get(session_id)

    def list_sessions(self) -> list[SSHSession]:
        """List all active sessions."""
        return [s for s in self._sessions.values() if s.is_connected()]

    async def close_session(self, session_id: str) -> bool:
        """Close a session."""
        session = self._sessions.pop(session_id, None)
        if session and session.conn:
            try:
                session.conn.close()
                await session.conn.wait_closed()
            except Exception:
                pass
            return True
        return False

    async def close_all(self) -> None:
        """Close all sessions."""
        for session_id in list(self._sessions.keys()):
            await self.close_session(session_id)


# Global session manager - shared across all SSH tools
_session_manager: SessionManager | None = None


def get_session_manager() -> SessionManager:
    """Get or create the global session manager."""
    global _session_manager
    if _session_manager is None:
        _session_manager = SessionManager()
    return _session_manager


# =============================================================================
# Tool Parameter Models
# =============================================================================


class SSHConnectParams(BaseModel):
    """Parameters for SSH connection."""

    host: str = Field(description="Target hostname or IP address")
    port: int = Field(default=22, ge=1, le=65535, description="SSH port (default 22)")
    username: str = Field(description="Username for authentication")
    password: str | None = Field(default=None, description="Password (if using password auth)")
    key_path: str | None = Field(
        default=None, description="Path to SSH private key (e.g., /loot/id_rsa)"
    )
    key_passphrase: str | None = Field(default=None, description="Passphrase for encrypted key")
    timeout: int = Field(default=10, ge=1, le=60, description="Connection timeout in seconds")
    insecure: bool = Field(
        default=False,
        description=(
            "Skip SSH host-key verification (INSECURE: exposes the connection to "
            "man-in-the-middle). Only enable for authorized, disposable lab targets "
            "whose host key is not yet trusted. Default verifies against ~/.ssh/known_hosts."
        ),
    )


class SSHExecParams(BaseModel):
    """Parameters for remote command execution."""

    session_id: str = Field(description="Session ID from SSHConnect (e.g., 'ssh_1')")
    command: str = Field(description="Command to execute on remote host")
    timeout: int = Field(default=60, ge=1, le=300, description="Command timeout in seconds")


class SSHSessionsParams(BaseModel):
    """Parameters for listing sessions (none required)."""

    # Gemini 3 requires at least one field for OBJECT type schemas
    verbose: bool = Field(default=False, description="Show detailed session information")


class SSHDisconnectParams(BaseModel):
    """Parameters for disconnecting a session."""

    session_id: str = Field(description="Session ID to disconnect (e.g., 'ssh_1')")


class SSHUploadParams(BaseModel):
    """Parameters for uploading files."""

    session_id: str = Field(description="Session ID from SSHConnect")
    local_path: str = Field(description="Local file path to upload")
    remote_path: str = Field(description="Remote destination path")


class SSHDownloadParams(BaseModel):
    """Parameters for downloading files."""

    session_id: str = Field(description="Session ID from SSHConnect")
    remote_path: str = Field(description="Remote file path to download")
    local_path: str = Field(description="Local destination path (e.g., /results/loot/)")


class SSHPortForwardParams(BaseModel):
    """Parameters for port forwarding."""

    session_id: str = Field(description="Session ID from SSHConnect")
    forward_type: str = Field(
        description="Type: 'local' (-L), 'remote' (-R), or 'dynamic' (-D SOCKS proxy)"
    )
    local_port: int = Field(ge=1, le=65535, description="Local port to bind")
    remote_host: str | None = Field(
        default=None, description="Remote host (for local/remote forwards)"
    )
    remote_port: int | None = Field(
        default=None, ge=1, le=65535, description="Remote port (for local/remote forwards)"
    )


# =============================================================================
# SSH Tools
# =============================================================================


class SSHConnect(CallableTool2[SSHConnectParams]):
    """Establish SSH connection to a remote host."""

    name: ClassVar[str] = "SSHConnect"
    description: ClassVar[str] = load_desc(
        Path(__file__).parent / "connect.md",
        {},
    )
    params: ClassVar[type[SSHConnectParams]] = SSHConnectParams

    def __init__(self, approval: Approval, **kwargs: Any):
        super().__init__(**kwargs)
        self._approval = approval

    async def __call__(self, params: SSHConnectParams) -> ToolReturnType:
        # Host-key verification is on by default; opt out per-call (insecure) or
        # globally for lab-only use via AESC_SSH_INSECURE.
        insecure = params.insecure or os.getenv("AESC_SSH_INSECURE", "").lower() in (
            "1",
            "true",
            "yes",
        )

        # Request approval for establishing remote connection
        conn_desc = f"Connect to {params.username}@{params.host}:{params.port}"
        if insecure:
            conn_desc += " (host-key verification DISABLED)"
        if not await self._approval.request(
            self.name,
            "establish SSH connection",
            conn_desc,
        ):
            from aesc.tools.utils import ToolRejectedError

            return ToolRejectedError()

        builder = ToolResultBuilder()

        try:
            manager = get_session_manager()
            session = await manager.create_session(
                host=params.host,
                port=params.port,
                username=params.username,
                password=params.password,
                key_path=params.key_path,
                key_passphrase=params.key_passphrase,
                timeout=params.timeout,
                verify_host_key=not insecure,
            )

            builder.write(f"Connected to {session.display_name}\n")
            builder.write(f"Session ID: {session.session_id}\n")
            builder.write("\nUse SSHExec with this session_id to run commands.")

            return builder.ok(
                f"SSH session established: {session.session_id}",
                brief=f"Connected: {session.session_id} → {session.display_name}",
            )

        except FileNotFoundError as e:
            return builder.error(str(e), brief="Key file not found")
        except TimeoutError:
            return builder.error(
                f"Connection timed out to {params.host}:{params.port} (timeout={params.timeout}s)",
                brief="Connection timeout",
            )
        except OSError as e:
            # Handle network-level errors
            error_msg = str(e)
            if "Connection refused" in error_msg or e.errno == 111:
                return builder.error(
                    f"Connection refused to {params.host}:{params.port}",
                    brief="Connection refused",
                )
            elif "No route to host" in error_msg or "Network is unreachable" in error_msg:
                return builder.error(
                    f"Cannot reach {params.host}",
                    brief="Host unreachable",
                )
            else:
                return builder.error(
                    f"Network error connecting to {params.host}:{params.port}: {e}",
                    brief="Network error",
                )
        except Exception as e:
            error_msg = str(e)
            error_type = type(e).__name__
            if "host key" in error_msg.lower() or "known_hosts" in error_msg.lower():
                return builder.error(
                    f"Host key for {params.host} is not trusted. If this is an "
                    "authorized, disposable target, set insecure=true (or export "
                    "AESC_SSH_INSECURE=1) to skip verification; otherwise add the "
                    "host to ~/.ssh/known_hosts.",
                    brief="Host key not verified",
                )
            if "Authentication failed" in error_msg or "Permission denied" in error_msg:
                return builder.error(
                    f"Authentication failed for {params.username}@{params.host}",
                    brief="Auth failed",
                )
            elif "Connection refused" in error_msg:
                return builder.error(
                    f"Connection refused to {params.host}:{params.port}",
                    brief="Connection refused",
                )
            elif "No route to host" in error_msg or "Network is unreachable" in error_msg:
                return builder.error(
                    f"Cannot reach {params.host}",
                    brief="Host unreachable",
                )
            else:
                return builder.error(
                    f"SSH connection failed ({error_type}): {e or 'Unknown error'}",
                    brief="Connection failed",
                )


class SSHExec(CallableTool2[SSHExecParams]):
    """Execute command on remote host via SSH."""

    name: ClassVar[str] = "SSHExec"
    description: ClassVar[str] = load_desc(
        Path(__file__).parent / "exec.md",
        {},
    )
    params: ClassVar[type[SSHExecParams]] = SSHExecParams

    def __init__(self, approval: Approval, **kwargs: Any):
        super().__init__(**kwargs)
        self._approval = approval

    async def __call__(self, params: SSHExecParams) -> ToolReturnType:
        manager = get_session_manager()
        session = manager.get_session(params.session_id)

        if not session:
            return ToolOk(
                output=f"Session '{params.session_id}' not found. "
                "Use SSHSessions to list active sessions.",
                brief="Session not found",
            )

        if not session.is_connected():
            return ToolOk(
                output=f"Session '{params.session_id}' is disconnected. Reconnect with SSHConnect.",
                brief="Session disconnected",
            )

        # Request approval for remote command execution
        if not await self._approval.request(
            self.name,
            "execute remote command",
            f"Run `{params.command}` on {session.display_name}",
        ):
            from aesc.tools.utils import ToolRejectedError

            return ToolRejectedError()

        builder = ToolResultBuilder()

        try:
            # Execute command with timeout
            result = await asyncio.wait_for(
                session.conn.run(params.command, check=False),
                timeout=params.timeout,
            )

            # Capture output
            stdout = result.stdout or ""
            stderr = result.stderr or ""
            exit_code = result.exit_status

            if stdout:
                builder.write(stdout)
            if stderr:
                builder.write(f"\n[stderr]\n{stderr}")

            builder.write(f"\n[exit code: {exit_code}]")

            if exit_code == 0:
                # Truncate brief for long outputs
                brief_output = stdout.strip().split("\n")[0][:50] if stdout.strip() else "Success"
                return builder.ok(
                    f"Command executed on {session.display_name}",
                    brief=brief_output,
                )
            else:
                return builder.error(
                    f"Command failed with exit code {exit_code}",
                    brief=f"Exit code: {exit_code}",
                )

        except TimeoutError:
            return builder.error(
                f"Command timed out after {params.timeout}s",
                brief="Timeout",
            )
        except Exception as e:
            return builder.error(f"Execution failed: {e}", brief="Exec failed")


class SSHSessions(CallableTool2[SSHSessionsParams]):
    """List all active SSH sessions."""

    name: ClassVar[str] = "SSHSessions"
    description: ClassVar[str] = "List all active SSH sessions with their IDs and connection info."
    params: ClassVar[type[SSHSessionsParams]] = SSHSessionsParams

    def __init__(self, **kwargs: Any):
        super().__init__(**kwargs)

    async def __call__(self, params: SSHSessionsParams) -> ToolReturnType:
        manager = get_session_manager()
        sessions = manager.list_sessions()

        if not sessions:
            return ToolOk(
                output="No active SSH sessions.\nUse SSHConnect to establish a connection.",
                brief="No sessions",
            )

        lines = ["Active SSH Sessions:", "─" * 40]
        for s in sessions:
            status = "✓ connected" if s.is_connected() else "✗ disconnected"
            lines.append(f"  {s.session_id}: {s.display_name} [{status}]")
            if s.forwards:
                for fwd in s.forwards:
                    lines.append(f"    └─ {fwd['type']}: {fwd['desc']}")

        return ToolOk(
            output="\n".join(lines),
            brief=f"{len(sessions)} active session(s)",
        )


class SSHDisconnect(CallableTool2[SSHDisconnectParams]):
    """Disconnect an SSH session."""

    name: ClassVar[str] = "SSHDisconnect"
    description: ClassVar[str] = "Disconnect and close an SSH session."
    params: ClassVar[type[SSHDisconnectParams]] = SSHDisconnectParams

    def __init__(self, **kwargs: Any):
        super().__init__(**kwargs)

    async def __call__(self, params: SSHDisconnectParams) -> ToolReturnType:
        manager = get_session_manager()
        session = manager.get_session(params.session_id)

        if not session:
            return ToolOk(
                output=f"Session '{params.session_id}' not found.",
                brief="Not found",
            )

        display_name = session.display_name
        await manager.close_session(params.session_id)

        return ToolOk(
            output=f"Disconnected from {display_name}",
            brief=f"Closed {params.session_id}",
        )


class SSHUpload(CallableTool2[SSHUploadParams]):
    """Upload file to remote host via SCP/SFTP."""

    name: ClassVar[str] = "SSHUpload"
    description: ClassVar[str] = load_desc(
        Path(__file__).parent / "upload.md",
        {},
    )
    params: ClassVar[type[SSHUploadParams]] = SSHUploadParams

    def __init__(self, approval: Approval, **kwargs: Any):
        super().__init__(**kwargs)
        self._approval = approval

    async def __call__(self, params: SSHUploadParams) -> ToolReturnType:
        manager = get_session_manager()
        session = manager.get_session(params.session_id)

        if not session:
            return ToolOk(
                output=f"Session '{params.session_id}' not found.",
                brief="Session not found",
            )

        if not session.is_connected():
            return ToolOk(
                output=f"Session '{params.session_id}' is disconnected.",
                brief="Disconnected",
            )

        local_path = Path(params.local_path)
        if not local_path.exists():
            return ToolOk(
                output=f"Local file not found: {params.local_path}",
                brief="File not found",
            )

        # Request approval for uploading files
        if not await self._approval.request(
            self.name,
            "upload file to remote host",
            f"Upload {params.local_path} → {session.display_name}:{params.remote_path}",
        ):
            from aesc.tools.utils import ToolRejectedError

            return ToolRejectedError()

        builder = ToolResultBuilder()

        try:
            import asyncssh

            await asyncssh.scp(
                str(local_path),
                (session.conn, params.remote_path),
            )

            file_size = local_path.stat().st_size
            return builder.ok(
                f"Uploaded {params.local_path} ({file_size} bytes) to {params.remote_path}",
                brief=f"Uploaded {local_path.name}",
            )

        except Exception as e:
            return builder.error(f"Upload failed: {e}", brief="Upload failed")


class SSHDownload(CallableTool2[SSHDownloadParams]):
    """Download file from remote host via SCP/SFTP."""

    name: ClassVar[str] = "SSHDownload"
    description: ClassVar[str] = load_desc(
        Path(__file__).parent / "download.md",
        {},
    )
    params: ClassVar[type[SSHDownloadParams]] = SSHDownloadParams

    def __init__(self, approval: Approval, **kwargs: Any):
        super().__init__(**kwargs)
        self._approval = approval

    async def __call__(self, params: SSHDownloadParams) -> ToolReturnType:
        manager = get_session_manager()
        session = manager.get_session(params.session_id)

        if not session:
            return ToolOk(
                output=f"Session '{params.session_id}' not found.",
                brief="Session not found",
            )

        if not session.is_connected():
            return ToolOk(
                output=f"Session '{params.session_id}' is disconnected.",
                brief="Disconnected",
            )

        # Ensure local directory exists
        local_path = Path(params.local_path)
        if local_path.is_dir():
            # Download to directory with original filename
            remote_filename = Path(params.remote_path).name
            local_path = local_path / remote_filename
        else:
            local_path.parent.mkdir(parents=True, exist_ok=True)

        # Request approval for downloading files
        if not await self._approval.request(
            self.name,
            "download file from remote host",
            f"Download {session.display_name}:{params.remote_path} → {local_path}",
        ):
            from aesc.tools.utils import ToolRejectedError

            return ToolRejectedError()

        builder = ToolResultBuilder()

        try:
            import asyncssh

            await asyncssh.scp(
                (session.conn, params.remote_path),
                str(local_path),
            )

            file_size = local_path.stat().st_size
            return builder.ok(
                f"Downloaded {params.remote_path} ({file_size} bytes) to {local_path}",
                brief=f"Downloaded → {local_path.name}",
            )

        except Exception as e:
            return builder.error(f"Download failed: {e}", brief="Download failed")


class SSHPortForward(CallableTool2[SSHPortForwardParams]):
    """Set up SSH port forwarding for pivoting."""

    name: ClassVar[str] = "SSHPortForward"
    description: ClassVar[str] = load_desc(
        Path(__file__).parent / "portforward.md",
        {},
    )
    params: ClassVar[type[SSHPortForwardParams]] = SSHPortForwardParams

    def __init__(self, approval: Approval, **kwargs: Any):
        super().__init__(**kwargs)
        self._approval = approval

    async def __call__(self, params: SSHPortForwardParams) -> ToolReturnType:
        manager = get_session_manager()
        session = manager.get_session(params.session_id)

        if not session:
            return ToolOk(
                output=f"Session '{params.session_id}' not found.",
                brief="Session not found",
            )

        if not session.is_connected():
            return ToolOk(
                output=f"Session '{params.session_id}' is disconnected.",
                brief="Disconnected",
            )

        # Build description for approval
        if params.forward_type == "dynamic":
            fwd_desc = f"SOCKS proxy on localhost:{params.local_port}"
        elif params.forward_type == "local":
            fwd_desc = f"localhost:{params.local_port} → {params.remote_host}:{params.remote_port}"
        else:  # remote
            fwd_desc = f"remote:{params.remote_port} → localhost:{params.local_port}"

        # Request approval for port forwarding
        if not await self._approval.request(
            self.name,
            "set up port forwarding",
            f"Forward via {session.display_name}: {fwd_desc}",
        ):
            from aesc.tools.utils import ToolRejectedError

            return ToolRejectedError()

        builder = ToolResultBuilder()

        try:
            if params.forward_type == "dynamic":
                # SOCKS proxy
                listener = await session.conn.forward_socks("", params.local_port)
                session.forwards.append(
                    {
                        "type": "dynamic",
                        "desc": f"SOCKS localhost:{params.local_port}",
                        "listener": listener,
                    }
                )
                builder.write(f"SOCKS proxy listening on localhost:{params.local_port}\n")
                builder.write(f"Configure proxychains: socks5 127.0.0.1 {params.local_port}\n")
                builder.write("Or use: proxychains <command>")
                return builder.ok(
                    f"SOCKS proxy active on port {params.local_port}",
                    brief=f"SOCKS :{params.local_port}",
                )

            elif params.forward_type == "local":
                # Local port forward
                if not params.remote_host or not params.remote_port:
                    return builder.error(
                        "Local forward requires remote_host and remote_port",
                        brief="Missing params",
                    )

                listener = await session.conn.forward_local_port(
                    "",
                    params.local_port,
                    params.remote_host,
                    params.remote_port,
                )
                session.forwards.append(
                    {
                        "type": "local",
                        "desc": f":{params.local_port} → {params.remote_host}:{params.remote_port}",
                        "listener": listener,
                    }
                )
                builder.write(
                    f"Local forward: localhost:{params.local_port} → "
                    f"{params.remote_host}:{params.remote_port}\n"
                )
                builder.write(f"Access internal service via: localhost:{params.local_port}")
                fwd_info = f":{params.local_port} → {params.remote_host}:{params.remote_port}"
                return builder.ok(
                    f"Port forward active: {fwd_info}",
                    brief=f"Forward :{params.local_port}",
                )

            elif params.forward_type == "remote":
                # Remote port forward
                if not params.remote_port:
                    return builder.error(
                        "Remote forward requires remote_port",
                        brief="Missing params",
                    )

                listener = await session.conn.forward_remote_port(
                    "",
                    params.remote_port,
                    "localhost",
                    params.local_port,
                )
                session.forwards.append(
                    {
                        "type": "remote",
                        "desc": f"remote:{params.remote_port} → localhost:{params.local_port}",
                        "listener": listener,
                    }
                )
                builder.write(
                    f"Remote forward: {session.host}:{params.remote_port} → "
                    f"localhost:{params.local_port}"
                )
                return builder.ok(
                    "Remote forward active",
                    brief=f"Remote :{params.remote_port}",
                )

            else:
                return builder.error(
                    f"Unknown forward type: {params.forward_type}. "
                    "Use 'local', 'remote', or 'dynamic'.",
                    brief="Invalid type",
                )

        except Exception as e:
            return builder.error(f"Port forward failed: {e}", brief="Forward failed")


# Export all tools
__all__ = [
    "SSHConnect",
    "SSHExec",
    "SSHSessions",
    "SSHDisconnect",
    "SSHUpload",
    "SSHDownload",
    "SSHPortForward",
    "get_session_manager",
]
