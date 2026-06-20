from __future__ import annotations

import base64
import sys


def is_clipboard_available() -> bool:
    """Check if clipboard is available (always True for OSC52)."""
    # OSC52 works through terminal emulator, so it's generally available
    # as long as we're in a terminal
    return sys.stdout.isatty()


def copy_to_clipboard(text: str) -> bool:
    """
    Copy text to clipboard using OSC 52 escape sequence.

    OSC 52 is supported by most modern terminal emulators:
    - iTerm2, Terminal.app (macOS)
    - Windows Terminal, ConEmu
    - xterm, rxvt, alacritty, kitty, foot
    - VSCode integrated terminal
    - tmux (with set -g set-clipboard on)

    This works even in Docker containers and SSH sessions!
    """
    if not text:
        return False

    try:
        # Encode text as base64
        encoded = base64.b64encode(text.encode("utf-8")).decode("ascii")

        # OSC 52 sequence: \033]52;c;<base64-data>\007
        # 'c' means clipboard (as opposed to 'p' for primary selection)
        osc52_seq = f"\033]52;c;{encoded}\007"

        # Write directly to terminal (bypass any buffering)
        # Use /dev/tty to ensure we write to the controlling terminal
        try:
            with open("/dev/tty", "w") as tty:
                tty.write(osc52_seq)
                tty.flush()
        except OSError:
            # Fallback to stdout if /dev/tty not available
            sys.stdout.write(osc52_seq)
            sys.stdout.flush()

        return True
    except Exception:
        return False


def copy_to_clipboard_fallback(text: str) -> bool:
    """
    Fallback copy using pyperclip (for non-terminal environments).
    """
    try:
        import pyperclip

        pyperclip.copy(text)
        return True
    except Exception:
        return False
