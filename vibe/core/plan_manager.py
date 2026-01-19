from __future__ import annotations

from collections.abc import Callable
import json
from pathlib import Path
import time
from typing import TypeVar
from uuid import UUID

from vibe.core.planning_models import (
    AgentPlan,
    Epic,
    ItemStatus,
    PlanItem,
    Subtask,
    Task,
)

T = TypeVar("T", bound=PlanItem)


class PlanManager:
    """Manages the AgentPlan, including creation, loading, saving, and manipulation of plan items."""

    def __init__(self, project_path: Path) -> None:
        self.project_path = project_path
        self._plan_file_path = self._get_plan_file_path()
        self._agent_plan: AgentPlan | None = None
        self.load_plan()  # Attempt to load an existing plan on initialization

    def _get_plan_file_path(self) -> Path:
        """Determines the path where the plan JSON will be stored."""
        vibe_path = self.project_path / ".vibe"
        plans_dir = vibe_path / "plans"
        plans_dir.mkdir(parents=True, exist_ok=True)
        return plans_dir / "agent_plan.json"

    def create_new_plan(self, goal: str) -> AgentPlan:
        """Creates a new AgentPlan and saves it."""
        self._agent_plan = AgentPlan(goal=goal)
        self.save_plan()
        return self._agent_plan

    def load_plan(self) -> AgentPlan | None:
        """Loads an existing AgentPlan from file."""
        if not self._plan_file_path.exists():
            self._agent_plan = None
            return None
        try:
            with self._plan_file_path.open("r", encoding="utf-8") as f:
                plan_data = json.load(f)
            self._agent_plan = AgentPlan.model_validate(plan_data)
            return self._agent_plan
        except (OSError, json.JSONDecodeError, FileNotFoundError):
            self._agent_plan = None
            return None

    def save_plan(self) -> None:
        """Saves the current AgentPlan to file."""
        if self._agent_plan:
            self._agent_plan.last_updated = time.time()
            with self._plan_file_path.open("w", encoding="utf-8") as f:
                json.dump(self._agent_plan.model_dump(mode="json"), f, indent=4)

    @property
    def current_plan(self) -> AgentPlan | None:
        return self._agent_plan

    def _find_item_recursive(
        self, item_id: UUID, items: list[PlanItem]
    ) -> PlanItem | None:
        """Helper to recursively find an item by ID within a list of PlanItems."""
        for item in items:
            if item.id == item_id:
                return item
            if isinstance(item, Epic):
                found = self._find_item_recursive(item_id, item.tasks)
                if found:
                    return found
            if isinstance(item, Task):
                found = self._find_item_recursive(item_id, item.subtasks)
                if found:
                    return found
        return None

    def get_item_by_id(self, item_id: UUID) -> PlanItem | None:
        """Finds any plan item (Epic, Task, or Subtask) by its ID."""
        if not self._agent_plan:
            return None
        return self._find_item_recursive(item_id, self._agent_plan.epics)

    def update_item_status(self, item_id: UUID, new_status: ItemStatus) -> bool:
        """Updates the status of a plan item and its updated_at timestamp."""
        item = self.get_item_by_id(item_id)
        if item:
            item.status = new_status
            item.updated_at = time.time()
            self.save_plan()
            self._sync_plan_to_markdown()
            # Optionally, update parent status if all children are complete
            self._update_parent_status(item_id)
            return True
        return False

    def _update_parent_status(self, child_id: UUID) -> None:
        """Checks if a parent item can be marked as completed based on its children's status."""
        if not self._agent_plan:
            return

        # Find the parent of the child_id
        parent_item: PlanItem | None = None
        for epic in self._agent_plan.epics:
            if child_id in [t.id for t in epic.tasks]:
                parent_item = epic
                break
            for task in epic.tasks:
                if child_id in [s.id for s in task.subtasks]:
                    parent_item = task
                    break
            if parent_item:
                break

        if parent_item:
            children_are_completed = False
            if isinstance(parent_item, Epic):
                children_are_completed = all(
                    task.status == ItemStatus.COMPLETED for task in parent_item.tasks
                )
            elif isinstance(parent_item, Task):
                children_are_completed = all(
                    subtask.status == ItemStatus.COMPLETED
                    for subtask in parent_item.subtasks
                )

            if children_are_completed and parent_item.status != ItemStatus.COMPLETED:
                parent_item.status = ItemStatus.COMPLETED
                parent_item.updated_at = time.time()
                self.save_plan()
                # Recursively check if this completion affects its parent
                self._update_parent_status(parent_item.id)

    def get_next_actionable_item(self) -> Task | Subtask | None:
        """Finds the next actionable item (Task or Subtask).

        Finds an item that is PENDING and has all its dependencies COMPLETED.
        Prioritizes subtasks, then tasks.
        """
        if not self._agent_plan:
            return None

        # A cache for dependency status to avoid repeated lookups
        dependency_status_cache: dict[UUID, bool] = {}

        def is_dependency_completed(dep_id: UUID) -> bool:
            if dep_id not in dependency_status_cache:
                dep_item = self.get_item_by_id(dep_id)
                dependency_status_cache[dep_id] = (
                    dep_item is not None and dep_item.status == ItemStatus.COMPLETED
                )
            return dependency_status_cache[dep_id]

        for epic in self._agent_plan.epics:
            if epic.status not in {ItemStatus.PENDING, ItemStatus.IN_PROGRESS}:
                continue

            for task in epic.tasks:
                if task.status not in {ItemStatus.PENDING, ItemStatus.IN_PROGRESS}:
                    continue

                if subtask := self._find_actionable_subtask(
                    task, is_dependency_completed
                ):
                    return subtask

                if self._can_execute_task(task, is_dependency_completed):
                    return task
        return None

    def _find_actionable_subtask(
        self, task: Task, dep_check_fn: Callable[[UUID], bool]
    ) -> Subtask | None:
        for subtask in task.subtasks:
            if subtask.status == ItemStatus.PENDING:
                if all(dep_check_fn(dep) for dep in subtask.dependencies):
                    return subtask
        return None

    def _can_execute_task(
        self, task: Task, dep_check_fn: Callable[[UUID], bool]
    ) -> bool:
        if task.status != ItemStatus.PENDING:
            return False

        if task.subtasks:
            all_subtasks_handled = all(
                s.status not in {ItemStatus.PENDING, ItemStatus.IN_PROGRESS}
                for s in task.subtasks
            )
            if not all_subtasks_handled:
                return False

        return all(dep_check_fn(dep) for dep in task.dependencies)

    def add_epic(
        self,
        name: str,
        description: str | None = None,
        dependencies: list[UUID] | None = None,
    ) -> Epic | None:
        """Adds a new epic to the plan."""
        if not self._agent_plan:
            return None
        epic = Epic(name=name, description=description, dependencies=dependencies or [])
        self._agent_plan.epics.append(epic)
        self.save_plan()
        return epic

    def add_task_to_epic(
        self,
        epic_id: UUID,
        name: str,
        description: str | None = None,
        dependencies: list[UUID] | None = None,
        effort_estimate: str | None = None,
        priority: int | None = None,
    ) -> Task | None:
        """Adds a new task to a specific epic."""
        epic = self.get_item_by_id(epic_id)
        if isinstance(epic, Epic):
            task = Task(
                name=name,
                description=description,
                dependencies=dependencies or [],
                effort_estimate=effort_estimate,
                priority=priority,
            )
            epic.tasks.append(task)
            self.save_plan()
            return task
        return None

    def add_subtask_to_task(
        self,
        task_id: UUID,
        name: str,
        description: str | None = None,
        dependencies: list[UUID] | None = None,
    ) -> Subtask | None:
        """Adds a new subtask to a specific task."""
        task = self.get_item_by_id(task_id)
        if isinstance(task, Task):
            subtask = Subtask(
                name=name, description=description, dependencies=dependencies or []
            )
            task.subtasks.append(subtask)
            self.save_plan()
            return subtask
        return None

    def _get_updated_line_status(self, line: str) -> str:
        """Helper to determine the updated checkbox status for a given line."""
        if "[ ]" not in line and "[x]" not in line:
            return line

        if not self._agent_plan:
            return line

        for epic in self._agent_plan.epics:
            if epic.name in line:
                status_box = "[x]" if epic.status == ItemStatus.COMPLETED else "[ ]"
                return line.replace("[ ]", status_box).replace("[x]", status_box)

            for task in epic.tasks:
                if task.name in line:
                    status_box = "[x]" if task.status == ItemStatus.COMPLETED else "[ ]"
                    return line.replace("[ ]", status_box).replace("[x]", status_box)
        return line

    def _sync_plan_to_markdown(self) -> None:
        """Updates the dev/PLAN.md file to reflect the current plan state."""
        plan_md_path = self.project_path / "dev" / "PLAN.md"
        if not plan_md_path.exists() or not self._agent_plan:
            return

        try:
            with plan_md_path.open("r", encoding="utf-8") as f:
                lines = f.readlines()

            new_lines = [self._get_updated_line_status(line) for line in lines]

            with plan_md_path.open("w", encoding="utf-8") as f:
                f.writelines(new_lines)
        except Exception:
            # Plan sync should not crash the main thread
            pass
