"""Task Manager for Dual-Model Collaboration.

Manages the distribution of tasks between Devstral-2 and Deepseek-Coder-v2
based on task type and model capabilities.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
import hashlib
import json
import logging
from pathlib import Path
import threading
import uuid

from vibe.core.paths.global_paths import VIBE_HOME

logger = logging.getLogger(__name__)

DEFAULT_PRIORITY = 3


class TaskType(Enum):
    """Types of tasks that can be assigned to models."""

    PLANNING = auto()
    ARCHITECTURE = auto()
    CODE_IMPLEMENTATION = auto()
    DOCUMENTATION = auto()
    CODE_REVIEW = auto()
    REFACTORING = auto()
    TESTING = auto()
    MAINTENANCE = auto()
    REPOSITORY_HYGIENE = auto()


class TaskStatus(Enum):
    """Possible statuses for a collaborative task."""

    PENDING = auto()
    ASSIGNED = auto()
    IN_PROGRESS = auto()
    DEBUGGING = auto()
    COMPLETED = auto()
    BLOCKED = auto()


class ModelRole(Enum):
    """Roles assigned to different models."""

    PLANNER = "devstral-2"
    IMPLEMENTER = "deepseek-coder-v2"
    REVIEWER = "qwq"
    DOCS = "llama3.2"


@dataclass
class CollaborativeTask:
    """Represents a task in the collaborative workflow."""

    task_id: str
    task_type: TaskType
    description: str
    priority: int = DEFAULT_PRIORITY  # 1-5 scale, 1 being highest
    status: TaskStatus = TaskStatus.PENDING
    assigned_to: ModelRole | None = None
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    dependencies: list[str] = field(default_factory=list)  # IDs of dependent tasks


class TaskManager:
    """Manages the lifecycle of collaborative tasks."""

    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root
        self.tasks: dict[str, CollaborativeTask] = {}
        self.task_queue: list[str] = []
        self.completed_tasks: list[str] = []
        self.task_history_file = self._get_storage_path()
        self._lock = threading.RLock()

        # Load existing tasks if any
        self._load_tasks()

    def _get_storage_path(self) -> Path:
        """Get the centralized storage path for collaborative tasks."""
        project_name = self.project_root.name
        path_hash = hashlib.sha256(
            str(self.project_root.resolve()).encode()
        ).hexdigest()[:8]

        storage_dir = (
            VIBE_HOME.path / "collaborative_tasks" / f"{project_name}_{path_hash}"
        )
        storage_dir.mkdir(parents=True, exist_ok=True)
        return storage_dir / "tasks.json"

    def _load_tasks(self) -> None:
        """Load tasks from persistent storage."""
        if self.task_history_file.exists():
            try:
                with open(self.task_history_file) as f:
                    task_data = json.load(f)

                # Deduplicate by description during load
                seen_descriptions = set()

                for task_id, task_info in task_data.items():
                    desc = task_info["description"].strip()
                    if desc in seen_descriptions:
                        continue
                    seen_descriptions.add(desc)

                    task = CollaborativeTask(
                        task_id=task_id,
                        task_type=TaskType[task_info["task_type"]],
                        description=desc,
                        priority=task_info.get("priority", 3),
                        status=TaskStatus[task_info["status"]],
                        assigned_to=ModelRole(task_info["assigned_to"])
                        if task_info.get("assigned_to")
                        else None,
                        created_at=datetime.fromisoformat(task_info["created_at"]),
                        updated_at=datetime.fromisoformat(task_info["updated_at"]),
                        dependencies=task_info.get("dependencies", []),
                    )
                    self.tasks[task_id] = task
                    if task.status == TaskStatus.PENDING:
                        self.task_queue.append(task_id)
                    elif task.status == TaskStatus.COMPLETED:
                        self.completed_tasks.append(task_id)
            except (json.JSONDecodeError, KeyError) as e:
                logger.warning("Could not load tasks: %s", e)

    def _save_tasks(self) -> None:
        """Save tasks to persistent storage."""
        with self._lock:  # Ensure no other thread is writing
            task_data = {}
            for task_id, task in self.tasks.items():
                task_data[task_id] = {
                    "task_type": task.task_type.name,
                    "description": task.description,
                    "priority": task.priority,
                    "status": task.status.name,
                    "assigned_to": task.assigned_to.value if task.assigned_to else None,
                    "created_at": task.created_at.isoformat(),
                    "updated_at": task.updated_at.isoformat(),
                    "dependencies": task.dependencies,
                }

            try:
                with open(self.task_history_file, "w") as f:
                    json.dump(task_data, f, indent=2)
            except OSError as e:
                logger.warning(
                    "Could not save tasks to %s: %s", self.task_history_file, e
                )

    def create_task(
        self,
        task_type: TaskType,
        description: str,
        priority: int = DEFAULT_PRIORITY,
        dependencies: list[str] | None = None,
    ) -> str:
        """Create a new collaborative task."""
        task_id = str(uuid.uuid4())

        task = CollaborativeTask(
            task_id=task_id,
            task_type=task_type,
            description=description,
            priority=priority,
            dependencies=dependencies or [],
        )

        with self._lock:
            self.tasks[task_id] = task
            self.task_queue.append(task_id)
            self._save_tasks()

        return task_id

    def assign_task(self, task_id: str, model_role: ModelRole) -> None:
        """Assign a task to a specific model."""
        if task_id not in self.tasks:
            raise ValueError(f"Task {task_id} not found")

        with self._lock:
            task = self.tasks[task_id]
            task.assigned_to = model_role
            task.status = TaskStatus.ASSIGNED
            task.updated_at = datetime.now()
            self._save_tasks()

    def complete_task(self, task_id: str) -> None:
        """Mark a task as completed."""
        if task_id not in self.tasks:
            raise ValueError(f"Task {task_id} not found")

        with self._lock:
            task = self.tasks[task_id]
            task.status = TaskStatus.COMPLETED
            task.updated_at = datetime.now()

            if task_id in self.task_queue:
                self.task_queue.remove(task_id)
            self.completed_tasks.append(task_id)
            self._save_tasks()

    def get_next_task(self) -> tuple[str, CollaborativeTask] | None:
        """Get the next available task from the queue whose dependencies are met."""
        with self._lock:
            if not self.task_queue:
                return None

            # Sort by priority (lower numbers = higher priority)
            self.task_queue.sort(key=lambda tid: self.tasks[tid].priority)

            for task_id in list(
                self.task_queue
            ):  # Iterate over a copy to allow modification
                if self._is_task_blocked(task_id):
                    task = self.tasks[task_id]
                    if (
                        task.status != TaskStatus.BLOCKED
                    ):  # Only update if status changed
                        task.status = TaskStatus.BLOCKED
                        task.updated_at = datetime.now()
                        self._save_tasks()
                    continue

                # If not blocked, this is the next available task
                return task_id, self.tasks[task_id]

            return None  # No unblocked tasks found

    def get_next_task_for_model(
        self, model_role: ModelRole
    ) -> tuple[str, CollaborativeTask] | None:
        """Get the next available task specifically for a given model role."""
        with self._lock:
            if not self.task_queue:
                return None

            # Sort by priority
            self.task_queue.sort(key=lambda tid: self.tasks[tid].priority)

            for task_id in list(self.task_queue):
                # Check if assigned to this model (or not assigned yet but matches rules - but auto_assign handles that)
                # We strictly look for tasks already assigned to this role
                task = self.tasks[task_id]

                if task.assigned_to != model_role:
                    continue

                if self._is_task_blocked(task_id):
                    if task.status != TaskStatus.BLOCKED:
                        task.status = TaskStatus.BLOCKED
                        task.updated_at = datetime.now()
                        self._save_tasks()
                    continue

                # Found a valid task for this model
                return task_id, task

            return None

    def _is_task_blocked(self, task_id: str) -> bool:
        """Check if a task is blocked by uncompleted dependencies."""
        task = self.tasks[task_id]
        for dep_id in task.dependencies:
            if (
                dep_id not in self.tasks
                or self.tasks[dep_id].status != TaskStatus.COMPLETED
            ):
                return True
        return False

    def get_task_status(self) -> dict[str, int]:
        """Get summary of task statuses."""
        status_counts = {status.name: 0 for status in TaskStatus}

        for task in self.tasks.values():
            status_counts[task.status.name] += 1

        return status_counts

    def get_tasks_by_model(
        self, model_role: ModelRole
    ) -> list[tuple[str, CollaborativeTask]]:
        """Get all tasks assigned to a specific model."""
        return [
            (tid, task)
            for tid, task in self.tasks.items()
            if task.assigned_to == model_role and task.status != TaskStatus.COMPLETED
        ]

    def auto_assign_tasks(self) -> None:
        """Automatically assign tasks based on task type and model capabilities."""
        # Task type to model mapping
        task_assignment_rules = {
            TaskType.PLANNING: ModelRole.PLANNER,
            TaskType.ARCHITECTURE: ModelRole.PLANNER,
            TaskType.CODE_REVIEW: ModelRole.REVIEWER,
            TaskType.CODE_IMPLEMENTATION: ModelRole.IMPLEMENTER,
            TaskType.DOCUMENTATION: ModelRole.DOCS,
            TaskType.REFACTORING: ModelRole.IMPLEMENTER,
            TaskType.TESTING: ModelRole.IMPLEMENTER,
            TaskType.MAINTENANCE: ModelRole.IMPLEMENTER,
            TaskType.REPOSITORY_HYGIENE: ModelRole.DOCS,
        }

        with (
            self._lock
        ):  # Lock the whole operation to prevent race conditions during assignment
            for task_id, task in self.tasks.items():
                if task.status == TaskStatus.PENDING and task_id in self.task_queue:
                    assigned_role = task_assignment_rules.get(task.task_type)
                    if assigned_role:
                        task.assigned_to = assigned_role
                        task.status = TaskStatus.ASSIGNED
                        task.updated_at = datetime.now()
            self._save_tasks()

    def set_task_dependencies(self, task_id: str, dependencies: list[str]) -> None:
        """Set canonical dependencies for an existing task."""
        if task_id not in self.tasks:
            raise ValueError(f"Task {task_id} not found")

        with self._lock:
            task = self.tasks[task_id]
            task.dependencies = dependencies
            task.updated_at = datetime.now()
            self._save_tasks()

    def clear_all_tasks(self) -> None:
        """Clear all tasks from the manager."""
        with self._lock:
            self.tasks.clear()
            self.task_queue.clear()
            self.completed_tasks.clear()
            self._save_tasks()
