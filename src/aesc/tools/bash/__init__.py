import asyncio
import os
import platform
import re
import signal
import subprocess
import threading
from collections import deque
from collections.abc import Callable
from pathlib import Path
from typing import Any, override

from pydantic import BaseModel, Field

from aesc.provider import CallableTool2, ToolReturnType
from aesc.soul.approval import Approval
from aesc.soul.toolset import get_current_tool_call_or_none
from aesc.tools.utils import ToolRejectedError, ToolResultBuilder, load_desc
from aesc.wire.message import ToolOutputChunk

# Whether PTY-based subprocess execution is available (Unix only)
_PTY_AVAILABLE = platform.system() != "Windows"
if _PTY_AVAILABLE:
    try:
        import pty
        import select
    except ImportError:
        _PTY_AVAILABLE = False

MAX_TIMEOUT = 10 * 60  # 10 minutes max

# Pagination guidance appended when Bash output is truncated
_BASH_PAGINATION_HINT = (
    "Use head/tail/grep/sed to view specific sections, "
    "or pipe through 'head -n 100' to limit output."
)

# Environment variables to strip from child shell processes.
# The parent Python process keeps these for LiteLLM/SDK auth,
# but shell commands (env, printenv, etc.) won't see them.
_SENSITIVE_ENV_PATTERNS = re.compile(
    r"^("
    r"OPENAI_API_KEY|ANTHROPIC_API_KEY|GOOGLE_API_KEY|GOOGLE_APPLICATION_CREDENTIALS"
    r"|VERTEX_PROJECT|VERTEXAI_PROJECT|GOOGLE_CLOUD_PROJECT"
    r"|AESC_VERTEX_MAAS|OPENAI_BASE_URL"
    r"|.*_SECRET_KEY|.*_TOKEN|.*_CREDENTIALS"
    r"|REDIS_URL"
    r")$",
    re.IGNORECASE,
)


def _get_sanitized_env() -> dict[str, str]:
    """Build a subprocess environment with platform secrets stripped."""
    import os

    return {k: v for k, v in os.environ.items() if not _SENSITIVE_ENV_PATTERNS.match(k)}


# Network scanning tools that need longer timeouts
SLOW_NETWORK_TOOLS = frozenset(
    {
        "nmap",
        "masscan",
        "nikto",
        "gobuster",
        "ffuf",
        "dirb",
        "dirbuster",
        "wpscan",
        "nuclei",
        "httpx",
        "subfinder",
        "amass",
        "theHarvester",
        "enum4linux",
        "smbclient",
        "rpcclient",
        "ldapsearch",
        "crackmapexec",
        "hydra",
        "medusa",
        "sqlmap",
        "wfuzz",
        "feroxbuster",
        "rustscan",
    }
)

# Default timeouts by tool type
DEFAULT_TIMEOUT = 60  # Normal commands
NETWORK_SCAN_TIMEOUT = 300  # 5 minutes for network scans


def _get_smart_timeout(command: str, user_timeout: int | None) -> int:
    """
    Determine appropriate timeout based on command.

    If user explicitly specified a timeout, use that.
    Otherwise, auto-detect network scanning tools and use longer timeout.
    """
    if user_timeout is not None:
        return user_timeout

    # Extract first command word (handles pipes, paths, sudo, etc.)
    cmd_lower = command.lower().strip()

    # Handle sudo prefix
    if cmd_lower.startswith("sudo "):
        cmd_lower = cmd_lower[5:].strip()

    # Get the actual command (first word, strip path)
    first_word = cmd_lower.split()[0] if cmd_lower else ""
    cmd_name = first_word.split("/")[-1]  # Handle /usr/bin/nmap -> nmap

    # Check if it's a slow network tool
    if cmd_name in SLOW_NETWORK_TOOLS:
        return NETWORK_SCAN_TIMEOUT

    # Also check if any slow tool appears in a pipe chain
    for tool in SLOW_NETWORK_TOOLS:
        if f" {tool} " in f" {cmd_lower} " or cmd_lower.startswith(f"{tool} "):
            return NETWORK_SCAN_TIMEOUT

    return DEFAULT_TIMEOUT


class Params(BaseModel):
    command: str = Field(description="The bash command to execute.")
    timeout: int | None = Field(
        description=(
            "The timeout in seconds for the command to execute. "
            "If the command takes longer than this, it will be killed. "
            "If not specified, network scanning tools (nmap, nikto, etc.) "
            "automatically get 5 minutes, other commands get 60 seconds."
        ),
        default=None,
        ge=1,
        le=MAX_TIMEOUT,
    )


_NAME = "CMD" if platform.system() == "Windows" else "Bash"
_DESC_FILE = "cmd.md" if platform.system() == "Windows" else "bash.md"


class Bash(CallableTool2[Params]):
    name: str = _NAME
    description: str = load_desc(Path(__file__).parent / _DESC_FILE, {})
    params: type[Params] = Params

    def __init__(self, approval: Approval, **kwargs: Any):
        super().__init__(**kwargs)
        self._approval = approval

    @override
    async def __call__(self, params: Params) -> ToolReturnType:
        builder = ToolResultBuilder()

        if not await self._approval.request(
            self.name,
            "run shell command",
            f"Run command `{params.command}`",
            command=params.command,
        ):
            return ToolRejectedError()

        # Get current tool call ID for streaming output
        tool_call = get_current_tool_call_or_none()
        tool_call_id = tool_call.id if tool_call else None

        # IMPORTANT: Capture wire reference NOW before entering async callbacks
        # ContextVar values may not propagate correctly to stream reader callbacks
        from aesc.soul import get_wire_or_none

        captured_wire = get_wire_or_none()

        # Debug logging (only when AESC_DEBUG is set)
        import os
        import time

        _debug = os.environ.get("AESC_DEBUG")
        if _debug:
            debug_file = os.environ.get("AESC_DEBUG_FILE", "/tmp/ash_debug.log")
            with open(debug_file, "a") as f:
                f.write(
                    f"[BASH] tool_call_id={tool_call_id}, wire_captured={captured_wire is not None}, cmd={params.command[:80]}\n"
                )

        # Throttle output streaming - batch lines to reduce UI updates
        output_buffer: list[str] = []
        last_send_time = time.time()
        THROTTLE_INTERVAL = 0.3  # Send at most every 300ms
        MAX_BUFFER_LINES = 80  # Cap buffer to prevent massive single flushes
        KEEP_LINES = 40  # Keep last N lines when truncating

        def _maybe_send_output():
            nonlocal output_buffer, last_send_time
            # Cap buffer size to prevent UI choking on massive flushes
            if len(output_buffer) > MAX_BUFFER_LINES:
                output_buffer = output_buffer[-KEEP_LINES:]
            now = time.time()
            if output_buffer and (now - last_send_time) >= THROTTLE_INTERVAL:
                chunk_text = "".join(output_buffer)
                if tool_call_id and captured_wire is not None:
                    chunk = ToolOutputChunk(tool_call_id, chunk_text, is_stderr=False)
                    captured_wire.soul_side.send(chunk)
                output_buffer = []
                last_send_time = now

        def stdout_cb(line: bytes):
            line_str = line.decode(encoding="utf-8", errors="replace")
            if not line_str:
                return
            builder.write(line_str)
            output_buffer.append(line_str)
            _maybe_send_output()

        def stderr_cb(line: bytes):
            line_str = line.decode(encoding="utf-8", errors="replace")
            if not line_str:
                return
            builder.write(line_str)
            output_buffer.append(line_str)
            _maybe_send_output()

        # Get smart timeout (auto-detect network tools if not specified)
        effective_timeout = _get_smart_timeout(params.command, params.timeout)

        try:
            exitcode = await _stream_subprocess(
                params.command,
                stdout_cb,
                stderr_cb,
                effective_timeout,
                tool_call_id,
                should_stop=lambda: builder.is_full,
            )

            # Flush any remaining buffered output
            if output_buffer and tool_call_id and captured_wire is not None:
                captured_wire.soul_side.send(
                    ToolOutputChunk(tool_call_id, "".join(output_buffer), is_stderr=False)
                )

            if exitcode == 0:
                return builder.ok(
                    "Command executed successfully.",
                    tool_hint=_BASH_PAGINATION_HINT,
                )
            else:
                return builder.error(
                    f"Command failed with exit code: {exitcode}.",
                    brief=f"Failed with exit code: {exitcode}",
                    tool_hint=_BASH_PAGINATION_HINT,
                )
        except TimeoutError:
            return builder.error(
                f"Command killed by timeout ({effective_timeout}s)",
                brief=f"Killed by timeout ({effective_timeout}s)",
                tool_hint=_BASH_PAGINATION_HINT,
            )


async def _stream_subprocess(
    command: str,
    stdout_cb: Callable[[bytes], None],
    stderr_cb: Callable[[bytes], None],
    timeout: int,
    tool_call_id: str | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> int:
    """Stream subprocess output. Uses PTY on Unix, pipes on Windows."""
    if _PTY_AVAILABLE:
        return await _stream_subprocess_pty(
            command,
            stdout_cb,
            timeout,
            tool_call_id,
            should_stop,
        )
    return await _stream_subprocess_pipes(
        command,
        stdout_cb,
        stderr_cb,
        timeout,
        tool_call_id,
        should_stop,
    )


async def _stream_subprocess_pty(
    command: str,
    output_cb: Callable[[bytes], None],
    timeout: int,
    tool_call_id: str | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> int:
    """Stream subprocess output using PTY for proper terminal handling.

    Adopts CAI's production pattern: pty.openpty() + os.setsid() + select.select().
    Advantages over pipes:
    - No terminal escape sequence corruption (PTY kernel layer handles it)
    - No readline() deadlock on unbuffered output (reads 4096-byte chunks)
    - Process group isolation for clean SIGTERM/SIGKILL of entire command tree
    """
    from aesc.tools.process_registry import get_registry

    master_fd, slave_fd = pty.openpty()

    # Launch subprocess with PTY and process group isolation
    process = subprocess.Popen(
        command,
        shell=True,
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        preexec_fn=os.setsid,
        env=_get_sanitized_env(),
    )

    # Close slave in parent — child inherited its own copy via fork
    os.close(slave_fd)

    pgid: int | None = None
    try:
        pgid = os.getpgid(process.pid)
    except (ProcessLookupError, OSError):
        pass

    # Thread-safe output queue: read thread appends, event loop drains
    output_queue: deque[bytes] = deque()
    read_done = threading.Event()

    def _read_loop():
        """Background thread: read PTY output via non-blocking select."""
        try:
            while not read_done.is_set():
                if should_stop and should_stop():
                    break
                if process.poll() is not None:
                    # Process exited — drain remaining output
                    while True:
                        try:
                            ready, _, _ = select.select([master_fd], [], [], 0.1)
                        except (ValueError, OSError):
                            break
                        if not ready:
                            break
                        try:
                            chunk = os.read(master_fd, 4096)
                            if chunk:
                                output_queue.append(chunk)
                            else:
                                break
                        except OSError:
                            break
                    break

                try:
                    ready, _, _ = select.select([master_fd], [], [], 0.5)
                except (ValueError, OSError):
                    break
                if ready:
                    try:
                        chunk = os.read(master_fd, 4096)
                        if chunk:
                            output_queue.append(chunk)
                        elif process.poll() is not None:
                            break
                    except OSError:
                        break
        except Exception:
            pass
        finally:
            read_done.set()

    # Start read thread
    read_thread = threading.Thread(target=_read_loop, daemon=True)
    read_thread.start()

    # Register for tracking (enables kill from UI)
    registry = get_registry()
    if tool_call_id:
        registry.register(tool_call_id, command, process, pgid=pgid)

    try:
        # Async polling loop: drain output queue and call callbacks from event loop
        async def _poll_and_forward():
            while True:
                # Drain accumulated chunks — normalize \r\n → \n (PTY kernel adds \r)
                while output_queue:
                    chunk = output_queue.popleft()
                    output_cb(chunk.replace(b"\r\n", b"\n"))

                if read_done.is_set():
                    # Final drain
                    while output_queue:
                        chunk = output_queue.popleft()
                        output_cb(chunk.replace(b"\r\n", b"\n"))
                    break

                await asyncio.sleep(0.1)  # 100ms poll interval

        await asyncio.wait_for(_poll_and_forward(), timeout)

        # Output limit stop — kill if still running
        if should_stop and should_stop() and process.poll() is None:
            _kill_process_group(process, pgid)

        if process.returncode is not None:
            return process.returncode
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            _kill_process_group(process, pgid)
        return process.returncode if process.returncode is not None else -1

    except TimeoutError:
        _kill_process_group(process, pgid)
        raise TimeoutError(f"Command timed out after {timeout}s")

    finally:
        # Signal read thread to stop and wait for it
        read_done.set()
        read_thread.join(timeout=2)

        # Close master fd
        try:
            os.close(master_fd)
        except OSError:
            pass

        # Ensure process is dead
        if process.poll() is None:
            _kill_process_group(process, pgid)
            try:
                process.wait(timeout=2)
            except Exception:
                pass

        # Unregister
        if tool_call_id:
            registry.unregister(tool_call_id)


def _kill_process_group(
    process: subprocess.Popen,
    pgid: int | None,
) -> None:
    """Kill a process and its entire process group (SIGTERM → SIGKILL)."""
    if pgid is not None:
        try:
            os.killpg(pgid, signal.SIGTERM)
            try:
                process.wait(timeout=1)
                return
            except subprocess.TimeoutExpired:
                os.killpg(pgid, signal.SIGKILL)
                return
        except (ProcessLookupError, OSError):
            pass
    # Fallback: kill just the process
    try:
        process.kill()
    except (ProcessLookupError, OSError):
        pass


async def _stream_subprocess_pipes(
    command: str,
    stdout_cb: Callable[[bytes], None],
    stderr_cb: Callable[[bytes], None],
    timeout: int,
    tool_call_id: str | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> int:
    """Fallback: stream subprocess output using pipes (Windows or PTY unavailable)."""
    from aesc.tools.process_registry import get_registry

    async def _read_stream(stream: asyncio.StreamReader, cb: Callable[[bytes], None]):
        while True:
            if should_stop and should_stop():
                break
            line = await stream.readline()
            if line:
                cb(line)
            else:
                break

    process = await asyncio.create_subprocess_shell(
        command,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=_get_sanitized_env(),
    )

    if process.stdout is None or process.stderr is None:
        raise RuntimeError("Failed to create subprocess pipes for stdout/stderr")

    registry = get_registry()
    if tool_call_id:
        registry.register(tool_call_id, command, process)

    try:
        await asyncio.wait_for(
            asyncio.gather(
                _read_stream(process.stdout, stdout_cb),
                _read_stream(process.stderr, stderr_cb),
            ),
            timeout,
        )
        if should_stop and should_stop() and process.returncode is None:
            process.kill()
            await process.wait()
        return process.returncode if process.returncode is not None else await process.wait()
    except TimeoutError:
        process.kill()
        await process.wait()
        raise
    finally:
        if tool_call_id:
            registry.unregister(tool_call_id)
