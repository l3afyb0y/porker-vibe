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

            # Plan sync hook: update dev/PLAN.md checkboxes based on todo status
            self._sync_to_plan_md(args.content)

            return TodoWriteResult(
                path=str(todo_path),
                bytes_written=content_bytes,
                message=f"Updated todos.md ({content_bytes} bytes)",
            )
        except Exception as e:
            raise ToolError(f"Error writing todo file {todo_path}: {e}") from e

    def _sync_to_plan_md(self, todos_content: str) -> None:
        """Sync completed todos to dev/PLAN.md checkboxes.

        When a todo is marked [x] in todos.md, find matching items in PLAN.md
        and update their checkboxes.
        """
        import re

        plan_path = self.config.effective_workdir / "dev" / "PLAN.md"
        if not plan_path.exists():
            return

        try:
            # Parse todos to find completed items
            todo_pattern = re.compile(
                r"^\s*-\s*\[([xX/\s])\]\s*\*{0,2}(.+?)\*{0,2}\s*$"
            )
            completed_items: set[str] = set()
            in_progress_items: set[str] = set()

            for line in todos_content.splitlines():
                match = todo_pattern.match(line)
                if match:
                    status_char = match.group(1).lower()
                    item_name = match.group(2).strip()
                    # Normalize: remove markdown bold markers
                    item_name = item_name.strip("*").strip()

                    if status_char == "x":
                        completed_items.add(item_name.lower())
                    elif status_char == "/":
                        in_progress_items.add(item_name.lower())

            if not completed_items and not in_progress_items:
                return

            # Read and update PLAN.md
            plan_content = plan_path.read_text(encoding="utf-8")
            plan_lines = plan_content.splitlines()
            updated_lines: list[str] = []
            plan_pattern = re.compile(
                r"^(\s*-\s*)\[([xX\s])\]\s*\*{0,2}(.+?)\*{0,2}\s*$"
            )

            for line in plan_lines:
                match = plan_pattern.match(line)
                if match:
                    prefix = match.group(1)
                    _current_status = match.group(2)  # Unused but kept for clarity
                    item_name = match.group(3).strip().strip("*").strip()

                    if item_name.lower() in completed_items:
                        # Mark as completed
                        updated_lines.append(f"{prefix}[x] **{item_name}**")
                    else:
                        updated_lines.append(line)
                else:
                    updated_lines.append(line)

            # Write back if changed
            new_content = "\n".join(updated_lines)
            if new_content != plan_content:
                plan_path.write_text(new_content + "\n", encoding="utf-8")

        except Exception:
            # Plan sync should not fail the main todo write
            pass
