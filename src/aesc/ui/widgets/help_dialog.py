"""Help Dialog - Show keybindings and commands"""

from rich.panel import Panel
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Static


class HelpDialog(ModalScreen):
    """Help dialog. Use /help to open, Esc to close."""

    DEFAULT_CSS = """
    HelpDialog {
        align: center middle;
    }

    #help-container {
        width: 50;
        height: auto;
        max-height: 80%;
        background: $surface;
        border: solid $primary;
        padding: 1 2;
    }

    #help-content {
        height: auto;
    }
    """

    BINDINGS = [
        ("escape", "dismiss", "Close"),
        ("q", "dismiss", "Close"),
    ]

    def compose(self) -> ComposeResult:
        with Container(id="help-container"):
            yield Static(self._build_help_content(), id="help-content")

    def _build_help_content(self) -> Panel:
        """Build help content."""
        help_text = Text()

        help_text.append("KEYS\n", style="bold cyan")
        help_text.append("Esc        ", style="cyan")
        help_text.append("Stop / Close\n", style="white")
        help_text.append("Ctrl+O     ", style="cyan")
        help_text.append("Toggle output\n", style="white")
        help_text.append("Ctrl+R     ", style="cyan")
        help_text.append("Results viewer\n", style="white")
        help_text.append("Ctrl+Y     ", style="cyan")
        help_text.append("Copy last response\n", style="white")
        help_text.append("Ctrl+L     ", style="cyan")
        help_text.append("Copy all conversation\n", style="white")
        help_text.append("Ctrl+D     ", style="cyan")
        help_text.append("Exit\n", style="white")

        help_text.append("\n")
        help_text.append("COMMANDS\n", style="bold magenta")
        help_text.append("/help      ", style="magenta")
        help_text.append("This help\n", style="white")
        help_text.append("/results   ", style="magenta")
        help_text.append("Browse results\n", style="white")
        help_text.append("/clear     ", style="magenta")
        help_text.append("Clear history\n", style="white")
        help_text.append("/compact   ", style="magenta")
        help_text.append("Compact context\n", style="white")
        help_text.append("/exit      ", style="magenta")
        help_text.append("Exit\n", style="white")

        help_text.append("\n")
        help_text.append("APPROVAL\n", style="bold green")
        help_text.append("y          ", style="green")
        help_text.append("Yes (once)\n", style="white")
        help_text.append("a          ", style="green")
        help_text.append("Always (session)\n", style="white")
        help_text.append("n          ", style="green")
        help_text.append("No\n", style="white")

        return Panel(
            help_text,
            title="[bold]Help[/bold]",
            subtitle="[dim]Esc to close[/dim]",
            border_style="cyan",
            padding=(0, 1),
        )

    def action_dismiss(self) -> None:
        """Close dialog."""
        self.dismiss()
