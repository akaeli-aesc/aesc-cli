"""Glob tool implementation."""

import asyncio
from pathlib import Path
from typing import Any, override

import aiofiles.os
from pydantic import BaseModel, Field

from aesc.provider import CallableTool2, ToolError, ToolOk, ToolReturnType
from aesc.soul.runtime import BuiltinSystemPromptArgs
from aesc.tools.file import validate_path_or_error
from aesc.tools.utils import load_desc

MAX_MATCHES = 1000


class Params(BaseModel):
    pattern: str = Field(description=("Glob pattern to match files/directories."))
    directory: str | None = Field(
        description=(
            "Absolute path to the directory to search in (defaults to working directory)."
        ),
        default=None,
    )
    include_dirs: bool = Field(
        description="Whether to include directories in results.",
        default=True,
    )


class Glob(CallableTool2[Params]):
    name: str = "Glob"
    description: str = load_desc(
        Path(__file__).parent / "glob.md",
        {
            "MAX_MATCHES": str(MAX_MATCHES),
        },
    )
    params: type[Params] = Params

    # System paths allowed for searching (security tools, wordlists, etc.)
    _ALLOWED_SYSTEM_PATHS = [
        Path("/usr/share/wordlists"),
        Path("/usr/share/seclists"),
        Path("/usr/share/nmap"),
        Path("/usr/share/metasploit-framework"),
        Path("/opt"),
        Path("/results"),
        Path("/workspace"),
    ]

    def __init__(self, builtin_args: BuiltinSystemPromptArgs, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._work_dir = builtin_args.AESC_WORK_DIR

    async def _validate_pattern(self, pattern: str) -> ToolError | None:
        """Validate that the pattern is safe to use."""
        if pattern.startswith("**"):
            ls_result = await aiofiles.os.listdir(self._work_dir)
            return ToolError(
                output="\n".join(ls_result),
                message=(
                    f"Pattern `{pattern}` starts with '**' which is not allowed. "
                    "This would recursively search all directories and may include large "
                    "directories like `node_modules`. Use more specific patterns instead. "
                    "For your convenience, a list of all files and directories in the "
                    "top level of the working directory is provided below."
                ),
                brief="Unsafe pattern",
            )
        return None

    def _validate_directory(self, directory: Path) -> ToolError | None:
        """Validate that the directory is safe to search."""
        try:
            resolved = directory.resolve()
            # Check if it's within an allowed system path
            for allowed in self._ALLOWED_SYSTEM_PATHS:
                try:
                    resolved.relative_to(allowed.resolve())
                    return None  # Path is within allowed system directory
                except ValueError:
                    continue
        except OSError:
            pass  # Fall through to work_dir validation

        # Fall back to working directory check
        return validate_path_or_error(directory, self._work_dir, operation="search")

    @override
    async def __call__(self, params: Params) -> ToolReturnType:
        try:
            # Validate pattern safety
            pattern_error = await self._validate_pattern(params.pattern)
            if pattern_error:
                return pattern_error

            dir_path = Path(params.directory) if params.directory else self._work_dir

            if not dir_path.is_absolute():
                return ToolError(
                    message=(
                        f"`{params.directory}` is not an absolute path. "
                        "You must provide an absolute path to search."
                    ),
                    brief="Invalid directory",
                )

            # Validate directory safety
            dir_error = self._validate_directory(dir_path)
            if dir_error:
                return dir_error

            if not dir_path.exists():
                return ToolError(
                    message=f"`{params.directory}` does not exist.",
                    brief="Directory not found",
                )
            if not dir_path.is_dir():
                return ToolError(
                    message=f"`{params.directory}` is not a directory.",
                    brief="Invalid directory",
                )

            def _glob(pattern: str) -> list[Path]:
                return list(dir_path.glob(pattern))

            # Perform the glob search - users can use ** directly in pattern
            try:
                matches = await asyncio.to_thread(_glob, params.pattern)
            except RuntimeError as e:
                # asyncio.to_thread can fail if event loop issues
                return ToolError(
                    message=f"Failed to execute glob in thread: {e}",
                    brief="Threading error",
                )

            # Filter out directories if not requested
            if not params.include_dirs:
                matches = [p for p in matches if p.is_file()]

            # Sort for consistent output
            matches.sort()

            # Limit matches
            message = (
                f"Found {len(matches)} matches for pattern `{params.pattern}`."
                if len(matches) > 0
                else f"No matches found for pattern `{params.pattern}`."
            )
            if len(matches) > MAX_MATCHES:
                matches = matches[:MAX_MATCHES]
                message += (
                    f" Only the first {MAX_MATCHES} matches are returned. "
                    "You may want to use a more specific pattern."
                )

            return ToolOk(
                output="\n".join(str(p.relative_to(dir_path)) for p in matches),
                message=message,
            )

        except FileNotFoundError as e:
            return ToolError(
                message=f"Directory not found: {e}",
                brief="Directory not found",
            )
        except PermissionError as e:
            return ToolError(
                message=f"Permission denied: {e}",
                brief="Permission denied",
            )
        except OSError as e:
            return ToolError(
                message=f"Failed to search for pattern {params.pattern}: {e}",
                brief="I/O error",
            )
        except asyncio.CancelledError:
            return ToolError(
                message="Glob operation was cancelled",
                brief="Cancelled",
            )
        except Exception as e:
            # Catch-all for unexpected errors - log and return specific error type
            import logging

            logging.getLogger(__name__).exception(f"Glob failed unexpectedly: {e}")
            return ToolError(
                message=f"Glob failed ({type(e).__name__}): {e}",
                brief=f"Error: {type(e).__name__}",
            )
