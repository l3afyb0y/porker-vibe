from __future__ import annotations

from typing import ClassVar, final

import aiofiles
from pydantic import BaseModel, Field

from vibe.core.tools.base import (
    BaseTool,
    BaseToolConfig,
    BaseToolState,
    ToolError,
    ToolPermission,
)
from vibe.core.tools.ui import ToolCallDisplay, ToolResultDisplay, ToolUIData
from vibe.core.types import ToolCallEvent, ToolResultEvent


class TodoWriteArgs(BaseModel):
    content: str = Field(
        description="Full content of the todos.md file in markdown format."
    )


class TodoWriteResult(BaseModel):
    path: str
    bytes_written: int
    message: str


class TodoWriteConfig(BaseToolConfig):
    permission: ToolPermission = ToolPermission.ALWAYS


class TodoWriteState(BaseToolState):
    pass


class TodoWrite(
    BaseTool[TodoWriteArgs, TodoWriteResult, TodoWriteConfig, TodoWriteState],
    ToolUIData[TodoWriteArgs, TodoWriteResult],
):
    """Maintain a persistent list of tasks in ./.vibe/plans/todos.md.

    This tool is the primary way to track progress in the UI.
    ALWAYS mark a task as 'in_progress' BEFORE starting work on it and 'completed' IMMEDIATELY after finishing.
    Use GFM task list syntax:
    - [ ] pending
    - [/] in_progress
    - [x] completed
    """

    description: ClassVar[str] = (
        "Create or update the project's todo list at ./.vibe/plans/todos.md."
    )

    @classmethod
    def get_call_display(cls, event: ToolCallEvent) -> ToolCallDisplay:
        if not isinstance(event.args, TodoWriteArgs):
            return ToolCallDisplay(summary="Invalid arguments")

        return ToolCallDisplay(summary="Updating todo list", content=event.args.content)

    @classmethod
    def get_result_display(cls, event: ToolResultEvent) -> ToolResultDisplay:
        if isinstance(event.result, TodoWriteResult):
            return ToolResultDisplay(success=True, message=event.result.message)
        return ToolResultDisplay(success=True, message="Todo list updated")

    @classmethod
    def get_status_text(cls) -> str:
        return "Updating todos"

    @final
    async def run(self, args: TodoWriteArgs) -> TodoWriteResult:
        todo_path = self.config.effective_workdir / ".vibe" / "plans" / "todos.md"

        try:
            todo_path.parent.mkdir(parents=True, exist_ok=True)
            content_bytes = len(args.content.encode("utf-8"))

            async with aiofiles.open(todo_path, mode="w", encoding="utf-8") as f:
                await f.write(args.content)

            return TodoWriteResult(
                path=str(todo_path),
                bytes_written=content_bytes,
                message=f"Updated todos.md ({content_bytes} bytes)",
            )
        except Exception as e:
            raise ToolError(f"Error writing todo file {todo_path}: {e}") from e
