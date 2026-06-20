"""
AESC Provider - Custom LLM abstraction layer.

This module provides a streamlined, Gemini 3-compatible implementation for LLM interactions.

Key features:
- Full Gemini 3 thought_signature support for function calling
- OpenAI-compatible API support
- Native Anthropic and Chaos providers

Example:
    from aesc.provider import step, StepResult, Message, OpenAIProvider

    provider = OpenAIProvider(
        model="gemini-3-flash-preview",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        api_key="..."
    )

    result = await step(
        provider.with_thinking("high"),
        system_prompt="You are a helpful assistant.",
        toolset=my_toolset,
        history=[Message(role="user", content="Hello")],
    )
"""

# Base types
from aesc.provider.anthropic_provider import AnthropicProvider
from aesc.provider.base import ChatProvider, StreamedMessage, ThinkingEffort
from aesc.provider.chaos_provider import ChaosConfig, ChaosProvider

# Errors
from aesc.provider.errors import (
    APIConnectionError,
    APIEmptyResponseError,
    APIStatusError,
    APITimeoutError,
    ChatProviderError,
)
from aesc.provider.litellm_provider import LiteLLMProvider

# Messages
from aesc.provider.message import (
    AudioURLPart,
    ContentPart,
    ImageURLPart,
    MergeableMixin,
    Message,
    StreamedMessagePart,
    TextPart,
    ThinkPart,
    ToolCall,
    ToolCallPart,
)

# Providers
from aesc.provider.openai_provider import OpenAIProvider

# Step and generate
from aesc.provider.step import (
    GenerateResult,
    StepResult,
    generate,
    step,
)

# Tools
from aesc.provider.tool import (
    CallableTool,
    CallableTool2,
    HandleResult,
    JsonType,
    SimpleToolset,
    Tool,
    ToolError,
    ToolNotFoundError,
    ToolOk,
    ToolParseError,
    ToolResult,
    ToolResultFuture,
    ToolReturnType,
    ToolRuntimeError,
    Toolset,
    ToolType,
    ToolValidateError,
)

# Usage
from aesc.provider.usage import TokenUsage
from aesc.provider.vertex_native import VertexNativeProvider

__all__ = [
    # Base
    "ChatProvider",
    "StreamedMessage",
    "ThinkingEffort",
    # Messages
    "MergeableMixin",
    "ContentPart",
    "TextPart",
    "ThinkPart",
    "ImageURLPart",
    "AudioURLPart",
    "ToolCall",
    "ToolCallPart",
    "StreamedMessagePart",
    "Message",
    # Tools
    "Tool",
    "ToolOk",
    "ToolError",
    "ToolValidateError",
    "ToolNotFoundError",
    "ToolParseError",
    "ToolRuntimeError",
    "ToolReturnType",
    "ToolResult",
    "ToolResultFuture",
    "HandleResult",
    "Toolset",
    "CallableTool",
    "CallableTool2",
    "SimpleToolset",
    "ToolType",
    "JsonType",
    # Errors
    "ChatProviderError",
    "APIStatusError",
    "APIConnectionError",
    "APITimeoutError",
    "APIEmptyResponseError",
    # Usage
    "TokenUsage",
    # Providers
    "OpenAIProvider",
    "AnthropicProvider",
    "ChaosProvider",
    "ChaosConfig",
    "LiteLLMProvider",
    "VertexNativeProvider",
    # Step
    "step",
    "StepResult",
    "generate",
    "GenerateResult",
]
