"""
Tool definitions and results.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from asyncio import Future
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol, Self, override, runtime_checkable

import jsonschema
import pydantic
from pydantic import BaseModel, model_validator
from pydantic.json_schema import GenerateJsonSchema

from aesc.provider.message import ContentPart, ToolCall

type ParametersType = dict[str, Any]
type JsonType = dict[str, Any] | list[Any] | str | int | float | bool | None


class Tool(BaseModel):
    """The definition of a tool that can be recognized by the model."""

    name: str
    """The name of the tool."""

    description: str
    """The description of the tool."""

    parameters: ParametersType
    """The parameters of the tool, in JSON Schema format."""

    @model_validator(mode="after")
    def _validate_parameters(self) -> Self:
        jsonschema.validate(self.parameters, jsonschema.Draft202012Validator.META_SCHEMA)
        return self


@dataclass(frozen=True, kw_only=True, slots=True)
class ToolOk:
    """The successful output returned by a tool."""

    output: str | ContentPart | Sequence[ContentPart]
    """The output content returned by the tool."""
    message: str = ""
    """An explanatory message to be given to the model."""
    brief: str = ""
    """A brief message to be shown to the user."""


@dataclass(frozen=True, kw_only=True, slots=True)
class ToolError:
    """The error returned by a tool. This is not an exception."""

    output: str | ContentPart | Sequence[ContentPart] = ""
    """The output content returned by the tool."""
    message: str
    """An error message to be given to the model."""
    brief: str
    """A brief message to be shown to the user."""


@dataclass(frozen=True, kw_only=True, slots=True)
class ToolValidateError(ToolError):
    """A validation error returned by a tool."""

    def __init__(self, message: str):
        object.__setattr__(self, "output", "")
        object.__setattr__(self, "message", message)
        object.__setattr__(self, "brief", "Validation error")


type ToolReturnType = ToolOk | ToolError
"""The return type of a callable tool."""


class _GenerateJsonSchemaNoTitles(GenerateJsonSchema):
    """Custom JSON schema generator that omits titles."""

    @override
    def field_title_should_be_set(self, schema) -> bool:  # pyright: ignore
        return False

    @override
    def _update_class_schema(self, json_schema, cls, config) -> None:  # pyright: ignore
        super()._update_class_schema(json_schema, cls, config)
        json_schema.pop("title", None)


class CallableTool(Tool, ABC):
    """
    Abstract base class for tools that can be called as callables.
    """

    @property
    def base(self) -> Tool:
        return self

    async def call(self, arguments: JsonType) -> ToolReturnType:
        try:
            jsonschema.validate(arguments, self.parameters)
        except jsonschema.ValidationError as e:
            return ToolValidateError(str(e))

        if isinstance(arguments, list):
            ret = await self.__call__(*arguments)
        elif isinstance(arguments, dict):
            ret = await self.__call__(**arguments)
        else:
            ret = await self.__call__(arguments)
        if not isinstance(ret, ToolOk | ToolError):
            ret = ToolError(
                message=f"Invalid return type: {type(ret)}",
                brief="Invalid return type",
            )
        return ret

    @abstractmethod
    async def __call__(self, *args: Any, **kwargs: Any) -> ToolReturnType:
        """The implementation of the callable tool."""
        ...


class CallableTool2[Params: BaseModel](BaseModel, ABC):
    """
    Abstract base class for tools with typed parameters.
    """

    name: str
    description: str
    params: type[Params]

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._base = Tool(
            name=self.name,
            description=self.description,
            parameters=self.params.model_json_schema(schema_generator=_GenerateJsonSchemaNoTitles),
        )

    @property
    def base(self) -> Tool:
        return self._base

    async def call(self, arguments: JsonType) -> ToolReturnType:
        try:
            params = self.params.model_validate(arguments)
        except pydantic.ValidationError as e:
            return ToolValidateError(str(e))

        ret = await self.__call__(params)
        if not isinstance(ret, ToolOk | ToolError):
            ret = ToolError(
                message=f"Invalid return type: {type(ret)}",
                brief="Invalid return type",
            )
        return ret

    @abstractmethod
    async def __call__(self, params: Params) -> ToolReturnType:
        """The implementation of the callable tool."""
        ...


@dataclass(frozen=True)
class ToolResult:
    """The result of a tool call."""

    tool_call_id: str
    """The ID of the tool call."""
    result: ToolReturnType
    """The actual return value of the tool call."""


ToolResultFuture = Future[ToolResult]
type HandleResult = ToolResultFuture | ToolResult


@runtime_checkable
class Toolset(Protocol):
    """Interface for toolsets that can register tools and handle tool calls."""

    @property
    def tools(self) -> list[Tool]:
        """The list of tool definitions registered in this toolset."""
        ...

    def handle(self, tool_call: ToolCall) -> HandleResult:
        """
        Handle a tool call.
        Returns the result or a future of the result.
        """
        ...


# Tool error types
class ToolNotFoundError(ToolError):
    """The tool was not found."""

    def __init__(self, tool_name: str):
        super().__init__(
            message=f"Tool `{tool_name}` not found",
            brief=f"Tool `{tool_name}` not found",
        )


class ToolParseError(ToolError):
    """The arguments of the tool are not valid JSON."""

    def __init__(self, message: str):
        super().__init__(
            message=f"Error parsing JSON arguments: {message}",
            brief="Invalid arguments",
        )


class ToolRuntimeError(ToolError):
    """The tool failed to run."""

    def __init__(self, message: str):
        super().__init__(
            message=f"Error running tool: {message}",
            brief="Tool runtime error",
        )


# Tool type alias
type ToolType = CallableTool | CallableTool2[Any]


class SimpleToolset(Toolset):
    """A simple toolset that can handle tool calls concurrently."""

    _tool_dict: dict[str, ToolType]

    def __init__(self, tools: Sequence[ToolType] | None = None):
        self._tool_dict = {}
        if tools:
            for tool in tools:
                self += tool

    def __iadd__(self, tool: ToolType) -> Self:
        """Add a tool to the toolset."""
        import inspect

        return_annotation = inspect.signature(tool.__call__).return_annotation
        if return_annotation is not ToolReturnType:
            raise TypeError(
                f"Expected tool `{tool.name}` to return `ToolReturnType`, "
                f"but got `{return_annotation}`"
            )
        self._tool_dict[tool.name] = tool
        return self

    def __add__(self, tool: ToolType) -> SimpleToolset:
        """Return a new toolset with the given tool added."""
        new_toolset = SimpleToolset()
        new_toolset._tool_dict = self._tool_dict.copy()
        new_toolset += tool
        return new_toolset

    @property
    def tools(self) -> list[Tool]:
        return [tool.base for tool in self._tool_dict.values()]

    def handle(self, tool_call: ToolCall) -> HandleResult:
        import asyncio
        import json

        if tool_call.function.name not in self._tool_dict:
            return ToolResult(
                tool_call.id,
                ToolNotFoundError(tool_call.function.name),
            )

        tool = self._tool_dict[tool_call.function.name]

        try:
            arguments: JsonType = json.loads(tool_call.function.arguments or "{}")
        except json.JSONDecodeError as e:
            return ToolResult(tool_call.id, ToolParseError(str(e)))

        async def _call():
            try:
                ret = await tool.call(arguments)
                return ToolResult(tool_call.id, ret)
            except Exception as e:
                return ToolResult(tool_call.id, ToolRuntimeError(str(e)))

        return asyncio.create_task(_call())
