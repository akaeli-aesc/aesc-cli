from __future__ import annotations

import asyncio
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any, Literal

import typer

from aesc.constant import VERSION
from aesc.exception import ConfigError
from aesc.soul import LLMNotSet
from aesc.utils.logging import logger


class Reload(Exception):
    """Reload configuration."""

    pass


cli = typer.Typer(
    add_completion=False,
    context_settings={"help_option_names": ["-h", "--help"]},
    help="AESC - AI-powered security agent",
)

UIMode = Literal["shell", "print", "acp", "wire"]
InputFormat = Literal["text", "stream-json"]
OutputFormat = Literal["text", "stream-json"]


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"aesc, version {VERSION}")
        raise typer.Exit()


@cli.command()
def aesc(
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            "-V",
            help="Show version and exit.",
            callback=_version_callback,
            is_eager=True,
        ),
    ] = False,
    verbose: Annotated[
        bool,
        typer.Option(
            "--verbose",
            help="Print verbose information. Default: no.",
        ),
    ] = False,
    debug: Annotated[
        bool,
        typer.Option(
            "--debug",
            help="Log debug information. Default: no.",
        ),
    ] = False,
    agent_file: Annotated[
        Path | None,
        typer.Option(
            "--agent-file",
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
            help="Custom agent specification file. Default: builtin default agent.",
        ),
    ] = None,
    model_name: Annotated[
        str | None,
        typer.Option(
            "--model",
            "-m",
            help="LLM model to use. Default: default model set in config file.",
        ),
    ] = None,
    work_dir: Annotated[
        Path | None,
        typer.Option(
            "--work-dir",
            "-w",
            exists=True,
            file_okay=False,
            dir_okay=True,
            readable=True,
            writable=True,
            help="Working directory for the agent. Default: current directory.",
        ),
    ] = None,
    continue_: Annotated[
        bool,
        typer.Option(
            "--continue",
            "-C",
            help="Continue the previous session for the working directory. Default: no.",
        ),
    ] = False,
    command: Annotated[
        str | None,
        typer.Option(
            "--command",
            "-c",
            "--query",
            "-q",
            help="User query to the agent. Default: prompt interactively.",
        ),
    ] = None,
    print_mode: Annotated[
        bool,
        typer.Option(
            "--print",
            "--headless",
            "--non-interactive",
            help=(
                "Run in print mode (non-interactive). Outputs to stdout, auto-approves all actions. "
                "Aliases: --headless, --non-interactive. Note: print mode implicitly adds `--yolo`."
            ),
        ),
    ] = False,
    acp_mode: Annotated[
        bool,
        typer.Option(
            "--acp",
            help="Run as ACP server.",
        ),
    ] = False,
    wire_mode: Annotated[
        bool,
        typer.Option(
            "--wire",
            help="Run as Wire server (experimental).",
        ),
    ] = False,
    input_format: Annotated[
        InputFormat | None,
        typer.Option(
            "--input-format",
            help=(
                "Input format to use. Must be used with `--print` "
                "and the input must be piped in via stdin. "
                "Default: text."
            ),
        ),
    ] = None,
    output_format: Annotated[
        OutputFormat | None,
        typer.Option(
            "--output-format",
            help="Output format to use. Must be used with `--print`. Default: text.",
        ),
    ] = None,
    mcp_config_file: Annotated[
        list[Path] | None,
        typer.Option(
            "--mcp-config-file",
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
            help=(
                "MCP config file to load. Add this option multiple times to specify multiple MCP "
                "configs. Default: none."
            ),
        ),
    ] = None,
    mcp_config: Annotated[
        list[str] | None,
        typer.Option(
            "--mcp-config",
            help=(
                "MCP config JSON to load. Add this option multiple times to specify multiple MCP "
                "configs. Default: none."
            ),
        ),
    ] = None,
    yolo: Annotated[
        bool,
        typer.Option(
            "--yolo",
            "--yes",
            "-y",
            "--auto-approve",
            help="Automatically approve all actions. Default: no.",
        ),
    ] = False,
    thinking: Annotated[
        bool,
        typer.Option(
            "--thinking",
            help="Enable thinking mode if supported. Default: no.",
        ),
    ] = False,
    exclude_tools: Annotated[
        list[str] | None,
        typer.Option(
            "--exclude-tools",
            help=(
                "Tools to exclude from the agent's toolset. "
                "Use module:Class format (e.g., 'aesc.tools.task:Task'). "
                "Can be specified multiple times."
            ),
        ),
    ] = None,
):
    """AESC - AI-powered security agent."""
    del version  # handled in the callback

    from aesc.app import AescCLI
    from aesc.session import Session
    from aesc.share import get_share_dir

    def _noop_echo(*args: Any, **kwargs: Any):
        pass

    special_flags = {
        "--print": print_mode,
        "--acp": acp_mode,
        "--wire": wire_mode,
    }
    active_specials = [flag for flag, active in special_flags.items() if active]
    if len(active_specials) > 1:
        raise typer.BadParameter(
            f"Cannot combine {', '.join(active_specials)}.",
            param_hint=active_specials[0],
        )

    ui: UIMode = "shell"
    if print_mode:
        ui = "print"
    elif acp_mode:
        ui = "acp"
    elif wire_mode:
        ui = "wire"

    # Check for TTY in interactive mode
    if ui == "shell" and not sys.stdin.isatty():
        typer.secho(
            "Error: Interactive shell requires a TTY. Run with 'docker run -it' or use '--headless' mode.",
            fg="red",
            err=True,
        )
        typer.secho("Examples:", fg="yellow", err=True)
        typer.secho("  docker run -it aesc:dev                   # Interactive mode", err=True)
        typer.secho(
            "  docker run aesc:dev -c 'query' --headless  # Non-interactive (CI/CD)", err=True
        )
        raise typer.Exit(1)

    echo: Callable[..., None] = typer.echo if verbose else _noop_echo

    if debug:
        logger.enable("aesc.provider")
    # TEMP DISABLED:     logger.add(
    # TEMP DISABLED:         get_share_dir() / "logs" / "aesc.log",
    # TEMP DISABLED:         level="TRACE" if debug else "INFO",
    # TEMP DISABLED:         rotation="06:00",
    # TEMP DISABLED:         retention="10 days",
    # TEMP DISABLED:     )

    work_dir = (work_dir or Path.cwd()).absolute()
    if continue_:
        session = Session.continue_(work_dir)
        if session is None:
            raise typer.BadParameter(
                "No previous session found for the working directory",
                param_hint="--continue",
            )
        echo(f"✓ Continuing previous session: {session.id}")
    else:
        session = Session.create(work_dir)
        echo(f"✓ Created new session: {session.id}")
    echo(f"✓ Session history file: {session.history_file}")

    if command is not None:
        command = command.strip()
        if not command:
            raise typer.BadParameter("Command cannot be empty", param_hint="--command")

    if input_format is not None and ui != "print":
        raise typer.BadParameter(
            "Input format is only supported for print UI",
            param_hint="--input-format",
        )
    if output_format is not None and ui != "print":
        raise typer.BadParameter(
            "Output format is only supported for print UI",
            param_hint="--output-format",
        )

    file_configs = list(mcp_config_file or [])
    raw_mcp_config = list(mcp_config or [])

    try:
        mcp_configs = [json.loads(conf.read_text(encoding="utf-8")) for conf in file_configs]
    except json.JSONDecodeError as e:
        raise typer.BadParameter(f"Invalid JSON: {e}", param_hint="--mcp-config-file") from e

    try:
        mcp_configs += [json.loads(conf) for conf in raw_mcp_config]
    except json.JSONDecodeError as e:
        raise typer.BadParameter(f"Invalid JSON: {e}", param_hint="--mcp-config") from e

    async def _run() -> bool:
        instance = await AescCLI.create(
            session,
            yolo=yolo or (ui == "print"),  # print mode implies yolo
            stream=ui != "print",  # use non-streaming mode only for print UI
            mcp_configs=mcp_configs,
            model_name=model_name,
            thinking=thinking,
            agent_file=agent_file,
            exclude_tools=exclude_tools,
        )
        match ui:
            case "shell":
                return await instance.run_shell_mode(command)
            case "print":
                return await instance.run_print_mode(
                    input_format or "text",
                    output_format or "text",
                    command,
                )
            case "acp":
                if command is not None:
                    logger.warning("ACP server ignores command argument")
                return await instance.run_acp_server()
            case "wire":
                if command is not None:
                    logger.warning("Wire server ignores command argument")
                return await instance.run_wire_server()

    while True:
        try:
            succeeded = asyncio.run(_run())
            if succeeded:
                session.mark_as_last()
                break
            sys.exit(1)
        except Reload:
            continue
        except KeyboardInterrupt:
            # Clean exit on Ctrl+C
            if debug:
                logger.debug("Exiting due to KeyboardInterrupt")
            sys.exit(0)
        except (ConfigError, LLMNotSet) as e:
            # No usable LLM is configured (common on first run / in --print mode).
            # Give actionable guidance instead of a crash report.
            msg = str(e) or "No LLM provider configured."
            typer.secho(f"\n{msg}", fg="red", err=True)
            typer.secho(
                "Set an API key (e.g. ANTHROPIC_API_KEY or OPENAI_API_KEY) or run "
                "`aesc` and use /setup to configure a provider.",
                fg="yellow",
                err=True,
            )
            sys.exit(1)
        except Exception as e:
            # Log the full traceback for debugging
            logger.exception("Fatal error in aesc CLI:")

            # Print user-friendly error message
            import traceback

            typer.secho(
                "\n╭─ AESC Crash Report ─────────────────────────────────────╮", fg="red", err=True
            )
            typer.secho(f"│ Error: {type(e).__name__}: {e}", fg="red", err=True)
            typer.secho(
                "╰────────────────────────────────────────────────────────╯", fg="red", err=True
            )

            if debug:
                typer.secho("\nFull traceback:", fg="yellow", err=True)
                traceback.print_exc()
            else:
                typer.secho("\nRun with --debug for full traceback", fg="yellow", err=True)
                typer.secho(
                    f"Logs: {get_share_dir() / 'logs' / 'aesc.log'}", fg="bright_black", err=True
                )

            sys.exit(1)


def main():
    """Entry point with top-level exception handling."""
    try:
        cli()
    except Exception as e:
        # Catch any exceptions that escape the CLI (e.g., during startup)
        import sys
        import traceback

        print(
            "\n\033[91m╭─ AESC Startup Error ─────────────────────────────────────╮\033[0m",
            file=sys.stderr,
        )
        print(f"\033[91m│ {type(e).__name__}: {e}\033[0m", file=sys.stderr)
        print(
            "\033[91m╰─────────────────────────────────────────────────────────╯\033[0m",
            file=sys.stderr,
        )
        print("\nFull traceback:", file=sys.stderr)
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
