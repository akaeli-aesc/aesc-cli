from __future__ import annotations

import importlib
import inspect
import string
from pathlib import Path
from typing import Any, NamedTuple, get_type_hints

from aesc.agentspec import ResolvedAgentSpec, load_agent_spec
from aesc.config import Config
from aesc.provider import CallableTool, CallableTool2, Toolset
from aesc.session import Session
from aesc.soul.approval import Approval
from aesc.soul.denwarenji import DenwaRenji
from aesc.soul.runtime import BuiltinSystemPromptArgs, Runtime
from aesc.soul.toolset import CustomToolset
from aesc.tools import SkipThisTool
from aesc.utils.logging import logger


class Agent(NamedTuple):
    """The loaded agent."""

    name: str
    system_prompt: str
    toolset: Toolset


async def load_agent(
    agent_file: Path,
    runtime: Runtime,
    *,
    mcp_configs: list[dict[str, Any]],
    extra_exclude_tools: list[str] | None = None,
) -> Agent:
    """
    Load agent from specification file.

    Raises:
        FileNotFoundError: If the agent spec file does not exist.
        AgentSpecError: If the agent spec is not valid.
    """
    logger.info("Loading agent: {agent_file}", agent_file=agent_file)
    agent_spec = load_agent_spec(agent_file)

    system_prompt = _load_system_prompt(
        agent_spec.system_prompt_path,
        agent_spec.system_prompt_args,
        runtime.builtin_args,
    )

    tool_deps = {
        ResolvedAgentSpec: agent_spec,
        Runtime: runtime,
        Config: runtime.config,
        BuiltinSystemPromptArgs: runtime.builtin_args,
        Session: runtime.session,
        DenwaRenji: runtime.denwa_renji,
        Approval: runtime.approval,
    }
    tools = agent_spec.tools
    # Merge spec-defined exclusions with CLI-provided exclusions
    all_excluded = list(agent_spec.exclude_tools)
    if extra_exclude_tools:
        all_excluded.extend(extra_exclude_tools)
    if all_excluded:
        logger.debug("Excluding tools: {tools}", tools=all_excluded)
        tools = [tool for tool in tools if tool not in all_excluded]
    toolset = CustomToolset()
    bad_tools = _load_tools(toolset, tools, tool_deps)
    if bad_tools:
        raise ValueError(f"Invalid tools: {bad_tools}")

    assert isinstance(toolset, CustomToolset)
    if mcp_configs:
        await _load_mcp_tools(toolset, mcp_configs)

    return Agent(
        name=agent_spec.name,
        system_prompt=system_prompt,
        toolset=toolset,
    )


def _load_system_prompt(
    path: Path, args: dict[str, str], builtin_args: BuiltinSystemPromptArgs
) -> str:
    logger.info("Loading system prompt: {path}", path=path)
    system_prompt = path.read_text(encoding="utf-8").strip()
    logger.debug(
        "Substituting system prompt with builtin args: {builtin_args}, spec args: {spec_args}",
        builtin_args=builtin_args,
        spec_args=args,
    )
    return string.Template(system_prompt).substitute(builtin_args._asdict(), **args)


type ToolType = CallableTool | CallableTool2[Any]


def _load_tools(
    toolset: CustomToolset,
    tool_paths: list[str],
    dependencies: dict[type[Any], Any],
) -> list[str]:
    bad_tools: list[str] = []
    for tool_path in tool_paths:
        try:
            tool = _load_tool(tool_path, dependencies)
        except SkipThisTool:
            logger.info("Skipping tool: {tool_path}", tool_path=tool_path)
            continue
        if tool:
            toolset += tool
        else:
            bad_tools.append(tool_path)
    logger.info("Loaded tools: {tools}", tools=[tool.name for tool in toolset.tools])
    if bad_tools:
        logger.error("Bad tools: {bad_tools}", bad_tools=bad_tools)
    return bad_tools


def _load_tool(tool_path: str, dependencies: dict[type[Any], Any]) -> ToolType | None:
    logger.debug("Loading tool: {tool_path}", tool_path=tool_path)
    module_name, class_name = tool_path.rsplit(":", 1)
    try:
        module = importlib.import_module(module_name)
    except ImportError:
        return None
    cls = getattr(module, class_name, None)
    if cls is None:
        return None

    # Use get_type_hints to resolve string annotations (PEP 563)
    # This properly handles `from __future__ import annotations`
    try:
        type_hints = get_type_hints(cls.__init__)
    except Exception:
        # Fallback for classes without proper __init__ annotations
        type_hints = {}

    args: list[Any] = []
    for param in inspect.signature(cls).parameters.values():
        if param.kind == inspect.Parameter.KEYWORD_ONLY:
            # once we encounter a keyword-only parameter, we stop injecting dependencies
            break
        if param.name == "self":
            continue
        # Use resolved type hint if available, otherwise fall back to annotation
        annotation = type_hints.get(param.name, param.annotation)
        # Check if this is an injectable dependency
        if annotation in dependencies:
            args.append(dependencies[annotation])
        elif param.default is not inspect.Parameter.empty:
            # Parameter has a default value, stop injecting - remaining params use defaults
            break
        else:
            # Required parameter without a dependency - error
            raise ValueError(f"Tool dependency not found: {annotation}")
    return cls(*args)


async def _load_mcp_tools(
    toolset: CustomToolset,
    mcp_configs: list[dict[str, Any]],
):
    """
    Raises:
        ValueError: If the MCP config is not valid.
        RuntimeError: If the MCP server cannot be connected.
    """
    import fastmcp

    from aesc.tools.mcp import MCPTool

    for mcp_config in mcp_configs:
        logger.info("Loading MCP tools from: {mcp_config}", mcp_config=mcp_config)
        client = fastmcp.Client(mcp_config)
        async with client:
            for tool in await client.list_tools():
                toolset += MCPTool(tool, client)
    return toolset
