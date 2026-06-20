"""Textual output writer for TUI."""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING

from rich.panel import Panel
from rich.text import Text

if TYPE_CHECKING:
    from collections.abc import Generator

    from rich.console import RenderableType
    from rich.table import Table

    from aesc.ui.shell.textual_chat_app import TextualChatApp


class TextualOutputWriter:
    """OutputWriter implementation for Textual UI.

    This converts Rich renderables to Textual widgets and displays them
    in the chat interface.
    """

    def __init__(self, chat_app: TextualChatApp):
        """Initialize with a TextualChatApp instance.

        Args:
            chat_app: The Textual chat application
        """
        self._chat_app = chat_app

    def print(self, content: RenderableType, *, style: str | None = None) -> None:
        """Add content as a message to the chat."""
        if isinstance(content, str) and style:
            content = Text(content, style=style)
        self._chat_app.add_message(content)

    def panel(
        self,
        content: RenderableType,
        *,
        title: str | None = None,
        border_style: str = "blue",
        **kwargs,
    ) -> None:
        """Display content in a Rich Panel as a chat message."""
        panel = Panel(content, title=title, border_style=border_style, **kwargs)
        self._chat_app.add_message(panel)

    def table(self, table: Table) -> None:
        """Display a Rich Table as a chat message."""
        self._chat_app.add_message(table)

    @contextmanager
    def status(self, message: str) -> Generator[None]:
        """Show status message in chat.

        For Textual, we show the status message, execute the work,
        then show a completion message.
        """
        # Show status message
        status_msg = Text(f"⏳ {message}", style="cyan")
        self._chat_app.add_message(status_msg)

        try:
            yield
            # Show completion
            done_msg = Text(f"✓ {message} - Done", style="green")
            self._chat_app.add_message(done_msg)
        except Exception:
            # Show error
            error_msg = Text(f"✗ {message} - Failed", style="red")
            self._chat_app.add_message(error_msg)
            raise

    @contextmanager
    def pager(self, *, styles: bool = True) -> Generator[None]:
        """For Textual, paging is not needed - just display content.

        The scrollable chat container serves as a built-in pager.
        """
        # In Textual, content is already scrollable, so we just yield
        # and let content be added normally
        yield
