"""Textual-based visualizer - Professional UI following Kimi-CLI patterns.

Key improvements:
- Clean separation of live vs final rendering
- Professional widget classes for tool calls and approvals
- Consistent spacing (1 blank line between sections)
- No debug logging (production-ready)
- Proper approval panel lifecycle (appears → disappears after action)
"""

from __future__ import annotations

import asyncio
import contextlib
import os
from typing import TYPE_CHECKING

from rich.markdown import Markdown as RichMarkdown
from rich.text import Text

from aesc.provider import TextPart, ThinkPart, ToolCall, ToolCallPart, ToolResult
from aesc.security.risk import RiskLevel
from aesc.soul import StatusSnapshot
from aesc.tools.utils import ToolRejectedError
from aesc.ui.widgets.approval_panel import ApprovalPanel
from aesc.ui.widgets.compaction_panel import CompactionPanel
from aesc.ui.widgets.decision_panel import DecisionPanel
from aesc.ui.widgets.tool_call_display import ToolCallDisplay
from aesc.wire import WireUISide
from aesc.wire.message import (
    ApprovalRequest,
    CompactionBegin,
    CompactionEnd,
    StatusUpdate,
    StepBegin,
    StepInterrupted,
    SubagentEvent,
    ToolOutputChunk,
    WireMessage,
)

if TYPE_CHECKING:
    from aesc.ui.shell.textual_chat_app import TextualChatApp


async def visualize_for_textual(
    wire: WireUISide,
    *,
    chat_app: TextualChatApp | None,
    initial_status: StatusSnapshot,
    cancel_event: asyncio.Event | None = None,
):
    """
    Visualize agent behavior for TextualChatApp.

    Clean architecture:
    1. Receive wire messages
    2. Update internal state
    3. Render to chat_app using widget classes
    """
    if not chat_app:
        return

    visualizer = _TextualVisualizer(chat_app, initial_status, cancel_event)
    await visualizer.run(wire)


class _TextualVisualizer:
    """
    Professional visualizer outputting to TextualChatApp.

    Pattern: Kimi-CLI's visualize.py:59-480
    Architecture:
    - Separate state tracking from rendering
    - Use widget classes for complex UI (ToolCallDisplay, ApprovalPanel)
    - Single responsibility: translate wire messages → chat messages
    """

    def __init__(
        self,
        chat_app: TextualChatApp,
        initial_status: StatusSnapshot,
        cancel_event: asyncio.Event | None = None,
    ):
        self.chat_app = chat_app
        self.cancel_event = cancel_event
        self._status = initial_status

        # Current streaming content (accumulated until flush)
        self._current_text = ""
        self._is_thinking = False
        self._streaming_message_id: str | None = None  # Track streaming message for updates

        # Tool calls tracking
        self._tool_displays: dict[str, ToolCallDisplay] = {}
        self._tool_call_order: list[str] = []
        self._active_tool_ids: set[str] = set()  # Tools that need periodic refresh

        # Message ordering: Track first tool call message ID in current step
        # Used to insert explanation text BEFORE tool calls when LLM sends tool first
        self._first_tool_msg_id_this_step: str | None = None
        self._step_has_shown_tool: bool = False  # True if any tool call displayed this step

        # Approval tracking - queue for handling parallel approval requests
        # Tuple: (request, panel, panel_msg_id, is_subagent)
        self._approval_panel: tuple[ApprovalRequest, ApprovalPanel, str, bool] | None = None
        self._pending_approvals: list[ApprovalRequest] = []  # Queue for parallel requests

        # Spinner refresh task
        self._spinner_task: asyncio.Task | None = None

        # Tool call collapsing - group consecutive similar tools
        self._collapsed_groups: dict[str, list[str]] = {}  # group_msg_id -> [tool_call_ids]
        self._tool_to_group: dict[str, str] = {}  # tool_call_id -> group_msg_id
        self._last_tool_name: str | None = None
        self._current_group_msg_id: str | None = None
        self._collapse_threshold = 3  # Collapse after this many consecutive same-type tools

        # Decision watching
        self._decision_watcher_task: asyncio.Task | None = None
        # Tuple: (decision_id, panel_msg_id, panel)
        self._pending_decision: tuple[str, str, DecisionPanel] | None = None
        self._known_decisions: set[str] = set()  # Track decisions we've already shown

        # Adaptive polling for decision watcher
        self._decision_poll_interval = 0.5  # Start fast
        self._decision_poll_min = 0.3  # Minimum interval when active
        self._decision_poll_max = 2.0  # Maximum interval when idle
        self._decision_poll_backoff = 1.5  # Multiplier when no activity
        self._decision_last_activity = False  # Track if last poll found something

        # Compaction tracking
        self._compaction_in_progress = False
        self._compaction_panels: dict[str, CompactionPanel] = {}  # msg_id -> panel

        # Approval collapsing — group consecutive approvals into single summary
        self._last_approval_msg_id: str | None = None
        self._consecutive_approval_count: int = 0
        self._max_approval_risk: RiskLevel | None = None  # Highest risk in collapsed group

        # Register output toggle handler
        self.chat_app.set_output_toggle_handler(self._toggle_all_outputs)

        # Register cancel handler for ESC key
        if self.cancel_event:
            self.chat_app.set_cancel_handler(self._on_cancel)

        # Performance: limit history to prevent unbounded growth
        self._max_tool_history = 50  # Keep last N tool calls in memory

    def _on_cancel(self) -> None:
        """Handle ESC key - cancel generation and reject pending approvals."""
        import asyncio

        # Reject current approval panel
        if self._approval_panel is not None:
            request, panel, panel_msg_id, _is_subagent = self._approval_panel
            if not request.resolved:
                request.respond(False)  # Reject
            # Remove panel from UI
            self.chat_app.remove_message(panel_msg_id)
            self._approval_panel = None
            self.chat_app.set_approval_handler(None)

        # Reject all pending approvals in queue
        for request in self._pending_approvals:
            if not request.resolved:
                request.respond(False)
        self._pending_approvals.clear()

        # Kill all running bash processes
        try:
            from aesc.tools.process_registry import get_registry as get_process_registry

            proc_registry = get_process_registry()
            for proc in list(proc_registry.get_running()):
                proc_registry.kill(proc.tool_call_id)
        except Exception as e:
            from aesc.utils.logging import logger

            logger.debug(f"Failed to kill running processes: {e}")

        # Kill all running subagents
        try:
            from aesc.soul.subagent_registry import get_registry as get_subagent_registry

            async def kill_all_subagents():
                registry = get_subagent_registry()
                for session in list(registry.get_running()):
                    await registry.kill(session.task_tool_call_id)

            # Run in background - don't block
            asyncio.create_task(kill_all_subagents())
        except Exception as e:
            from aesc.utils.logging import logger

            logger.debug(f"Failed to kill running subagents: {e}")

        # Set cancel event to stop generation
        if self.cancel_event:
            self.cancel_event.set()

        # Clear loading indicator
        if hasattr(self.chat_app, "loading_indicator"):
            self.chat_app.loading_indicator.clear()

    def _cleanup_old_tools(self):
        """Clean up old tool displays to prevent memory leaks.

        Performance: Also cleans up collapsed groups and tool-to-group mappings.
        """
        if len(self._tool_call_order) <= self._max_tool_history:
            return

        # Remove oldest tools beyond limit
        tools_to_remove = self._tool_call_order[: -self._max_tool_history]
        groups_to_check: set[str] = set()

        for tool_id in tools_to_remove:
            self._tool_displays.pop(tool_id, None)
            self._active_tool_ids.discard(tool_id)

            # Track which groups might need cleanup
            if tool_id in self._tool_to_group:
                groups_to_check.add(self._tool_to_group[tool_id])
                self._tool_to_group.pop(tool_id, None)

        # Clean up empty or stale collapsed groups
        for group_msg_id in groups_to_check:
            if group_msg_id in self._collapsed_groups:
                # Remove tool IDs that were cleaned up
                group_tools = self._collapsed_groups[group_msg_id]
                group_tools = [t for t in group_tools if t not in tools_to_remove]
                if group_tools:
                    self._collapsed_groups[group_msg_id] = group_tools
                else:
                    # Group is empty, remove it
                    self._collapsed_groups.pop(group_msg_id, None)
                    if self._current_group_msg_id == group_msg_id:
                        self._current_group_msg_id = None

        self._tool_call_order = self._tool_call_order[-self._max_tool_history :]

    async def run(self, wire: WireUISide):
        """Main loop - process wire messages and render to chat."""
        # Start spinner refresh task
        self._spinner_task = asyncio.create_task(self._refresh_running_tools())
        # Start decision watcher task
        self._decision_watcher_task = asyncio.create_task(self._watch_decisions())

        try:
            while True:
                # Use wait with cancel event to allow ESC to interrupt wire.receive()
                if self.cancel_event:
                    receive_task = asyncio.create_task(wire.receive())
                    cancel_task = asyncio.create_task(self.cancel_event.wait())

                    done, pending = await asyncio.wait(
                        [receive_task, cancel_task], return_when=asyncio.FIRST_COMPLETED
                    )

                    # Cancel pending tasks
                    for task in pending:
                        task.cancel()
                        try:
                            await task
                        except asyncio.CancelledError:
                            pass

                    # Check if cancelled
                    if cancel_task in done:
                        self._finalize_all()
                        self.chat_app.add_message(Text("Interrupted by user", style="red"))
                        break

                    # Get the message from receive task (guard: only if it completed)
                    if receive_task not in done:
                        continue
                    try:
                        msg = receive_task.result()
                    except asyncio.QueueShutDown:
                        self._finalize_all()
                        break
                    except Exception:
                        # Unexpected error from wire — finalize and exit
                        self._finalize_all()
                        break
                else:
                    # No cancel event, just receive normally
                    try:
                        msg = await wire.receive()
                    except asyncio.QueueShutDown:
                        self._finalize_all()
                        break

                # Dispatch message to appropriate handler
                await self._dispatch_message(msg)

                # Handle interruption (StepInterrupted message - don't show duplicate)
                if isinstance(msg, StepInterrupted):
                    self._finalize_all()
                    break
        finally:
            # Clean up spinner task
            if self._spinner_task:
                self._spinner_task.cancel()
                try:
                    await self._spinner_task
                except asyncio.CancelledError:
                    pass
            # Clean up decision watcher task
            if self._decision_watcher_task:
                self._decision_watcher_task.cancel()
                try:
                    await self._decision_watcher_task
                except asyncio.CancelledError:
                    pass
            # Clear all handlers to allow input to work again
            self.chat_app.set_cancel_handler(None)
            self.chat_app.set_approval_handler(None)
            self.chat_app.set_decision_handler(None)
            # Return focus to input
            try:
                self.chat_app.chat_input.focus()
            except Exception:
                pass

    async def _refresh_running_tools(self):
        """Periodically refresh running tool displays to animate spinners and show live output.

        Performance: Only refreshes tools that are actually running (not finished).
        Uses a set to track active tools for O(1) lookup.
        Runs at 2 FPS (500ms) to reduce contention with mount/remove operations.
        """
        from aesc.ui.widgets.tool_call_display import ToolState

        refresh_count = 0

        while True:
            try:
                await asyncio.sleep(0.5)  # 2 FPS — sufficient for spinner animation
                refresh_count += 1

                # Skip refresh if chat app is busy mounting/removing widgets
                if getattr(self.chat_app, "_dom_busy", False):
                    continue

                # Only refresh tools that are still active (not finished)
                if not self._active_tool_ids:
                    continue

                for tool_id in list(self._active_tool_ids):
                    display = self._tool_displays.get(tool_id)
                    if not display:
                        self._active_tool_ids.discard(tool_id)
                        continue

                    if display.state == ToolState.FINISHED:
                        self._active_tool_ids.discard(tool_id)
                        continue

                    # Refresh active tool widget
                    msg_id = self.chat_app._tool_call_map.get(tool_id)
                    if msg_id and msg_id in self.chat_app._message_map:
                        widget = self.chat_app._message_map[msg_id]
                        widget.content = display.render_live()
                        widget.refresh()

                # Periodic cleanup of old tool displays (~every 15s)
                if refresh_count % 30 == 0:
                    self._cleanup_old_tools()

            except asyncio.CancelledError:
                break
            except Exception as e:
                from aesc.utils.logging import logger

                logger.debug(f"Refresh error: {e}")

    async def _dispatch_message(self, msg: WireMessage):
        """Dispatch wire message to appropriate handler."""
        from aesc.utils.logging import logger

        # Debug: Log message order to understand sequencing
        match msg:
            case StepBegin():
                logger.debug("WIRE: StepBegin")
                self._handle_step_begin()

            case TextPart():
                logger.debug(f"WIRE: TextPart ({len(msg.text)} chars): {msg.text[:50]!r}...")
                self._handle_text_part(msg)

            case ThinkPart():
                logger.debug(f"WIRE: ThinkPart ({len(msg.think)} chars)")
                self._handle_think_part(msg)

            case ToolCall():
                logger.debug(
                    f"WIRE: ToolCall {msg.function.name} (pending_text={len(self._current_text)} chars)"
                )
                self._handle_tool_call(msg)

            case ToolCallPart():
                pass  # Ignore tool call parts (we get full ToolCall)

            case ToolResult():
                self._handle_tool_result(msg)

            case ApprovalRequest():
                await self._handle_approval_request(msg)

            case StatusUpdate():
                self._handle_status_update(msg)

            case ToolOutputChunk():
                self._handle_tool_output_chunk(msg)

            case CompactionBegin():
                self._handle_compaction_begin()

            case CompactionEnd():
                self._handle_compaction_end(msg)

            case SubagentEvent():
                self._handle_subagent_event(msg)

            case _:
                pass  # Unknown message type, ignore

    def _handle_step_begin(self):
        """Handle step begin - reset step-level tracking."""
        # Reset message ordering state for new step
        self._first_tool_msg_id_this_step = None
        self._step_has_shown_tool = False
        # Reset approval collapse tracking (new step = new context)
        self._last_approval_msg_id = None
        self._consecutive_approval_count = 0
        self._max_approval_risk = None

        # Show loading indicator (guard against double-set from on_input_submitted)
        if hasattr(self.chat_app, "loading_indicator"):
            if not self.chat_app.loading_indicator.is_active:
                self.chat_app.loading_indicator.set_thinking()

    def _handle_text_part(self, part: TextPart):
        """Handle text content with streaming support."""
        self._current_text += part.text
        self._is_thinking = False
        # Stream text by updating message in place
        self._stream_current_text()

    def _handle_think_part(self, part: ThinkPart):
        """Accumulate thinking content until flush."""
        self._current_text += part.think
        self._is_thinking = True

    def _handle_tool_call(self, tool_call: ToolCall):
        """
        Handle new tool call - show with spinner.

        Pattern: Kimi-CLI visualize.py:171-180

        Collapsing logic:
        - Track consecutive same-type tool calls
        - After threshold, collapse into a summary group
        - Individual tool calls still tracked for result handling
        """
        # Flush any pending text first
        self._flush_current_text()

        # Create tool call display
        display = ToolCallDisplay(tool_call)
        self._tool_displays[tool_call.id] = display
        self._tool_call_order.append(tool_call.id)
        self._active_tool_ids.add(tool_call.id)  # Track for periodic refresh

        # Update status bar with running tools count
        self._update_running_tools_count()

        tool_name = tool_call.function.name

        # Update loading indicator to show tool execution
        if hasattr(self.chat_app, "loading_indicator"):
            # Get command preview for Bash tool
            command_preview = ""
            if tool_name == "Bash":
                try:
                    import json

                    args = json.loads(tool_call.function.arguments)
                    command_preview = args.get("command", "")[:60]
                except Exception:
                    pass
            self.chat_app.loading_indicator.set_tool_running(tool_name, command_preview)

        # Check if this continues a collapsible sequence
        # Only collapse Bash and Think tools (the noisy ones)
        collapsible_tools = {"Bash", "Think"}

        if tool_name in collapsible_tools and tool_name == self._last_tool_name:
            # Same tool type as last - potential collapse
            if self._current_group_msg_id and self._current_group_msg_id in self._collapsed_groups:
                group = self._collapsed_groups[self._current_group_msg_id]
                group.append(tool_call.id)
                self._tool_to_group[tool_call.id] = self._current_group_msg_id

                # Update the group summary display
                self._update_collapsed_group(self._current_group_msg_id)

                # Map this tool to the group message for result updates
                self.chat_app.map_tool_call_to_message(tool_call.id, self._current_group_msg_id)
                return  # Don't add individual message

            # Check if we should START collapsing (reached threshold)
            # Count recent consecutive same-type tools
            consecutive = 0
            for tid in reversed(self._tool_call_order[:-1]):  # Exclude current
                if tid in self._tool_displays:
                    if self._tool_displays[tid].tool_name == tool_name:
                        consecutive += 1
                    else:
                        break

            if consecutive >= self._collapse_threshold - 1:
                # Start a new collapsed group - gather previous same-type tools
                group_tool_ids = []
                for tid in reversed(self._tool_call_order):
                    if (
                        tid in self._tool_displays
                        and self._tool_displays[tid].tool_name == tool_name
                    ):
                        group_tool_ids.insert(0, tid)
                    else:
                        break

                # Remove individual messages for tools being collapsed
                for tid in group_tool_ids[:-1]:  # Keep the current one's slot
                    old_msg_id = self.chat_app._tool_call_map.get(tid)
                    if old_msg_id:
                        self.chat_app.remove_message(old_msg_id)

                # Create collapsed group message
                group_msg_id = self.chat_app.add_message(
                    self._render_collapsed_group(tool_name, group_tool_ids)
                )

                # Track the group
                self._collapsed_groups[group_msg_id] = group_tool_ids
                self._current_group_msg_id = group_msg_id
                for tid in group_tool_ids:
                    self._tool_to_group[tid] = group_msg_id
                    self.chat_app.map_tool_call_to_message(tid, group_msg_id)

                return

        # Not collapsing - reset group tracking
        self._last_tool_name = tool_name
        self._current_group_msg_id = None

        # Add live display (with spinner) to chat
        msg_id = self.chat_app.add_message(display.render_live())

        # Track first tool call message for text insertion ordering
        if not self._step_has_shown_tool:
            self._first_tool_msg_id_this_step = msg_id
            self._step_has_shown_tool = True

        # Track tool_call_id -> message_id mapping
        self.chat_app.map_tool_call_to_message(tool_call.id, msg_id)

    def _handle_tool_result(self, result: ToolResult):
        """
        Handle tool result - update display to show result.

        Pattern: Kimi-CLI visualize.py:185-195
        """
        if result.tool_call_id not in self._tool_displays:
            return  # Unknown tool call, skip

        # Skip rejected tools - approval panel already shows rejection message
        if isinstance(result.result, ToolRejectedError):
            # Just mark as finished, don't update display (approval panel handles it)
            display = self._tool_displays[result.tool_call_id]
            display.finished = True
            self._active_tool_ids.discard(result.tool_call_id)  # No longer active
            return

        # Update display with result
        display = self._tool_displays[result.tool_call_id]
        display.result = result.result
        display.finished = True

        # Remove from active set - no longer needs periodic refresh
        self._active_tool_ids.discard(result.tool_call_id)

        # Update status bar with running tools count
        self._update_running_tools_count()

        # Clear loading indicator if no more active tools
        if not self._active_tool_ids and hasattr(self.chat_app, "loading_indicator"):
            self.chat_app.loading_indicator.clear()

        # Check if this tool is part of a collapsed group
        if result.tool_call_id in self._tool_to_group:
            group_msg_id = self._tool_to_group[result.tool_call_id]
            self._update_collapsed_group(group_msg_id)
            return

        # Update message in chat (spinner → checkmark/X)
        self.chat_app.update_tool_call_message(result.tool_call_id, display.render_complete())

        # Periodic cleanup to prevent memory leak in long sessions
        if len(self._tool_call_order) > self._max_tool_history:
            self._cleanup_old_tools()

    def _handle_tool_output_chunk(self, chunk: ToolOutputChunk):
        """
        Handle streaming output from a running tool.

        Appends to buffer but does NOT update display on every chunk.
        The periodic refresh task handles display updates (throttled).
        """
        if chunk.tool_call_id not in self._tool_displays:
            return  # Unknown tool, ignore

        display = self._tool_displays[chunk.tool_call_id]
        display.append_live_output(chunk.chunk)

    def _handle_subagent_event(self, event: SubagentEvent):
        """
        Handle subagent events - show subagent activity within parent Task tool.

        Performance: Updates data model only. The periodic _refresh_running_tools()
        handles re-rendering (throttled at 200ms). Only ToolCall and ToolResult
        trigger immediate re-render since they're infrequent and important.
        """
        # Reset decision polling to fast mode - subagent activity may produce decisions
        self._decision_poll_interval = self._decision_poll_min

        parent_display = self._tool_displays.get(event.task_tool_call_id)
        if parent_display is None:
            return  # Unknown parent task, ignore

        # Ensure parent Task is shown as RUNNING (not PENDING) when subagent is active
        from aesc.ui.widgets.tool_call_display import ToolState

        if parent_display.state == ToolState.PENDING:
            parent_display.set_running()

        # Ensure parent is tracked for periodic refresh
        self._active_tool_ids.add(event.task_tool_call_id)

        match event.event:
            case ToolCall() as tool_call:
                # Subagent started a tool - immediate render (infrequent + important)
                parent_display.set_subagent_launching(False)
                parent_display.add_subagent_tool_call(tool_call)
                self.chat_app.update_tool_call_message(
                    event.task_tool_call_id, parent_display.render_live()
                )

            case ToolCallPart() as tool_call_part:
                # Streaming args - data-only, periodic refresh handles display
                parent_display.update_subagent_tool_args(tool_call_part)

            case ToolResult() as tool_result:
                # Tool finished - immediate render (infrequent + important)
                parent_display.finish_subagent_tool_call(tool_result)
                self.chat_app.update_tool_call_message(
                    event.task_tool_call_id, parent_display.render_live()
                )

            case TextPart() as text_part:
                # Check for launch notification - immediate render
                if text_part.text.startswith("[Launching ") and text_part.text.endswith("]"):
                    agent_name = text_part.text[len("[Launching ") : -1]
                    parent_display.set_subagent_name(agent_name)
                    parent_display.set_subagent_launching(True)
                    self.chat_app.update_tool_call_message(
                        event.task_tool_call_id, parent_display.render_live()
                    )
                else:
                    # Streaming text - data-only, periodic refresh handles display
                    parent_display.set_subagent_launching(False)
                    parent_display.append_subagent_output(text_part.text)

            case ThinkPart() as think_part:
                # Thinking - data-only, periodic refresh handles display
                parent_display.append_subagent_thinking(think_part.think)

            case ToolOutputChunk() as chunk:
                # Streaming output - data-only, periodic refresh handles display
                parent_display.append_subagent_tool_output(chunk)

            case _:
                pass

    # =========================================================================
    # Compaction Handling
    # =========================================================================

    def _handle_compaction_begin(self):
        """Handle compaction begin - show progress indicator."""
        self._compaction_in_progress = True
        # Flush any pending content
        self._flush_current_text()

        # Show a brief "compacting..." message (styled as system message)
        msg = Text("📦 Compacting context...", style="cyan dim")
        self._compaction_msg_id = self.chat_app.add_message(msg, is_system_message=True)

    def _handle_compaction_end(self, event: CompactionEnd):
        """Handle compaction end - show summary panel."""
        self._compaction_in_progress = False

        # Remove the "compacting..." message
        if hasattr(self, "_compaction_msg_id") and self._compaction_msg_id:
            self.chat_app.remove_message(self._compaction_msg_id)
            self._compaction_msg_id = None

        # Only show panel if there was actual compaction or session restore
        if event.original_tokens > 0 or event.compacted_tokens > 0 or event.full_summary:
            panel = CompactionPanel(
                summary=event.summary,
                full_summary=event.full_summary,
                original_tokens=event.original_tokens,
                compacted_tokens=event.compacted_tokens,
                compression_ratio=event.compression_ratio,
                is_session_restore=event.is_session_restore,
            )
            # Add as system message for distinct styling
            msg_id = self.chat_app.add_message(panel.render(), is_system_message=True)
            self._compaction_panels[msg_id] = panel

    async def _handle_approval_request(self, request: ApprovalRequest):
        """
        Handle approval request - show panel and wait for keyboard input.

        Pattern: Kimi-CLI visualize.py:213-260

        CRITICAL: Panel must DISAPPEAR after user action (y/n/a/s).

        For parallel tool calls: Queue requests and show one at a time.
        When user responds to current panel, show next queued request.

        For subagent approvals: The tool_call_id belongs to the subagent's tool,
        not the parent Task tool. We should NOT change the parent's display state.
        """
        from aesc.utils.logging import logger

        # Flush any pending content
        self._flush_current_text()
        self._flush_tool_calls()

        # Update loading indicator to show waiting for approval
        if hasattr(self.chat_app, "loading_indicator"):
            self.chat_app.loading_indicator.set_waiting_approval()

        # If already resolved, skip (shouldn't happen)
        if request.resolved:
            logger.debug("Approval request already resolved, skipping: {id}", id=request.id)
            return

        # If there's already an approval panel showing, queue this request
        if self._approval_panel is not None:
            queue_size = len(self._pending_approvals) + 1
            logger.debug(
                "Queueing approval request: {id}, queue size: {size}",
                id=request.id,
                size=queue_size,
            )
            self._pending_approvals.append(request)
            return

        # Check if this is a subagent approval (tool_call_id not in our displays)
        is_subagent_approval = request.tool_call_id not in self._tool_displays

        # Show this approval request
        logger.debug(
            "Showing approval panel for request: {id}, is_subagent: {is_sub}, tool_call_id: {tcid}",
            id=request.id,
            is_sub=is_subagent_approval,
            tcid=request.tool_call_id,
        )

        # For subagent approvals, ensure parent Task tools stay RUNNING
        # (they should show subagent activity, not "waiting for approval")
        if is_subagent_approval:
            from aesc.ui.widgets.tool_call_display import ToolState

            for display in self._tool_displays.values():
                if display.tool_name == "Task" and display.state != ToolState.FINISHED:
                    display.set_running()

        self._show_approval_panel(request, is_subagent=is_subagent_approval)

    def _show_approval_panel(self, request: ApprovalRequest, *, is_subagent: bool = False):
        """Display an approval panel for the given request.

        Args:
            request: The approval request to show.
            is_subagent: True if this approval is from a subagent's tool (not in _tool_displays).
                         When True, we should NOT change the parent Task tool's display state.
        """
        # Only set the tool to PENDING state if it's a direct tool call (not subagent)
        # This prevents the parent Task from showing "waiting for approval" when
        # the approval is actually for a subagent's tool
        if not is_subagent and request.tool_call_id in self._tool_displays:
            display = self._tool_displays[request.tool_call_id]
            display.set_pending()
            # Update the tool display to show "? waiting for approval..."
            self.chat_app.update_tool_call_message(request.tool_call_id, display.render_live())

        # Create approval panel
        panel = ApprovalPanel(request)

        # Add panel to chat and track its message ID
        panel_msg_id = self.chat_app.add_message(panel.render())

        # Store panel with its message ID for later removal (include is_subagent flag)
        self._approval_panel = (request, panel, panel_msg_id, is_subagent)

        # Register keyboard handler
        self.chat_app.set_approval_handler(self._handle_approval_key)

        # Update status bar to show prominent approval indicator
        if hasattr(self.chat_app, "status_bar") and self.chat_app.status_bar:
            self.chat_app.status_bar.set_pending_approval(True)

        # DO NOT await request.wait() here!
        # The keyboard handler will resolve it, and soul/approval.py is waiting

    def _handle_approval_key(self, key: str) -> bool:
        """
        Handle keyboard input for approval panel.

        Returns True if key was handled, False otherwise.

        Keys:
        - y: Approve
        - a: Approve for session
        - n: Reject
        - up/down: Navigate options
        - enter: Select current option
        """
        # Capture reference to avoid race condition
        approval_panel = self._approval_panel
        if not approval_panel or not isinstance(approval_panel, tuple) or len(approval_panel) != 4:
            return False

        request, panel, panel_msg_id, is_subagent = approval_panel

        # Safety check: ensure options list is not empty
        if not panel.options:
            return False

        # Handle navigation - update panel in place, don't add new message
        if key in ("up", "down"):
            if key == "down":
                panel.selected_index = (panel.selected_index + 1) % len(panel.options)
            else:
                panel.selected_index = (panel.selected_index - 1) % len(panel.options)

            # Update existing panel widget content directly
            if panel_msg_id in self.chat_app._message_map:
                widget = self.chat_app._message_map[panel_msg_id]
                widget.content = panel.render()
                widget.refresh()
            return True

        # Handle selection with bounds check
        if key == "enter":
            if 0 <= panel.selected_index < len(panel.options):
                selected_key = panel.options[panel.selected_index][0]
            else:
                selected_key = "n"  # Default to reject on invalid state
        elif key in ("y", "n", "a"):
            selected_key = key
        else:
            return False  # Not a valid approval key

        # Resolve approval based on key (with safety check for already resolved)
        approved = False
        try:
            if selected_key == "y":
                request.approve()
                approval_display = panel.get_approval_display(approved=True)
                approved = True
            elif selected_key == "a":
                request.approve_for_session()
                approval_display = panel.get_approval_display(approved=True, for_session=True)
                approved = True
            else:  # n
                request.reject()
                approval_display = panel.get_approval_display(approved=False)
        except Exception:
            # Request may already be resolved (race condition)
            approval_display = panel.get_approval_display(approved=False)

        # Remove the specific approval panel message (not just "last message")
        self.chat_app.remove_message(panel_msg_id)

        # Show approval result — collapse consecutive subagent approvals
        if approved and is_subagent and self._last_approval_msg_id is not None:
            # Collapse into existing summary
            self._consecutive_approval_count += 1
            if panel.risk_level and (
                self._max_approval_risk is None
                or panel.risk_level > self._max_approval_risk
            ):
                self._max_approval_risk = panel.risk_level

            summary = Text()
            summary.append("● ", style="#4ade80")
            risk_text = (
                f" (up to {self._max_approval_risk.display_name})"
                if self._max_approval_risk
                else ""
            )
            summary.append(
                f"{self._consecutive_approval_count} commands approved{risk_text}",
                style="#4ade80",
            )
            try:
                self.chat_app.update_message(self._last_approval_msg_id, summary)
            except Exception as e:
                from aesc.utils.logging import logger

                logger.debug(f"Failed to update approval message: {e}")
            # No extra spacing — the group's first line already has it
        else:
            # First approval in a group, or non-subagent, or rejection
            try:
                msg_id = self.chat_app.add_message(approval_display)
            except Exception as e:
                from aesc.utils.logging import logger

                logger.debug(f"Failed to add approval message: {e}")
                msg_id = None

            if approved and is_subagent:
                # Start a new collapse group
                self._last_approval_msg_id = msg_id
                self._consecutive_approval_count = 1
                self._max_approval_risk = panel.risk_level if panel.risk_level else None
            else:
                # Non-subagent or rejection — reset collapse tracking
                self._last_approval_msg_id = None
                self._consecutive_approval_count = 0
                self._max_approval_risk = None

            # Add spacing after approval section
            try:
                self.chat_app.add_spacing()
            except Exception:
                pass

        # If approved, create NEW tool display message AFTER approval message
        # This ensures correct visual order: Approved → Running → Result
        # For subagent approvals, we don't update the parent Task's display - it stays running
        if approved and not is_subagent and request.tool_call_id in self._tool_displays:
            display = self._tool_displays[request.tool_call_id]
            display.set_running()

            # Remove the old "? waiting..." message
            old_msg_id = self.chat_app._tool_call_map.get(request.tool_call_id)
            if old_msg_id:
                self.chat_app.remove_message(old_msg_id)

            # Add NEW message for "running..." state (appears after approval message)
            new_msg_id = self.chat_app.add_message(display.render_live())
            self.chat_app.map_tool_call_to_message(request.tool_call_id, new_msg_id)

        # Clear current panel state
        self._approval_panel = None
        self.chat_app.set_approval_handler(None)

        # Show next queued approval if any
        self._show_next_pending_approval()

        return True

    def _show_next_pending_approval(self):
        """Show the next pending approval request if any are queued."""
        from aesc.utils.logging import logger

        queue_size = len(self._pending_approvals)
        logger.debug("Checking pending approvals, queue size: {size}", size=queue_size)

        while self._pending_approvals:
            next_request = self._pending_approvals.pop(0)
            # Skip already resolved requests
            if next_request.resolved:
                logger.debug("Skipping already resolved request: {id}", id=next_request.id)
                continue
            # Show this request - check if it's a subagent approval
            is_subagent = next_request.tool_call_id not in self._tool_displays
            logger.debug(
                "Showing next pending approval: {id}, is_subagent: {is_sub}",
                id=next_request.id,
                is_sub=is_subagent,
            )
            self._show_approval_panel(next_request, is_subagent=is_subagent)
            return

        # No more pending approvals - clear status bar indicator
        logger.debug("No more pending approvals")
        if hasattr(self.chat_app, "status_bar") and self.chat_app.status_bar:
            self.chat_app.status_bar.set_pending_approval(False)

    def _update_running_tools_count(self):
        """Update status bar with count of currently running tools."""
        if hasattr(self.chat_app, "status_bar") and self.chat_app.status_bar:
            self.chat_app.status_bar.set_running_tools(len(self._active_tool_ids))

    def _handle_status_update(self, update: StatusUpdate):
        """Update status bar."""
        self._status = update.status
        self.chat_app.update_status(self._status)

    def _stream_current_text(self):
        """
        Stream text content - update existing message or create new one.

        This enables real-time token-by-token display.
        PERFORMANCE: Use plain Text during streaming, only render markdown on flush.

        Message Ordering: If tool calls have already been displayed this step,
        insert the text BEFORE the first tool call for correct chronological order.
        (LLMs often send tool_use blocks before explanation text)
        """
        if not self._current_text:
            return

        # During streaming, use plain Text (MUCH faster than markdown parsing)
        style = "grey50 italic" if self._is_thinking else ""
        content = Text(self._current_text, style=style)

        if self._streaming_message_id:
            # Update existing streaming message - direct widget update, no scroll
            if self._streaming_message_id in self.chat_app._message_map:
                widget = self.chat_app._message_map[self._streaming_message_id]
                widget.content = content
                widget.refresh()
        else:
            # Create new streaming message
            # If tool calls already shown, insert BEFORE first tool for correct order
            if self._step_has_shown_tool and self._first_tool_msg_id_this_step:
                self._streaming_message_id = self.chat_app.insert_message_before(
                    content, self._first_tool_msg_id_this_step, scroll=False
                )
            else:
                # Normal case - append to end
                self._streaming_message_id = self.chat_app.add_message(content, scroll=False)

    def _flush_current_text(self):
        """
        Flush accumulated text content to chat (finalize streaming).

        Renders as markdown with appropriate styling.

        Message Ordering: If tool calls have already been displayed this step
        and we need to create a new message, insert BEFORE the first tool call.
        """
        if not self._current_text:
            return

        # Render as markdown
        style = "grey50 italic" if self._is_thinking else ""
        content = RichMarkdown(self._current_text, style=style)

        # Track if we need to insert spacing before tool call
        insert_before_tool = (
            self._step_has_shown_tool
            and self._first_tool_msg_id_this_step
            and not self._streaming_message_id
        )

        if self._streaming_message_id:
            # Finalize the streaming message - scroll now that streaming is done
            self.chat_app.update_message(self._streaming_message_id, content, scroll=True)
        else:
            # No streaming message yet, create one
            # If tool calls already shown, insert BEFORE first tool for correct order
            if insert_before_tool:
                self.chat_app.insert_message_before(
                    content, self._first_tool_msg_id_this_step, scroll=True
                )
            else:
                self.chat_app.add_message(content)

        # Add spacing after text content
        # If we inserted before a tool call, spacing should also be before the tool
        if insert_before_tool:
            self.chat_app.insert_spacing_before(self._first_tool_msg_id_this_step)
        else:
            self.chat_app.add_spacing()

        # Clear buffer and streaming state
        self._current_text = ""
        self._is_thinking = False
        self._streaming_message_id = None

    def _flush_tool_calls(self):
        """
        Finalize all pending tool calls.

        Ensures all tool calls are in "complete" state.
        Only finalizes tools that are actually finished (RUNNING or FINISHED state).
        Tools still PENDING (waiting for approval) should NOT be force-completed.
        """
        from aesc.ui.widgets.tool_call_display import ToolState

        for tool_id in self._tool_call_order:
            display = self._tool_displays[tool_id]
            # Don't force-complete tools still waiting for approval
            if not display.finished and display.state != ToolState.PENDING:
                # Force finalize (shouldn't happen in normal flow)
                self.chat_app.update_tool_call_message(tool_id, display.render_complete())

        # Add spacing after tool calls (if any)
        if self._tool_call_order:
            self.chat_app.add_spacing()

    def _finalize_all(self):
        """Finalize everything - called when stream ends."""
        self._flush_current_text()
        self._flush_tool_calls()
        # Clean up old tool displays to prevent memory leaks
        self._cleanup_old_tools()

    def _toggle_all_outputs(self):
        """Toggle expansion of all tool call outputs and compaction panels (Ctrl+O handler)."""
        from aesc.ui.widgets.tool_call_display import ToolState

        # Toggle tool displays (if any)
        if self._tool_displays:
            # Toggle all tool displays (both running and finished)
            for tool_id in self._tool_call_order:
                display = self._tool_displays.get(tool_id)
                if not display:
                    continue

                # Skip tools in collapsed groups (they're handled by group toggle)
                if tool_id in self._tool_to_group:
                    continue

                if display.state == ToolState.RUNNING:
                    # Toggle live output for running tools
                    display.toggle_live_output()
                    self.chat_app.update_tool_call_message(tool_id, display.render_live())
                elif display.finished:
                    # Toggle expanded for finished tools
                    display.toggle_expanded()
                    self.chat_app.update_tool_call_message(tool_id, display.render_complete())

            # Toggle collapsed groups
            for group_msg_id in self._collapsed_groups:
                self._toggle_collapsed_group(group_msg_id)

        # Toggle compaction panels
        for msg_id, panel in self._compaction_panels.items():
            panel.toggle_expanded()
            # Update the message with new render
            if msg_id in self.chat_app._message_map:
                widget = self.chat_app._message_map[msg_id]
                widget.content = panel.render()
                widget.refresh()

    def _render_collapsed_group(self, tool_name: str, tool_ids: list[str]) -> Text:
        """
        Render a collapsed group of tool calls.

        Format: ✓ Bash (5 commands) - 4 succeeded, 1 failed [Ctrl+O to expand]
        """
        from aesc.provider import ToolOk

        total = len(tool_ids)
        finished = 0
        succeeded = 0
        failed = 0
        running = 0

        for tid in tool_ids:
            display = self._tool_displays.get(tid)
            if display:
                if display.finished:
                    finished += 1
                    if isinstance(display.result, ToolOk):
                        succeeded += 1
                    else:
                        failed += 1
                else:
                    running += 1

        # Determine overall status
        if running > 0:
            icon = "⠿"
            style = "cyan"
            status = f"{running} running"
        elif failed > 0:
            icon = "✗"
            style = "red"
            status = f"{failed} failed"
        else:
            icon = "✓"
            style = "green"
            status = "all succeeded"

        text = Text()
        text.append(f"{icon} ", style=style)
        text.append(f"{tool_name}", style="cyan bold")
        text.append(f" ({total} calls)", style="grey50")
        text.append(f" - {status}", style="grey50")

        if finished == total:
            text.append(" [Ctrl+O to expand]", style="dim italic")

        return text

    def _update_collapsed_group(self, group_msg_id: str):
        """Update the display of a collapsed group."""
        if group_msg_id not in self._collapsed_groups:
            return

        tool_ids = self._collapsed_groups[group_msg_id]
        if not tool_ids:
            return

        # Get tool name from first tool
        first_display = self._tool_displays.get(tool_ids[0])
        if not first_display:
            return

        tool_name = first_display.tool_name

        # Update the message
        if group_msg_id in self.chat_app._message_map:
            widget = self.chat_app._message_map[group_msg_id]
            widget.content = self._render_collapsed_group(tool_name, tool_ids)
            widget.refresh()

    def _toggle_collapsed_group(self, group_msg_id: str):
        """Toggle expansion of a collapsed group (show/hide individual tool details)."""
        # For now, just update the group display
        # Future: could expand to show all individual tool calls
        self._update_collapsed_group(group_msg_id)

    # =========================================================================
    # Decision Watching (Human-in-the-loop for subagent decisions)
    # =========================================================================

    async def _watch_decisions(self):
        """
        Watch for new subagent decisions and show decision panels.

        This enables human-in-the-loop control:
        - Subagents write decisions to ./results/decisions/
        - We detect unresolved decisions and show a panel
        - Human can respond with keyboard shortcuts
        - Response is written back to the decision file

        Uses adaptive polling: faster when active, slower when idle.
        """
        from pathlib import Path

        from aesc.tools.results.schemas import Decision
        from aesc.utils.logging import logger

        decisions_dir = Path("./results/decisions")

        while True:
            try:
                await asyncio.sleep(self._decision_poll_interval)

                found_decision = False

                # Skip if there's already a decision panel showing
                if self._pending_decision is not None:
                    # Keep fast polling while panel is shown (waiting for response)
                    self._decision_poll_interval = self._decision_poll_min
                    continue

                # Skip if there's an approval panel (approvals take priority)
                if self._approval_panel is not None:
                    continue

                # Check for unresolved decisions we haven't shown yet
                if not decisions_dir.exists():
                    # No decisions dir, slow down polling
                    self._decision_poll_interval = min(
                        self._decision_poll_interval * self._decision_poll_backoff,
                        self._decision_poll_max,
                    )
                    continue

                for decision_file in sorted(decisions_dir.glob("*.json")):
                    try:
                        decision = Decision.model_validate_json(decision_file.read_text())

                        # Skip already resolved
                        if decision.resolved:
                            continue

                        # Skip already shown
                        if decision.id in self._known_decisions:
                            continue

                        # Found a new unresolved decision - show panel
                        logger.debug(
                            "Found new decision: {id}, question: {q}",
                            id=decision.id,
                            q=decision.question[:50],
                        )
                        self._known_decisions.add(decision.id)
                        self._show_decision_panel(decision)
                        found_decision = True
                        break  # Only show one at a time

                    except Exception:
                        continue  # Skip malformed files

                # Adaptive polling: speed up when active, slow down when idle
                if found_decision:
                    # Reset to fast polling when activity detected
                    self._decision_poll_interval = self._decision_poll_min
                else:
                    # Gradually slow down when no activity
                    self._decision_poll_interval = min(
                        self._decision_poll_interval * self._decision_poll_backoff,
                        self._decision_poll_max,
                    )

            except asyncio.CancelledError:
                break
            except Exception as e:
                from aesc.utils.logging import logger

                logger.debug(f"Decision watcher error: {e}")

    def _show_decision_panel(self, decision):
        """Display a decision panel for the given decision."""

        # Flush any pending content
        self._flush_current_text()

        # Create decision panel
        panel = DecisionPanel(decision)

        # Add panel to chat and track its message ID
        panel_msg_id = self.chat_app.add_message(panel.render())

        # Store panel info for later removal
        self._pending_decision = (decision.id, panel_msg_id, panel)

        # Register keyboard handler (temporarily override approval handler)
        self.chat_app.set_decision_handler(self._handle_decision_key)

    def _handle_decision_key(self, key: str) -> bool:
        """
        Handle keyboard input for decision panel.

        Returns True if key was handled, False otherwise.

        Keys:
        - A/B/C/D or 1/2/3/4: Select option directly
        - up/down: Navigate options
        - enter: Select current option
        """
        from pathlib import Path

        from aesc.tools.results.schemas import Decision

        # Capture reference to avoid race condition
        pending = self._pending_decision
        if not pending:
            return False

        decision_id, panel_msg_id, panel = pending

        # Handle navigation
        if key in ("up", "down"):
            max_idx = len(panel.decision.options) - 1
            if key == "down":
                panel.selected_index = min(panel.selected_index + 1, max_idx)
            else:
                panel.selected_index = max(panel.selected_index - 1, 0)

            # Update existing panel widget content directly
            if panel_msg_id in self.chat_app._message_map:
                widget = self.chat_app._message_map[panel_msg_id]
                widget.content = panel.render()
                widget.refresh()
            return True

        # Handle direct option selection (A/B/C/D or a/b/c/d)
        chosen_id = None
        key_upper = key.upper()

        if key == "enter":
            chosen_id = panel.get_selected_option_id()
        elif key_upper in "ABCD":
            idx = ord(key_upper) - ord("A")
            if idx < len(panel.decision.options):
                chosen_id = panel.decision.options[idx].id
        elif key in "1234567890":
            idx = int(key) - 1
            if 0 <= idx < len(panel.decision.options):
                chosen_id = panel.decision.options[idx].id

        if chosen_id is None:
            return False  # Not a valid decision key

        # Write resolution to decision file (atomic write to prevent TOCTOU race)
        import tempfile

        from aesc.utils.logging import logger

        try:
            decisions_dir = Path("./results/decisions")
            decision_file = decisions_dir / f"{decision_id}.json"

            if decision_file.exists():
                decision = Decision.model_validate_json(decision_file.read_text())
                decision.resolved = True
                decision.resolution = chosen_id

                # Atomic write: write to temp file then rename
                temp_fd, temp_path = tempfile.mkstemp(
                    dir=decisions_dir, suffix=".tmp", prefix=f"{decision_id}_"
                )
                try:
                    with os.fdopen(temp_fd, "w") as f:
                        f.write(decision.model_dump_json(indent=2))
                    os.replace(temp_path, decision_file)  # Atomic on POSIX
                except Exception:
                    # Clean up temp file on error
                    with contextlib.suppress(OSError):
                        os.unlink(temp_path)
                    raise

                logger.debug(
                    "Decision resolved: {id} -> {choice}", id=decision_id, choice=chosen_id
                )
            else:
                logger.warning("Decision file not found: {file}", file=decision_file)
        except Exception as e:
            logger.error("Failed to write decision resolution: {error}", error=str(e))

        # Remove the decision panel message
        self.chat_app.remove_message(panel_msg_id)

        # Show decision result
        decision_display = panel.get_decision_display(chosen_id)
        try:
            self.chat_app.add_message(decision_display)
        except Exception as e:
            from aesc.utils.logging import logger

            logger.debug(f"Failed to add decision display: {e}")

        # Add spacing
        try:
            self.chat_app.add_spacing()
        except Exception as e:
            from aesc.utils.logging import logger

            logger.debug(f"Failed to add spacing after decision: {e}")

        # Clear current panel state
        self._pending_decision = None
        self.chat_app.set_decision_handler(None)

        return True
