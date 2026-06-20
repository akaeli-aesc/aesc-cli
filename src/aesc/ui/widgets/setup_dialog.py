"""Setup Dialog - LiteLLM Provider Configuration for AESC.

Fully configurable LLM setup supporting all LiteLLM providers.
"""

from __future__ import annotations

import os
from typing import NamedTuple

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, ListItem, ListView, Static, Switch

# Theme colors
_BRAND = "#a855f7"
_TEXT_MUTED = "#a1a1aa"
_TEXT_DIM = "#71717a"
_SUCCESS = "#4ade80"
_WARNING = "#fbbf24"


class Provider(NamedTuple):
    """LiteLLM provider configuration."""

    id: str
    name: str
    prefix: str  # LiteLLM model prefix (e.g., "gemini/", "vertex_ai/")
    env_key: str  # Environment variable for API key
    requires_project: bool = False  # For Vertex AI
    requires_location: bool = False  # For Vertex AI
    base_url: str | None = None  # Optional custom base URL


# All LiteLLM-supported providers
PROVIDERS = [
    Provider(
        id="anthropic",
        name="Anthropic (Claude)",
        prefix="anthropic/",
        env_key="ANTHROPIC_API_KEY",
    ),
    Provider(
        id="openai",
        name="OpenAI (GPT-4, o1, o3)",
        prefix="openai/",
        env_key="OPENAI_API_KEY",
    ),
    Provider(
        id="gemini",
        name="Google AI Studio (Gemini)",
        prefix="gemini/",
        env_key="GEMINI_API_KEY",
    ),
    Provider(
        id="vertex_ai",
        name="Google Vertex AI",
        prefix="vertex_ai/",
        env_key="GOOGLE_APPLICATION_CREDENTIALS",
        requires_project=True,
        requires_location=True,
    ),
    Provider(
        id="azure",
        name="Azure OpenAI",
        prefix="azure/",
        env_key="AZURE_API_KEY",
    ),
    Provider(
        id="bedrock",
        name="AWS Bedrock",
        prefix="bedrock/",
        env_key="AWS_ACCESS_KEY_ID",
    ),
    Provider(
        id="groq",
        name="Groq",
        prefix="groq/",
        env_key="GROQ_API_KEY",
    ),
    Provider(
        id="together",
        name="Together AI",
        prefix="together_ai/",
        env_key="TOGETHERAI_API_KEY",
    ),
    Provider(
        id="deepseek",
        name="DeepSeek",
        prefix="deepseek/",
        env_key="DEEPSEEK_API_KEY",
    ),
    Provider(
        id="openrouter",
        name="OpenRouter",
        prefix="openrouter/",
        env_key="OPENROUTER_API_KEY",
    ),
    Provider(
        id="ollama",
        name="Ollama (Local)",
        prefix="ollama/",
        env_key="",  # No API key needed
        base_url="http://localhost:11434",
    ),
    Provider(
        id="custom",
        name="Custom OpenAI-Compatible",
        prefix="openai/",
        env_key="",
    ),
]

# Popular models per provider with context sizes
MODELS: dict[str, list[tuple[str, int, str]]] = {
    "anthropic": [
        ("claude-sonnet-4-20250514", 200000, "Claude 4 Sonnet - best for coding"),
        ("claude-opus-4-20250514", 200000, "Claude 4 Opus - most capable"),
        ("claude-3-5-sonnet-20241022", 200000, "Claude 3.5 Sonnet"),
        ("claude-3-5-haiku-20241022", 200000, "Claude 3.5 Haiku - fast"),
    ],
    "openai": [
        ("gpt-4o", 128000, "GPT-4o - flagship multimodal"),
        ("gpt-4o-mini", 128000, "GPT-4o Mini - fast"),
        ("o1", 200000, "o1 - reasoning"),
        ("o3-mini", 200000, "o3 Mini - latest reasoning"),
    ],
    "gemini": [
        ("gemini-3-flash-preview", 1000000, "Gemini 3 Flash Preview - latest"),
        ("gemini-2.5-flash-preview-04-17", 1000000, "Gemini 2.5 Flash Preview"),
        ("gemini-2.0-flash", 1000000, "Gemini 2.0 Flash - 1M context"),
        ("gemini-2.0-flash-lite", 1000000, "Gemini 2.0 Flash Lite"),
        ("gemini-1.5-pro", 2000000, "Gemini 1.5 Pro - 2M context"),
        ("gemini-1.5-flash", 1000000, "Gemini 1.5 Flash"),
    ],
    "vertex_ai": [
        ("gemini-3-flash-preview", 1000000, "Gemini 3 Flash Preview (requires global)"),
        ("gemini-2.5-flash-preview-04-17", 1000000, "Gemini 2.5 Flash Preview"),
        ("gemini-2.0-flash", 1000000, "Gemini 2.0 Flash"),
        ("gemini-1.5-pro", 2000000, "Gemini 1.5 Pro"),
        ("claude-3-5-sonnet-v2@20241022", 200000, "Claude 3.5 Sonnet (Model Garden)"),
    ],
    "azure": [
        ("gpt-4o", 128000, "GPT-4o deployment"),
        ("gpt-4-turbo", 128000, "GPT-4 Turbo deployment"),
    ],
    "bedrock": [
        ("anthropic.claude-3-5-sonnet-20241022-v2:0", 200000, "Claude 3.5 Sonnet"),
        ("anthropic.claude-3-haiku-20240307-v1:0", 200000, "Claude 3 Haiku"),
        ("amazon.nova-pro-v1:0", 300000, "Amazon Nova Pro"),
    ],
    "groq": [
        ("llama-3.3-70b-versatile", 128000, "Llama 3.3 70B"),
        ("llama-3.1-8b-instant", 128000, "Llama 3.1 8B - ultra fast"),
        ("mixtral-8x7b-32768", 32768, "Mixtral 8x7B"),
    ],
    "together": [
        ("meta-llama/Meta-Llama-3.1-405B-Instruct-Turbo", 128000, "Llama 3.1 405B"),
        ("meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo", 128000, "Llama 3.1 70B"),
        ("Qwen/Qwen2.5-72B-Instruct-Turbo", 128000, "Qwen 2.5 72B"),
    ],
    "deepseek": [
        ("deepseek-chat", 64000, "DeepSeek Chat"),
        ("deepseek-coder", 64000, "DeepSeek Coder"),
    ],
    "openrouter": [
        ("anthropic/claude-3.5-sonnet", 200000, "Claude 3.5 Sonnet"),
        ("openai/gpt-4o", 128000, "GPT-4o"),
        ("google/gemini-pro-1.5", 1000000, "Gemini 1.5 Pro"),
    ],
    "ollama": [
        ("llama3.2", 128000, "Llama 3.2"),
        ("codellama", 16000, "Code Llama"),
        ("mistral", 32000, "Mistral 7B"),
    ],
    "custom": [],
}


class SetupResult(NamedTuple):
    """Result from setup dialog."""

    provider_id: str
    model: str  # Full LiteLLM model string (e.g., "gemini/gemini-2.0-flash")
    api_key: str
    api_base: str | None
    max_context: int
    # Vertex AI specific
    project_id: str | None
    location: str | None


class ProviderItem(ListItem):
    """A provider item in the list."""

    def __init__(self, provider: Provider, **kwargs):
        super().__init__(**kwargs)
        self.provider = provider

    def compose(self) -> ComposeResult:
        text = Text()
        text.append(self.provider.name)
        if os.getenv(self.provider.env_key):
            text.append(" ✓", style=_SUCCESS)
        yield Static(text)


class ModelItem(ListItem):
    """A model item in the list."""

    def __init__(self, model_id: str, context_size: int, description: str, **kwargs):
        super().__init__(**kwargs)
        self.model_id = model_id
        self.context_size = context_size
        self.description = description

    def compose(self) -> ComposeResult:
        text = Text()
        text.append(self.model_id, style="bold")
        text.append(f" ({self.context_size // 1000}K)", style=_TEXT_DIM)
        if self.description:
            text.append(f" - {self.description}", style=_TEXT_MUTED)
        yield Static(text)


class SetupDialog(ModalScreen[SetupResult | None]):
    """LiteLLM provider configuration dialog.

    Steps:
    1. Select provider
    2. Configure credentials (API key, project ID, etc.)
    3. Select or enter model
    """

    DEFAULT_CSS = """
    SetupDialog {
        align: center middle;
    }

    #setup-container {
        width: 80;
        height: auto;
        max-height: 90%;
        background: $surface;
        border: thick $primary;
        padding: 1 2;
    }

    #setup-title {
        text-align: center;
        text-style: bold;
        color: #a855f7;
        margin-bottom: 1;
    }

    #setup-content {
        height: auto;
        max-height: 35;
    }

    .step-label {
        margin-bottom: 1;
        color: $text;
    }

    .hint-label {
        color: #71717a;
        margin-bottom: 1;
    }

    #provider-list {
        height: 12;
        margin-bottom: 1;
        border: solid $primary;
    }

    #provider-list > ListItem {
        padding: 0 1;
    }

    #provider-list > ListItem:hover {
        background: $accent 30%;
    }

    #model-list {
        height: 8;
        margin-bottom: 1;
        border: solid $primary;
    }

    #model-list > ListItem {
        padding: 0 1;
    }

    #model-list > ListItem:hover {
        background: $accent 30%;
    }

    .config-input {
        margin-bottom: 1;
    }

    #custom-model-row {
        height: 3;
        margin-bottom: 1;
    }

    #custom-model-switch {
        margin-right: 1;
    }

    #button-row {
        margin-top: 1;
        height: 3;
        align: center middle;
    }

    #button-row Button {
        margin: 0 1;
    }

    #error-label {
        color: $error;
        margin-top: 1;
        height: auto;
    }

    #info-label {
        color: #a1a1aa;
        margin-top: 1;
        height: auto;
    }
    """

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
    ]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._step = 1  # 1=provider, 2=credentials, 3=model
        self._provider: Provider | None = None
        self._api_key: str = ""
        self._api_base: str = ""
        self._project_id: str = ""
        self._location: str = "global"
        self._custom_model: bool = False
        self._models: list[tuple[str, int, str]] = []

    def compose(self) -> ComposeResult:
        with Container(id="setup-container"):
            yield Static("◆ Setup AESC", id="setup-title")

            with Vertical(id="setup-content"):
                # Step 1: Provider selection
                yield Label("Select LLM Provider:", classes="step-label", id="provider-label")
                yield Label(
                    "✓ = API key found in environment", classes="hint-label", id="provider-hint"
                )
                yield ListView(
                    *[ProviderItem(p, id=f"provider-{p.id}") for p in PROVIDERS],
                    id="provider-list",
                )

                # Step 2: Credentials
                yield Label("API Key:", classes="step-label", id="apikey-label")
                yield Input(
                    placeholder="Enter API key or leave empty if using env var",
                    password=True,
                    id="api-key-input",
                    classes="config-input",
                )

                yield Label("API Base URL (optional):", classes="step-label", id="apibase-label")
                yield Input(
                    placeholder="Custom endpoint URL (leave empty for default)",
                    id="api-base-input",
                    classes="config-input",
                )

                # Vertex AI specific
                yield Label("GCP Project ID:", classes="step-label", id="project-label")
                yield Input(
                    placeholder="your-gcp-project-id",
                    id="project-input",
                    classes="config-input",
                )

                yield Label("GCP Location:", classes="step-label", id="location-label")
                yield Input(
                    placeholder="global (required for Gemini 3)",
                    value="global",
                    id="location-input",
                    classes="config-input",
                )

                # Step 3: Model selection
                yield Label("Select Model:", classes="step-label", id="model-label")
                yield ListView(id="model-list")

                with Horizontal(id="custom-model-row"):
                    yield Switch(id="custom-model-switch")
                    yield Label("Enter custom model name", id="custom-model-label")

                yield Input(
                    placeholder="model-name (without provider prefix)",
                    id="custom-model-input",
                    classes="config-input",
                )

                # Status labels
                yield Static("", id="error-label")
                yield Static("", id="info-label")

            with Container(id="button-row"):
                yield Button("Back", variant="default", id="back-btn")
                yield Button("Cancel", variant="default", id="cancel-btn")
                yield Button("Next", variant="primary", id="next-btn")

    def on_mount(self) -> None:
        """Setup initial state."""
        self._show_step(1)

    def _show_step(self, step: int) -> None:
        """Show UI for the given step."""
        self._step = step

        # Hide all elements first
        self.query_one("#provider-label").display = False
        self.query_one("#provider-hint").display = False
        self.query_one("#provider-list").display = False
        self.query_one("#apikey-label").display = False
        self.query_one("#api-key-input").display = False
        self.query_one("#apibase-label").display = False
        self.query_one("#api-base-input").display = False
        self.query_one("#project-label").display = False
        self.query_one("#project-input").display = False
        self.query_one("#location-label").display = False
        self.query_one("#location-input").display = False
        self.query_one("#model-label").display = False
        self.query_one("#model-list").display = False
        self.query_one("#custom-model-row").display = False
        self.query_one("#custom-model-input").display = False
        self.query_one("#error-label", Static).update("")
        self.query_one("#info-label", Static).update("")

        back_btn = self.query_one("#back-btn", Button)
        next_btn = self.query_one("#next-btn", Button)

        if step == 1:
            # Provider selection
            self.query_one("#provider-label").display = True
            self.query_one("#provider-hint").display = True
            self.query_one("#provider-list").display = True
            self.query_one("#provider-list", ListView).focus()
            back_btn.display = False
            next_btn.label = "Next"

        elif step == 2:
            # Credentials
            back_btn.display = True
            next_btn.label = "Next"

            if self._provider:
                # Show API key input
                env_val = os.getenv(self._provider.env_key) if self._provider.env_key else None

                apikey_label = self.query_one("#apikey-label", Label)

                # Vertex AI and Bedrock use cloud credentials, not API keys
                if self._provider.id == "vertex_ai":
                    self.query_one("#apikey-label").display = True
                    self.query_one("#api-key-input").display = False
                    apikey_label.update("✓ Uses GCP credentials (gcloud auth)")
                    self.query_one("#info-label", Static).update(
                        "Ensure 'gcloud auth application-default login' is done"
                    )
                elif self._provider.id == "bedrock":
                    self.query_one("#apikey-label").display = True
                    self.query_one("#api-key-input").display = False
                    apikey_label.update("✓ Uses AWS credentials (~/.aws/credentials)")
                else:
                    self.query_one("#apikey-label").display = True
                    self.query_one("#api-key-input").display = True

                    if env_val:
                        apikey_label.update(f"API Key (found in ${self._provider.env_key}):")
                        self._api_key = env_val
                    elif self._provider.env_key:
                        apikey_label.update(f"API Key (or set ${self._provider.env_key}):")
                    else:
                        apikey_label.update("API Key (optional for local):")

                # API Base URL for custom/ollama
                if self._provider.id in ("custom", "ollama"):
                    self.query_one("#apibase-label").display = True
                    self.query_one("#api-base-input").display = True
                    if self._provider.base_url:
                        self.query_one("#api-base-input", Input).value = self._provider.base_url

                # Vertex AI specific fields
                if self._provider.requires_project:
                    self.query_one("#project-label").display = True
                    self.query_one("#project-input").display = True
                if self._provider.requires_location:
                    self.query_one("#location-label").display = True
                    self.query_one("#location-input").display = True

                self.query_one("#api-key-input", Input).focus()

        elif step == 3:
            # Model selection
            back_btn.display = True
            next_btn.label = "Finish"

            self.query_one("#model-label").display = True
            self.query_one("#model-list").display = True
            self.query_one("#custom-model-row").display = True

            # Show custom model input if switch is on
            if self._custom_model:
                self.query_one("#custom-model-input").display = True
                self.query_one("#custom-model-input", Input).focus()
            else:
                self.query_one("#model-list", ListView).focus()

            # Load models for this provider
            self._load_models()

    def _load_models(self) -> None:
        """Load models for the selected provider."""
        if not self._provider:
            return

        model_list = self.query_one("#model-list", ListView)
        model_list.clear()

        self._models = MODELS.get(self._provider.id, [])
        for model_id, ctx_size, desc in self._models:
            model_list.append(ModelItem(model_id, ctx_size, desc, id=f"model-{model_id}"))

        if not self._models:
            self.query_one("#info-label", Static).update(
                "No predefined models. Enable custom model input."
            )

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Handle list selection."""
        if self._step == 1 and isinstance(event.item, ProviderItem):
            self._provider = event.item.provider
            self._show_step(2)
        elif self._step == 3 and isinstance(event.item, ModelItem):
            self._finish_with_model(event.item.model_id, event.item.context_size)

    def on_switch_changed(self, event: Switch.Changed) -> None:
        """Handle custom model switch."""
        if event.switch.id == "custom-model-switch":
            self._custom_model = event.value
            self.query_one("#custom-model-input").display = event.value
            if event.value:
                self.query_one("#custom-model-input", Input).focus()

    def _finish_with_model(self, model_id: str, context_size: int) -> None:
        """Complete setup with selected model."""
        if not self._provider:
            return

        # Build full LiteLLM model string
        full_model = f"{self._provider.prefix}{model_id}"

        # Get API key (from input or env)
        api_key = self.query_one("#api-key-input", Input).value.strip()
        if not api_key and self._provider.env_key:
            api_key = os.getenv(self._provider.env_key, "")

        # Get optional fields
        api_base = self.query_one("#api-base-input", Input).value.strip() or None
        project_id = self.query_one("#project-input", Input).value.strip() or None
        location = self.query_one("#location-input", Input).value.strip() or None

        result = SetupResult(
            provider_id=self._provider.id,
            model=full_model,
            api_key=api_key,
            api_base=api_base,
            max_context=context_size,
            project_id=project_id,
            location=location,
        )
        self.dismiss(result)

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "cancel-btn":
            self.dismiss(None)
        elif event.button.id == "back-btn":
            if self._step > 1:
                self._show_step(self._step - 1)
        elif event.button.id == "next-btn":
            await self._handle_next()

    async def _handle_next(self) -> None:
        """Handle next button."""
        if self._step == 1:
            # Validate provider selection
            provider_list = self.query_one("#provider-list", ListView)
            if provider_list.highlighted_child and isinstance(
                provider_list.highlighted_child, ProviderItem
            ):
                self._provider = provider_list.highlighted_child.provider
                self._show_step(2)
            else:
                self.query_one("#error-label", Static).update("Please select a provider")

        elif self._step == 2:
            # Validate credentials
            api_key = self.query_one("#api-key-input", Input).value.strip()
            env_key = (
                os.getenv(self._provider.env_key)
                if self._provider and self._provider.env_key
                else None
            )

            # For most providers, require API key
            # Exceptions: ollama, custom, vertex_ai (uses GCP credentials), bedrock (uses AWS credentials)
            if (
                not api_key
                and not env_key
                and self._provider
                and self._provider.id not in ("ollama", "custom", "vertex_ai", "bedrock")
            ):
                self.query_one("#error-label", Static).update("API key required")
                return

            # Vertex AI requires project
            if self._provider and self._provider.requires_project:
                project = self.query_one("#project-input", Input).value.strip()
                if not project:
                    self.query_one("#error-label", Static).update("GCP Project ID required")
                    return

            self._show_step(3)

        elif self._step == 3:
            # Finish with model
            if self._custom_model:
                custom_model = self.query_one("#custom-model-input", Input).value.strip()
                if not custom_model:
                    self.query_one("#error-label", Static).update("Enter model name")
                    return
                # Use a default context size for custom models
                self._finish_with_model(custom_model, 128000)
            else:
                model_list = self.query_one("#model-list", ListView)
                if model_list.highlighted_child and isinstance(
                    model_list.highlighted_child, ModelItem
                ):
                    item = model_list.highlighted_child
                    self._finish_with_model(item.model_id, item.context_size)
                else:
                    self.query_one("#error-label", Static).update(
                        "Select a model or enable custom input"
                    )

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle Enter in input fields."""
        if self._step == 2 or self._step == 3 and event.input.id == "custom-model-input":
            await self._handle_next()

    def action_cancel(self) -> None:
        """Cancel and close dialog."""
        self.dismiss(None)
