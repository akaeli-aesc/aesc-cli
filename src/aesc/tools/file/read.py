from pathlib import Path
from typing import Any, override

import aiofiles
from pydantic import BaseModel, Field

from aesc.provider import CallableTool2, ToolError, ToolOk, ToolReturnType
from aesc.soul.runtime import BuiltinSystemPromptArgs
from aesc.tools.utils import load_desc, truncate_line

MAX_LINES = 1000
MAX_LINE_LENGTH = 2000
MAX_BYTES = 100 << 10  # 100KB

# Paths that leak platform secrets (API keys, credentials, tokens).
# These are infrastructure files, not engagement targets.
_BLOCKED_PATHS = frozenset(
    {
        "/proc/self/environ",
        "/proc/self/status",
        "/proc/1/environ",
    }
)
_BLOCKED_PREFIXES = (
    "/proc/self/environ",
    "/proc/1/environ",
)


class Params(BaseModel):
    path: str = Field(description="The absolute path to the file to read")
    line_offset: int = Field(
        description=(
            "The line number to start reading from. "
            "By default read from the beginning of the file. "
            "Set this when the file is too large to read at once."
        ),
        default=1,
        ge=1,
    )
    n_lines: int = Field(
        description=(
            "The number of lines to read. "
            f"By default read up to {MAX_LINES} lines, which is the max allowed value. "
            "Set this value when the file is too large to read at once."
        ),
        default=MAX_LINES,
        ge=1,
    )


class ReadFile(CallableTool2[Params]):
    name: str = "ReadFile"
    description: str = load_desc(
        Path(__file__).parent / "read.md",
        {
            "MAX_LINES": str(MAX_LINES),
            "MAX_LINE_LENGTH": str(MAX_LINE_LENGTH),
            "MAX_BYTES": str(MAX_BYTES),
        },
    )
    params: type[Params] = Params

    def __init__(self, builtin_args: BuiltinSystemPromptArgs, **kwargs: Any) -> None:
        super().__init__(**kwargs)

        self._work_dir = builtin_args.AESC_WORK_DIR

    @override
    async def __call__(self, params: Params) -> ToolReturnType:
        # - check if the path may contain secrets
        # - check if the file format is readable
        try:
            p = Path(params.path)

            if not p.is_absolute():
                return ToolError(
                    message=(
                        f"`{params.path}` is not an absolute path. "
                        "You must provide an absolute path to read a file."
                    ),
                    brief="Invalid path",
                )

            # Block reads of process environment and other platform secret paths
            resolved = str(p.resolve())
            if resolved in _BLOCKED_PATHS or resolved.startswith(_BLOCKED_PREFIXES):
                return ToolError(
                    message=f"Access denied: `{params.path}` is a restricted system path.",
                    brief="Access denied",
                )

            if not p.exists():
                return ToolError(
                    message=f"`{params.path}` does not exist.",
                    brief="File not found",
                )
            if not p.is_file():
                return ToolError(
                    message=f"`{params.path}` is not a file.",
                    brief="Invalid path",
                )

            if params.line_offset < 1:
                return ToolError(
                    message="line_offset must be >= 1",
                    brief="Invalid parameter",
                )
            if params.n_lines < 1:
                return ToolError(
                    message="n_lines must be >= 1",
                    brief="Invalid parameter",
                )

            lines: list[str] = []
            n_bytes = 0
            truncated_line_numbers: list[int] = []
            max_lines_reached = False
            max_bytes_reached = False
            async with aiofiles.open(p, encoding="utf-8", errors="replace") as f:
                current_line_no = 0
                async for line in f:
                    current_line_no += 1
                    if current_line_no < params.line_offset:
                        continue
                    truncated = truncate_line(line, MAX_LINE_LENGTH)
                    if truncated != line:
                        truncated_line_numbers.append(current_line_no)
                    lines.append(truncated)
                    n_bytes += len(truncated.encode("utf-8"))
                    if len(lines) >= params.n_lines:
                        break
                    if len(lines) >= MAX_LINES:
                        max_lines_reached = True
                        break
                    if n_bytes >= MAX_BYTES:
                        max_bytes_reached = True
                        break

            # Format output with line numbers like `cat -n`
            lines_with_no: list[str] = []
            for line_num, line in zip(
                range(params.line_offset, params.line_offset + len(lines)), lines, strict=True
            ):
                # Use 6-digit line number width, right-aligned, with tab separator
                lines_with_no.append(f"{line_num:6d}\t{line}")

            message = (
                f"{len(lines)} lines read from file starting from line {params.line_offset}."
                if len(lines) > 0
                else "No lines read from file."
            )
            if max_lines_reached:
                message += f" Max {MAX_LINES} lines reached."
            elif max_bytes_reached:
                message += f" Max {MAX_BYTES} bytes reached."
            elif len(lines) < params.n_lines:
                message += " End of file reached."
            if truncated_line_numbers:
                message += f" Lines {truncated_line_numbers} were truncated."
            return ToolOk(
                output="".join(lines_with_no),  # lines already contain \n, just join them
                message=message,
            )
        except FileNotFoundError:
            return ToolError(
                message=f"File not found: {params.path}",
                brief="File not found",
            )
        except PermissionError:
            return ToolError(
                message=f"Permission denied reading: {params.path}",
                brief="Permission denied",
            )
        except IsADirectoryError:
            return ToolError(
                message=f"Path is a directory, not a file: {params.path}",
                brief="Path is a directory",
            )
        except OSError as e:
            return ToolError(
                message=f"Failed to read {params.path}: {e}",
                brief="I/O error",
            )
