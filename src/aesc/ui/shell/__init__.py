from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Coroutine
from dataclasses import dataclass
from enum import Enum
from typing import Any

from rich.console import Group, RenderableType
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from aesc.provider import APIStatusError, ChatProviderError, ContentPart


def _format_provider_error(error: ChatProviderError) -> Text:
    """Format a ChatProviderError into a clean, user-friendly message.

    Avoids dumping raw JSON/HTTP responses to the UI. Shows a concise
    error with actionable hints for common issues (rate limits, auth, etc.).
    """
    error_str = str(error)
    error_lower = error_str.lower()

    msg = Text()

    # Rate limit / quota exhausted
    if any(kw in error_lower for kw in ("429", "rate limit", "resource_exhausted", "quota")):
        msg.append("Rate limited", style="red bold")
        msg.append(" — API quota exhausted. ", style="red")
        msg.append("Wait ~60s or switch to a GA model with higher limits.", style="yellow")
        return msg

    # Auth errors
    if any(kw in error_lower for kw in ("401", "403", "unauthorized", "forbidden", "permission")):
        msg.append("Auth error", style="red bold")
        msg.append(" — check your API key/credentials.", style="red")
        return msg

    # Model not found
    if any(kw in error_lower for kw in ("404", "not found", "model not found")):
        msg.append("Model not found", style="red bold")
        msg.append(" — verify the model name is correct.", style="red")
        return msg

    # Timeout
    if "timeout" in error_lower:
        msg.append("Request timed out", style="red bold")
        msg.append(" — the API didn't respond in time.", style="red")
        return msg

    # Connection error
    if "connection" in error_lower:
        msg.append("Connection error", style="red bold")
        msg.append(" — check network connectivity.", style="red")
        return msg

    # Generic: truncate to avoid flooding the UI
    # Show first 150 chars of the error, skip raw JSON bodies
    brief = error_str
    # Strip raw JSON/HTTP bodies
    for marker in (" - b'{", ' - b"', "\n{"):
        if marker in brief:
            brief = brief[: brief.index(marker)]
            break
    if len(brief) > 150:
        brief = brief[:150] + "..."
    msg.append("LLM error: ", style="red bold")
    msg.append(brief, style="red")
    return msg


from aesc.cli import Reload
from aesc.soul import LLMNotSet, LLMNotSupported, MaxStepsReached, RunCancelled, Soul, run_soul
from aesc.soul.aescsoul import AescSoul
from aesc.ui.output import OutputWriter
from aesc.ui.output.console import ConsoleOutputWriter
from aesc.ui.shell.console import console
from aesc.ui.shell.metacmd import get_meta_command
from aesc.ui.shell.prompt import toast
from aesc.ui.shell.replay import replay_recent_history
from aesc.ui.shell.update import LATEST_VERSION_FILE, UpdateResult, do_update, semver_tuple
from aesc.utils.logging import logger
from aesc.utils.signals import install_sigint_handler


class ShellApp:
    def __init__(
        self,
        soul: Soul,
        welcome_info: list[WelcomeInfoItem] | None = None,
    ):
        self.soul = soul
        self._welcome_info = list(welcome_info or [])
        self._background_tasks: set[asyncio.Task[Any]] = set()
        self._chat_app: Any | None = None  # Textual ChatApp instance

        # Output abstraction - will be set to TextualOutputWriter when in chat mode
        self.output: OutputWriter = ConsoleOutputWriter(console)

    async def run(self, command: str | None = None) -> bool:
        if command is not None:
            # run single command and exit
            logger.info("Running agent with command: {command}", command=command)
            return await self._run_textual_soul_command(command)

        self._start_background_task(self._auto_update())

        # Use Textual chat mode
        return await self._run_textual_chat_mode()

    async def _run_textual_chat_mode(self) -> bool:
        """Run in Textual chat mode with proper scrolling."""
        from rich.text import Text

        from aesc.ui.output.textual import TextualOutputWriter
        from aesc.ui.shell.textual_chat_app import TextualChatApp

        logger.debug("Starting Textual chat mode")

        try:
            welcome_panel = _create_welcome_panel(self.soul.name or "aesc", self._welcome_info)
        except Exception as e:
            logger.exception("Failed to create welcome panel:")
            raise RuntimeError(f"Failed to create welcome panel: {e}") from e

        input_queue: asyncio.Queue[str] = asyncio.Queue()
        processor_task: asyncio.Task | None = None

        async def handle_input(text: str):
            """Handle user input from TextualChatApp."""
            await input_queue.put(text)

        async def process_inputs():
            """Process user inputs from the queue."""
            while True:
                try:
                    user_input = await input_queue.get()

                    # Handle exit commands
                    if user_input in ["exit", "quit", "/exit", "/quit"]:
                        self._chat_app.add_message(Text("Bye!", style="grey50"))
                        await asyncio.sleep(0.5)
                        self._chat_app.exit()
                        break

                    # Add user message to chat
                    self._chat_app.add_user_message(user_input)

                    # Handle meta commands
                    if user_input.startswith("/"):
                        logger.debug("Running meta command: {command}", command=user_input)
                        await self._run_meta_command(user_input[1:])
                        continue

                    # Run agent command
                    logger.info("Running agent command: {command}", command=user_input)
                    await self._run_textual_soul_command(user_input)

                except asyncio.CancelledError:
                    # Task was cancelled (e.g., app is shutting down)
                    logger.debug("Input processor cancelled")
                    break
                except Reload:
                    # /clear or /reload requested - exit app to trigger reload
                    logger.info("Reload requested")
                    self._chat_app.exit()
                    raise
                except Exception as e:
                    logger.exception("Error processing input:")
                    if self._chat_app:
                        self._chat_app.add_message(Text(f"Error: {e}", style="red"))

        async def on_ready():
            """Start background tasks when Textual app is ready."""
            nonlocal processor_task
            processor_task = asyncio.create_task(process_inputs())

            # Set model info in prompt bar
            if isinstance(self.soul, AescSoul):
                try:
                    llm = self.soul._runtime._llm
                    if llm and hasattr(self._chat_app, "prompt_bar"):
                        model_name = llm.model_name if hasattr(llm, "model_name") else ""
                        max_context = (
                            llm.max_context_size if hasattr(llm, "max_context_size") else 0
                        )
                        self._chat_app.prompt_bar.set_model_info(model_name, max_context)
                except Exception:
                    pass  # LLM not set or error

            # Show session restore summary if we have restored context
            if isinstance(self.soul, AescSoul) and self.soul.context.has_restored_content:
                from aesc.soul.compaction import estimate_messages_tokens
                from aesc.ui.widgets.compaction_panel import CompactionPanel

                context = self.soul.context
                full_summary = context.get_session_summary()
                token_estimate = estimate_messages_tokens(context.history)

                if full_summary:
                    # Create brief summary (first line)
                    summary = full_summary.split("\n")[0][:100]
                    if len(summary) < len(full_summary):
                        summary += "..."

                    panel = CompactionPanel(
                        summary=summary,
                        full_summary=full_summary,
                        original_tokens=0,  # Unknown for restore
                        compacted_tokens=token_estimate,
                        compression_ratio=1.0,
                        is_session_restore=True,
                    )
                    self._chat_app.add_message(panel.render())
                    # Store panel reference for Ctrl+O toggle
                    if hasattr(self, "_session_restore_panel"):
                        pass  # Already stored
                    self._session_restore_panel = panel

        self._chat_app = TextualChatApp(
            welcome_panel=welcome_panel,
            prompt_text="",
            on_submit=handle_input,
            on_ready=on_ready,
        )

        self.output = TextualOutputWriter(self._chat_app)

        reload_requested = False
        try:
            await self._chat_app.run_async()
            return True
        except (KeyboardInterrupt, EOFError):
            logger.debug("Exiting textual chat mode")
            return True
        except Reload:
            # Reload was requested - propagate it up
            reload_requested = True
            raise
        except Exception:
            # Catch any unexpected exceptions to prevent raw crash
            logger.exception("Unexpected error in Textual chat mode:")
            return False
        finally:
            # Properly shutdown input queue to unblock processor
            try:
                input_queue.shutdown()
            except Exception:
                pass

            # Cancel processor task with proper cleanup
            if processor_task:
                processor_task.cancel()
                try:
                    await processor_task
                except asyncio.CancelledError:
                    pass
                except Reload:
                    # Reload was requested from processor - propagate it
                    if not reload_requested:
                        raise
                except Exception:
                    logger.debug("Processor task cleanup error (ignored)")

    async def _run_textual_soul_command(self, user_input: str) -> bool:
        """
        Run soul command with full agent integration for Textual chat UI.
        Uses the visualize_textual system for proper message updates.
        """
        cancel_event = asyncio.Event()

        def _handler():
            logger.debug("SIGINT received.")
            cancel_event.set()

        loop = asyncio.get_running_loop()
        remove_sigint = install_sigint_handler(loop, _handler)

        try:
            if isinstance(self.soul, AescSoul):
                # Set thinking mode if needed
                pass

            # Use Textual-compatible visualizer
            from aesc.ui.shell.visualize_textual import visualize_for_textual

            await run_soul(
                self.soul,
                user_input,
                lambda wire: visualize_for_textual(
                    wire,
                    chat_app=self._chat_app,
                    initial_status=self.soul.status,
                    cancel_event=cancel_event,
                ),
                cancel_event,
            )

            # Spacing is now handled by visualizer
            return True
        except LLMNotSet:
            logger.error("LLM not set")
            if self._chat_app:
                from rich.text import Text

                msg = "LLM not set, send /setup to configure"
                self._chat_app.add_message(Text(msg, style="red"))
        except ChatProviderError as e:
            logger.exception("LLM provider error:")
            if self._chat_app:
                self._chat_app.add_message(_format_provider_error(e))
        except MaxStepsReached as e:
            logger.warning("Max steps reached: {n_steps}", n_steps=e.n_steps)
            if self._chat_app:
                self._chat_app.add_message(Text(f"Max steps reached: {e.n_steps}", style="yellow"))
        except RunCancelled:
            logger.info("Cancelled by user")
            # Message already shown by visualizer, don't duplicate
        except BaseException as e:
            logger.exception("Unknown error:")
            if self._chat_app:
                from rich.text import Text

                self._chat_app.add_message(Text(f"Unknown error: {e}", style="red"))
            raise
        finally:
            remove_sigint()
        return False

    async def _run_shell_command(self, command: str) -> None:
        """Run a shell command in foreground."""
        if not command.strip():
            return

        logger.info("Running shell command: {cmd}", cmd=command)

        proc: asyncio.subprocess.Process | None = None

        def _handler():
            logger.debug("SIGINT received.")
            if proc:
                proc.terminate()

        loop = asyncio.get_running_loop()
        remove_sigint = install_sigint_handler(loop, _handler)
        try:
            # Later we should consider making this behave like a real shell.
            proc = await asyncio.create_subprocess_shell(command)
            await proc.wait()
        except Exception as e:
            logger.exception("Failed to run shell command:")
            console.print(f"[red]Failed to run shell command: {e}[/red]")
        finally:
            remove_sigint()

    async def _run_meta_command(self, command_str: str):
        from aesc.cli import Reload

        parts = command_str.split(" ")
        command_name = parts[0]
        command_args = parts[1:]
        command = get_meta_command(command_name)
        if command is None:
            msg = f"Meta command /{command_name} not found"
            if self._chat_app:
                self._chat_app.add_message(Text(msg, style="red"))
            else:
                console.print(msg)
            return
        if command.ash_soul_only and not isinstance(self.soul, AescSoul):
            msg = f"Meta command /{command_name} not supported"
            if self._chat_app:
                self._chat_app.add_message(Text(msg, style="red"))
            else:
                console.print(msg)
            return
        logger.debug(
            "Running meta command: {command_name} with args: {command_args}",
            command_name=command_name,
            command_args=command_args,
        )
        try:
            ret = command.func(self, command_args)
            if isinstance(ret, Awaitable):
                await ret
        except LLMNotSet:
            logger.error("LLM not set")
            msg = Text("LLM not set, send /setup to configure", style="red")
            if self._chat_app:
                self._chat_app.add_message(msg)
            else:
                console.print(msg)
        except ChatProviderError as e:
            logger.exception("LLM provider error:")
            msg = _format_provider_error(e)
            if self._chat_app:
                self._chat_app.add_message(msg)
            else:
                console.print(msg)
        except asyncio.CancelledError:
            logger.info("Interrupted by user")
            msg = Text("Interrupted by user", style="red")
            if self._chat_app:
                self._chat_app.add_message(msg)
            else:
                console.print(msg)
        except Reload:
            # just propagate
            raise
        except BaseException as e:
            logger.exception("Unknown error:")
            msg = Text(f"Unknown error: {e}", style="red")
            if self._chat_app:
                self._chat_app.add_message(msg)
            else:
                console.print(msg)
            raise  # re-raise unknown error

    async def _auto_update(self) -> None:
        toast("checking for updates...", topic="update", duration=2.0)
        result = await do_update(print=False, check_only=True)
        if result == UpdateResult.UPDATE_AVAILABLE:
            while True:
                toast(
                    "new version found, run `uv tool upgrade aesc` to upgrade",
                    topic="update",
                    duration=30.0,
                )
                await asyncio.sleep(60.0)
        elif result == UpdateResult.UPDATED:
            toast("auto updated, restart to use the new version", topic="update", duration=5.0)

    def _start_background_task(self, coro: Coroutine[Any, Any, Any]) -> asyncio.Task[Any]:
        task = asyncio.create_task(coro)
        self._background_tasks.add(task)

        def _cleanup(t: asyncio.Task[Any]) -> None:
            self._background_tasks.discard(t)
            try:
                t.result()
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.exception("Background task failed:")

        task.add_done_callback(_cleanup)
        return task


# Theme colors
_BRAND = "#a855f7"
_TEXT = "#fafafa"
_TEXT_MUTED = "#a1a1aa"
_TEXT_DIM = "#71717a"
_TEXT_SUBTLE = "#52525b"
_SUCCESS = "#4ade80"
_WARNING = "#fbbf24"
_ERROR = "#f87171"
_BORDER = "#3f3f46"


@dataclass(slots=True)
class WelcomeInfoItem:
    class Level(Enum):
        INFO = "#a1a1aa"
        WARN = "#fbbf24"
        ERROR = "#f87171"
        SUCCESS = "#4ade80"

    name: str
    value: str
    level: Level = Level.INFO


def _create_welcome_panel(name: str, info_items: list[WelcomeInfoItem]) -> RenderableType:
    """Create minimal welcome display for chat mode - Claude Code inspired."""
    from aesc.constant import VERSION

    rows: list[RenderableType] = []

    # Clean header - single line, minimal
    header = Text()
    header.append("◆ ", style=f"bold {_BRAND}")
    header.append("AESC", style=f"bold {_BRAND}")
    header.append("  by akæli", style=_TEXT_DIM)
    header.append(f"  v{VERSION}", style=_TEXT_SUBTLE)
    rows.append(header)

    # Info items - compact format
    if info_items:
        for item in info_items:
            line = Text()
            line.append(f"  {item.name}: ", style=_TEXT_DIM)
            line.append(item.value, style=item.level.value)
            rows.append(line)

    # Help hint - subtle
    help_line = Text()
    help_line.append("  /help", style=_TEXT_DIM)
    help_line.append(" commands  ", style=_TEXT_SUBTLE)
    help_line.append("/setup", style=_TEXT_DIM)
    help_line.append(" configure", style=_TEXT_SUBTLE)
    rows.append(help_line)

    # Version update notice if available
    if LATEST_VERSION_FILE.exists():
        from aesc.constant import VERSION as current_version

        latest_version = LATEST_VERSION_FILE.read_text(encoding="utf-8").strip()
        if semver_tuple(latest_version) > semver_tuple(current_version):
            update_line = Text()
            update_line.append("  ● ", style=_WARNING)
            update_line.append(f"v{latest_version} available", style=_WARNING)
            update_line.append("  uv tool upgrade aesc", style=_TEXT_DIM)
            rows.append(update_line)

    # Return as simple Group - no panel border
    return Group(*rows)


def _print_welcome_info(name: str, info_items: list[WelcomeInfoItem]) -> None:
    """Print professional welcome banner for AESC CLI (classic mode)."""
    welcome = _create_welcome_panel(name, info_items)
    console.print(welcome)
