"""Tests for aesc.ui.shell.keyboard module."""

from __future__ import annotations

import sys
import threading
from unittest.mock import MagicMock, patch

import pytest

from aesc.ui.shell.keyboard import KeyEvent, listen_for_keyboard


class TestKeyEvent:
    """Test KeyEvent enum."""

    def test_key_events_exist(self):
        """All key events should exist."""
        assert KeyEvent.UP
        assert KeyEvent.DOWN
        assert KeyEvent.LEFT
        assert KeyEvent.RIGHT
        assert KeyEvent.ENTER
        assert KeyEvent.ESCAPE
        assert KeyEvent.TAB

    def test_key_events_are_unique(self):
        """Each key event has a unique value."""
        values = [e.value for e in KeyEvent]
        assert len(values) == len(set(values))

    def test_key_event_count(self):
        """Should have 7 key events."""
        assert len(KeyEvent) == 7


class TestArrowKeyMapping:
    """Test arrow key escape sequence mapping."""

    def test_arrow_key_sequences(self):
        """Arrow keys have standard escape sequences."""
        from aesc.ui.shell.keyboard import _ARROW_KEY_MAP

        # Standard ANSI escape sequences for arrow keys
        assert _ARROW_KEY_MAP.get(b"\x1b[A") == KeyEvent.UP
        assert _ARROW_KEY_MAP.get(b"\x1b[B") == KeyEvent.DOWN
        assert _ARROW_KEY_MAP.get(b"\x1b[C") == KeyEvent.RIGHT
        assert _ARROW_KEY_MAP.get(b"\x1b[D") == KeyEvent.LEFT


@pytest.mark.skipif(sys.platform == "win32", reason="Unix-only tests")
class TestUnixKeyboardListener:
    """Test Unix keyboard listener."""

    def test_non_tty_graceful_exit(self):
        """Non-TTY stdin exits gracefully."""
        from aesc.ui.shell.keyboard import _listen_for_keyboard_unix

        cancel = threading.Event()
        events = []

        def emit(event):
            events.append(event)

        # Mock isatty to return False (not a terminal)
        with patch("os.isatty", return_value=False):
            _listen_for_keyboard_unix(cancel, emit)

        # Should exit without error or events
        assert events == []

    def test_stdin_not_available(self):
        """Missing stdin exits gracefully."""
        from aesc.ui.shell.keyboard import _listen_for_keyboard_unix

        cancel = threading.Event()
        events = []

        def emit(event):
            events.append(event)

        # Mock fileno to raise OSError
        mock_stdin = MagicMock()
        mock_stdin.fileno.side_effect = OSError("No stdin")

        with patch.object(sys, "stdin", mock_stdin):
            _listen_for_keyboard_unix(cancel, emit)

        assert events == []

    def test_termios_setup_failure(self):
        """Termios setup failure exits gracefully."""
        from aesc.ui.shell.keyboard import _listen_for_keyboard_unix

        cancel = threading.Event()
        events = []

        def emit(event):
            events.append(event)

        # Mock isatty to return True, but tcgetattr to fail
        with patch("os.isatty", return_value=True):
            with patch("termios.tcgetattr", side_effect=OSError("No terminal")):
                _listen_for_keyboard_unix(cancel, emit)

        assert events == []


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-only tests")
class TestWindowsKeyboardListener:
    """Test Windows keyboard listener."""

    def test_windows_listener_exists(self):
        """Windows listener function exists."""
        from aesc.ui.shell.keyboard import _listen_for_keyboard_windows

        assert callable(_listen_for_keyboard_windows)


class TestListenForKeyboard:
    """Test the main listen_for_keyboard async generator."""

    @pytest.mark.asyncio
    async def test_generator_type(self):
        """listen_for_keyboard returns an async generator."""
        gen = listen_for_keyboard()
        assert hasattr(gen, "__anext__")
        # Clean up - cancel the generator
        await gen.aclose()

    @pytest.mark.asyncio
    async def test_cancel_stops_listener(self):
        """Closing the generator stops the listener thread."""
        gen = listen_for_keyboard()

        # Start and immediately close
        await gen.aclose()

        # Should complete without hanging


class TestKeyEventUsage:
    """Test practical usage of KeyEvent."""

    def test_key_in_list(self):
        """KeyEvent can be checked against a list."""
        navigation_keys = [KeyEvent.UP, KeyEvent.DOWN, KeyEvent.LEFT, KeyEvent.RIGHT]

        assert KeyEvent.UP in navigation_keys
        assert KeyEvent.ENTER not in navigation_keys

    def test_key_comparison(self):
        """KeyEvent can be compared."""
        key = KeyEvent.ENTER

        assert key == KeyEvent.ENTER
        assert key != KeyEvent.ESCAPE

    def test_key_as_dict_key(self):
        """KeyEvent can be used as dictionary key."""
        handlers = {
            KeyEvent.UP: "move_up",
            KeyEvent.DOWN: "move_down",
            KeyEvent.ENTER: "select",
        }

        assert handlers[KeyEvent.UP] == "move_up"
        assert handlers.get(KeyEvent.ESCAPE) is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
