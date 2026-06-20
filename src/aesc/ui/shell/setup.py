from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, NamedTuple

import aiohttp
from pydantic import SecretStr

from aesc.config import LLMModel, LLMProvider, MoonshotSearchConfig, load_config, save_config
from aesc.llm import create_llm
from aesc.ui.shell.metacmd import meta_command
from aesc.utils.aiohttp import new_client_session

if TYPE_CHECKING:
    from aesc.ui.shell import ShellApp


class _SetupResult(NamedTuple):
    platform_id: str
    platform_name: str
    base_url: str
    provider_type: str
    api_key: SecretStr
    model_id: str
    max_context_size: int
    search_url: str | None = None


@meta_command
async def setup(app: ShellApp, args: list[str]):
    """Setup AESC"""
    # Check if we're in Textual chat mode
    if app._chat_app is not None:
        result = await _setup_textual(app)
    else:
        result = await _setup_console(app)

    if not result:
        # error message already printed or dialog cancelled
        return

    config = load_config()

    # Add provider configuration
    config.providers[result.platform_id] = LLMProvider(
        type=result.provider_type,
        base_url=result.base_url,
        api_key=result.api_key,
    )

    # Add model configuration
    config.models[result.model_id] = LLMModel(
        provider=result.platform_id,
        model=result.model_id,
        max_context_size=result.max_context_size,
    )
    config.default_model = result.model_id

    # Add search service if available (Kimi)
    if result.search_url:
        config.services.moonshot_search = MoonshotSearchConfig(
            base_url=result.search_url,
            api_key=result.api_key,
        )

    try:
        save_config(config)
    except Exception as e:
        app.output.print(f"[red]Failed to save config: {e}[/red]")
        return

    # Hot-reload the LLM without restarting the app
    provider = config.providers[result.platform_id]
    model = config.models[result.model_id]

    try:
        new_llm = create_llm(
            provider,
            model,
            stream=True,
            session_id=app.soul._runtime.session.id,
        )
        app.soul._runtime.set_llm(new_llm)
        app.output.print(
            f"[green]✓[/green] AESC configured! Using model: [cyan]{result.model_id}[/cyan]"
        )

        # Update prompt bar with model info
        if app._chat_app is not None:
            # Update prompt bar model display
            if hasattr(app._chat_app, "_prompt_bar") and app._chat_app._prompt_bar:
                app._chat_app._prompt_bar.set_model_info(
                    result.model_id,
                    result.max_context_size,
                )
            # Update welcome panel if available
            if hasattr(app._chat_app, "update_welcome_model"):
                runtime = app.soul._runtime
                app._chat_app.update_welcome_model(
                    model_name=result.model_id,
                    directory=str(runtime.session.work_dir),
                    session_id=runtime.session.id,
                )
    except Exception as e:
        app.output.print(f"[red]Failed to initialize LLM: {e}[/red]")
        app.output.print("[yellow]Config saved. Restart aesc to apply changes.[/yellow]")


async def _setup_textual(app: ShellApp) -> _SetupResult | None:
    """Setup using Textual dialog (for chat mode)."""
    import os

    from aesc.ui.widgets import SetupDialog

    # Use an event to wait for the dialog result
    result_holder: list = []
    done_event = asyncio.Event()

    def on_dismiss(result):
        result_holder.append(result)
        done_event.set()

    app._chat_app.push_screen(SetupDialog(), callback=on_dismiss)
    await done_event.wait()

    result = result_holder[0] if result_holder else None
    if not result:
        return None

    # Map provider_id to provider configuration
    # For LiteLLM, we use "litellm" as the provider type
    provider_configs = {
        "anthropic": ("Anthropic (Claude)", "https://api.anthropic.com", "anthropic"),
        "openai": ("OpenAI", "https://api.openai.com/v1", "openai_responses"),
        "gemini": (
            "Google AI Studio",
            "https://generativelanguage.googleapis.com/v1beta",
            "litellm",
        ),
        "vertex_ai": ("Google Vertex AI", "", "litellm"),
        "azure": ("Azure OpenAI", "", "litellm"),
        "bedrock": ("AWS Bedrock", "", "litellm"),
        "groq": ("Groq", "https://api.groq.com/openai/v1", "litellm"),
        "together": ("Together AI", "https://api.together.xyz/v1", "litellm"),
        "deepseek": ("DeepSeek", "https://api.deepseek.com", "litellm"),
        "openrouter": ("OpenRouter", "https://openrouter.ai/api/v1", "litellm"),
        "ollama": ("Ollama", "http://localhost:11434", "litellm"),
        "custom": ("Custom", result.api_base or "", "litellm"),
    }

    config = provider_configs.get(result.provider_id, ("Custom", "", "litellm"))
    platform_name, base_url, provider_type = config

    # Override base_url if provided
    if result.api_base:
        base_url = result.api_base

    # For Vertex AI, set environment variables
    if result.provider_id == "vertex_ai":
        if result.project_id:
            os.environ["VERTEX_PROJECT"] = result.project_id
        if result.location:
            os.environ["VERTEX_LOCATION"] = result.location

    # Convert SetupResult to _SetupResult
    # The model field is the full LiteLLM string (e.g., "gemini/gemini-2.0-flash")
    return _SetupResult(
        platform_id=result.provider_id,
        platform_name=platform_name,
        base_url=base_url,
        provider_type=provider_type,
        api_key=SecretStr(result.api_key) if result.api_key else SecretStr(""),
        model_id=result.model,  # Full LiteLLM model string
        max_context_size=result.max_context,
    )


# Platforms for console mode (duplicated from setup_dialog for independence)
_CONSOLE_PLATFORMS = [
    ("anthropic", "Anthropic (Claude)", "https://api.anthropic.com", "anthropic"),
    ("openai", "OpenAI (GPT-4, o1, o3)", "https://api.openai.com/v1", "openai_responses"),
    (
        "gemini",
        "Google Gemini",
        "https://generativelanguage.googleapis.com/v1beta",
        "openai_responses",
    ),
    (
        "qwen",
        "Alibaba Qwen",
        "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
        "openai_responses",
    ),
    ("moonshot", "Moonshot AI (Kimi)", "https://api.moonshot.ai/v1", "kimi"),
]

_CONSOLE_MODELS = {
    "anthropic": [
        ("claude-sonnet-4-20250514", 200000, "Latest Claude 4 Sonnet"),
        ("claude-opus-4-20250514", 200000, "Claude 4 Opus"),
        ("claude-haiku-4-20250514", 200000, "Claude 4 Haiku"),
        ("claude-3-5-sonnet-20241022", 200000, "Claude 3.5 Sonnet"),
    ],
    "openai": [
        ("gpt-4o", 128000, "GPT-4 Omni"),
        ("gpt-4o-mini", 128000, "GPT-4o Mini"),
        ("o1", 200000, "o1 reasoning"),
        ("o3-mini", 200000, "o3 Mini"),
    ],
    "gemini": [
        ("gemini-2.0-flash", 1000000, "Gemini 2.0 Flash"),
        ("gemini-1.5-pro", 2000000, "Gemini 1.5 Pro"),
    ],
    "qwen": [
        ("qwen-max", 32000, "Qwen Max"),
        ("qwen-plus", 128000, "Qwen Plus"),
        ("qwen-turbo", 1000000, "Qwen Turbo"),
    ],
    "moonshot": [
        ("kimi-k2-0711-preview", 128000, "Kimi K2"),
        ("moonshot-v1-128k", 128000, "Moonshot v1"),
    ],
}


async def _setup_console(app: ShellApp) -> _SetupResult | None:
    """Setup using console prompts (for classic mode)."""
    from prompt_toolkit import PromptSession
    from prompt_toolkit.shortcuts.choice_input import ChoiceInput

    async def _prompt_choice(*, header: str, choices: list[str]) -> str | None:
        if not choices:
            return None
        try:
            return await ChoiceInput(
                message=header,
                options=[(choice, choice) for choice in choices],
                default=choices[0],
            ).prompt_async()
        except (EOFError, KeyboardInterrupt):
            return None

    async def _prompt_text(prompt: str, *, is_password: bool = False) -> str | None:
        session = PromptSession()
        try:
            return str(await session.prompt_async(f" {prompt}: ", is_password=is_password)).strip()
        except (EOFError, KeyboardInterrupt):
            return None

    # Select the API platform
    platform_names = [p[1] for p in _CONSOLE_PLATFORMS]
    platform_name = await _prompt_choice(
        header="Select the API platform",
        choices=platform_names,
    )
    if not platform_name:
        app.output.print("[red]No platform selected[/red]")
        return None

    platform = next(p for p in _CONSOLE_PLATFORMS if p[1] == platform_name)
    platform_id, _, base_url, provider_type = platform

    # Enter the API key
    api_key = await _prompt_text("Enter your API key", is_password=True)
    if not api_key:
        return None

    # Select model from predefined list
    if platform_id in _CONSOLE_MODELS:
        models = _CONSOLE_MODELS[platform_id]
        model_choices = [f"{m[0]} - {m[2]}" for m in models]
        selected = await _prompt_choice(
            header="Select the model",
            choices=model_choices,
        )
        if not selected:
            app.output.print("[red]No model selected[/red]")
            return None

        idx = model_choices.index(selected)
        model_id, max_context, _ = models[idx]

        return _SetupResult(
            platform_id=platform_id,
            platform_name=platform_name,
            base_url=base_url,
            provider_type=provider_type,
            api_key=SecretStr(api_key),
            model_id=model_id,
            max_context_size=max_context,
        )

    # Fallback: try to fetch models from API
    models_url = f"{base_url}/models"
    try:
        async with (
            new_client_session() as session,
            session.get(
                models_url,
                headers={"Authorization": f"Bearer {api_key}"},
                raise_for_status=True,
            ) as response,
        ):
            resp_json = await response.json()
    except aiohttp.ClientError as e:
        app.output.print(f"[red]Failed to get models: {e}[/red]")
        return None

    model_ids: list[str] = [model["id"] for model in resp_json.get("data", [])]
    if not model_ids:
        app.output.print("[red]No models available[/red]")
        return None

    model_id = await _prompt_choice(
        header="Select the model",
        choices=model_ids,
    )
    if not model_id:
        app.output.print("[red]No model selected[/red]")
        return None

    model_data = next((m for m in resp_json["data"] if m["id"] == model_id), {})
    max_context = model_data.get("context_length", 128000)

    return _SetupResult(
        platform_id=platform_id,
        platform_name=platform_name,
        base_url=base_url,
        provider_type=provider_type,
        api_key=SecretStr(api_key),
        model_id=model_id,
        max_context_size=max_context,
    )
