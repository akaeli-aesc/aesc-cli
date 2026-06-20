"""
LLM configuration and factory.

This module creates LLM instances using the new aesc.provider module.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, cast, get_args

from pydantic import SecretStr

from aesc.constant import USER_AGENT
from aesc.provider import (
    AnthropicProvider,
    ChaosConfig,
    ChaosProvider,
    ChatProvider,
    LiteLLMProvider,
    OpenAIProvider,
    VertexNativeProvider,
)

if TYPE_CHECKING:
    from aesc.config import LLMModel, LLMProvider

type ProviderType = Literal[
    "kimi", "openai_legacy", "openai_responses", "anthropic", "litellm", "vertex_native", "_chaos"
]

type ModelCapability = Literal["image_in", "thinking"]
ALL_MODEL_CAPABILITIES: set[ModelCapability] = set(get_args(ModelCapability))


@dataclass(slots=True)
class LLM:
    chat_provider: ChatProvider
    max_context_size: int
    capabilities: set[ModelCapability]

    @property
    def model_name(self) -> str:
        return self.chat_provider.model_name


def augment_provider_with_env_vars(provider: LLMProvider, model: LLMModel) -> dict[str, str]:
    """Override provider/model settings from environment variables.

    Returns:
        Mapping of environment variables that were applied.
    """
    applied: dict[str, str] = {}

    match provider.type:
        case "kimi":
            if base_url := os.getenv("AESC_BASE_URL"):
                provider.base_url = base_url
                applied["AESC_BASE_URL"] = base_url
            if api_key := os.getenv("AESC_API_KEY"):
                provider.api_key = SecretStr(api_key)
                applied["AESC_API_KEY"] = "******"
            if model_name := os.getenv("AESC_MODEL_NAME"):
                model.model = model_name
                applied["AESC_MODEL_NAME"] = model_name
            if max_context_size := os.getenv("AESC_MODEL_MAX_CONTEXT_SIZE"):
                model.max_context_size = int(max_context_size)
                applied["AESC_MODEL_MAX_CONTEXT_SIZE"] = max_context_size
            if capabilities := os.getenv("AESC_MODEL_CAPABILITIES"):
                caps_lower = (cap.strip().lower() for cap in capabilities.split(",") if cap.strip())
                model.capabilities = set(
                    cast(ModelCapability, cap)
                    for cap in caps_lower
                    if cap in get_args(ModelCapability)
                )
                applied["AESC_MODEL_CAPABILITIES"] = capabilities
        case "openai_legacy" | "openai_responses":
            if base_url := os.getenv("OPENAI_BASE_URL"):
                provider.base_url = base_url
                applied["OPENAI_BASE_URL"] = base_url
            if api_key := os.getenv("OPENAI_API_KEY"):
                provider.api_key = SecretStr(api_key)
                applied["OPENAI_API_KEY"] = "******"
            if model_name := os.getenv("AESC_MODEL_NAME"):
                model.model = model_name
                applied["AESC_MODEL_NAME"] = model_name
            if max_context_size := os.getenv("AESC_MODEL_MAX_CONTEXT_SIZE"):
                model.max_context_size = int(max_context_size)
                applied["AESC_MODEL_MAX_CONTEXT_SIZE"] = max_context_size
        case "anthropic":
            if base_url := os.getenv("ANTHROPIC_BASE_URL"):
                provider.base_url = base_url
                applied["ANTHROPIC_BASE_URL"] = base_url
            if api_key := os.getenv("ANTHROPIC_API_KEY"):
                provider.api_key = SecretStr(api_key)
                applied["ANTHROPIC_API_KEY"] = "******"
            if model_name := os.getenv("AESC_MODEL_NAME"):
                model.model = model_name
                applied["AESC_MODEL_NAME"] = model_name
            if max_context_size := os.getenv("AESC_MODEL_MAX_CONTEXT_SIZE"):
                model.max_context_size = int(max_context_size)
                applied["AESC_MODEL_MAX_CONTEXT_SIZE"] = max_context_size
        case "litellm":
            if base_url := os.getenv("AESC_BASE_URL"):
                provider.base_url = base_url
                applied["AESC_BASE_URL"] = base_url
            if api_key := os.getenv("AESC_API_KEY"):
                provider.api_key = SecretStr(api_key)
                applied["AESC_API_KEY"] = "******"
            if model_name := os.getenv("AESC_MODEL_NAME"):
                model.model = model_name
                applied["AESC_MODEL_NAME"] = model_name
            if max_context_size := os.getenv("AESC_MODEL_MAX_CONTEXT_SIZE"):
                model.max_context_size = int(max_context_size)
                applied["AESC_MODEL_MAX_CONTEXT_SIZE"] = max_context_size
            if capabilities := os.getenv("AESC_MODEL_CAPABILITIES"):
                caps_lower = (cap.strip().lower() for cap in capabilities.split(",") if cap.strip())
                model.capabilities = set(
                    cast(ModelCapability, cap)
                    for cap in caps_lower
                    if cap in get_args(ModelCapability)
                )
                applied["AESC_MODEL_CAPABILITIES"] = capabilities
        case "vertex_native":
            # Vertex Native uses GCP credentials, no API key needed
            if model_name := os.getenv("AESC_MODEL_NAME"):
                model.model = model_name
                applied["AESC_MODEL_NAME"] = model_name
            if max_context_size := os.getenv("AESC_MODEL_MAX_CONTEXT_SIZE"):
                model.max_context_size = int(max_context_size)
                applied["AESC_MODEL_MAX_CONTEXT_SIZE"] = max_context_size
            if project_id := os.getenv("VERTEXAI_PROJECT"):
                applied["VERTEXAI_PROJECT"] = project_id
            if location := os.getenv("VERTEXAI_LOCATION"):
                applied["VERTEXAI_LOCATION"] = location

    return applied


def create_llm(
    provider: LLMProvider,
    model: LLMModel,
    *,
    stream: bool = True,
    session_id: str | None = None,
) -> LLM:
    """Create an LLM instance based on provider configuration."""
    chat_provider: ChatProvider

    match provider.type:
        case "kimi":
            # Kimi uses OpenAI-compatible API with custom headers
            chat_provider = OpenAIProvider(
                model=model.model,
                base_url=provider.base_url,
                api_key=provider.api_key.get_secret_value(),
                stream=stream,
                default_headers={
                    "User-Agent": USER_AGENT,
                    **(provider.custom_headers or {}),
                },
            )
        case "openai_legacy" | "openai_responses":
            # Use our new OpenAIProvider with Gemini 3 support
            chat_provider = OpenAIProvider(
                model=model.model,
                base_url=provider.base_url,
                api_key=provider.api_key.get_secret_value(),
                stream=stream,
            )
        case "anthropic":
            max_output_tokens = int(os.getenv("AESC_MAX_OUTPUT_TOKENS", "8000"))

            chat_provider = AnthropicProvider(
                model=model.model,
                base_url=provider.base_url,
                api_key=provider.api_key.get_secret_value(),
                stream=stream,
                default_max_tokens=max_output_tokens,
            )
        case "litellm":
            # LiteLLM provider - supports 100+ models
            chat_provider = LiteLLMProvider(
                model=model.model,
                api_key=provider.api_key.get_secret_value(),
                base_url=provider.base_url if provider.base_url else None,
                stream=stream,
            )
        case "vertex_native":
            # Native Vertex AI provider for Gemini 3 models
            project_id = os.getenv("VERTEXAI_PROJECT") or getattr(provider, "project_id", None)
            location = os.getenv("VERTEXAI_LOCATION", "global")
            chat_provider = VertexNativeProvider(
                model=model.model,
                project_id=project_id,
                location=location,
                stream=stream,
            )
        case "_chaos":
            chat_provider = ChaosProvider(
                model=model.model,
                base_url=provider.base_url,
                api_key=provider.api_key.get_secret_value(),
                chaos_config=ChaosConfig(
                    error_probability=0.8,
                    error_types=[429, 500, 503],
                ),
            )

    return LLM(
        chat_provider=chat_provider,
        max_context_size=model.max_context_size,
        capabilities=_derive_capabilities(provider, model),
    )


def _derive_capabilities(provider: LLMProvider, model: LLMModel) -> set[ModelCapability]:
    capabilities = model.capabilities or set()
    if provider.type != "kimi":
        return capabilities

    if model.model == "kimi-for-coding" or "thinking" in model.model:
        capabilities.add("thinking")
    return capabilities
