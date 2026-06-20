import asyncio
from pathlib import Path
from typing import Any, override

from loguru import logger
from pydantic import BaseModel, Field

from aesc.agentspec import ResolvedAgentSpec, SubagentSpec
from aesc.provider import CallableTool2, TextPart, ToolError, ToolOk, ToolReturnType
from aesc.soul import MaxStepsReached, get_wire_or_none, run_soul
from aesc.soul.aescsoul import AescSoul
from aesc.soul.agent import Agent, load_agent
from aesc.soul.context import Context
from aesc.soul.runtime import Runtime
from aesc.soul.subagent_registry import get_registry
from aesc.soul.toolset import get_current_tool_call_or_none
from aesc.tools.utils import load_desc
from aesc.utils.message import message_extract_text
from aesc.utils.path import next_available_rotation
from aesc.wire import WireUISide
from aesc.wire.message import ApprovalRequest, SubagentEvent, WireMessage

# Maximum continuation attempts for task summary
MAX_CONTINUE_ATTEMPTS = 1

# Cap concurrent subagent executions to prevent API quota exhaustion.
# When the LLM issues 4+ Task calls in parallel, this limits how many
# actually run simultaneously (the rest queue).
MAX_CONCURRENT_SUBAGENTS = 3
_subagent_semaphore: asyncio.Semaphore | None = None


def _get_subagent_semaphore() -> asyncio.Semaphore:
    """Lazily initialise subagent concurrency semaphore."""
    global _subagent_semaphore
    if _subagent_semaphore is None:
        _subagent_semaphore = asyncio.Semaphore(MAX_CONCURRENT_SUBAGENTS)
    return _subagent_semaphore


def _clean_subagent_error(e: Exception) -> str:
    """Convert a subagent exception into a clean, user-facing message."""
    raw = str(e).lower()
    if any(kw in raw for kw in ("429", "rate limit", "resource_exhausted", "quota")):
        return "Rate limited — API quota exhausted"
    if any(kw in raw for kw in ("401", "403", "unauthorized", "forbidden")):
        return "Auth error — check API credentials"
    if "timeout" in raw:
        return "Request timed out"
    if "connection" in raw:
        return "Connection error — check network"
    if any(kw in raw for kw in ("safety", "block", "refuse", "cannot")):
        return "Model refused — safety filter triggered"
    # Generic: strip raw bodies, keep first 120 chars
    msg = str(e)
    for marker in (" - b'{", ' - b"', "\n{", '\n"error"'):
        if marker in msg:
            msg = msg[: msg.index(marker)]
            break
    if len(msg) > 120:
        msg = msg[:120] + "..."
    return msg.strip()


CONTINUE_PROMPT = """
Your previous response was too brief. Please provide a more comprehensive summary that includes:

1. Specific technical details and implementations
2. Complete code examples if relevant
3. Detailed findings and analysis
4. All important information that should be aware of by the caller
""".strip()


class Params(BaseModel):
    description: str = Field(description="A short (3-5 word) description of the task")
    subagent_name: str = Field(
        description="The name of the specialized subagent to use for this task"
    )
    prompt: str = Field(
        description=(
            "The task for the subagent to perform. "
            "You must provide a detailed prompt with all necessary background information "
            "because the subagent cannot see anything in your context."
        )
    )


class Task(CallableTool2[Params]):
    name: str = "Task"
    params: type[Params] = Params

    def __init__(self, agent_spec: ResolvedAgentSpec, runtime: Runtime, **kwargs: Any):
        super().__init__(
            description=load_desc(
                Path(__file__).parent / "task.md",
                {
                    "SUBAGENTS_MD": "\n".join(
                        f"- `{name}`: {spec.description}"
                        for name, spec in agent_spec.subagents.items()
                    ),
                },
            ),
            **kwargs,
        )

        self._runtime = runtime
        self._session = runtime.session
        self._subagents: dict[str, Agent] = {}

        try:
            loop = asyncio.get_running_loop()
            self._load_task = loop.create_task(self._load_subagents(agent_spec.subagents))
        except RuntimeError:
            # In case there's no running event loop, e.g., during synchronous tests
            self._load_task = None
            asyncio.run(self._load_subagents(agent_spec.subagents))

    async def _load_subagents(self, subagent_specs: dict[str, SubagentSpec]) -> None:
        """Load all subagents specified in the agent spec."""
        for name, spec in subagent_specs.items():
            agent = await load_agent(spec.path, self._runtime, mcp_configs=[])
            self._subagents[name] = agent

    async def _get_subagent_history_file(self) -> Path:
        """Generate a unique history file path for subagent."""
        main_history_file = self._session.history_file
        subagent_base_name = f"{main_history_file.stem}_sub"
        main_history_file.parent.mkdir(parents=True, exist_ok=True)  # just in case
        sub_history_file = await next_available_rotation(
            main_history_file.parent / f"{subagent_base_name}{main_history_file.suffix}"
        )
        assert sub_history_file is not None
        return sub_history_file

    async def _get_findings_summary(self) -> str:
        """Get summary of current findings for context injection."""
        try:
            results_dir = self._session.results_dir / "findings"
            if not results_dir.exists():
                return ""

            findings = []
            for finding_file in sorted(results_dir.glob("*.json"))[-10:]:  # Last 10
                try:
                    import json

                    data = json.loads(finding_file.read_text())
                    severity = data.get("severity", "info").upper()
                    title = data.get("title", "Unknown")
                    target = data.get("target", "")
                    findings.append(f"- [{severity}] {title}" + (f" ({target})" if target else ""))
                except Exception:
                    continue

            if not findings:
                return ""

            return "## Current Findings\n" + "\n".join(findings) + "\n"
        except Exception:
            return ""

    def _build_enhanced_prompt(self, original_prompt: str, agent_name: str) -> str:
        """Build enhanced prompt with context injection."""
        # Run synchronously since we need it in async context
        import asyncio

        try:
            loop = asyncio.get_running_loop()
            findings = loop.run_until_complete(self._get_findings_summary())
        except RuntimeError:
            findings = ""

        if not findings:
            return original_prompt

        return f"""{findings}
## Task
{original_prompt}
"""

    @override
    async def __call__(self, params: Params) -> ToolReturnType:
        # Wait for subagents to load
        if self._load_task is not None:
            try:
                await self._load_task
            except Exception as e:
                return ToolError(
                    message=f"Failed to load subagents: {e}",
                    brief="Subagent loading failed",
                )
            finally:
                self._load_task = None

        if params.subagent_name not in self._subagents:
            available = ", ".join(self._subagents.keys()) if self._subagents else "none"
            return ToolError(
                message=f"Subagent '{params.subagent_name}' not found. Available: {available}",
                brief=f"Unknown subagent: {params.subagent_name}",
            )
        agent = self._subagents[params.subagent_name]

        # Limit concurrent subagent executions to avoid API quota exhaustion
        sem = _get_subagent_semaphore()
        logger.debug(
            "Subagent '{}' waiting for slot ({}/{} in use)",
            params.subagent_name,
            MAX_CONCURRENT_SUBAGENTS - sem._value,
            MAX_CONCURRENT_SUBAGENTS,
        )
        async with sem:
            return await self._execute_subagent(agent, params)

    async def _execute_subagent(self, agent: Agent, params: Params) -> ToolReturnType:
        """Run a subagent with error handling."""
        try:
            # Inject findings context into prompt
            findings_summary = await self._get_findings_summary()
            if findings_summary:
                enhanced_prompt = f"{findings_summary}\n## Task\n{params.prompt}"
            else:
                enhanced_prompt = params.prompt

            result = await self._run_subagent(agent, enhanced_prompt, params.subagent_name)
            return result
        except AssertionError as e:
            # Wire/context assertions - running outside proper execution context
            return ToolError(
                message=f"Task tool requires proper execution context: {e}",
                brief="Execution context error",
            )
        except OSError as e:
            # File I/O errors (history file creation, etc.)
            return ToolError(
                message=f"File operation failed: {e}",
                brief="File I/O error",
            )
        except asyncio.CancelledError:
            return ToolError(
                message="Subagent task was cancelled",
                brief="Task cancelled",
            )
        except Exception as e:
            logger.exception(f"Subagent failed: {e}")
            clean_msg = _clean_subagent_error(e)
            return ToolError(message=clean_msg, brief=clean_msg[:60])

    async def _run_subagent(
        self, agent: Agent, prompt: str, agent_name: str = "unknown"
    ) -> ToolReturnType:
        """Run subagent with optional continuation for task summary."""
        super_wire = get_wire_or_none()
        assert super_wire is not None
        current_tool_call = get_current_tool_call_or_none()
        assert current_tool_call is not None
        current_tool_call_id = current_tool_call.id

        # Get registry for tracking
        registry = get_registry()

        def _super_wire_send(msg: WireMessage) -> None:
            if isinstance(msg, ApprovalRequest):
                super_wire.soul_side.send(msg)
                return

            # Also store in registry for UI access
            registry.append_event(current_tool_call_id, msg)

            event = SubagentEvent(
                task_tool_call_id=current_tool_call_id,
                event=msg,
            )
            super_wire.soul_side.send(event)

        async def _ui_loop_fn(wire: WireUISide) -> None:
            while True:
                msg = await wire.receive()
                _super_wire_send(msg)

        # Send launch notification so UI shows feedback during cold start
        launch_event = SubagentEvent(
            task_tool_call_id=current_tool_call_id,
            event=TextPart(text=f"[Launching {agent_name}]"),
        )
        super_wire.soul_side.send(launch_event)

        subagent_history_file = await self._get_subagent_history_file()
        context = Context(file_backend=subagent_history_file)
        soul = AescSoul(agent, runtime=self._runtime, context=context)

        # Register subagent session
        session = await registry.register(
            task_tool_call_id=current_tool_call_id,
            agent_name=agent_name,
            prompt=prompt,
            soul=soul,
        )

        try:
            await run_soul(soul, prompt, _ui_loop_fn, asyncio.Event())
            session.mark_completed()
        except MaxStepsReached as e:
            session.mark_failed(f"Max steps {e.n_steps} reached")
            return ToolError(
                message=(
                    f"Max steps {e.n_steps} reached when running subagent. "
                    "Please try splitting the task into smaller subtasks."
                ),
                brief="Max steps reached",
            )
        except Exception as e:
            session.mark_failed(str(e))
            raise

        # Check if the subagent context is valid
        if len(context.history) == 0:
            session.mark_failed("No response")
            return ToolError(
                message="Subagent produced no response. The LLM may have failed or returned empty.",
                brief="No response from subagent",
            )

        if context.history[-1].role != "assistant":
            last_role = context.history[-1].role
            session.mark_failed(f"Invalid response (last: {last_role})")
            return ToolError(
                message=f"Subagent ended with '{last_role}' message instead of assistant response.",
                brief=f"Invalid response (last: {last_role})",
            )

        final_response = message_extract_text(context.history[-1])

        # Check if response is too brief, if so, run again with continuation prompt
        n_attempts_remaining = MAX_CONTINUE_ATTEMPTS
        if len(final_response) < 200 and n_attempts_remaining > 0:
            await run_soul(soul, CONTINUE_PROMPT, _ui_loop_fn, asyncio.Event())

            if len(context.history) == 0:
                session.mark_failed("Continuation failed")
                return ToolError(
                    message="Subagent continuation produced no response.",
                    brief="Continuation failed",
                )
            if context.history[-1].role != "assistant":
                session.mark_failed("Continuation incomplete")
                return ToolError(
                    message="Subagent continuation ended without assistant response.",
                    brief="Continuation incomplete",
                )
            final_response = message_extract_text(context.history[-1])

        session.result = (
            final_response[:200] + "..." if len(final_response) > 200 else final_response
        )
        return ToolOk(output=final_response)
