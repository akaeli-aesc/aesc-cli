"""Tests for agent loading functionality."""

from __future__ import annotations

import tempfile
from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest

from aesc.config import Config
from aesc.session import Session
from aesc.soul.agent import _load_system_prompt, _load_tools, load_agent
from aesc.soul.approval import Approval
from aesc.soul.denwarenji import DenwaRenji
from aesc.soul.runtime import BuiltinSystemPromptArgs, Runtime
from aesc.soul.toolset import CustomToolset


def test_load_system_prompt(system_prompt_file: Path, builtin_args: BuiltinSystemPromptArgs):
    """Test loading system prompt with template substitution."""
    prompt = _load_system_prompt(system_prompt_file, {"CUSTOM_ARG": "test_value"}, builtin_args)

    assert "Test system prompt with " in prompt
    assert "1970-01-01" in prompt  # Should contain the actual timestamp
    assert builtin_args.AESC_NOW in prompt
    assert "test_value" in prompt


def test_load_tools_valid(runtime: Runtime):
    """Test loading valid tools."""
    tool_paths = ["aesc.tools.think:Think", "aesc.tools.bash:Bash"]
    toolset = CustomToolset()
    bad_tools = _load_tools(
        toolset,
        tool_paths,
        {
            Runtime: runtime,
            Config: runtime.config,
            BuiltinSystemPromptArgs: runtime.builtin_args,
            Session: runtime.session,
            DenwaRenji: runtime.denwa_renji,
            Approval: runtime.approval,
        },
    )

    assert len(bad_tools) == 0
    assert toolset is not None


def test_load_tools_invalid(runtime: Runtime):
    """Test loading with invalid tool paths."""
    tool_paths = ["aesc.tools.nonexistent:Tool", "aesc.tools.think:Think"]
    toolset = CustomToolset()
    bad_tools = _load_tools(
        toolset,
        tool_paths,
        {
            Runtime: runtime,
            Config: runtime.config,
            BuiltinSystemPromptArgs: runtime.builtin_args,
            Session: runtime.session,
            DenwaRenji: runtime.denwa_renji,
            Approval: runtime.approval,
        },
    )

    assert len(bad_tools) == 1
    assert "aesc.tools.nonexistent:Tool" in bad_tools


@pytest.mark.asyncio
async def test_load_agent_invalid_tools(agent_file_invalid_tools: Path, runtime: Runtime):
    """Test loading agent with invalid tools raises ValueError."""
    with pytest.raises(ValueError, match="Invalid tools"):
        await load_agent(agent_file_invalid_tools, runtime, mcp_configs=[])


@pytest.fixture
def agent_file_invalid_tools() -> Generator[Path, Any, Any]:
    """Create an agent configuration file with invalid tools."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # Create system.md
        system_md = tmpdir / "system.md"
        system_md.write_text("You are a test agent")

        # Create agent.yaml with invalid tools
        agent_yaml = tmpdir / "agent.yaml"
        agent_yaml.write_text("""
version: 1
agent:
  name: "Test Agent"
  system_prompt_path: ./system.md
  tools: ["aesc.tools.nonexistent:Tool"]
""")

        yield agent_yaml


@pytest.fixture
def system_prompt_file() -> Generator[Path, Any, Any]:
    """Create a system prompt file with template variables."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        system_md = tmpdir / "system.md"
        system_md.write_text("Test system prompt with ${AESC_NOW} and ${CUSTOM_ARG}")

        yield system_md
