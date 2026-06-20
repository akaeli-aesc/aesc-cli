"""Console output writer using Rich Console."""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING

from rich.panel import Panel

if TYPE_CHECKING:
    from collections.abc import Generator

    from rich.console import RenderableType
    from rich.table import Table


class ConsoleOutputWriter:
    """OutputWriter implementation using Rich Console.

    This wraps the existing console.print() functionality to conform
    to the OutputWriter protocol.
    """

    def __init__(self, console):
        """Initialize with a Rich Console instance.

        Args:
            console: Rich Console object
        """
        self._console = console

    def print(self, content: RenderableType, *, style: str | None = None) -> None:
        """Print content using console.print()."""
        if style:
            self._console.print(content, style=style)
        else:
            self._console.print(content)

    def panel(
        self,
        content: RenderableType,
        *,
        title: str | None = None,
        border_style: str = "blue",
        **kwargs,
    ) -> None:
        """Display content in a Rich Panel."""
        panel = Panel(content, title=title, border_style=border_style, **kwargs)
        self._console.print(panel)

    def table(self, table: Table) -> None:
        """Display a Rich Table."""
        self._console.print(table)

    @contextmanager
    def status(self, message: str) -> Generator[None]:
        """Show status using console.status()."""
        with self._console.status(message):
            yield

    @contextmanager
    def pager(self, *, styles: bool = True) -> Generator[None]:
        """Display content in pager using console.pager()."""
        with self._console.pager(styles=styles):
            yield
