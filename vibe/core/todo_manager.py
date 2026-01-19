"""
Todo Manager for Vibe CLI

Manages agent todos during conversation - persistent per-project.
Similar to Claude Code's TodoWrite functionality.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional
from uuid import UUID, uuid4


class TodoStatus(str, Enum):
    """Status of a todo item."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


@dataclass
class TodoItem:
    """A single todo item."""
    id: UUID = field(default_factory=uuid4)
    content: str = ""
    active_form: str = ""  # Present continuous form (e.g., "Running tests")
    status: TodoStatus = TodoStatus.PENDING
    parent_id: Optional[UUID] = None  # For hierarchical organization
    order: int = 0  # Display order within parent
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "id": str(self.id),
            "content": self.content,
            "active_form": self.active_form,
            "status": self.status.value,
            "parent_id": str(self.parent_id) if self.parent_id else None,
            "order": self.order,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> TodoItem:
        """Create from dictionary."""
        parent_id_str = data.get("parent_id")
        return cls(
            id=UUID(data["id"]),
            content=data["content"],
            active_form=data["active_form"],
            status=TodoStatus(data["status"]),
            parent_id=UUID(parent_id_str) if parent_id_str else None,
            order=data.get("order", 0),
            created_at=data["created_at"],
            updated_at=data["updated_at"],
        )


class TodoManager:
    """
    Manages todos for the current agent session.
    Todos are persistent per-project and stored in ./.vibe/plans/todos.md
    """

    def __init__(self, project_path: Path):
        self.project_path = project_path
        self._todos_file_path = self._get_todos_file_path()
        self._todos: list[TodoItem] = []
        self._ensure_path_exists()
        self.load_todos()

    def _get_todos_file_path(self) -> Path:
        """Get the path where todos Markdown will be stored."""
        return self.project_path / ".vibe" / "plans" / "todos.md"

    def _ensure_path_exists(self) -> None:
        """Ensure the directory and file for the todos exist."""
        self._todos_file_path.parent.mkdir(parents=True, exist_ok=True)
        if not self._todos_file_path.exists():
            self._todos_file_path.write_text("# Project Todos\n\n", encoding="utf-8")

    def load_todos(self) -> None:
        """Load todos from Markdown file."""
        if not self._todos_file_path.exists():
            self._todos = []
            return

        try:
            content = self._todos_file_path.read_text(encoding="utf-8")
            lines = content.splitlines()
            raw_todos = []
            
            # Simple Markdown parsing
            # Format: - [ ] content <!-- active_form="...", order=0 -->
            import re
            pattern = re.compile(r"^\s*-\s*\[([\s/xX])\]\s*(.*?)(?:\s*<!--\s*(.*?)\s*-->)?$")
            
            for i, line in enumerate(lines):
                match = pattern.match(line)
                if not match:
                    continue
                    
                status_char = match.group(1).lower()
                content_text = match.group(2).strip()
                metadata_str = match.group(3) or ""
                
                # Parse metadata (active_form, order)
                metadata = {}
                if metadata_str:
                    for item in metadata_str.split(","):
                        if "=" in item:
                            k, v = item.split("=", 1)
                            metadata[k.strip()] = v.strip().strip('"').strip("'")
                
                status = TodoStatus.PENDING
                if status_char == "x":
                    status = TodoStatus.COMPLETED
                elif status_char == "/":
                    status = TodoStatus.IN_PROGRESS
                
                raw_todos.append(TodoItem(
                    content=content_text,
                    active_form=metadata.get("active_form", ""),
                    status=status,
                    order=int(metadata.get("order", i)),
                ))
            
            # Deduplicate by content during load
            seen_content = set()
            deduplicated = []
            for todo in raw_todos:
                content_stripped = todo.content.strip()
                if content_stripped and content_stripped not in seen_content:
                    seen_content.add(content_stripped)
                    deduplicated.append(todo)
            self._todos = deduplicated
        except (IOError, Exception):
            self._todos = []

    def save_todos(self) -> None:
        """Save todos to Markdown file."""
        lines = ["# Project Todos", ""]
        for todo in sorted(self._todos, key=lambda t: t.order):
            status_char = " "
            if todo.status == TodoStatus.COMPLETED:
                status_char = "x"
            elif todo.status == TodoStatus.IN_PROGRESS:
                status_char = "/"
            
            metadata = f"active_form=\"{todo.active_form}\", order={todo.order}"
            lines.append(f"- [{status_char}] {todo.content} <!-- {metadata} -->")
        
        self._todos_file_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def set_todos(self, todos: list[dict]) -> None:
        """
        Set todos from a list of dictionaries.
        Expected format: [{"content": "...", "status": "pending|in_progress|completed", "activeForm": "..."}]
        """
        new_todos = []
        seen_content = set()
        
        for todo_data in todos:
            content = todo_data.get("content", "").strip()
            if not content or content in seen_content:
                continue
                
            seen_content.add(content)
            
            # Try to find existing todo by content to preserve ID
            existing_todo = None
            for existing in self._todos:
                if existing.content == content:
                    existing_todo = existing
                    break

            if existing_todo:
                # Update existing todo
                existing_todo.status = TodoStatus(todo_data.get("status", "pending"))
                existing_todo.active_form = todo_data.get("activeForm", "")
                existing_todo.order = len(new_todos)
                existing_todo.updated_at = time.time()
                new_todos.append(existing_todo)
            else:
                # Create new todo
                new_todos.append(TodoItem(
                    content=content,
                    active_form=todo_data.get("activeForm", ""),
                    status=TodoStatus(todo_data.get("status", "pending")),
                    order=len(new_todos),
                ))

        self._todos = new_todos
        self.save_todos()

    def get_todos(self) -> list[TodoItem]:
        """Get all todos."""
        # Guard against None _todos
        if self._todos is None:
            self._todos = []
        return self._todos.copy()

    def get_todos_in_order(self) -> list[TodoItem]:
        """Get todos sorted by order field."""
        # Guard against None _todos
        if self._todos is None:
            self._todos = []
        return sorted(self._todos, key=lambda t: t.order)

    def clear_todos(self) -> None:
        """Clear all todos."""
        self._todos = []
        self.save_todos()

    def get_active_todo(self) -> Optional[TodoItem]:
        """Get the currently in-progress todo."""
        # Guard against None _todos
        if self._todos is None:
            self._todos = []
        for todo in self._todos:
            if todo.status == TodoStatus.IN_PROGRESS:
                return todo
        return None

    def get_stats(self) -> dict:
        """Get todo statistics."""
        # Guard against None _todos
        if self._todos is None:
            self._todos = []

        total = len(self._todos)
        completed = sum(1 for todo in self._todos if todo.status == TodoStatus.COMPLETED)
        in_progress = sum(1 for todo in self._todos if todo.status == TodoStatus.IN_PROGRESS)
        pending = sum(1 for todo in self._todos if todo.status == TodoStatus.PENDING)

        return {
            "total": total,
            "completed": completed,
            "in_progress": in_progress,
            "pending": pending,
        }

    def are_all_complete(self) -> bool:
        """Check if all todos are completed."""
        if not self._todos:
            return False
        return all(todo.status == TodoStatus.COMPLETED for todo in self._todos)

    def has_active_work(self) -> bool:
        """Check if there are any pending or in-progress todos."""
        return any(
            todo.status in {TodoStatus.PENDING, TodoStatus.IN_PROGRESS}
            for todo in self._todos
        )
