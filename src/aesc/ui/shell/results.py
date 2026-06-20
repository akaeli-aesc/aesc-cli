"""Meta commands for results management."""

from __future__ import annotations

from typing import TYPE_CHECKING

from aesc.ui.shell.metacmd import meta_command

if TYPE_CHECKING:
    from aesc.ui.shell import ShellApp


@meta_command
async def results(app: ShellApp, args: list[str]):
    """Open results viewer"""
    # Get session-specific results directory
    results_dir = app.soul._runtime.session.results_dir

    # If in Textual mode, open the results dialog
    if app._chat_app is not None:
        from aesc.ui.widgets import ResultsDialog

        await app._chat_app.push_screen(ResultsDialog(results_dir=results_dir))
    else:
        # Fallback for non-Textual mode - show path
        app.output.print(f"Results directory: {results_dir}")
