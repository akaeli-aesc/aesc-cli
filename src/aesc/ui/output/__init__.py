"""UI output abstraction layer.

This module provides an abstraction over different UI outputs (console, Textual, etc.)
so that meta commands and other components can output to any UI without being coupled
to a specific implementation.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Generator

    from rich.console import RenderableType
    from rich.table import Table


@runtime_checkable
class OutputWriter(Protocol):
    """Abstract interface for UI output.

    Meta commands and other components should use this interface instead of
    directly using console.print() or widget methods. This allows the same
    code to work with different UIs (Rich Console, Textual, Web UI, etc.)
    """

    def print(self, content: RenderableType, *, style: str | None = None) -> None:
        """Print content to the UI.

        Args:
            content: Rich renderable content (Text, Panel, str, etc.)
            style: Optional style for text content
        """
        ...

    def panel(
        self,
        content: RenderableType,
        *,
        title: str | None = None,
        border_style: str = "blue",
        **kwargs,
    ) -> None:
        """Display content in a panel.

        Args:
            content: Content to display in panel
            title: Optional panel title
            border_style: Border color/style
            **kwargs: Additional panel options
        """
        ...

    def table(self, table: Table) -> None:
        """Display a table.

        Args:
            table: Rich Table object
        """
        ...

    @contextmanager
    def status(self, message: str) -> Generator[None]:
        """Show a status/loading message.

        Args:
            message: Status message to display

        Yields:
            None

        Example:
            with output.status("Processing..."):
                do_work()
        """
        ...

    @contextmanager
    def pager(self, *, styles: bool = True) -> Generator[None]:
        """Display content in a pager (for long output).

        Args:
            styles: Whether to preserve Rich styles

        Yields:
            None (output goes to context manager)
        """
        ...


__all__ = ["OutputWriter"]
