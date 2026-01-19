from __future__ import annotations

from datetime import datetime
from enum import StrEnum, auto
from pathlib import Path
import re
import traceback
from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.widgets import Static

from vibe.cli.textual_ui.widgets.no_markup_static import NoMarkupStatic
from vibe.collaborative.task_manager import TaskStatus
from vibe.core.planning_models import ItemStatus

if TYPE_CHECKING:
    from vibe.collaborative.vibe_integration import CollaborativeVibeIntegration
    from vibe.core.plan_manager import PlanManager

# Display constants
MAX_TODO_TEXT_LENGTH = 40
MAX_VISIBLE_TODOS = 5


class TodoStatus(StrEnum):
    """Status of a todo item (parsed from markdown)."""

    PENDING = auto()
    IN_PROGRESS = auto()
    COMPLETED = auto()


class TodoWidget(Static):
    """Widget to display the current plan/todos.

    Reads todos directly from `.vibe/plans/todos.md` file.
    Supports both core PlanManager and Collaborative TaskManager.
    """

    def __init__(
        self,
        plan_manager: PlanManager,
        workdir: Path,
        collaborative_integration: CollaborativeVibeIntegration | None = None,
        collapsed: bool = True,
    ) -> None:
        super().__init__()
        self.plan_manager = plan_manager
        self._workdir = workdir
        self._todos_file = workdir / ".vibe" / "plans" / "todos.md"
        self.collaborative_integration = collaborative_integration
        self.collapsed = collapsed
        self.add_class("todo-widget")

    def compose(self) -> ComposeResult:
        with Vertical(id="todo-container"):
            yield NoMarkupStatic("Plan / Todos", id="todo-header")
            self._todo_list = VerticalScroll(id="todo-list")
            yield self._todo_list

    async def on_mount(self) -> None:
        await self.update_todos()

    def _parse_todos_from_file(self) -> list[tuple[str, TodoStatus]]:
        """Parse todos from the markdown file."""
        if not self._todos_file.exists():
            return []

        try:
            content = self._todos_file.read_text(encoding="utf-8")
            lines = content.splitlines()
            todos: list[tuple[str, TodoStatus]] = []

            pattern = re.compile(r"^\s*-\s*\[([\s/xX])\]\s*(.+?)(?:\s*<!--.*-->)?$")

            for line in lines:
                match = pattern.match(line)
                if not match:
                    continue

                status_char = match.group(1).lower()
                content_text = match.group(2).strip()

                if status_char == "x":
                    status = TodoStatus.COMPLETED
                elif status_char == "/":
                    status = TodoStatus.IN_PROGRESS
                else:
                    status = TodoStatus.PENDING

                todos.append((content_text, status))

            return todos
        except Exception:
            return []

    async def _render_file_todos(self) -> bool:
        """Render todos from markdown file. Returns True if any were rendered."""
        all_todos = self._parse_todos_from_file()
        active_todos = [t for t in all_todos if t[1] != TodoStatus.COMPLETED]

        if not active_todos:
            return False

        visible_todos = active_todos[:5]

        for content_text, status in visible_todos:
            icon = self._get_todo_status_icon(status)
            text = content_text
            if len(text) > MAX_TODO_TEXT_LENGTH:
                text = text[:37] + "..."

            await self._todo_list.mount(
                NoMarkupStatic(f"{icon} {text}", classes="todo-task")
            )

        if len(active_todos) > MAX_VISIBLE_TODOS:
            await self._todo_list.mount(
                NoMarkupStatic(
                    f"  ... (+{len(active_todos) - MAX_VISIBLE_TODOS} more)",
                    classes="todo-more",
                )
            )
        return True

    async def _render_plan_todos(self, add_separator: bool) -> bool:
        """Render plan todos. Returns True if rendered."""
        if not self.plan_manager.current_plan:
            return False

        plan = self.plan_manager.current_plan
        if any(epic.status != ItemStatus.COMPLETED for epic in plan.epics):
            if add_separator:
                await self._todo_list.mount(
                    NoMarkupStatic("---", classes="todo-separator")
                )
            await self._todo_list.mount(
                NoMarkupStatic(f"Goal: {plan.goal[:30]}...", classes="todo-goal")
            )
            return True
        return False

    async def _render_collaborative_todos(self, add_separator: bool) -> bool:
        """Render collaborative todos. Returns True if rendered."""
        if (
            not self.collaborative_integration
            or not self.collaborative_integration.collaborative_agent
        ):
            return False

        tasks = self.collaborative_integration.collaborative_agent.task_manager.tasks
        active_collab = [t for t in tasks.values() if t.status != TaskStatus.COMPLETED]

        if not active_collab:
            return False

        if add_separator:
            await self._todo_list.mount(NoMarkupStatic("---", classes="todo-separator"))

        for task in active_collab[:3]:
            status_icon = self._get_collab_status_icon(task.status)
            desc = task.description if task.description else ""
            await self._todo_list.mount(
                NoMarkupStatic(f"{status_icon} {desc[:35]}", classes="todo-task")
            )
        return True

    async def update_todos(self) -> None:
        """Update the todo display by reading from the markdown file."""
        error_log_path = Path.home() / ".vibe" / "error.log"

        try:
            has_content = False
            await self._todo_list.remove_children()

            # 1. Parse todos from markdown file
            has_content = await self._render_file_todos()

            # 2. Check core PlanManager
            if await self._render_plan_todos(has_content):
                has_content = True

            # 3. Check Collaborative TaskManager
            if await self._render_collaborative_todos(has_content):
                has_content = True

            if not has_content:
                await self._todo_list.mount(
                    NoMarkupStatic("○ No active tasks", classes="todo-empty")
                )

            self.display = True
        except Exception as e:
            try:
                error_log_path.parent.mkdir(parents=True, exist_ok=True)
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                with open(error_log_path, "a", encoding="utf-8") as f:
                    f.write(f"\n{'=' * 80}\n")
                    f.write(f"[{timestamp}] Error in TodoWidget.update_todos()\n")
                    f.write(f"{'=' * 80}\n")
                    f.write(f"Error Type: {type(e).__name__}\n")
                    f.write(f"Error Message: {e!s}\n")
                    f.write("\nTraceback:\n")
                    f.write(traceback.format_exc())
                    f.write(f"\n{'=' * 80}\n")
            except Exception:
                pass
            raise

    def _get_todo_status_icon(self, status: TodoStatus) -> str:
        match status:
            case TodoStatus.COMPLETED:
                return "✓"
            case TodoStatus.IN_PROGRESS:
                return "▶"
            case TodoStatus.PENDING:
                return "○"
            case _:
                return " "

    def _get_status_icon(self, status: ItemStatus) -> str:
        match status:
            case ItemStatus.COMPLETED:
                return "✓"
            case ItemStatus.IN_PROGRESS:
                return "▶"
            case ItemStatus.FAILED:
                return "✕"
            case ItemStatus.BLOCKED:
                return "!"
            case ItemStatus.SKIPPED:
                return "○"
            case _:
                return " "

    def _get_collab_status_icon(self, status: TaskStatus) -> str:
        match status:
            case TaskStatus.COMPLETED:
                return "✓"
            case TaskStatus.IN_PROGRESS:
                return "▶"
            case TaskStatus.ASSIGNED:
                return "●"
            case TaskStatus.PENDING:
                return "○"
            case _:
                return " "

    async def set_collapsed(self, collapsed: bool) -> None:
        self.collapsed = collapsed
        if collapsed:
            self.add_class("-collapsed")
        else:
            self.remove_class("-collapsed")
        self._todo_list.display = not collapsed
