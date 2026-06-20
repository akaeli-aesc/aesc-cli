"""Chat-style UI layout for AESC CLI - Modern chat interface."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from prompt_toolkit import Application
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.formatted_text import FormattedText, StyleAndTextTuples
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import (
    HSplit,
    Layout,
    Window,
)
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
from rich.console import Console, RenderableType
from rich.panel import Panel

from aesc.ui.shell.console import console as rich_console


@dataclass
class ChatMessage:
    """A message in the chat history."""

    content: RenderableType
    is_user: bool = False


class ChatLayout:
    """WhatsApp-style chat layout with fixed bottom input."""

    def __init__(
        self,
        welcome_panel: Panel,
        prompt_symbol: str = "",
        on_input: Callable[[str], Any] | None = None,
    ):
        self.welcome_panel = welcome_panel
        self.prompt_symbol = prompt_symbol
        self.on_input = on_input
        self.messages: list[ChatMessage] = []
        self._input_text = ""

        # Create a string-based console for rendering to text
        from io import StringIO

        self._string_buffer = StringIO()
        self._string_console = Console(
            file=self._string_buffer,
            force_terminal=False,
            width=rich_console.width,
        )

        # Input buffer
        self.input_buffer = Buffer(
            multiline=False,
            on_text_insert=self._on_text_change,
        )

        # Key bindings
        kb = KeyBindings()

        @kb.add("enter")
        def _(event):
            text = self.input_buffer.text.strip()
            if text:
                # Add user message
                self.add_user_message(text)
                # Clear input
                self.input_buffer.reset()
                # Callback
                if self.on_input:
                    asyncio.create_task(self._handle_input(text))

        @kb.add("c-c")
        def _(event):
            event.app.exit(exception=KeyboardInterrupt)

        @kb.add("c-d")
        def _(event):
            if not self.input_buffer.text:
                event.app.exit(exception=EOFError)

        # Message display control
        self.message_control = FormattedTextControl(
            text=self._get_message_text,
            focusable=False,
        )

        # Message window (scrollable)
        self.message_window = Window(
            content=self.message_control,
            wrap_lines=True,
            always_hide_cursor=True,
        )

        # Input control
        self.input_control = BufferControl(
            buffer=self.input_buffer,
            focus_on_click=True,
        )

        # Input window (fixed at bottom)
        self.input_window = Window(
            content=self.input_control,
            height=1,
            always_hide_cursor=False,
            prompt=lambda: FormattedText([("class:prompt", self.prompt_symbol)]),
        )

        # Layout
        self.layout = Layout(
            HSplit(
                [
                    self.message_window,  # Scrollable messages
                    self.input_window,  # Fixed input
                ]
            )
        )

        # Application
        self.app = Application(
            layout=self.layout,
            key_bindings=kb,
            full_screen=True,
            mouse_support=True,
        )

    def _on_text_change(self, _):
        """Handle text changes in input buffer."""
        self._input_text = self.input_buffer.text

    async def _handle_input(self, text: str):
        """Handle user input."""
        if self.on_input:
            try:
                result = self.on_input(text)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as e:
                self.add_system_message(f"Error: {e}")

    def _get_message_text(self) -> StyleAndTextTuples:
        """Get formatted text for all messages."""
        # Render welcome panel first
        self._string_buffer.truncate(0)
        self._string_buffer.seek(0)

        # Center welcome panel
        from rich.align import Align

        self._string_console.print(Align.center(self.welcome_panel))
        self._string_console.print()  # Empty line

        # Render messages
        for msg in self.messages:
            if msg.is_user:
                # User messages with prompt symbol
                self._string_console.print(f"{self.prompt_symbol}{msg.content}")
            else:
                # System/agent messages
                self._string_console.print(msg.content)
            self._string_console.print()  # Empty line between messages

        # Get rendered text
        text = self._string_buffer.getvalue()

        # Convert to FormattedText
        return [("", text)]

    def add_user_message(self, text: str):
        """Add a user message to the chat."""
        self.messages.append(ChatMessage(content=text, is_user=True))
        self.app.invalidate()

    def add_system_message(self, content: RenderableType):
        """Add a system/agent message to the chat."""
        self.messages.append(ChatMessage(content=content, is_user=False))
        self.app.invalidate()

    def add_rich_content(self, renderable: RenderableType):
        """Add rich content (Panel, Text, etc.) to chat."""
        self.add_system_message(renderable)

    async def run_async(self):
        """Run the chat application."""
        return await self.app.run_async()
