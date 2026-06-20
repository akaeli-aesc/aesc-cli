"""Terminal theme detection utilities."""

import select
import sys
from typing import Literal


def detect_terminal_theme() -> Literal["dark", "light"]:
    """Detect if terminal background is dark or light.

    Uses ANSI escape sequence to query terminal background color,
    then calculates luminance to determine if it's dark or light.

    Returns:
        "dark" or "light"

    Note: Falls back to "dark" if detection fails or not running in TTY.
    """
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        return "dark"  # Default

    try:
        # Set raw mode temporarily
        import termios
        import tty

        # Save terminal settings
        old_settings = termios.tcgetattr(sys.stdin)

        try:
            tty.setraw(sys.stdin.fileno())

            # Send query for background color (OSC 11)
            sys.stdout.write("\x1b]11;?\x07")
            sys.stdout.flush()

            # Read response with timeout
            readable, _, _ = select.select([sys.stdin], [], [], 1.0)

            if not readable:
                return "dark"  # Timeout, assume dark

            # Read response
            response = ""
            while True:
                char = sys.stdin.read(1)
                response += char
                # Stop at bell or ESC
                if char in ("\x07", "\x1b"):
                    break
                if len(response) > 100:  # Prevent infinite loop
                    break

            # Parse color from response
            # Format: ESC]11;rgb:RRRR/GGGG/BBBB BEL or ESC \
            # Example: \x1b]11;rgb:0000/0000/0000\x07
            if "rgb:" in response:
                # Extract RGB values
                rgb_part = response.split("rgb:")[1].split("\x07")[0].split("\x1b")[0]
                parts = rgb_part.split("/")

                if len(parts) >= 3:
                    try:
                        # Convert from 16-bit to 8-bit (RRRR -> RR)
                        r = int(parts[0][:2], 16) if len(parts[0]) >= 2 else 0
                        g = int(parts[1][:2], 16) if len(parts[1]) >= 2 else 0
                        b = int(parts[2][:2], 16) if len(parts[2]) >= 2 else 0

                        # Calculate relative luminance
                        # https://www.w3.org/TR/WCAG20/#relativeluminancedef
                        luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255

                        return "light" if luminance > 0.5 else "dark"
                    except (ValueError, IndexError):
                        pass

            return "dark"  # Failed to parse, assume dark

        finally:
            # Restore terminal settings
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)

    except Exception:
        # Any error, default to dark
        return "dark"


def get_textual_theme(terminal_theme: Literal["dark", "light"]) -> str:
    """Get Textual theme name based on terminal theme.

    Args:
        terminal_theme: "dark" or "light"

    Returns:
        Textual theme name
    """
    if terminal_theme == "light":
        return "textual-light"
    else:
        return "textual-dark"
