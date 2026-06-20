from pathlib import Path
from typing import Literal, override

from pydantic import BaseModel, Field

from aesc.provider import CallableTool2, ToolOk, ToolReturnType
from aesc.tools.utils import load_desc


class Todo(BaseModel):
    title: str = Field(description="The title of the todo", min_length=1)
    status: Literal["Pending", "In Progress", "Done"] = Field(description="The status of the todo")


class Params(BaseModel):
    todos: list[Todo] = Field(description="The updated todo list")


class SetTodoList(CallableTool2[Params]):
    name: str = "SetTodoList"
    description: str = load_desc(Path(__file__).parent / "set_todo_list.md")
    params: type[Params] = Params

    @override
    async def __call__(self, params: Params) -> ToolReturnType:
        # Create clean plain-text todo list (no markdown)
        output = self._render_todos(params.todos)

        # Count by status for brief
        in_progress = sum(1 for t in params.todos if t.status == "In Progress")
        pending = sum(1 for t in params.todos if t.status == "Pending")
        done = sum(1 for t in params.todos if t.status == "Done")

        brief = f"{len(params.todos)} tasks"
        if in_progress:
            brief += f" ({in_progress} active)"

        return ToolOk(
            output=output,
            message="Todo list updated",
            brief=brief,
        )

    def _render_todos(self, todos: list[Todo]) -> str:
        """Render todo list with clean plain text - no markdown."""
        if not todos:
            return "No tasks"

        lines = []

        # Group todos by status
        in_progress = [t for t in todos if t.status == "In Progress"]
        pending = [t for t in todos if t.status == "Pending"]
        done = [t for t in todos if t.status == "Done"]

        # Render in-progress first (most important)
        if in_progress:
            for todo in in_progress:
                lines.append(f"● {todo.title}")

        # Then pending
        if pending:
            for todo in pending:
                lines.append(f"○ {todo.title}")

        # Finally completed (dimmed)
        if done:
            for todo in done:
                lines.append(f"✓ {todo.title}")

        return "\n".join(lines)
