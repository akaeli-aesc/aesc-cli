from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from typing import TYPE_CHECKING, NamedTuple, overload

from aesc.soul.aescsoul import AescSoul

if TYPE_CHECKING:
    from aesc.ui.shell import ShellApp

type MetaCmdFunc = Callable[["ShellApp", list[str]], None | Awaitable[None]]


class MetaCommand(NamedTuple):
    name: str
    description: str
    func: MetaCmdFunc
    aliases: list[str]
    ash_soul_only: bool

    def slash_name(self):
        """/name (aliases)"""
        if self.aliases:
            return f"/{self.name} ({', '.join(self.aliases)})"
        return f"/{self.name}"


# primary name -> MetaCommand
_meta_commands: dict[str, MetaCommand] = {}
# primary name or alias -> MetaCommand
_meta_command_aliases: dict[str, MetaCommand] = {}


def get_meta_command(name: str) -> MetaCommand | None:
    return _meta_command_aliases.get(name)


def get_meta_commands() -> list[MetaCommand]:
    """Get all unique primary meta commands (without duplicating aliases)."""
    return list(_meta_commands.values())


@overload
def meta_command(func: MetaCmdFunc, /) -> MetaCmdFunc: ...


@overload
def meta_command(
    *,
    name: str | None = None,
    aliases: Sequence[str] | None = None,
    ash_soul_only: bool = False,
) -> Callable[[MetaCmdFunc], MetaCmdFunc]: ...


def meta_command(
    func: MetaCmdFunc | None = None,
    *,
    name: str | None = None,
    aliases: Sequence[str] | None = None,
    ash_soul_only: bool = False,
) -> (
    MetaCmdFunc
    | Callable[
        [MetaCmdFunc],
        MetaCmdFunc,
    ]
):
    """Decorator to register a meta command."""

    def _register(f: MetaCmdFunc):
        primary = name or f.__name__
        alias_list = list(aliases) if aliases else []

        cmd = MetaCommand(
            name=primary,
            description=(f.__doc__ or "").strip(),
            func=f,
            aliases=alias_list,
            ash_soul_only=ash_soul_only,
        )

        _meta_commands[primary] = cmd
        _meta_command_aliases[primary] = cmd

        for alias in alias_list:
            _meta_command_aliases[alias] = cmd

        return f

    if func is not None:
        return _register(func)
    return _register


# ─────────────────────────────────────────────────────────────────────────────
# Core Commands (Keep these)
# ─────────────────────────────────────────────────────────────────────────────


@meta_command(aliases=["quit"])
def exit(app: ShellApp, args: list[str]):
    """Exit the application"""
    raise NotImplementedError


@meta_command(aliases=["h", "?"])
def help(app: ShellApp, args: list[str]):
    """Show help information"""
    from rich.console import Group
    from rich.table import Table
    from rich.text import Text

    # Beatles quote
    quote = Text()
    quote.append("    Help! I need somebody. Help! Not just anybody.\n", style="dim italic")
    quote.append("    Help! You know I need someone. Help!\n", style="dim italic")
    quote.append("    — The Beatles\n", style="dim")

    # Commands table
    cmd_table = Table(show_header=False, box=None, padding=(0, 2))
    cmd_table.add_column("Command", style="cyan")
    cmd_table.add_column("Description")
    cmd_table.add_row("/help", "Show this help")
    cmd_table.add_row("/results", "Open results viewer")
    cmd_table.add_row("/clear", "Clear conversation")
    cmd_table.add_row("/compact", "Compact context")
    cmd_table.add_row("/setup", "Configure LLM provider")
    cmd_table.add_row("/exit", "Exit AESC")

    # Keys table
    key_table = Table(show_header=False, box=None, padding=(0, 2))
    key_table.add_column("Key", style="yellow")
    key_table.add_column("Action")
    key_table.add_row("Esc", "Stop generation / Close dialog")
    key_table.add_row("Ctrl+O", "Toggle tool output")
    key_table.add_row("Ctrl+R", "Open results viewer")
    key_table.add_row("Ctrl+Y", "Copy last response")
    key_table.add_row("Ctrl+L", "Copy all conversation")
    key_table.add_row("Ctrl+D", "Exit AESC")

    # Approval table
    approval_table = Table(show_header=False, box=None, padding=(0, 2))
    approval_table.add_column("Key", style="green")
    approval_table.add_column("Action")
    approval_table.add_row("y", "Approve once")
    approval_table.add_row("a", "Approve for session (always)")
    approval_table.add_row("n", "Reject")

    # Combine
    content = Group(
        quote,
        Text("\nAESC is ready to help with security assessments!\n", style="white"),
        Text("COMMANDS", style="bold cyan"),
        cmd_table,
        Text("\nKEYBOARD SHORTCUTS", style="bold yellow"),
        key_table,
        Text("\nTOOL APPROVAL", style="bold green"),
        approval_table,
    )

    app.output.panel(
        content,
        title="[bold]AESC Help[/bold]",
        border_style="cyan",
        padding=(1, 2),
    )


@meta_command(aliases=["reset"], ash_soul_only=True)
async def clear(app: ShellApp, args: list[str]):
    """Clear the conversation"""
    assert isinstance(app.soul, AescSoul)

    # Clear the context history (only if there's something to clear)
    if app.soul._context.n_checkpoints > 0:
        await app.soul._context.revert_to(0)

    # Clear the UI and show welcome screen again
    if app._chat_app is not None:
        # First update welcome panel with current model (so clear uses updated panel)
        model_name = app.soul.model_name
        if model_name:
            runtime = app.soul._runtime
            app._chat_app.update_welcome_model(
                model_name=model_name,
                directory=str(runtime.session.work_dir),
                session_id=runtime.session.id,
            )
        # Then clear and re-show (uses updated self.welcome_panel)
        app._chat_app.clear_and_show_welcome()

    app.output.print("Conversation cleared.", style="green")


@meta_command(ash_soul_only=True)
async def compact(app: ShellApp, args: list[str]):
    """Compact the context"""
    assert isinstance(app.soul, AescSoul)

    if len(app.soul._context.history) == 0:
        app.output.print("Context is empty.", style="yellow")
        return

    with app.output.status("Compacting..."):
        await app.soul.compact_context()
    app.output.print("Context compacted.", style="green")


# Import additional commands
from . import (  # noqa: E402
    results,  # noqa: F401
    setup,  # noqa: F401
)
