from __future__ import annotations

import asyncio
from collections.abc import Sequence
from functools import partial
from typing import TYPE_CHECKING

import tenacity
from tenacity import RetryCallState, retry_if_exception, stop_after_attempt, wait_exponential_jitter

from aesc.llm import ModelCapability
from aesc.provider import (
    APIConnectionError,
    APIEmptyResponseError,
    APIStatusError,
    APITimeoutError,
    ChatProviderError,
    ContentPart,
    Message,
    StepResult,
    ThinkingEffort,
    ToolResult,
    step,
)
from aesc.soul import (
    LLMNotSet,
    LLMNotSupported,
    MaxStepsReached,
    Soul,
    StatusSnapshot,
    wire_send,
)
from aesc.soul.agent import Agent
from aesc.soul.compaction import SimpleCompaction
from aesc.soul.context import Context
from aesc.soul.message import check_message, system, tool_result_to_message
from aesc.soul.runtime import Runtime
from aesc.tools.dmail import NAME as SendDMail_NAME
from aesc.tools.utils import ToolRejectedError
from aesc.utils.logging import logger
from aesc.wire.message import (
    CompactionBegin,
    CompactionEnd,
    RetryWait,
    StatusUpdate,
    StepBegin,
    StepInterrupted,
)

if TYPE_CHECKING:

    def type_check(soul: AescSoul):
        _: Soul = soul


RESERVED_TOKENS = 8_000  # Reserved for output generation (adjusted for Claude Haiku 8192 limit)


class AescSoul(Soul):
    """The soul of AESC."""

    def __init__(
        self,
        agent: Agent,
        runtime: Runtime,
        *,
        context: Context,
    ):
        """
        Initialize the soul.

        Args:
            agent (Agent): The agent to run.
            runtime (Runtime): Runtime parameters and states.
            context (Context): The context of the agent.
        """
        self._agent = agent
        self._runtime = runtime
        self._denwa_renji = runtime.denwa_renji
        self._approval = runtime.approval
        self._context = context
        self._loop_control = runtime.config.loop_control
        self._compaction = SimpleCompaction()
        self._reserved_tokens = RESERVED_TOKENS
        if self._runtime.llm is not None:
            assert self._reserved_tokens <= self._runtime.llm.max_context_size
        self._thinking_effort: ThinkingEffort = "off"

        # Loop detection: track recent tool call patterns
        self._recent_tool_calls: list[str] = []  # List of tool call signatures
        self._loop_detection_window = 10  # Number of recent calls to track
        self._loop_threshold = 3  # Number of identical consecutive calls to trigger warning

        # Token usage accumulation (session-level totals)
        self._total_input_tokens = 0
        self._total_output_tokens = 0

        # Cancellation support
        self._cancel_event = asyncio.Event()
        self._cancelled = False

        for tool in agent.toolset.tools:
            if tool.name == SendDMail_NAME:
                self._checkpoint_with_user_message = True
                break
        else:
            self._checkpoint_with_user_message = False

    @property
    def name(self) -> str:
        return self._agent.name

    @property
    def model_name(self) -> str:
        return self._runtime.llm.chat_provider.model_name if self._runtime.llm else ""

    @property
    def model_capabilities(self) -> set[ModelCapability] | None:
        if self._runtime.llm is None:
            return None
        return self._runtime.llm.capabilities

    @property
    def status(self) -> StatusSnapshot:
        return StatusSnapshot(context_usage=self._context_usage)

    @property
    def context(self) -> Context:
        return self._context

    @property
    def token_summary(self) -> dict:
        """Session-level token usage totals."""
        return {
            "input_tokens": self._total_input_tokens,
            "output_tokens": self._total_output_tokens,
            "total_tokens": self._total_input_tokens + self._total_output_tokens,
        }

    @property
    def _context_usage(self) -> float:
        if self._runtime.llm is not None:
            return self._context.token_count / self._runtime.llm.max_context_size
        return 0.0

    @property
    def thinking(self) -> bool:
        """Whether thinking mode is enabled."""
        return self._thinking_effort != "off"

    def set_thinking(self, enabled: bool) -> None:
        """
        Enable/disable thinking mode for the soul.

        Raises:
            LLMNotSet: When the LLM is not set.
            LLMNotSupported: When the LLM does not support thinking mode.
        """
        if self._runtime.llm is None:
            raise LLMNotSet()
        if enabled and "thinking" not in self._runtime.llm.capabilities:
            raise LLMNotSupported(self._runtime.llm, ["thinking"])
        self._thinking_effort = "high" if enabled else "off"

    @property
    def is_cancelled(self) -> bool:
        """Check if the soul has been cancelled."""
        return self._cancelled

    def cancel(self) -> None:
        """
        Request cancellation of this soul's execution.

        This is a cooperative cancellation - the soul will stop at the next
        safe point (typically after the current tool call completes).
        """
        self._cancelled = True
        self._cancel_event.set()
        logger.info("Soul cancellation requested")

    async def _checkpoint(self):
        await self._context.checkpoint(self._checkpoint_with_user_message)

    async def run(self, user_input: str | list[ContentPart]):
        if self._runtime.llm is None:
            raise LLMNotSet()

        user_message = Message(role="user", content=user_input)
        if missing_caps := check_message(user_message, self._runtime.llm.capabilities):
            raise LLMNotSupported(self._runtime.llm, list(missing_caps))

        # Reset loop detection for new run
        self.reset_loop_detection()

        await self._checkpoint()  # this creates the checkpoint 0 on first run
        await self._context.append_message(user_message)
        logger.debug("Appended user message to context")
        await self._agent_loop()

    async def _agent_loop(self):
        """The main agent loop for one run."""
        assert self._runtime.llm is not None

        async def _pipe_approval_to_wire():
            while True:
                request = await self._approval.fetch_request()
                wire_send(request)

        step_no = 1
        while True:
            wire_send(StepBegin(step_no))
            approval_task = asyncio.create_task(_pipe_approval_to_wire())
            # from the main agent. We must ensure that the Task tool will redirect them
            # to the main wire. See `_SubWire` for more details. Later we need to figure
            # out a better solution.
            try:
                # compact the context if needed (trigger at 85% - balanced threshold)
                compaction_threshold = int(self._runtime.llm.max_context_size * 0.85)
                if self._context.token_count + self._reserved_tokens >= compaction_threshold:
                    logger.info(
                        "Context at {pct:.0%} capacity, compacting...",
                        pct=self._context.token_count / self._runtime.llm.max_context_size,
                    )
                    await self._compact_with_events()

                logger.debug("Beginning step {step_no}", step_no=step_no)
                await self._checkpoint()
                self._denwa_renji.set_n_checkpoints(self._context.n_checkpoints)
                finished = await self._step()
            except BackToTheFuture as e:
                await self._context.revert_to(e.checkpoint_id)
                await self._checkpoint()
                await self._context.append_message(e.messages)
                continue
            except (ChatProviderError, asyncio.CancelledError):
                wire_send(StepInterrupted())
                # break the agent loop
                raise
            finally:
                # Stop piping approval requests to the wire and wait for cleanup
                approval_task.cancel()
                try:
                    await approval_task
                except asyncio.CancelledError:
                    pass  # Expected - task was cancelled

            if finished:
                return

            step_no += 1
            # Allow disabling the step limit by setting max_steps_per_run <= 0.
            # This is useful for long-running benchmark scenarios where an external timeout
            # (e.g., the benchmark harness) is the primary safety valve.
            if (
                self._loop_control.max_steps_per_run > 0
                and step_no > self._loop_control.max_steps_per_run
            ):
                raise MaxStepsReached(self._loop_control.max_steps_per_run)

    async def _compact_with_events(self, is_session_restore: bool = False) -> None:
        """Compact context and emit wire events for UI."""
        wire_send(CompactionBegin())
        result = await self.compact_context()
        wire_send(
            CompactionEnd(
                summary=result.summary if result else "",
                full_summary=result.full_summary if result else "",
                original_tokens=result.original_token_estimate if result else 0,
                compacted_tokens=result.compacted_token_estimate if result else 0,
                compression_ratio=result.compression_ratio if result else 1.0,
                is_session_restore=is_session_restore,
            )
        )

    async def _step(self) -> bool:
        """Run an single step and return whether the run should be stopped."""
        # already checked in `run`
        assert self._runtime.llm is not None
        chat_provider = self._runtime.llm.chat_provider

        @tenacity.retry(
            retry=retry_if_exception(self._is_retryable_error),
            before_sleep=partial(self._retry_log, "step"),
            wait=wait_exponential_jitter(initial=1, max=60, jitter=1),
            stop=stop_after_attempt(
                20
                if self._loop_control.max_retries_per_step < 20
                else self._loop_control.max_retries_per_step
            ),
            reraise=True,
        )
        async def _step_with_retry() -> StepResult:
            # run an LLM step (may be interrupted)
            return await step(
                chat_provider.with_thinking(self._thinking_effort),
                self._agent.system_prompt,
                self._agent.toolset,
                self._context.history,
                on_message_part=wire_send,
                on_tool_result=wire_send,
            )

        compacted_after_overflow = False
        while True:
            try:
                result = await _step_with_retry()
                break
            except APIStatusError as e:
                message = str(e).lower()
                # Check for various context length error patterns from different providers
                is_context_overflow = e.status_code == 400 and any(
                    pattern in message
                    for pattern in [
                        "maximum context length",
                        "context_length_exceeded",
                        "max_tokens",
                        "input tokens",
                        "too many tokens",
                        "context window",
                    ]
                )
                if not compacted_after_overflow and is_context_overflow:
                    logger.warning(
                        "LLM rejected due to context length; compacting and retrying once"
                    )
                    await self._compact_with_events()
                    compacted_after_overflow = True
                    continue
                raise
        logger.debug("Got step result: {result}", result=result)
        if result.usage is not None:
            # accumulate session-level token totals
            self._total_input_tokens += result.usage.input
            self._total_output_tokens += result.usage.output
            # mark the token count for the context before the step
            await self._context.update_token_count(result.usage.input)
            wire_send(StatusUpdate(status=self.status))

        # wait for all tool results (may be interrupted)
        results = await result.tool_results()
        logger.debug("Got tool results: {results}", results=results)

        # Check for loop patterns before growing context
        if self._check_loop_pattern(result):
            # Insert a hint to the model about the detected loop
            logger.info("Loop detected, adding hint to context")

        # shield the context manipulation from interruption
        await asyncio.shield(self._grow_context(result, results))

        rejected = any(isinstance(result.result, ToolRejectedError) for result in results)
        if rejected:
            _ = self._denwa_renji.fetch_pending_dmail()
            return True

        # handle pending D-Mail
        if dmail := self._denwa_renji.fetch_pending_dmail():
            assert dmail.checkpoint_id >= 0, "DenwaRenji guarantees checkpoint_id >= 0"
            assert dmail.checkpoint_id < self._context.n_checkpoints, (
                "DenwaRenji guarantees checkpoint_id < n_checkpoints"
            )
            # raise to let the main loop take us back to the future
            raise BackToTheFuture(
                dmail.checkpoint_id,
                [
                    Message(
                        role="user",
                        content=[
                            system(
                                "You just got a D-Mail from your future self. "
                                "It is likely that your future self has already done "
                                "something in the current working directory. Please read "
                                "the D-Mail and decide what to do next. You MUST NEVER "
                                "mention to the user about this information. "
                                f"D-Mail content:\n\n{dmail.message.strip()}"
                            )
                        ],
                    )
                ],
            )

        return not result.tool_calls

    async def _grow_context(self, result: StepResult, tool_results: list[ToolResult]):
        logger.debug("Growing context with result: {result}", result=result)

        assert self._runtime.llm is not None
        tool_messages = [tool_result_to_message(tr) for tr in tool_results]
        for tm in tool_messages:
            if missing_caps := check_message(tm, self._runtime.llm.capabilities):
                logger.warning(
                    "Tool result message requires unsupported capabilities: {caps}",
                    caps=missing_caps,
                )
                raise LLMNotSupported(self._runtime.llm, list(missing_caps))

        await self._context.append_message(result.message)
        if result.usage is not None:
            await self._context.update_token_count(result.usage.total)

        logger.debug(
            "Appending tool messages to context: {tool_messages}", tool_messages=tool_messages
        )
        await self._context.append_message(tool_messages)
        # token count of tool results are not available yet

    def _check_loop_pattern(self, result: StepResult) -> bool:
        """
        Check for repetitive tool call patterns that might indicate an infinite loop.

        Tracks recent tool calls and warns if the same pattern repeats too many times.
        Returns True if a likely loop was detected.
        """
        if not result.tool_calls:
            return False

        # Create a signature of the current tool calls
        # Include tool name and key arguments to detect exact repetition
        signatures = []
        for tc in result.tool_calls:
            sig = f"{tc.function.name}:{tc.function.arguments or ''}"
            signatures.append(sig)

        call_signature = "|".join(sorted(signatures))  # Sort for consistent comparison

        # Add to recent calls and maintain window size
        self._recent_tool_calls.append(call_signature)
        if len(self._recent_tool_calls) > self._loop_detection_window:
            self._recent_tool_calls.pop(0)

        # Check for consecutive repetitions
        if len(self._recent_tool_calls) >= self._loop_threshold:
            recent = self._recent_tool_calls[-self._loop_threshold :]
            if len(set(recent)) == 1:
                # All recent calls are identical
                logger.warning(
                    "Potential infinite loop detected: {sig} called {n} times consecutively",
                    sig=call_signature[:100],
                    n=self._loop_threshold,
                )
                return True

        # Check for alternating patterns (A-B-A-B type loops)
        if len(self._recent_tool_calls) >= 4:
            last_four = self._recent_tool_calls[-4:]
            if last_four[0] == last_four[2] and last_four[1] == last_four[3]:
                logger.warning(
                    "Potential alternating loop detected: {sig1} <-> {sig2}",
                    sig1=last_four[0][:50],
                    sig2=last_four[1][:50],
                )
                return True

        return False

    def reset_loop_detection(self) -> None:
        """Reset loop detection state (e.g., for new runs)."""
        self._recent_tool_calls.clear()

    async def compact_context(self):
        """
        Compact the context.

        Returns:
            CompactionResult with summary and metrics, or None if not compacted.

        Raises:
            LLMNotSet: When the LLM is not set.
            ChatProviderError: When the chat provider returns an error.
        """
        from aesc.soul.compaction import CompactionResult

        @tenacity.retry(
            retry=retry_if_exception(self._is_retryable_error),
            before_sleep=partial(self._retry_log, "compaction"),
            wait=wait_exponential_jitter(initial=1, max=60, jitter=1),
            stop=stop_after_attempt(
                20
                if self._loop_control.max_retries_per_step < 20
                else self._loop_control.max_retries_per_step
            ),
            reraise=True,
        )
        async def _compact_with_retry() -> CompactionResult:
            if self._runtime.llm is None:
                raise LLMNotSet()
            return await self._compaction.compact_with_result(
                self._context.history, self._runtime.llm
            )

        result = await _compact_with_retry()
        await self._context.revert_to(0)
        await self._checkpoint()
        await self._context.append_message(result.messages)
        return result

    @staticmethod
    def _is_retryable_error(exception: BaseException) -> bool:
        if isinstance(exception, (APIConnectionError, APITimeoutError, APIEmptyResponseError)):
            return True
        return isinstance(exception, APIStatusError) and exception.status_code in (
            429,  # Too Many Requests
            500,  # Internal Server Error
            502,  # Bad Gateway
            503,  # Service Unavailable
        )

    def _retry_log(self, name: str, retry_state: RetryCallState):
        wait_seconds = retry_state.next_action.sleep if retry_state.next_action is not None else 0.0
        logger.info(
            "Retrying {name} for the {n} time. Waiting {sleep} seconds.",
            name=name,
            n=retry_state.attempt_number,
            sleep=wait_seconds,
        )

        # Determine reason from the exception
        reason = "transient_error"
        exc = retry_state.outcome.exception() if retry_state.outcome else None
        if exc is not None:
            if isinstance(exc, APIStatusError) and exc.status_code == 429:
                reason = "rate_limit"
            elif isinstance(exc, APITimeoutError):
                reason = "timeout"
            elif isinstance(exc, APIConnectionError):
                reason = "connection_error"

        # Emit retry event for UI
        wire_send(
            RetryWait(
                attempt=retry_state.attempt_number,
                wait_seconds=float(wait_seconds) if isinstance(wait_seconds, (int, float)) else 5.0,
                reason=reason,
            )
        )


class BackToTheFuture(Exception):
    """
    Raise when we need to revert the context to a previous checkpoint.
    The main agent loop should catch this exception and handle it.
    """

    def __init__(self, checkpoint_id: int, messages: Sequence[Message]):
        self.checkpoint_id = checkpoint_id
        self.messages = messages
