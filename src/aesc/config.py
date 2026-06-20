from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Self

from pydantic import BaseModel, Field, SecretStr, ValidationError, field_serializer, model_validator

from aesc.exception import ConfigError
from aesc.llm import ModelCapability, ProviderType
from aesc.share import get_share_dir
from aesc.utils.logging import logger


class LLMProvider(BaseModel):
    """LLM provider configuration."""

    type: ProviderType
    """Provider type"""
    base_url: str
    """API base URL"""
    api_key: SecretStr
    """API key"""
    custom_headers: dict[str, str] | None = None
    """Custom headers to include in API requests"""

    @field_serializer("api_key", when_used="json")
    def dump_secret(self, v: SecretStr):
        return v.get_secret_value()


class LLMModel(BaseModel):
    """LLM model configuration."""

    provider: str
    """Provider name"""
    model: str
    """Model name"""
    max_context_size: int
    """Maximum context size (unit: tokens)"""
    capabilities: set[ModelCapability] | None = None
    """Model capabilities"""


class LoopControl(BaseModel):
    """Agent loop control configuration."""

    max_steps_per_run: int = 100
    """Maximum number of steps in one run"""
    max_retries_per_step: int = 3
    """Maximum number of retries in one step"""


class MoonshotSearchConfig(BaseModel):
    """Moonshot Search configuration."""

    base_url: str
    """Base URL for Moonshot Search service."""
    api_key: SecretStr
    """API key for Moonshot Search service."""
    custom_headers: dict[str, str] | None = None
    """Custom headers to include in API requests."""

    @field_serializer("api_key", when_used="json")
    def dump_secret(self, v: SecretStr):
        return v.get_secret_value()


class Services(BaseModel):
    """Services configuration."""

    moonshot_search: MoonshotSearchConfig | None = None
    """Moonshot Search configuration."""


class Config(BaseModel):
    """Main configuration structure."""

    default_model: str = Field(default="", description="Default model to use")
    models: dict[str, LLMModel] = Field(default_factory=dict, description="List of LLM models")
    providers: dict[str, LLMProvider] = Field(
        default_factory=dict, description="List of LLM providers"
    )
    loop_control: LoopControl = Field(default_factory=LoopControl, description="Agent loop control")
    services: Services = Field(default_factory=Services, description="Services configuration")

    @model_validator(mode="after")
    def validate_model(self) -> Self:
        if self.default_model and self.default_model not in self.models:
            raise ValueError(f"Default model {self.default_model} not found in models")
        for model in self.models.values():
            if model.provider not in self.providers:
                raise ValueError(f"Provider {model.provider} not found in providers")
        return self


def get_config_file() -> Path:
    """Get the configuration file path."""
    return get_share_dir() / "config.json"


def get_default_config() -> Config:
    """Get the default configuration."""
    return Config(
        default_model="",
        models={},
        providers={},
        services=Services(),
    )


def _check_api_key_overrides(config: Config) -> None:
    """
    Check if environment variables override API keys in config and warn the user.

    This is important for security agents that may use multiple API keys for different services.
    Environment variables take precedence, which can lead to confusion if not expected.

    Args:
        config (Config): The loaded configuration object.
    """
    env_key_mappings = {
        "OPENAI_API_KEY": ["openai", "openai_legacy", "openai_responses"],
        "ANTHROPIC_API_KEY": ["anthropic", "claude"],
        "MOONSHOT_API_KEY": ["kimi", "moonshot"],
        "TOGETHER_API_KEY": ["together"],
        "DEEPSEEK_API_KEY": ["deepseek"],
        "GEMINI_API_KEY": ["gemini", "google"],
        "OLLAMA_API_KEY": ["ollama"],
    }

    for env_var, provider_names in env_key_mappings.items():
        env_value = os.getenv(env_var)
        if env_value:
            # Check if any of these providers are configured with an API key
            for provider_name in provider_names:
                if provider_name in config.providers:
                    provider = config.providers[provider_name]
                    config_key = provider.api_key.get_secret_value()
                    if config_key and config_key != env_value:
                        logger.warning(
                            "⚠️  Environment variable {env_var} is set and may override "
                            "the API key configured for provider '{provider}' in config file",
                            env_var=env_var,
                            provider=provider_name,
                        )

    # Check Moonshot Search API key
    if config.services.moonshot_search:
        env_search_key = os.getenv("MOONSHOT_SEARCH_API_KEY")
        if env_search_key:
            config_search_key = config.services.moonshot_search.api_key.get_secret_value()
            if config_search_key and config_search_key != env_search_key:
                logger.warning(
                    "⚠️  Environment variable MOONSHOT_SEARCH_API_KEY is set and may override "
                    "the API key configured for Moonshot Search in config file"
                )


def load_config(config_file: Path | None = None) -> Config:
    """
    Load configuration from config file.
    If the config file does not exist, create it with default configuration.

    Args:
        config_file (Path | None): Path to the configuration file. If None, use default path.

    Returns:
        Validated Config object.

    Raises:
        ConfigError: If the configuration file is invalid.
    """
    config_file = config_file or get_config_file()
    logger.debug("Loading config from file: {file}", file=config_file)

    # Allow loop controls to be overridden at runtime (useful for benchmarks/CI).
    # Semantics:
    # - AESC_MAX_STEPS_PER_RUN <= 0 disables the step limit.
    def _apply_loop_control_env_overrides(cfg: Config) -> None:
        raw = os.getenv("AESC_MAX_STEPS_PER_RUN")
        if raw is None or raw == "":
            return
        try:
            cfg.loop_control.max_steps_per_run = int(raw)
        except ValueError as e:
            raise ConfigError(f"Invalid AESC_MAX_STEPS_PER_RUN (expected int): {raw!r}") from e

    if not config_file.exists():
        config = get_default_config()
        logger.debug("No config file found, creating default config: {config}", config=config)
        with open(config_file, "w", encoding="utf-8") as f:
            f.write(config.model_dump_json(indent=2, exclude_none=True))
        _apply_loop_control_env_overrides(config)
        return config

    try:
        with open(config_file, encoding="utf-8") as f:
            data = json.load(f)
        config = Config(**data)

        # Check for environment variable overrides and warn the user
        _check_api_key_overrides(config)
        _apply_loop_control_env_overrides(config)

        return config
    except json.JSONDecodeError as e:
        raise ConfigError(f"Invalid JSON in configuration file: {e}") from e
    except ValidationError as e:
        raise ConfigError(f"Invalid configuration file: {e}") from e


def save_config(config: Config, config_file: Path | None = None):
    """
    Save configuration to config file.

    Args:
        config (Config): Config object to save.
        config_file (Path | None): Path to the configuration file. If None, use default path.
    """
    config_file = config_file or get_config_file()
    logger.debug("Saving config to file: {file}", file=config_file)
    with open(config_file, "w", encoding="utf-8") as f:
        f.write(config.model_dump_json(indent=2, exclude_none=True))
