from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import Awaitable, Callable
from typing import Any, Literal

import acp  # pyright: ignore[reportMissingTypeStubs]
from pydantic import ValidationError

from aesc.provider import ChatProviderError
from aesc.soul import LLMNotSet, LLMNotSupported, MaxStepsReached, RunCancelled, Soul, run_soul
from aesc.soul.aescsoul import AescSoul
from aesc.utils.logging import logger
from aesc.wire import WireUISide
from aesc.wire.message import (
    ApprovalRequest,
    ApprovalResponse,
    Event,
    serialize_approval_request,
    serialize_event,
)

from .jsonrpc import (
    JSONRPC_MESSAGE_ADAPTER,
    JSONRPC_VERSION,
    JSONRPCErrorResponse,
    JSONRPCRequest,
    JSONRPCSuccessResponse,
)

_ResultKind = Literal["ok", "error"]


class _SoulRunner:
    def __init__(
        self,
        soul: Soul,
        send_event: Callable[[Event], Awaitable[None]],
        request_approval: Callable[[ApprovalRequest], Awaitable[ApprovalResponse]],
    ):
        self._soul = soul
        self._send_event = send_event
        self._request_approval = request_approval
        self._cancel_event: asyncio.Event | None = None
        self._task: asyncio.Task[tuple[_ResultKind, Any]] | None = None

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def run(self, user_input: str) -> tuple[_ResultKind, Any]:
        if self.is_running:
            raise RuntimeError("Soul is already running")

        self._cancel_event = asyncio.Event()
        self._task = asyncio.create_task(self._run(user_input))
        try:
            return await self._task
        finally:
            self._task = None
            self._cancel_event = None

    async def interrupt(self) -> None:
        if self._cancel_event is not None:
            self._cancel_event.set()

    async def shutdown(self) -> None:
        await self.interrupt()
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
            self._cancel_event = None

    def _usage_payload(self) -> dict[str, Any]:
        """Extract token usage from the soul for inclusion in run results."""
        try:
            if hasattr(self._soul, "token_summary"):
                return self._soul.token_summary
        except Exception:
            pass
        return {}

    async def _run(self, user_input: str) -> tuple[_ResultKind, Any]:
        assert self._cancel_event is not None
        try:
            await run_soul(
                self._soul,
                user_input,
                self._ui_loop,
                self._cancel_event,
            )
        except LLMNotSet:
            return ("error", (-32001, "LLM is not configured"))
        except LLMNotSupported as e:
            return ("error", (-32003, f"LLM not supported: {e}"))
        except ChatProviderError as e:
            return ("error", (-32002, f"LLM provider error: {e}"))
        except MaxStepsReached as e:
            return (
                "ok",
                {"status": "max_steps_reached", "steps": e.n_steps, **self._usage_payload()},
            )
        except RunCancelled:
            return ("ok", {"status": "cancelled", **self._usage_payload()})
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.exception("Soul run failed:")
            return ("error", (-32099, f"Run failed: {e}"))
        return ("ok", {"status": "finished", **self._usage_payload()})

    async def _ui_loop(self, wire: WireUISide) -> None:
        while True:
            message = await wire.receive()
            if isinstance(message, ApprovalRequest):
                response = await self._request_approval(message)
                message.resolve(response)
            else:
                # must be Event
                await self._send_event(message)


class WireServer:
    def __init__(self, soul: Soul):
        self._soul = soul
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._write_task: asyncio.Task[None] | None = None
        self._send_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._pending_requests: dict[str, ApprovalRequest] = {}
        self._runner = _SoulRunner(
            soul,
            send_event=self._send_event,
            request_approval=self._request_approval,
        )

    async def run(self) -> bool:
        logger.info("Starting Wire server on stdio")

        self._reader, self._writer = await acp.stdio_streams()
        self._write_task = asyncio.create_task(self._write_loop())
        try:
            await self._read_loop()
        finally:
            await self._shutdown()

        return True

    async def _read_loop(self) -> None:
        assert self._reader is not None

        while True:
            line = await self._reader.readline()
            if not line:
                logger.info("stdin closed, Wire server exiting")
                break

            logger.debug("[Wire] Received line: {line}", line=line[:200])

            try:
                payload = json.loads(line.decode("utf-8"))
            except json.JSONDecodeError:
                logger.warning("Invalid JSON line: {line}", line=line)
                continue

            logger.debug("[Wire] Parsed payload: {payload}", payload=payload)
            await self._dispatch(payload)

    async def _dispatch(self, payload: dict[str, Any]) -> None:
        version = payload.get("jsonrpc")
        if version != JSONRPC_VERSION:
            logger.warning("Unexpected jsonrpc version: {version}", version=version)
            return

        try:
            message = JSONRPC_MESSAGE_ADAPTER.validate_python(payload)
            logger.debug("[Wire] Validated message type: {type}", type=type(message).__name__)
        except ValidationError as e:
            logger.warning(
                "Ignoring malformed JSON-RPC payload: {message}; error={error}",
                message=payload,
                error=str(e),
            )
            return

        match message:
            case JSONRPCRequest():
                logger.debug("[Wire] Dispatching request")
                await self._handle_request(message)
            case JSONRPCSuccessResponse() | JSONRPCErrorResponse():
                logger.debug("[Wire] Dispatching response")
                await self._handle_response(message)

    async def _handle_request(self, message: JSONRPCRequest) -> None:
        method = message.method
        msg_id = message.id
        params = message.params

        if method == "run":
            await self._handle_run(msg_id, params)
        elif method == "interrupt":
            await self._handle_interrupt(msg_id)
        elif method == "status":
            await self._handle_status(msg_id)
        elif method == "clear":
            await self._handle_clear(msg_id, params)
        elif method == "compact":
            await self._handle_compact(msg_id)
        else:
            logger.warning("Unknown method: {method}", method=method)
            if msg_id is not None:
                await self._send_error(msg_id, -32601, f"Unknown method: {method}")

    async def _handle_response(
        self,
        message: JSONRPCSuccessResponse | JSONRPCErrorResponse,
    ) -> None:
        msg_id = message.id
        logger.debug("[Wire] Handling response id={id}", id=msg_id)

        if msg_id is None:
            logger.warning("Response without id: {message}", message=message.model_dump())
            return

        pending = self._pending_requests.get(msg_id)
        if pending is None:
            logger.warning("No pending request for response id={id}", id=msg_id)
            logger.debug(
                "[Wire] Pending request ids: {ids}", ids=list(self._pending_requests.keys())
            )
            return

        logger.debug("[Wire] Found pending request for id={id}", id=msg_id)

        try:
            if isinstance(message, JSONRPCErrorResponse):
                logger.debug("[Wire] Rejecting approval due to error response")
                pending.resolve(ApprovalResponse.REJECT)
            else:
                response = self._parse_approval_response(message.result)
                logger.debug("[Wire] Parsed approval response: {response}", response=response)
                pending.resolve(response)
                logger.debug("[Wire] Resolved pending request with: {response}", response=response)
        finally:
            self._pending_requests.pop(msg_id, None)

    async def _handle_run(self, msg_id: Any, params: dict[str, Any]) -> None:
        if msg_id is None:
            logger.warning("Run notification ignored")
            return

        if self._runner.is_running:
            await self._send_error(msg_id, -32000, "Run already in progress")
            return

        user_input = params.get("input")
        if not isinstance(user_input, str):
            user_input = params.get("prompt")
        if not isinstance(user_input, str):
            await self._send_error(msg_id, -32602, "`input` (or `prompt`) must be a string")
            return

        # Run as background task to not block the read loop
        # The read loop MUST continue running to receive approval responses!
        async def run_and_respond():
            try:
                kind, payload = await self._runner.run(user_input)
                if kind == "error":
                    code, message = payload
                    await self._send_error(msg_id, code, message)
                else:
                    await self._send_response(msg_id, payload)
            except asyncio.CancelledError:
                # Task cancelled (shutdown) — still send response so frontend knows
                await self._send_response(msg_id, {"status": "cancelled"})
            except RuntimeError:
                await self._send_error(msg_id, -32000, "Run already in progress")
            except Exception as e:
                logger.exception("run_and_respond failed:")
                await self._send_error(msg_id, -32099, f"Run failed: {e}")

        asyncio.create_task(run_and_respond())

    async def _handle_interrupt(self, msg_id: Any) -> None:
        if not self._runner.is_running:
            if msg_id is not None:
                await self._send_response(msg_id, {"status": "idle"})
            return

        await self._runner.interrupt()
        if msg_id is not None:
            await self._send_response(msg_id, {"status": "ok"})

    async def _handle_status(self, msg_id: Any) -> None:
        """Handle status request - returns current agent state."""
        if msg_id is None:
            return

        status = self._soul.status
        result = {
            "running": self._runner.is_running,
            "model": self._soul.model_name,
            "context_usage": status.context_usage,
        }

        # Add AescSoul-specific info if available
        if isinstance(self._soul, AescSoul):
            result["session_id"] = self._soul._runtime.session.id
            result["work_dir"] = str(self._soul._runtime.session.work_dir)
            result["results_dir"] = str(self._soul._runtime.session.results_dir)
            result["n_checkpoints"] = self._soul.context.n_checkpoints
            result["token_count"] = self._soul.context.token_count
            result["thinking"] = self._soul.thinking

        await self._send_response(msg_id, result)

    async def _handle_clear(self, msg_id: Any, params: dict[str, Any]) -> None:
        """Handle clear request - revert context to a checkpoint."""
        if msg_id is None:
            return

        # Cannot clear while running
        if self._runner.is_running:
            await self._send_error(msg_id, -32004, "Cannot clear while agent is running")
            return

        # Only AescSoul supports clear
        if not isinstance(self._soul, AescSoul):
            await self._send_error(msg_id, -32005, "Soul does not support clear operation")
            return

        checkpoint_id = params.get("checkpoint", 0)
        if not isinstance(checkpoint_id, int) or checkpoint_id < 0:
            await self._send_error(msg_id, -32602, "checkpoint must be a non-negative integer")
            return

        try:
            await self._soul.context.revert_to(checkpoint_id)
            await self._send_response(
                msg_id,
                {
                    "status": "ok",
                    "checkpoint": checkpoint_id,
                    "n_checkpoints": self._soul.context.n_checkpoints,
                },
            )
        except ValueError as e:
            await self._send_error(msg_id, -32006, str(e))
        except Exception as e:
            logger.exception("Clear failed:")
            await self._send_error(msg_id, -32099, f"Clear failed: {e}")

    async def _handle_compact(self, msg_id: Any) -> None:
        """Handle compact request - compress context to reduce token usage."""
        if msg_id is None:
            return

        # Cannot compact while running
        if self._runner.is_running:
            await self._send_error(msg_id, -32004, "Cannot compact while agent is running")
            return

        # Only AescSoul supports compact
        if not isinstance(self._soul, AescSoul):
            await self._send_error(msg_id, -32005, "Soul does not support compact operation")
            return

        tokens_before = self._soul.context.token_count

        try:
            await self._soul.compact_context()
            tokens_after = self._soul.context.token_count
            await self._send_response(
                msg_id,
                {
                    "status": "ok",
                    "tokens_before": tokens_before,
                    "tokens_after": tokens_after,
                    "tokens_saved": tokens_before - tokens_after,
                },
            )
        except LLMNotSet:
            await self._send_error(msg_id, -32001, "LLM is not configured")
        except Exception as e:
            logger.exception("Compact failed:")
            await self._send_error(msg_id, -32099, f"Compact failed: {e}")

    async def _send_event(self, event: Event) -> None:
        await self._send_notification("event", serialize_event(event))

    async def _request_approval(self, request: ApprovalRequest) -> ApprovalResponse:
        self._pending_requests[request.id] = request

        await self._send_request(
            request.id,
            "request",
            {"type": "approval", "payload": serialize_approval_request(request)},
        )

        try:
            return await request.wait()
        finally:
            self._pending_requests.pop(request.id, None)

    def _parse_approval_response(self, result: dict[str, Any]) -> ApprovalResponse:
        value = result.get("response")
        try:
            if isinstance(value, ApprovalResponse):
                return value
            return ApprovalResponse(str(value))
        except ValueError:
            logger.warning("Unknown approval response: {value}", value=value)
            return ApprovalResponse.REJECT

    async def _write_loop(self) -> None:
        assert self._writer is not None

        try:
            while True:
                try:
                    payload = await self._send_queue.get()
                except asyncio.QueueShutDown:
                    logger.debug("Send queue shut down, stopping Wire server write loop")
                    break
                data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
                self._writer.write(data.encode("utf-8") + b"\n")
                await self._writer.drain()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Wire server write loop error:")
            raise

    async def _send_notification(self, method: str, params: Any) -> None:
        await self._enqueue_payload(
            {"jsonrpc": JSONRPC_VERSION, "method": method, "params": params}
        )

    async def _send_request(self, msg_id: Any, method: str, params: Any) -> None:
        await self._enqueue_payload(
            {"jsonrpc": JSONRPC_VERSION, "id": msg_id, "method": method, "params": params}
        )

    async def _send_response(self, msg_id: Any, result: Any) -> None:
        await self._enqueue_payload({"jsonrpc": JSONRPC_VERSION, "id": msg_id, "result": result})

    async def _send_error(self, msg_id: Any, code: int, message: str) -> None:
        await self._enqueue_payload(
            {"jsonrpc": JSONRPC_VERSION, "id": msg_id, "error": {"code": code, "message": message}}
        )

    async def _enqueue_payload(self, payload: dict[str, Any]) -> None:
        try:
            await self._send_queue.put(payload)
        except asyncio.QueueShutDown:
            logger.debug("Send queue shut down; dropping payload: {payload}", payload=payload)

    async def _shutdown(self) -> None:
        await self._runner.shutdown()
        self._send_queue.shutdown()

        if self._write_task is not None:
            with contextlib.suppress(asyncio.CancelledError):
                await self._write_task

        for request in self._pending_requests.values():
            if not request.resolved:
                request.resolve(ApprovalResponse.REJECT)
        self._pending_requests.clear()

        if self._writer is not None:
            self._writer.close()
            with contextlib.suppress(Exception):
                await self._writer.wait_closed()
            self._writer = None

        self._reader = None
