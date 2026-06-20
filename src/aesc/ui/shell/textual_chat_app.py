"""Textual-based chat UI with proper scrolling and Rich integration."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Callable
from typing import Any

from rich.console import RenderableType
from rich.panel import Panel
from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import VerticalScroll
from textual.reactive import reactive
from textual.widgets import Input, Static

from aesc.tools.process_registry import get_registry as get_process_registry
from aesc.ui.shell.theme_detection import detect_terminal_theme, get_textual_theme
from aesc.ui.widgets import (
    ActivityBar,
    HelpDialog,
    LoadingIndicator,
    ResultsDialog,
    ToolSelectionDialog,
)
from aesc.ui.widgets.prompt_bar import EnhancedPromptBar
from aesc.utils.clipboard import copy_to_clipboard, is_clipboard_available
from aesc.utils.logging import logger

# Pattern to detect leaked mouse escape sequences (defensive fallback)
# Primary fix: subprocess stdin=DEVNULL in bash tool prevents most leaks
# This regex catches any edge cases that slip through
_MOUSE_ESCAPE_PATTERN = re.compile(
    r"("
    r"\[?<?\d+;\d+;\d+[Mm]"  # SGR: [<35;81;43M or <35;81;43M or 35;81;43M
    r"|\d+;\d+[Mm]"  # Coordinates: 44;43M
    r"|[Mm];\d*"  # M; or m; followed by optional digits
    r"|[Mm]\d+;\d+"  # M44;43 format
    r"|\[\<\d*"  # [< followed by optional digits (partial escape)
    r"|(?<=[Mm])\["  # [ immediately after M/m
    r"|\[B\[?B?"  # [B or [B[ or [BB patterns
    r"|\[BB?<?\d*"  # [BB<35 etc
    r")"
)

# Performance constants
MAX_VISIBLE_MESSAGES = 200  # Keep only last N messages in DOM
SCROLL_DEBOUNCE_MS = 50  # Debounce scroll_end calls


class MessageWidget(Static):
    """A single message in the chat.

    Performance optimizations:
    - Minimal CSS classes
    - Simple render() that just returns content
    - No reactive properties
    """

    DEFAULT_CSS = """
    MessageWidget {
        width: 100%;
        height: auto;
        padding: 0 1;
    }

    MessageWidget.user-message {
        background: #27272a;
        padding: 1 2;
        margin: 1 0;
        border-left: wide #a855f7;
    }
    """

    def __init__(
        self,
        content: RenderableType,
        is_user_message: bool = False,
        is_tool_call: bool = False,
        is_spacing: bool = False,
        is_system_message: bool = False,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.content = content
        self.is_user_message = is_user_message
        self.is_system_message = is_system_message
        self.is_tool_call = is_tool_call
        self.is_spacing = is_spacing
        if is_user_message:
            self.add_class("user-message")

    def render(self) -> RenderableType:
        """Render the message content."""
        return self.content


class WelcomeWidget(Static):
    """Welcome panel widget - centered and responsive."""

    DEFAULT_CSS = """
    WelcomeWidget {
        width: 100%;
        height: auto;
        padding: 1 0;
        content-align: center middle;
    }
    """

    def __init__(self, panel: Panel, **kwargs):
        super().__init__(**kwargs)
        self.panel = panel

    def render(self) -> RenderableType:
        """Render welcome panel centered."""
        from rich.align import Align

        return Align.center(self.panel)

    def update_panel(self, panel: Panel) -> None:
        """Update the welcome panel content."""
        self.panel = panel
        self.refresh()


class ChatContainer(VerticalScroll):
    """Scrollable container for chat messages."""

    can_focus = False  # Don't steal focus from input

    def __init__(self, welcome_panel: Panel, **kwargs):
        super().__init__(**kwargs)
        self.welcome_panel = welcome_panel

    def on_mount(self) -> None:
        """Add welcome message on mount."""
        self.mount(WelcomeWidget(self.welcome_panel))


# ChatInput removed - all key handling now in App.on_key
# The prompt bar uses standard Textual Input widget


class TextualChatApp(App):
    """
    Textual-based chat application with:
    - Scrollable message history (top)
    - Fixed input prompt (bottom)
    - Status bar (bottom)
    - Auto-scroll to bottom as messages arrive
    - Rich integration for beautiful rendering
    - Dialogs (Help, Tool Selection)
    - Keybindings (Ctrl+H, Ctrl+T, Tab)

    Note: Mouse is disabled to prevent escape sequence leaks from subprocesses.
    """

    ENABLE_COMMAND_PALETTE = False

    # Mouse is enabled for scrolling and clicking
    # Escape sequences are filtered in subprocess output (bash tool)

    # Minimal keybindings - most features via /commands
    BINDINGS = [
        ("escape", "cancel_or_close", "Cancel/Close"),
        ("ctrl+o", "toggle_output", "Toggle Output"),
        ("ctrl+r", "show_results", "Results"),
        ("ctrl+y", "copy_last", "Copy Last"),
        ("ctrl+l", "copy_all", "Copy All"),
    ]

    CSS = """
    Screen {
        background: #09090b;
    }

    /* Chat container - scrollable message area */
    ChatContainer {
        width: 100%;
        height: 1fr;
        background: #09090b;
        border: none;
        scrollbar-gutter: stable;
    }

    /* Activity bar - shows running processes/agents */
    ActivityBar {
        dock: bottom;
        width: 100%;
        height: auto;
        max-height: 10;
        background: #18181b;
        padding: 0 1;
        border-top: solid #27272a;
    }

    ActivityBar.no-activity {
        height: 0;
        display: none;
    }

    ActivityBar.collapsed {
        height: 1;
        max-height: 1;
    }

    /* Loading indicator - shows current task */
    LoadingIndicator {
        dock: bottom;
        width: 100%;
        height: 1;
        background: #18181b;
        padding: 0 1;
    }

    LoadingIndicator.hidden {
        display: none;
    }

    /* Enhanced 3-line prompt bar */
    EnhancedPromptBar {
        dock: bottom;
        width: 100%;
        height: 3;
        background: #18181b;
        border-top: solid #27272a;
    }

    EnhancedPromptBar StatusLine {
        background: #09090b;
    }

    EnhancedPromptBar HintLine {
        background: #18181b;
    }

    EnhancedPromptBar Input {
        background: transparent;
        border: none;
        padding: 0;
        color: #fafafa;
    }

    EnhancedPromptBar Input:focus {
        border: none;
    }
    """

    # Reactive state
    current_tool = reactive("")
    current_agent = reactive("")
    context_percent = reactive(0)

    def __init__(
        self,
        welcome_panel: Panel,
        prompt_text: str = "",
        on_submit: Callable[[str], Any] | None = None,
        on_ready: Callable[[], Any] | None = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.welcome_panel = welcome_panel
        self.prompt_text = prompt_text
        self._on_submit = on_submit
        self._on_ready = on_ready
        self._running = False
        self._exit_exception: BaseException | None = None
        self._ctrl_c_count = 0
        self._ctrl_c_timer: asyncio.Task | None = None
        self._approval_handler: Callable[[str], bool] | None = None
        self._decision_handler: Callable[[str], bool] | None = None
        self._cancel_handler: Callable[[], None] | None = None
        self._message_map: dict[str, MessageWidget] = {}
        self._tool_call_map: dict[str, str] = {}
        self._message_counter = 0  # Monotonic counter for unique IDs
        self._output_toggle_handler: Callable[[], None] | None = None

        # Performance: Track message order for efficient cleanup
        self._message_order: list[str] = []  # Ordered list of message IDs
        self._last_was_spacing = False  # Track if last message was spacing
        self._scroll_scheduled = False  # Debounce scroll calls
        self._pending_scroll = False  # Track if scroll is needed
        self._scroll_task: asyncio.Task | None = None  # Current scroll task (prevent leak)
        self._dom_busy = False  # True during mount/remove — spinner skips refresh

        # Activity bar state
        self._activity_refresh_task: asyncio.Task | None = None
        self._activity_bar_focused: bool = False

        # Subagent tabs and per-agent message buffers
        self._active_agent_id: str | None = None  # None = main agent
        self._agent_messages: dict[
            str, list[tuple[str, Any]]
        ] = {}  # agent_id -> [(msg_id, content)]
        self._main_messages: list[tuple[str, Any]] = []  # Main agent messages

    def compose(self) -> ComposeResult:
        """Create child widgets."""
        self.chat_container = ChatContainer(self.welcome_panel, id="chat-container")
        yield self.chat_container

        # Activity bar (above prompt, shows when activity exists)
        self.activity_bar = ActivityBar(
            on_kill_process=self._kill_process,
            on_kill_agent=self._kill_agent,
        )
        # Start with no-activity class, will be removed when activity detected
        self.activity_bar.add_class("no-activity")
        yield self.activity_bar

        # Loading indicator (shows current task with spinner)
        self.loading_indicator = LoadingIndicator()
        self.loading_indicator.add_class("hidden")
        yield self.loading_indicator

        # Enhanced 3-line prompt bar with status, input, and hints
        self.prompt_bar = EnhancedPromptBar()
        yield self.prompt_bar

        # Keep chat_input reference pointing to the actual input widget
        # This is set in on_mount after prompt_bar is fully composed

    async def on_mount(self) -> None:
        """Set up the app after mounting."""
        self._running = True

        # Get chat_input reference from prompt_bar after it's composed
        self.chat_input = self.prompt_bar.input
        # Also keep status_bar reference for compatibility
        self.status_bar = None  # Removed - functionality moved to prompt_bar

        # Auto-detect and apply terminal theme
        try:
            terminal_theme = detect_terminal_theme()
            textual_theme = get_textual_theme(terminal_theme)
            self.theme = textual_theme
        except Exception:
            # Fallback to dark theme if detection fails
            self.theme = "textual-dark"

        # Focus the input
        try:
            if self.chat_input:
                self.chat_input.focus()
        except Exception:
            pass  # Input widget may not be ready

        # Start activity bar refresh task
        self._activity_refresh_task = asyncio.create_task(self._refresh_activity_loop())

        # Call on_ready callback if provided
        if self._on_ready:
            try:
                result = self._on_ready()
                if asyncio.iscoroutine(result):
                    await result
            except Exception as e:
                # Log but don't crash on callback failure
                from rich.text import Text

                self.add_message(Text(f"Startup error: {e}", style="red"))

    def on_resize(self, event) -> None:
        """Handle terminal resize events.

        Note: Textual already handles resize efficiently, we just need
        to ensure input focus is restored if lost during resize.
        """
        # Don't call refresh(layout=True) - Textual handles this automatically
        # Just ensure input stays focused
        try:
            if hasattr(self, "chat_input") and self.chat_input:
                self.chat_input.focus()
        except Exception:
            pass

    # ─────────────────────────────────────────────────────────────────────────
    # Message Management (Performance Optimized)
    # ─────────────────────────────────────────────────────────────────────────

    def _schedule_scroll(self) -> None:
        """Debounced scroll to bottom - coalesces multiple scroll requests."""
        if self._scroll_scheduled:
            self._pending_scroll = True
            return

        self._scroll_scheduled = True

        async def _do_scroll():
            await asyncio.sleep(SCROLL_DEBOUNCE_MS / 1000)
            self._scroll_scheduled = False
            if self._running:
                self.chat_container.scroll_end(animate=False)
            # Handle any pending scrolls that came in during debounce
            if self._pending_scroll:
                self._pending_scroll = False
                self._schedule_scroll()

        self._scroll_task = asyncio.create_task(_do_scroll())

    def _cleanup_old_messages(self) -> None:
        """Remove oldest messages when exceeding MAX_VISIBLE_MESSAGES.

        Performance: Keeps DOM size bounded to prevent memory issues.
        """
        if len(self._message_order) <= MAX_VISIBLE_MESSAGES:
            return

        # Remove oldest messages (keep user messages and tool calls longer)
        messages_to_remove = len(self._message_order) - MAX_VISIBLE_MESSAGES

        removed = 0
        i = 0
        while removed < messages_to_remove and i < len(self._message_order):
            msg_id = self._message_order[i]
            widget = self._message_map.get(msg_id)

            if widget and not widget.is_user_message:
                # Remove from DOM (set dom_busy to prevent spinner contention)
                self._dom_busy = True
                try:
                    widget.remove()
                except Exception as e:
                    logger.debug(f"Failed to remove widget {msg_id}: {e}")
                finally:
                    self._dom_busy = False
                # Remove from tracking
                self._message_map.pop(msg_id, None)
                self._message_order.pop(i)
                removed += 1
            else:
                i += 1

    def add_message(
        self,
        content: RenderableType,
        scroll: bool = True,
        is_spacing: bool = False,
        is_system_message: bool = False,
    ) -> str:
        """Add a message to the chat history. Returns message ID.

        Args:
            content: The content to display
            scroll: Whether to scroll to bottom (default True for new messages)
            is_spacing: Whether this is a spacing message (for dedup)
            is_system_message: Whether this is a system message (compaction, etc.)
        """
        if not self._running:
            return ""

        msg_id = f"msg_{self._message_counter}"
        self._message_counter += 1
        widget = MessageWidget(
            content, id=msg_id, is_spacing=is_spacing, is_system_message=is_system_message
        )
        self._dom_busy = True
        try:
            self.chat_container.mount(widget)
        finally:
            self._dom_busy = False
        self._message_map[msg_id] = widget
        self._message_order.append(msg_id)
        self._last_was_spacing = is_spacing

        # Periodic cleanup of old messages
        if len(self._message_order) > MAX_VISIBLE_MESSAGES + 50:
            self._cleanup_old_messages()

        # Debounced scroll
        if scroll:
            self._schedule_scroll()

        return msg_id

    def insert_message_before(
        self,
        content: RenderableType,
        before_msg_id: str,
        scroll: bool = True,
    ) -> str:
        """Insert a message BEFORE another message (for correct chronological ordering).

        Used when LLM sends tool calls before explanation text - the text should
        visually appear before the tool call.

        Args:
            content: The content to display
            before_msg_id: The message ID to insert before
            scroll: Whether to scroll to bottom (default True)

        Returns:
            The new message ID, or empty string if insertion failed
        """
        if not self._running:
            return ""

        # Get the widget to insert before
        before_widget = self._message_map.get(before_msg_id)
        if not before_widget:
            # Fallback to normal append if target not found
            return self.add_message(content, scroll=scroll)

        msg_id = f"msg_{self._message_counter}"
        self._message_counter += 1
        widget = MessageWidget(content, id=msg_id)

        # Mount before the target widget
        self._dom_busy = True
        try:
            self.chat_container.mount(widget, before=before_widget)
        finally:
            self._dom_busy = False
        self._message_map[msg_id] = widget

        # Insert into message order at correct position
        try:
            idx = self._message_order.index(before_msg_id)
            self._message_order.insert(idx, msg_id)
        except ValueError:
            self._message_order.append(msg_id)

        self._last_was_spacing = False

        if scroll:
            self._schedule_scroll()

        return msg_id

    def add_user_message(self, text: str) -> None:
        """Add a user message with styled prompt symbol."""
        # Add spacing before prompt (deduped)
        self.add_spacing()

        # Create styled message content with brand-purple star
        message_content = Text()
        message_content.append("✶", style="bold #a855f7")
        message_content.append(" ", style="")
        message_content.append(text, style="bold")

        msg_id = f"msg_{self._message_counter}"
        self._message_counter += 1
        widget = MessageWidget(message_content, is_user_message=True, id=msg_id)
        self._dom_busy = True
        try:
            self.chat_container.mount(widget)
        finally:
            self._dom_busy = False
        self._message_map[msg_id] = widget
        self._message_order.append(msg_id)
        self._last_was_spacing = False

        # Add spacing after prompt
        self.add_spacing()

        # Scroll after user message
        self._schedule_scroll()

    def update_last_message(self, content: RenderableType) -> None:
        """Update the last message (for streaming). Skips user messages and tool calls."""
        if not self._running or not self._message_order:
            self.add_message(content)
            return

        # Get last non-spacing message
        last_msg_id = self._message_order[-1]
        last_message = self._message_map.get(last_msg_id)

        if not last_message:
            self.add_message(content)
            return

        # Don't update user messages or tool calls - they're immutable
        if last_message.is_user_message or last_message.is_tool_call:
            self.add_message(content)
            return

        last_message.content = content
        last_message.refresh()
        self._schedule_scroll()

    def remove_last_message(self) -> None:
        """Remove the last message from chat (used to remove approval UI)."""
        if not self._running or not self._message_order:
            return

        last_msg_id = self._message_order[-1]
        if last_msg_id in self._message_map:
            try:
                self._message_map[last_msg_id].remove()
            except Exception as e:
                logger.debug(f"Failed to remove last message {last_msg_id}: {e}")
            self._message_map.pop(last_msg_id, None)
            self._message_order.pop()

    def remove_message(self, message_id: str) -> None:
        """Remove a specific message by its ID."""
        if not self._running:
            return

        if message_id in self._message_map:
            try:
                self._message_map[message_id].remove()
            except Exception as e:
                logger.debug(f"Failed to remove message {message_id}: {e}")
            self._message_map.pop(message_id, None)
            # Remove from order list
            try:
                self._message_order.remove(message_id)
            except ValueError:
                pass

    def add_spacing(self) -> None:
        """Add single blank line for section separation.

        Performance: Uses flag to avoid O(n) query check.
        """
        if not self._running:
            return

        # Fast path: check flag instead of querying DOM
        if self._last_was_spacing:
            return

        self.add_message(Text(""), scroll=False, is_spacing=True)

    def insert_spacing_before(self, before_msg_id: str) -> None:
        """Insert spacing BEFORE a specific message (for message ordering).

        Used when text is inserted before tool calls - the spacing after
        text should also be before the tool call.
        """
        if not self._running:
            return

        # Don't insert duplicate spacing
        if self._last_was_spacing:
            return

        self.insert_message_before(Text(""), before_msg_id, scroll=False)
        self._last_was_spacing = True

    def update_message(
        self, message_id: str, content: RenderableType, scroll: bool = False
    ) -> None:
        """Update a message by its ID (for streaming updates)."""
        if not self._running:
            return

        widget = self._message_map.get(message_id)
        if not widget:
            return

        widget.content = content
        widget.refresh()

        if scroll:
            self._schedule_scroll()

    # ─────────────────────────────────────────────────────────────────────────
    # Tool Call Management
    # ─────────────────────────────────────────────────────────────────────────

    def map_tool_call_to_message(self, tool_call_id: str, message_id: str) -> None:
        """Map tool call ID to message ID for later updates."""
        self._tool_call_map[tool_call_id] = message_id

    def update_tool_call_message(self, tool_call_id: str, content: RenderableType) -> None:
        """Update tool call message (spinner → checkmark/X)."""
        if not self._running:
            return

        if tool_call_id not in self._tool_call_map:
            return

        message_id = self._tool_call_map[tool_call_id]
        if message_id not in self._message_map:
            return

        widget = self._message_map[message_id]
        widget.content = content
        widget.refresh()

    # ─────────────────────────────────────────────────────────────────────────
    # Approval & Status
    # ─────────────────────────────────────────────────────────────────────────

    def set_approval_handler(self, handler: Callable[[str], bool] | None) -> None:
        """Set approval keyboard handler (or clear it)."""
        self._approval_handler = handler

    def set_decision_handler(self, handler: Callable[[str], bool] | None) -> None:
        """Set decision keyboard handler (or clear it)."""
        self._decision_handler = handler

    def set_output_toggle_handler(self, handler: Callable[[], None] | None) -> None:
        """Set handler for Ctrl+O output toggle."""
        self._output_toggle_handler = handler

    def set_cancel_handler(self, handler: Callable[[], None] | None) -> None:
        """Set handler for Escape cancel (generation interrupt)."""
        self._cancel_handler = handler

    def update_status(self, status) -> None:
        """Update status bar with new status."""
        try:
            if self._running and hasattr(self, "status_bar") and self.status_bar:
                self.status_bar.update(status)
        except Exception:
            pass  # Status bar not ready or invalid

    def update_welcome_model(
        self,
        model_name: str,
        directory: str | None = None,
        session_id: str | None = None,
    ) -> None:
        """Update welcome panel after setup with model, directory, and session.

        Uses the same _create_welcome_panel function as the original,
        ensuring consistent styling.
        """
        try:
            from aesc.ui.shell import WelcomeInfoItem, _create_welcome_panel

            # Create info items matching original format
            info_items = []
            if directory:
                info_items.append(
                    WelcomeInfoItem(
                        name="Directory",
                        value=directory,
                        level=WelcomeInfoItem.Level.INFO,
                    )
                )
            if session_id:
                info_items.append(
                    WelcomeInfoItem(
                        name="Session",
                        value=session_id,
                        level=WelcomeInfoItem.Level.INFO,
                    )
                )
            info_items.append(
                WelcomeInfoItem(
                    name="Model",
                    value=model_name,
                    level=WelcomeInfoItem.Level.INFO,
                )
            )

            new_panel = _create_welcome_panel("aesc", info_items)

            # Update stored welcome panel for future clear operations
            self.welcome_panel = new_panel

            # Update any existing welcome widgets
            welcome_widgets = self.query(WelcomeWidget)
            for widget in welcome_widgets:
                widget.update_panel(new_panel)
                break
        except Exception as e:
            logger.debug(f"Welcome panel update skipped: {e}")

    # ─────────────────────────────────────────────────────────────────────────
    # App Lifecycle
    # ─────────────────────────────────────────────────────────────────────────

    async def run_async(self) -> None:
        """Run the chat application."""
        self._running = True
        try:
            await super().run_async()
            if self._exit_exception:
                raise self._exit_exception
        finally:
            self._running = False
            # Clean up activity refresh task
            if self._activity_refresh_task:
                self._activity_refresh_task.cancel()
                try:
                    await self._activity_refresh_task
                except asyncio.CancelledError:
                    pass
            # Clean up scroll task
            if self._scroll_task and not self._scroll_task.done():
                self._scroll_task.cancel()
                try:
                    await self._scroll_task
                except asyncio.CancelledError:
                    pass
            # Clean up Ctrl+C timer
            if self._ctrl_c_timer and not self._ctrl_c_timer.done():
                self._ctrl_c_timer.cancel()
                try:
                    await self._ctrl_c_timer
                except asyncio.CancelledError:
                    pass

    def action_quit(self) -> None:
        """Handle quit action."""
        self._exit_exception = KeyboardInterrupt()
        self.exit()

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle input submission from ChatInput."""
        if event.input.id not in ("chat-input", "prompt-input"):
            return

        text = (event.value or "").strip()
        if text and self._on_submit:
            event.input.value = ""
            # Show loading indicator immediately (prevents blank screen)
            if hasattr(self, "loading_indicator"):
                self.loading_indicator.set_thinking()
            result = self._on_submit(text)
            if asyncio.iscoroutine(result):
                await result

    # ─────────────────────────────────────────────────────────────────────────
    # Mouse Event Handlers (kept for reference, but mouse=False disables these)
    # ─────────────────────────────────────────────────────────────────────────
    # Note: Mouse tracking is disabled to prevent escape sequence leaks.
    # These handlers remain for when/if mouse support is re-enabled.

    # ─────────────────────────────────────────────────────────────────────────
    # Keyboard Event Handler
    # ─────────────────────────────────────────────────────────────────────────

    def on_key(self, event) -> None:
        """Handle key events globally.

        This handles:
        - Activity bar navigation (when focused)
        - Approval panel keys (y/n/a)
        - Decision panel keys (a-d, 1-4)
        - Activity bar expansion (down arrow)
        - Ctrl+C/Ctrl+D shortcuts
        """
        # Filter mouse escape sequences that might leak through
        if event.character and _MOUSE_ESCAPE_PATTERN.search(event.character):
            event.prevent_default()
            event.stop()
            return

        # Handle activity bar navigation when focused
        if self._activity_bar_focused:
            if not hasattr(self, "activity_bar") or not self.activity_bar.has_activity:
                self._activity_bar_focused = False
            else:
                handled = self._handle_activity_bar_key(event.key)
                if handled:
                    event.prevent_default()
                    event.stop()
                    return

        # Check if approval handler wants to handle this key (y/n/a/arrows/enter)
        if self._approval_handler:
            approval_keys = ("y", "n", "a", "up", "down", "enter")
            if event.key in approval_keys:
                handled = self._approval_handler(event.key)
                if handled:
                    event.prevent_default()
                    event.stop()
                    return

        # Check if decision handler wants to handle this key
        if self._decision_handler:
            decision_keys = ("a", "b", "c", "d", "1", "2", "3", "4", "up", "down", "enter")
            if event.key in decision_keys:
                handled = self._decision_handler(event.key)
                if handled:
                    event.prevent_default()
                    event.stop()
                    return

        # Arrow down expands activity bar when it has items
        if event.key == "down":
            try:
                if hasattr(self, "activity_bar"):
                    if self.activity_bar.has_activity and not self.activity_bar.is_expanded:
                        self.activity_bar.expand()
                        self._activity_bar_focused = True
                        self.notify("↑↓ navigate  k:kill  ESC:close", timeout=3)
                        event.prevent_default()
                        event.stop()
                        return
            except Exception as e:
                logger.debug(f"Activity bar expand error: {e}")

        # Tab key - prevent default focus switching
        if event.key == "tab":
            event.prevent_default()
            return

        # Ctrl+D - EOF (exit if input is empty)
        if event.key == "ctrl+d":
            if self.chat_input is None or not self.chat_input.value:
                self._exit_exception = EOFError()
                self.exit()
            return

        # Ctrl+C - Cancel/Interrupt (double press to exit)
        if event.key == "ctrl+c":
            self._ctrl_c_count += 1

            if self._ctrl_c_count == 1:
                from rich.text import Text

                self.add_message(Text("Press Ctrl+C again to exit", style="yellow"))

                # Reset counter after 2 seconds
                if self._ctrl_c_timer and not self._ctrl_c_timer.done():
                    self._ctrl_c_timer.cancel()

                async def reset_counter():
                    try:
                        await asyncio.sleep(2)
                        self._ctrl_c_count = 0
                    except asyncio.CancelledError:
                        pass  # Timer was cancelled, that's fine
                    except Exception:
                        pass  # Suppress any unexpected errors

                self._ctrl_c_timer = asyncio.create_task(reset_counter())

            elif self._ctrl_c_count >= 2:
                self._exit_exception = KeyboardInterrupt()
                self.exit()

            event.prevent_default()
            event.stop()

    # ─────────────────────────────────────────────────────────────────────────
    # Action Methods (Keybindings)
    # ─────────────────────────────────────────────────────────────────────────

    def action_cancel_or_close(self) -> None:
        """Cancel generation or close dialog (Escape)."""
        # If activity bar is expanded, collapse it first
        if self._activity_bar_focused:
            self.activity_bar.collapse()
            self._activity_bar_focused = False
            return

        # If there's a cancel handler (generation in progress), use it
        if self._cancel_handler:
            self._cancel_handler()
            self.notify("Interrupted - ready for new prompt", severity="warning", timeout=2)
            # Focus back to input
            try:
                self.chat_input.focus()
            except Exception:
                pass
        # Otherwise handled by screen stack (closes dialogs)

    def action_toggle_output(self) -> None:
        """Toggle tool output expansion (Ctrl+O)."""
        if self._output_toggle_handler:
            self._output_toggle_handler()

    async def action_show_help(self) -> None:
        """Show help dialog - called via /help command."""
        await self.push_screen(HelpDialog())

    async def action_select_tool(self) -> None:
        """Show tool selection dialog - called via /tools command."""
        selected_tool = await self.push_screen_wait(
            ToolSelectionDialog(current_tool=self.current_tool)
        )
        if selected_tool:
            self.current_tool = selected_tool

            from rich.text import Text

            notif = Text()
            notif.append("Switched to ", style="green")
            notif.append(selected_tool, style="cyan bold")
            notif.append(" tool", style="green")
            self.add_message(notif)

    async def action_show_results(self) -> None:
        """Show results folder viewer - called via /results command."""
        await self.push_screen(ResultsDialog())

    def _extract_text_from_renderable(self, content: RenderableType) -> str:
        """Extract plain text from a Rich renderable."""
        from io import StringIO

        from rich.console import Console

        buffer = StringIO()
        console = Console(file=buffer, force_terminal=False, no_color=True, width=200)
        console.print(content)
        return buffer.getvalue()

    def action_copy_last(self) -> None:
        """Copy last assistant response to clipboard (Ctrl+Y)."""
        if not is_clipboard_available():
            self.notify("No TTY available", severity="warning")
            return

        for msg_id in reversed(self._message_order):
            widget = self._message_map.get(msg_id)
            if widget and not widget.is_user_message and not widget.is_spacing:
                text = self._extract_text_from_renderable(widget.content).strip()
                if text:
                    if copy_to_clipboard(text):
                        lines = len(text.split("\n"))
                        self.notify(f"Copied {lines} lines", severity="information")
                    else:
                        self.notify("Copy failed", severity="error")
                    return

        self.notify("Nothing to copy", severity="warning")

    def action_copy_all(self) -> None:
        """Copy entire conversation to clipboard (Ctrl+L)."""
        if not is_clipboard_available():
            self.notify("No TTY available", severity="warning")
            return

        lines = []
        for msg_id in self._message_order:
            widget = self._message_map.get(msg_id)
            if widget and not widget.is_spacing:
                text = self._extract_text_from_renderable(widget.content).strip()
                if text:
                    prefix = "USER:" if widget.is_user_message else "ASSISTANT:"
                    lines.append(f"{prefix}\n{text}\n")

        if not lines:
            self.notify("Nothing to copy", severity="warning")
            return

        full_text = "\n".join(lines)
        if copy_to_clipboard(full_text):
            self.notify(f"Copied {len(lines)} messages", severity="information")
        else:
            self.notify("Copy failed", severity="error")

    def clear_and_show_welcome(self) -> None:
        """Clear all messages and show welcome screen again."""
        if not self._running:
            return

        # Remove all messages from display
        self._dom_busy = True
        try:
            for msg_id in list(self._message_order):
                widget = self._message_map.get(msg_id)
                if widget:
                    try:
                        widget.remove()
                    except Exception as e:
                        logger.debug(f"Failed to remove widget during clear: {e}")
        finally:
            self._dom_busy = False
        self._message_map.clear()
        self._message_order.clear()
        self._tool_call_map.clear()
        self._last_was_spacing = False

        # Remove existing welcome widgets first
        try:
            for widget in self.query(WelcomeWidget):
                widget.remove()
        except Exception as e:
            logger.debug(f"Failed to remove welcome widgets: {e}")

        # Re-add welcome panel
        try:
            self.chat_container.mount(WelcomeWidget(self.welcome_panel))
        except Exception as e:
            logger.debug(f"Failed to mount welcome panel: {e}")

    # ─────────────────────────────────────────────────────────────────────────
    # Reactive Watchers
    # ─────────────────────────────────────────────────────────────────────────

    def watch_current_tool(self, tool: str) -> None:
        """React to tool changes."""
        pass  # No longer shown in status bar

    def watch_current_agent(self, agent: str) -> None:
        """React to agent changes."""
        pass  # No longer shown in status bar

    def watch_context_percent(self, percent: int) -> None:
        """React to context percentage changes."""
        if hasattr(self, "prompt_bar"):
            self.prompt_bar.update_context(percent)

    # ─────────────────────────────────────────────────────────────────────────
    # Activity Bar
    # ─────────────────────────────────────────────────────────────────────────

    async def _refresh_activity_loop(self) -> None:
        """Periodically refresh activity bar and prompt bar with running processes/subagents."""
        from aesc.soul.subagent_registry import get_registry as get_subagent_registry

        # Cache previous counts to skip no-op refreshes
        _prev_proc_count = -1
        _prev_agent_count = -1

        while self._running:
            try:
                await asyncio.sleep(1.0)  # Activity status doesn't need high frequency
                if not self._running:
                    break

                # Get running processes
                process_registry = get_process_registry()
                processes = process_registry.get_all()

                # Get running subagents
                subagent_registry = get_subagent_registry()
                subagents = subagent_registry.get_running()

                proc_count = len(processes)
                agent_count = len(subagents)

                # Skip update if nothing changed (avoids expensive re-renders)
                if proc_count == _prev_proc_count and agent_count == _prev_agent_count:
                    continue
                _prev_proc_count = proc_count
                _prev_agent_count = agent_count

                # Update activity bar with both
                if hasattr(self, "activity_bar"):
                    self.activity_bar.update_activity(processes=processes, subagents=subagents)

                # Update prompt bar with activity (uses new 3-line design)
                total_running = proc_count + agent_count
                if hasattr(self, "prompt_bar"):
                    # Get current task description if any subagent is running
                    current_task = ""
                    if subagents:
                        current_task = (
                            subagents[0].prompt[:40]
                            if subagents[0].prompt
                            else subagents[0].agent_name
                        )

                    self.prompt_bar.update_activity(
                        tool_count=proc_count,
                        agent_count=agent_count,
                        is_thinking=total_running > 0,
                        current_task=current_task,
                    )

            except asyncio.CancelledError:
                break
            except Exception:
                pass  # Ignore refresh errors

    def _kill_process(self, tool_call_id: str) -> None:
        """Kill a running process by tool call ID."""
        registry = get_process_registry()
        if registry.kill(tool_call_id):
            self.notify("Process killed", severity="warning")
        else:
            self.notify("Process not found", severity="error")

    def _kill_agent(self, task_tool_call_id: str) -> None:
        """Kill a running subagent by task tool call ID."""
        import asyncio

        from aesc.soul.subagent_registry import get_registry as get_subagent_registry

        async def do_kill():
            registry = get_subagent_registry()
            if await registry.kill(task_tool_call_id):
                self.notify("Agent killed", severity="warning")
            else:
                self.notify("Agent not found", severity="error")

        asyncio.create_task(do_kill())

    def _handle_activity_bar_key(self, key: str) -> bool:
        """Handle keyboard input for activity bar.

        Returns True if key was handled, False otherwise.
        """
        if not hasattr(self, "activity_bar"):
            return False

        try:
            if key == "up":
                self.activity_bar.select_prev()
                return True
            elif key == "down":
                self.activity_bar.select_next()
                return True
            elif key == "k":
                self.activity_bar.kill_selected()
                return True
            elif key == "enter":
                self.activity_bar.inspect_selected()
                return True
            elif key == "escape" or key == "tab":
                # Collapse and return focus to input
                self._activity_bar_focused = False
                self.activity_bar.collapse()
                if hasattr(self, "chat_input"):
                    self.chat_input.focus()
                return True
        except Exception as e:
            # Log error but don't crash
            import logging

            logging.getLogger(__name__).warning(f"Activity bar key error: {e}")
            self._activity_bar_focused = False
            return False

        return False
