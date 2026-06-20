from enum import Enum
from pathlib import Path

from aesc.provider import ToolError


class FileActions(str, Enum):
    READ = "read file"
    EDIT = "edit file"


class PathValidationError(Exception):
    """Raised when path validation fails."""

    def __init__(self, message: str, brief: str):
        super().__init__(message)
        self.message = message
        self.brief = brief


def validate_path_within_workdir(
    path: Path,
    work_dir: Path,
    *,
    operation: str = "access",
) -> None:
    """
    Validate that a path is within the working directory.

    Uses Path.relative_to() which is secure against symlink attacks,
    unlike string prefix matching.

    Args:
        path: The path to validate (will be resolved)
        work_dir: The working directory (will be resolved)
        operation: Description of the operation for error messages

    Raises:
        PathValidationError: If the path is outside the working directory
    """
    try:
        resolved_path = path.resolve()
        resolved_work_dir = work_dir.resolve()

        # This raises ValueError if path is not relative to work_dir
        # It's secure because it checks the actual resolved paths,
        # not string prefixes that can be fooled by symlinks
        resolved_path.relative_to(resolved_work_dir)
    except ValueError as e:
        raise PathValidationError(
            message=(
                f"`{path}` is outside the working directory. "
                f"You can only {operation} files within the working directory."
            ),
            brief="Path outside working directory",
        ) from e


def validate_path_or_error(
    path: Path,
    work_dir: Path,
    *,
    operation: str = "access",
) -> ToolError | None:
    """
    Validate path and return ToolError if invalid, None if valid.

    Convenience wrapper around validate_path_within_workdir for tool implementations.
    """
    try:
        validate_path_within_workdir(path, work_dir, operation=operation)
        return None
    except PathValidationError as e:
        return ToolError(message=e.message, brief=e.brief)


from .glob import Glob  # noqa: E402
from .grep import Grep  # noqa: E402
from .patch import PatchFile  # noqa: E402
from .read import ReadFile  # noqa: E402
from .replace import StrReplaceFile  # noqa: E402
from .write import WriteFile  # noqa: E402

__all__ = (
    "ReadFile",
    "Glob",
    "Grep",
    "WriteFile",
    "StrReplaceFile",
    "PatchFile",
)
