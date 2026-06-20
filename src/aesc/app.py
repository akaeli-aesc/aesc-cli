from __future__ import annotations

import contextlib
import os
import warnings
from collections.abc import Generator
from pathlib import Path
from typing import Any

from pydantic import SecretStr

from aesc.agentspec import DEFAULT_AGENT_FILE
from aesc.cli import InputFormat, OutputFormat
from aesc.config import LLMModel, LLMProvider, load_config
from aesc.exception import ConfigError
from aesc.llm import augment_provider_with_env_vars, create_llm
from aesc.session import Session
from aesc.soul import LLMNotSet, LLMNotSupported
from aesc.soul.aescsoul import AescSoul
from aesc.soul.agent import load_agent
from aesc.soul.context import Context
from aesc.soul.runtime import Runtime
from aesc.utils.logging import StreamToLogger, logger


class AescCLI:
    @staticmethod
    async def create(
        session: Session,
        *,
        yolo: bool = False,
        stream: bool = True,
        mcp_configs: list[dict[str, Any]] | None = None,
        config_file: Path | None = None,
        model_name: str | None = None,
        thinking: bool = False,
        agent_file: Path | None = None,
        exclude_tools: list[str] | None = None,
    ) -> AescCLI:
        """
        Create an AescCLI instance.

        Args:
            session (Session): A session created by `Session.create` or `Session.continue_`.
            yolo (bool, optional): Approve all actions without confirmation. Defaults to False.
            stream (bool, optional): Use stream mode when calling LLM API. Defaults to True.
            config_file (Path | None, optional): Path to the configuration file. Defaults to None.
            model_name (str | None, optional): Name of the model to use. Defaults to None.
            agent_file (Path | None, optional): Path to the agent file. Defaults to None.

        Raises:
            FileNotFoundError: When the agent file is not found.
            ConfigError(AescCLIException): When the configuration is invalid.
            AgentSpecError(AescCLIException): When the agent specification is invalid.
        """
        config = load_config(config_file)
        logger.info("Loaded config: {config}", config=config)

        model: LLMModel | None = None
        provider: LLMProvider | None = None

        # try to use config file
        if not model_name and config.default_model:
            # no --model specified && default model is set in config
            model = config.models[config.default_model]
            provider = config.providers[model.provider]
        if model_name and model_name in config.models:
            # --model specified && model is set in config
            model = config.models[model_name]
            provider = config.providers[model.provider]

        if not model:
            model = LLMModel(provider="", model="", max_context_size=200_000)
            # Auto-detect provider from environment
            import os

            # Check for explicit model override first (critical for benchmarks)
            explicit_model = os.getenv("AESC_MODEL_NAME")

            # Vertex AI detection — accept the vertex_ai/ prefix from either the
            # -m flag (model_name) or AESC_MODEL_NAME, matching Bedrock's behavior.
            vertex_project = os.getenv("VERTEX_PROJECT") or os.getenv("VERTEXAI_PROJECT")
            vertex_model = next(
                (m for m in (model_name, explicit_model) if m and m.startswith("vertex_ai/")),
                None,
            )
            is_vertex_model = vertex_model is not None

            # Bedrock detection — model_name or AESC_MODEL_NAME starts with bedrock/
            is_bedrock_model = (model_name and model_name.startswith("bedrock/")) or (
                explicit_model and explicit_model.startswith("bedrock/")
            )

            if is_bedrock_model and os.getenv("AWS_ACCESS_KEY_ID"):
                # AWS Bedrock via LiteLLM — uses boto3 credentials from env vars
                model.model = model_name or explicit_model
                model.max_context_size = 200_000
                provider = LLMProvider(
                    type="litellm",
                    base_url="",  # boto3 handles endpoints
                    api_key=SecretStr(""),  # Uses AWS credentials
                )
            elif vertex_project and is_vertex_model:
                # Vertex AI via LiteLLM - uses GCP credentials (gcloud auth)
                model.model = vertex_model  # Full LiteLLM model string (from -m or env)
                model.max_context_size = 1_000_000  # Gemini models have 1M context
                provider = LLMProvider(
                    type="litellm",
                    base_url="",  # Not needed for Vertex AI
                    api_key=SecretStr(""),  # Uses GCP credentials
                )
            elif os.getenv("ANTHROPIC_API_KEY"):
                # Auto-select Claude Sonnet 4 (fast, efficient, great for security work)
                model.model = explicit_model or "claude-sonnet-4-20250514"
                provider = LLMProvider(
                    type="anthropic",
                    base_url="https://api.anthropic.com",  # SDK auto-appends /v1
                    api_key=SecretStr(""),
                )
            elif os.getenv("OPENAI_API_KEY"):
                # Check if this is for Gemini (via OpenAI-compatible API)
                custom_base_url = os.getenv("OPENAI_BASE_URL", "")
                is_gemini = "generativelanguage.googleapis.com" in custom_base_url
                is_official_openai = not custom_base_url or "api.openai.com" in custom_base_url

                if is_gemini and explicit_model:
                    # Gemini via OpenAI-compatible API
                    model.model = explicit_model
                    provider = LLMProvider(
                        type="openai_legacy",  # Use legacy for Gemini compatibility
                        base_url=custom_base_url,
                        api_key=SecretStr(""),
                    )
                else:
                    # Standard OpenAI or custom endpoint
                    model.model = explicit_model or "gpt-4o"
                    provider = LLMProvider(
                        type="openai_responses" if is_official_openai else "openai_legacy",
                        base_url=custom_base_url or "https://api.openai.com/v1",
                        api_key=SecretStr(""),
                    )
            else:
                provider = LLMProvider(type="kimi", base_url="", api_key=SecretStr(""))

        # try overwrite with environment variables
        if provider is None or model is None:
            raise ConfigError(
                "No LLM provider configured. Run /setup or set environment variables "
                "(ANTHROPIC_API_KEY, OPENAI_API_KEY, or AESC_API_KEY)"
            )
        env_overrides = augment_provider_with_env_vars(provider, model)

        # LiteLLM and vertex_native providers don't require base_url
        needs_base_url = provider.type not in ("litellm", "vertex_native")
        if (needs_base_url and not provider.base_url) or not model.model:
            llm = None
        else:
            logger.info("Using LLM provider: {provider}", provider=provider)
            logger.info("Using LLM model: {model}", model=model)
            llm = create_llm(provider, model, stream=stream, session_id=session.id)

        runtime = await Runtime.create(config, llm, session, yolo)

        if agent_file is None:
            agent_file = DEFAULT_AGENT_FILE
        agent = await load_agent(
            agent_file,
            runtime,
            mcp_configs=mcp_configs or [],
            extra_exclude_tools=exclude_tools,
        )

        context = Context(session.history_file)
        await context.restore()

        soul = AescSoul(
            agent,
            runtime,
            context=context,
        )
        try:
            soul.set_thinking(thinking)
        except (LLMNotSet, LLMNotSupported) as e:
            logger.warning("Failed to enable thinking mode: {error}", error=e)
        return AescCLI(soul, runtime, env_overrides)

    def __init__(
        self,
        _soul: AescSoul,
        _runtime: Runtime,
        _env_overrides: dict[str, str],
    ) -> None:
        self._soul = _soul
        self._runtime = _runtime
        self._env_overrides = _env_overrides

    @property
    def soul(self) -> AescSoul:
        """Get the AescSoul instance."""
        return self._soul

    @property
    def session(self) -> Session:
        """Get the Session instance."""
        return self._runtime.session

    @contextlib.contextmanager
    def _app_env(self) -> Generator[None]:
        original_cwd = Path.cwd()
        os.chdir(self._runtime.session.work_dir)
        try:
            # to ignore possible warnings from dateparser
            warnings.filterwarnings("ignore", category=DeprecationWarning)
            with contextlib.redirect_stderr(StreamToLogger()):
                yield
        finally:
            os.chdir(original_cwd)

    async def run_shell_mode(self, command: str | None = None) -> bool:
        from aesc.ui.shell import ShellApp, WelcomeInfoItem

        welcome_info = [
            WelcomeInfoItem(name="Directory", value=str(self._runtime.session.work_dir)),
            WelcomeInfoItem(name="Session", value=self._runtime.session.id),
        ]
        if base_url := self._env_overrides.get("AESC_BASE_URL"):
            welcome_info.append(
                WelcomeInfoItem(
                    name="API URL",
                    value=f"{base_url} (from AESC_BASE_URL)",
                    level=WelcomeInfoItem.Level.WARN,
                )
            )
        if not self._runtime.llm:
            welcome_info.append(
                WelcomeInfoItem(
                    name="Model",
                    value="not set, send /setup to configure",
                    level=WelcomeInfoItem.Level.WARN,
                )
            )
        elif "AESC_MODEL_NAME" in self._env_overrides:
            welcome_info.append(
                WelcomeInfoItem(
                    name="Model",
                    value=f"{self._soul.model_name} (from AESC_MODEL_NAME)",
                    level=WelcomeInfoItem.Level.WARN,
                )
            )
        else:
            welcome_info.append(
                WelcomeInfoItem(
                    name="Model",
                    value=self._soul.model_name,
                    level=WelcomeInfoItem.Level.INFO,
                )
            )
        with self._app_env():
            app = ShellApp(self._soul, welcome_info=welcome_info)
            return await app.run(command)

    async def run_print_mode(
        self,
        input_format: InputFormat,
        output_format: OutputFormat,
        command: str | None = None,
    ) -> bool:
        from aesc.ui.print import PrintApp

        with self._app_env():
            app = PrintApp(
                self._soul,
                input_format,
                output_format,
                self._runtime.session.history_file,
            )
            return await app.run(command)

    async def run_acp_server(self) -> bool:
        from aesc.ui.acp import ACPServer

        with self._app_env():
            app = ACPServer(self._soul)
            return await app.run()

    async def run_wire_server(self) -> bool:
        from aesc.ui.wire import WireServer

        with self._app_env():
            server = WireServer(self._soul)
            return await server.run()
