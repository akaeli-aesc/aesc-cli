from pathlib import Path
from typing import Any, Literal, override

import aiofiles
from pydantic import BaseModel, Field

from aesc.provider import CallableTool2, ToolError, ToolOk, ToolReturnType
from aesc.soul.approval import Approval
from aesc.soul.runtime import BuiltinSystemPromptArgs
from aesc.tools.file import FileActions, validate_path_or_error
from aesc.tools.utils import ToolRejectedError, load_desc


class Params(BaseModel):
    path: str = Field(description="The absolute path to the file to write")
    content: str = Field(description="The content to write to the file")
    mode: Literal["overwrite", "append"] = Field(
        description=(
            "The mode to use to write to the file. "
            "Two modes are supported: `overwrite` for overwriting the whole file and "
            "`append` for appending to the end of an existing file."
        ),
        default="overwrite",
    )


class WriteFile(CallableTool2[Params]):
    name: str = "WriteFile"
    description: str = load_desc(Path(__file__).parent / "write.md")
    params: type[Params] = Params

    def __init__(self, builtin_args: BuiltinSystemPromptArgs, approval: Approval, **kwargs: Any):
        super().__init__(**kwargs)
        self._work_dir = builtin_args.AESC_WORK_DIR
        self._results_dir = builtin_args.AESC_RESULTS_DIR
        self._approval = approval

    # Additional paths allowed for writing (outside working directory)
    # Note: Session-specific results dir is added dynamically in _validate_path
    _ALLOWED_PATHS = [Path("/results"), Path("/workspace")]

    def _validate_path(self, path: Path) -> ToolError | None:
        """Validate that the path is safe to write."""
        resolved_path = path.resolve()

        # Allow /results directory for saving findings
        for allowed in self._ALLOWED_PATHS:
            try:
                resolved_path.relative_to(allowed.resolve())
                return None  # Path is within an allowed directory
            except ValueError:
                continue

        # Fall back to working directory check
        return validate_path_or_error(path, self._work_dir, operation="write")

    @override
    async def __call__(self, params: Params) -> ToolReturnType:
        # - check if the path may contain secrets
        # - check if the file format is writable
        try:
            p = Path(params.path)

            if not p.is_absolute():
                return ToolError(
                    message=(
                        f"`{params.path}` is not an absolute path. "
                        "You must provide an absolute path to write a file."
                    ),
                    brief="Invalid path",
                )

            # Validate path safety
            path_error = self._validate_path(p)
            if path_error:
                return path_error

            if not p.parent.exists():
                return ToolError(
                    message=f"`{params.path}` parent directory does not exist.",
                    brief="Parent directory not found",
                )

            # Validate mode parameter
            if params.mode not in ["overwrite", "append"]:
                return ToolError(
                    message=(
                        f"Invalid write mode: `{params.mode}`. "
                        "Mode must be either `overwrite` or `append`."
                    ),
                    brief="Invalid write mode",
                )

            # Request approval
            if not await self._approval.request(
                self.name,
                FileActions.EDIT,
                f"Write file `{params.path}`",
            ):
                return ToolRejectedError()

            # Determine file mode for aiofiles
            file_mode = "w" if params.mode == "overwrite" else "a"

            # Write content to file
            async with aiofiles.open(p, mode=file_mode, encoding="utf-8") as f:
                await f.write(params.content)

            # Get file info for success message
            file_size = p.stat().st_size
            action = "overwritten" if params.mode == "overwrite" else "appended to"
            return ToolOk(
                output="",
                message=(f"File successfully {action}. Current size: {file_size} bytes."),
            )

        except FileNotFoundError:
            return ToolError(
                message=f"Parent directory does not exist: {params.path}",
                brief="Directory not found",
            )
        except PermissionError:
            return ToolError(
                message=f"Permission denied writing to: {params.path}",
                brief="Permission denied",
            )
        except IsADirectoryError:
            return ToolError(
                message=f"Path is a directory, not a file: {params.path}",
                brief="Path is a directory",
            )
        except OSError as e:
            return ToolError(
                message=f"Failed to write to {params.path}: {e}",
                brief="I/O error",
            )
