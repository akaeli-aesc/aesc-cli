from __future__ import annotations

import shutil

from rich.console import Console
from rich.theme import Theme


def get_adaptive_width(terminal_width: int) -> int:
    """
    Calculate adaptive console width using Gemini-style formula.

    - Small terminals (≤80 cols): 98% width
    - Large terminals (≥132 cols): 90% width
    - Medium terminals: Linear interpolation

    This provides better readability and aesthetics.
    """
    if terminal_width <= 80:
        return int(0.98 * terminal_width)
    if terminal_width >= 132:
        return int(0.90 * terminal_width)

    # Linear interpolation between 80 and 132
    t = (terminal_width - 80) / (132 - 80)
    percentage = 98 - (8 * t)  # 98% → 90%
    return int(percentage * terminal_width / 100)


_NEUTRAL_MARKDOWN_THEME = Theme(
    {
        "markdown.paragraph": "none",
        "markdown.block_quote": "none",
        "markdown.hr": "none",
        "markdown.item": "none",
        "markdown.item.bullet": "none",
        "markdown.item.number": "none",
        "markdown.link": "none",
        "markdown.link_url": "none",
        "markdown.h1": "none",
        "markdown.h1.border": "none",
        "markdown.h2": "none",
        "markdown.h3": "none",
        "markdown.h4": "none",
        "markdown.h5": "none",
        "markdown.h6": "none",
        "markdown.em": "none",
        "markdown.strong": "none",
        "markdown.s": "none",
        "status.spinner": "none",
    },
    inherit=True,
)

# Responsive console - adapts to terminal width using Gemini-style calculation
# Uses force_terminal for consistent behavior in different environments
terminal_width = shutil.get_terminal_size().columns
adaptive_width = get_adaptive_width(terminal_width)

console = Console(
    highlight=False,
    theme=_NEUTRAL_MARKDOWN_THEME,
    force_terminal=True,
    width=adaptive_width,
    soft_wrap=True,  # Enable text wrapping for long lines
    legacy_windows=False,  # Modern terminal support
)
