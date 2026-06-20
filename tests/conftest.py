"""Test configuration and fixtures."""

from __future__ import annotations

import platform
import tempfile
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr

from aesc.agentspec import DEFAULT_AGENT_FILE, ResolvedAgentSpec, load_agent_spec
from aesc.config import Config, MoonshotSearchConfig, get_default_config
from aesc.llm import LLM
from aesc.provider.base import ChatProvider, StreamedMessage  # Use base provider
from aesc.session import Session
from aesc.soul import _current_wire
from aesc.soul.approval import Approval
from aesc.soul.denwarenji import DenwaRenji
from aesc.soul.runtime import BuiltinSystemPromptArgs, Runtime
from aesc.tools.bash import Bash
from aesc.tools.dmail import SendDMail
from aesc.tools.file.glob import Glob
from aesc.tools.file.grep import Grep
from aesc.tools.file.patch import PatchFile
from aesc.tools.file.read import ReadFile
from aesc.tools.file.replace import StrReplaceFile
from aesc.tools.file.write import WriteFile
from aesc.tools.task import Task
from aesc.tools.think import Think
from aesc.tools.todo import SetTodoList
from aesc.tools.web.fetch import FetchURL
from aesc.tools.web.search import SearchWeb
from aesc.wire import Wire


class MockChatProvider(ChatProvider):
    """Simple mock chat provider for testing."""

    def __init__(self, responses: list[str] | None = None):
        self.responses = responses or ["Mock response"]
        self.call_count = 0

    @property
    def model_name(self) -> str:
        return "mock-model"

    async def generate(
        self,
        system_prompt: str,
        tools: Any = None,
        history: Any = None,
    ) -> StreamedMessage:
        """Return a mock streamed message."""
        raise NotImplementedError("MockChatProvider.generate not implemented for tests")

    def with_thinking(self, effort: Any) -> MockChatProvider:
        """Return self (no-op for mock)."""
        return self


@pytest.fixture
def config() -> Config:
    """Create a Config instance."""
    conf = get_default_config()
    conf.services.moonshot_search = MoonshotSearchConfig(
        base_url="https://api.kimi.com/coding/v1/search",
        api_key=SecretStr("test-api-key"),
    )
    return conf


@pytest.fixture
def llm() -> LLM:
    """Create a LLM instance."""
    return LLM(
        chat_provider=MockChatProvider([]),
        max_context_size=100_000,
        capabilities=set(),
    )


@pytest.fixture
def temp_work_dir() -> Generator[Path]:
    """Create a temporary working directory for tests."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def temp_share_dir() -> Generator[Path]:
    """Create a temporary shared directory for tests."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def builtin_args(temp_work_dir: Path) -> BuiltinSystemPromptArgs:
    """Create builtin arguments with temporary work directory."""
    # Create a results directory for tests
    results_dir = temp_work_dir / "results"
    results_dir.mkdir(parents=True, exist_ok=True)

    return BuiltinSystemPromptArgs(
        AESC_NOW="1970-01-01T00:00:00+00:00",
        AESC_WORK_DIR=temp_work_dir,
        AESC_WORK_DIR_LS="Test ls content",
        AESC_RESULTS_DIR=results_dir,
        AESC_SESSION_ID="test-session-id",
    )


@pytest.fixture
def denwa_renji() -> DenwaRenji:
    """Create a DenwaRenji instance."""
    return DenwaRenji()


@pytest.fixture
def session(temp_work_dir: Path, temp_share_dir: Path) -> Session:
    """Create a Session instance."""
    # Create session results directory
    results_dir = temp_work_dir / "results"
    results_dir.mkdir(parents=True, exist_ok=True)

    return Session(
        id="test",
        work_dir=temp_work_dir,
        history_file=temp_share_dir / "history.jsonl",
        results_dir=results_dir,
    )


@pytest.fixture
def approval() -> Approval:
    """Create a Approval instance."""
    return Approval(yolo=True)


@pytest.fixture
def runtime(
    config: Config,
    llm: LLM,
    builtin_args: BuiltinSystemPromptArgs,
    denwa_renji: DenwaRenji,
    session: Session,
    approval: Approval,
) -> Runtime:
    """Create a Runtime instance."""
    return Runtime(
        config=config,
        llm=llm,
        builtin_args=builtin_args,
        denwa_renji=denwa_renji,
        session=session,
        approval=approval,
    )


@pytest.fixture
def agent_spec() -> ResolvedAgentSpec:
    """Create a AgentSpec instance."""
    return load_agent_spec(DEFAULT_AGENT_FILE)


@contextmanager
def tool_call_context(tool_name: str) -> Generator[None]:
    """Create a tool call context."""
    from aesc.provider.message import ToolCall  # Updated import
    from aesc.soul.toolset import current_tool_call

    # Create a simple tool call for testing
    tool_call = ToolCall(id="test", function={"name": tool_name, "arguments": "{}"})

    token = current_tool_call.set(tool_call)
    try:
        yield
    finally:
        current_tool_call.reset(token)


@contextmanager
def wire_context() -> Generator[Wire]:
    """Create a wire context for testing tools that send wire messages."""
    wire = Wire()
    token = _current_wire.set(wire)
    try:
        yield wire
    finally:
        _current_wire.reset(token)
        wire.shutdown()


@pytest.fixture
def task_tool(agent_spec: ResolvedAgentSpec, runtime: Runtime) -> Task:
    """Create a Task tool instance."""
    return Task(agent_spec, runtime)


@pytest.fixture
def send_dmail_tool(denwa_renji: DenwaRenji) -> SendDMail:
    """Create a SendDMail tool instance."""
    return SendDMail(denwa_renji)


@pytest.fixture
def think_tool() -> Think:
    """Create a Think tool instance."""
    return Think()


@pytest.fixture
def set_todo_list_tool() -> SetTodoList:
    """Create a SetTodoList tool instance."""
    return SetTodoList()


@pytest.fixture
def bash_tool(approval: Approval) -> Generator[Bash]:
    """Create a Bash tool instance with wire context for streaming output."""
    with wire_context(), tool_call_context("Bash"):
        yield Bash(approval)


@pytest.fixture
def read_file_tool(builtin_args: BuiltinSystemPromptArgs) -> ReadFile:
    """Create a ReadFile tool instance."""
    return ReadFile(builtin_args)


@pytest.fixture
def glob_tool(builtin_args: BuiltinSystemPromptArgs) -> Glob:
    """Create a Glob tool instance."""
    return Glob(builtin_args)


@pytest.fixture
def grep_tool() -> Grep:
    """Create a Grep tool instance."""
    return Grep()


@pytest.fixture
def write_file_tool(
    builtin_args: BuiltinSystemPromptArgs, approval: Approval
) -> Generator[WriteFile]:
    """Create a WriteFile tool instance."""
    with tool_call_context("WriteFile"):
        yield WriteFile(builtin_args, approval)


@pytest.fixture
def str_replace_file_tool(
    builtin_args: BuiltinSystemPromptArgs, approval: Approval
) -> Generator[StrReplaceFile]:
    """Create a StrReplaceFile tool instance."""
    with tool_call_context("StrReplaceFile"):
        yield StrReplaceFile(builtin_args, approval)


@pytest.fixture
def patch_file_tool(
    builtin_args: BuiltinSystemPromptArgs, approval: Approval
) -> Generator[PatchFile]:
    """Create a PatchFile tool instance."""
    with tool_call_context("PatchFile"):
        yield PatchFile(builtin_args, approval)


@pytest.fixture
def search_web_tool(config: Config, approval: Approval) -> Generator[SearchWeb]:
    """Create a SearchWeb tool instance."""
    with tool_call_context("SearchWeb"):
        yield SearchWeb(config, approval)


@pytest.fixture
def fetch_url_tool(approval: Approval) -> Generator[FetchURL]:
    """Create a FetchURL tool instance."""
    with tool_call_context("FetchURL"):
        yield FetchURL(approval)


# misc fixtures


@pytest.fixture
def outside_file() -> Path:
    """Return a path to a file outside the working directory."""
    if platform.system() == "Windows":
        return Path("C:/outside_file.txt")
    else:
        return Path("/outside_file.txt")
