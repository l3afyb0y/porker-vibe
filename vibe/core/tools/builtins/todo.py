from __future__ import annotations

from datetime import datetime
from enum import StrEnum, auto
from typing import ClassVar

from pydantic import BaseModel, Field, PrivateAttr

import json
import os
from pathlib import Path

from vibe.core.middleware import ConversationContext, MiddlewareResult, MiddlewareAction
from vibe.core.tools.base import (
    BaseTool,
    BaseToolConfig,
    BaseToolState,
    ToolError,
    ToolPermission,
)
from vibe.core.tools.ui import ToolCallDisplay, ToolResultDisplay, ToolUIData
from vibe.core.types import ToolCallEvent, ToolResultEvent
from vibe.core.utils import VIBE_WARNING_TAG


class AutoTaskTrackingMiddleware:
    """Middleware for automatic task tracking based on agent actions."""
    
    def __init__(self, todo_tool: Todo):
        self.todo_tool = todo_tool
        self.tracked_actions = {
            'bash': 'Execute bash command',
            'grep': 'Search for patterns',
            'read_file': 'Read file content',
            'search_replace': 'Modify file content',
            'write_file': 'Create new file',
            'delegate_to_local': 'Delegate task to local model'
        }
    
    async def before_turn(self, context: 'ConversationContext') -> 'MiddlewareResult':
        """Check if we should create tasks before the agent turn."""
        # Analyze the last user message to detect potential tasks
        if context.messages and len(context.messages) > 1:
            last_user_message = context.messages[-1]
            if last_user_message.role == 'user':
                content = last_user_message.content or ""
                
                # Simple heuristic: if message contains specific action words, create task
                action_words = ['implement', 'create', 'build', 'fix', 'add', 'update', 'remove', 'delete']
                if any(word in content.lower() for word in action_words):
                    # Create an auto-tracked task
                    task_content = f"Auto-tracked: {content[:50]}..."
                    todo_item = TodoItem(
                        id=f"auto_{len(self.todo_tool.state.todos) + 1}",
                        content=task_content,
                        status=TodoStatus.PENDING,
                        priority=TodoPriority.MEDIUM,
                        auto_tracked=True,
                        context=content
                    )
                    
                    try:
                        self.todo_tool._add_todo(todo_item)
                        return MiddlewareResult(
                            action=MiddlewareAction.CONTINUE,
                            message=f"<{VIBE_WARNING_TAG}>Auto-tracked task created: {task_content}"
                        )
                    except Exception as e:
                        # Don't fail the conversation if task tracking fails
                        pass
        
        return MiddlewareResult(action=MiddlewareAction.CONTINUE)
    
    async def after_turn(self, context: 'ConversationContext') -> 'MiddlewareResult':
        """Update tasks after the agent turn based on tool usage."""
        # Check if any tools were used in the last turn
        last_message = context.messages[-1] if context.messages else None
        if last_message and last_message.role == 'assistant':
            content = last_message.content or ""
            
            # Check for tool usage patterns
            for tool_name, description in self.tracked_actions.items():
                if f"<tool_call>{tool_name}" in content:
                    # Find and update any auto-tracked tasks related to this tool
                    for todo in self.todo_tool.state.todos:
                        if todo.auto_tracked and tool_name in todo.context:
                            todo.status = TodoStatus.IN_PROGRESS
                            todo.updated_at = datetime.now()
                            break
                    else:
                        # Create new auto-tracked task for this tool usage
                        task_content = f"Auto-tracked: {description}"
                        todo_item = TodoItem(
                            id=f"auto_{len(self.todo_tool.state.todos) + 1}",
                            content=task_content,
                            status=TodoStatus.IN_PROGRESS,
                            priority=TodoPriority.MEDIUM,
                            auto_tracked=True,
                            context=f"Tool usage: {tool_name}",
                            tags=[tool_name]
                        )
                        
                        try:
                            self.todo_tool._add_todo(todo_item)
                        except Exception as e:
                            # Don't fail the conversation if task tracking fails
                            pass
                    
                    break
        
        return MiddlewareResult(action=MiddlewareAction.CONTINUE)


class TodoStatus(StrEnum):
    PENDING = auto()
    IN_PROGRESS = auto()
    COMPLETED = auto()
    CANCELLED = auto()


class TodoPriority(StrEnum):
    LOW = auto()
    MEDIUM = auto()
    HIGH = auto()


class TodoItem(BaseModel):
    id: str
    content: str
    status: TodoStatus = TodoStatus.PENDING
    priority: TodoPriority = TodoPriority.MEDIUM
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    due_date: datetime | None = None
    tags: list[str] = Field(default_factory=list)
    related_tasks: list[str] = Field(default_factory=list)
    context: str | None = None
    auto_tracked: bool = False


class TodoArgs(BaseModel):
    action: str = Field(description="Action to perform: 'read', 'write', 'add', 'update', 'remove', 'complete'")
    todos: list[TodoItem] | None = Field(
        default=None, description="Complete list of todos when writing."
    )
    todo_id: str | None = Field(
        default=None, description="ID of todo for partial updates (add/update/remove/complete)"
    )
    todo_item: TodoItem | None = Field(
        default=None, description="Todo item for add/update operations"
    )
    updates: dict[str, str | datetime | list[str] | bool] | None = Field(
        default=None, description="Partial updates for update operation"
    )


class TodoResult(BaseModel):
    message: str
    todos: list[TodoItem]
    total_count: int


class TodoConfig(BaseToolConfig):
    permission: ToolPermission = ToolPermission.ALWAYS
    max_todos: int = 100
    persistence_enabled: bool = True
    persistence_file: str = "~/.vibe_todos.json"


class TodoState(BaseToolState):
    todos: list[TodoItem] = Field(default_factory=list)
    _index_cache: dict[str, TodoItem] = PrivateAttr(default_factory=dict)
    _priority_cache: dict[TodoPriority, list[TodoItem]] = PrivateAttr(default_factory=dict)
    _status_cache: dict[TodoStatus, list[TodoItem]] = PrivateAttr(default_factory=dict)
    _cache_dirty: bool = PrivateAttr(default=False)


class Todo(
    BaseTool[TodoArgs, TodoResult, TodoConfig, TodoState],
    ToolUIData[TodoArgs, TodoResult],
):
    description: ClassVar[str] = (
        "Manage todos. Use action='read' to view, action='write' with complete list to update, "
        "or use 'add', 'update', 'remove', 'complete' for partial updates. "
        "Supports automatic task tracking via middleware."
    )

    @classmethod
    def get_call_display(cls, event: ToolCallEvent) -> ToolCallDisplay:
        if not isinstance(event.args, TodoArgs):
            return ToolCallDisplay(summary="Invalid arguments")

        args = event.args

        match args.action:
            case "read":
                return ToolCallDisplay(summary="Reading todos")
            case "write":
                count = len(args.todos) if args.todos else 0
                return ToolCallDisplay(summary=f"Writing {count} todos")
            case "add":
                return ToolCallDisplay(summary=f"Adding todo: {args.todo_item.content if args.todo_item else 'unknown'}")
            case "update":
                return ToolCallDisplay(summary=f"Updating todo: {args.todo_id}")
            case "remove":
                return ToolCallDisplay(summary=f"Removing todo: {args.todo_id}")
            case "complete":
                return ToolCallDisplay(summary=f"Completing todo: {args.todo_id}")
            case _:
                return ToolCallDisplay(summary=f"Unknown action: {args.action}")

    @classmethod
    def get_result_display(cls, event: ToolResultEvent) -> ToolResultDisplay:
        if not isinstance(event.result, TodoResult):
            return ToolResultDisplay(success=True, message="Success")

        result = event.result

        return ToolResultDisplay(success=True, message=result.message)

    @classmethod
    def get_status_text(cls) -> str:
        return "Managing todos"

    async def run(self, args: TodoArgs) -> TodoResult:
        match args.action:
            case "read":
                return self._read_todos()
            case "write":
                return self._write_todos(args.todos or [])
            case "add":
                return self._add_todo(args.todo_item)
            case "update":
                return self._update_todo(args.todo_id, args.updates)
            case "remove":
                return self._remove_todo(args.todo_id)
            case "complete":
                return self._complete_todo(args.todo_id)
            case _:
                raise ToolError(
                    f"Invalid action '{args.action}'. Use 'read', 'write', 'add', 'update', 'remove', or 'complete'."
                )

    def _read_todos(self) -> TodoResult:
        return TodoResult(
            message=f"Retrieved {len(self.state.todos)} todos",
            todos=self.state.todos,
            total_count=len(self.state.todos),
        )

    def _write_todos(self, todos: list[TodoItem]) -> TodoResult:
        if len(todos) > self.config.max_todos:
            raise ToolError(f"Cannot store more than {self.config.max_todos} todos")

        ids = [todo.id for todo in todos]
        if len(ids) != len(set(ids)):
            raise ToolError("Todo IDs must be unique")

        # Update timestamps for existing todos being modified
        current_todos = {todo.id: todo for todo in self.state.todos}
        updated_todos = []
        
        for todo in todos:
            current_todo = current_todos.get(todo.id)
            if current_todo:
                # Preserve created_at for existing todos, update updated_at
                todo.created_at = current_todo.created_at
                todo.updated_at = datetime.now()
            else:
                # New todo - ensure timestamps are set
                todo.updated_at = datetime.now()
            updated_todos.append(todo)

        self.state.todos = updated_todos
        self._auto_save_after_operation()
        self._rebuild_caches()

        return TodoResult(
            message=f"Updated {len(todos)} todos",
            todos=self.state.todos,
            total_count=len(self.state.todos),
        )

    def _add_todo(self, todo_item: TodoItem) -> TodoResult:
        if not todo_item:
            raise ToolError("Todo item is required for add operation")

        if len(self.state.todos) >= self.config.max_todos:
            raise ToolError(f"Cannot store more than {self.config.max_todos} todos")

        # Use cache for faster duplicate check
        if self._get_todo_by_id(todo_item.id):
            raise ToolError(f"Todo with ID '{todo_item.id}' already exists")

        # Set timestamps for new todo
        todo_item.created_at = datetime.now()
        todo_item.updated_at = datetime.now()
        
        self.state.todos.append(todo_item)
        self._mark_cache_dirty()
        self._auto_save_after_operation()

        return TodoResult(
            message=f"Added todo: {todo_item.content}",
            todos=self.state.todos,
            total_count=len(self.state.todos),
        )

    def _update_todo(self, todo_id: str, updates: dict[str, str | datetime | list[str] | bool]) -> TodoResult:
        if not todo_id:
            raise ToolError("Todo ID is required for update operation")

        if not updates:
            raise ToolError("Updates are required for update operation")

        # Use cache for faster lookup
        todo_to_update = self._get_todo_by_id(todo_id)
        
        if not todo_to_update:
            raise ToolError(f"Todo with ID '{todo_id}' not found")

        # Apply updates
        for field, value in updates.items():
            if hasattr(todo_to_update, field):
                setattr(todo_to_update, field, value)
            else:
                raise ToolError(f"Invalid field '{field}' for todo update")

        # Update timestamp
        todo_to_update.updated_at = datetime.now()
        self._mark_cache_dirty()
        self._auto_save_after_operation()

        return TodoResult(
            message=f"Updated todo: {todo_to_update.content}",
            todos=self.state.todos,
            total_count=len(self.state.todos),
        )

    def _remove_todo(self, todo_id: str) -> TodoResult:
        if not todo_id:
            raise ToolError("Todo ID is required for remove operation")

        # Use cache for faster existence check
        if not self._get_todo_by_id(todo_id):
            raise ToolError(f"Todo with ID '{todo_id}' not found")

        initial_count = len(self.state.todos)
        self.state.todos = [todo for todo in self.state.todos if todo.id != todo_id]
        self._mark_cache_dirty()
        self._auto_save_after_operation()
        
        if len(self.state.todos) == initial_count:
            raise ToolError(f"Todo with ID '{todo_id}' not found")

        return TodoResult(
            message=f"Removed todo: {todo_id}",
            todos=self.state.todos,
            total_count=len(self.state.todos),
        )

    def _complete_todo(self, todo_id: str) -> TodoResult:
        if not todo_id:
            raise ToolError("Todo ID is required for complete operation")

        # Use cache for faster lookup
        todo_to_complete = self._get_todo_by_id(todo_id)
        
        if not todo_to_complete:
            raise ToolError(f"Todo with ID '{todo_id}' not found")

        if todo_to_complete.status == TodoStatus.COMPLETED:
            raise ToolError(f"Todo with ID '{todo_id}' is already completed")

        todo_to_complete.status = TodoStatus.COMPLETED
        todo_to_complete.updated_at = datetime.now()
        self._mark_cache_dirty()
        self._auto_save_after_operation()

        return TodoResult(
            message=f"Completed todo: {todo_to_complete.content}",
            todos=self.state.todos,
            total_count=len(self.state.todos),
        )

    def create_auto_tracking_middleware(self) -> AutoTaskTrackingMiddleware:
        """Create middleware for automatic task tracking."""
        return AutoTaskTrackingMiddleware(self)

    def get_context_aware_suggestions(self, current_context: str | None = None) -> list[str]:
        """Get context-aware task suggestions based on current work."""
        suggestions = []
        
        if not current_context:
            current_context = ""
        
        # Analyze current todos for patterns using cache
        pending_todos = self._get_todos_by_status(TodoStatus.PENDING)
        in_progress_todos = self._get_todos_by_status(TodoStatus.IN_PROGRESS)
        
        # Suggestion 1: Complete in-progress tasks
        if in_progress_todos:
            suggestions.append(f"Complete in-progress task: {in_progress_todos[0].content}")
        
        # Suggestion 2: High priority tasks
        high_priority = [todo for todo in pending_todos if todo.priority == TodoPriority.HIGH]
        if high_priority:
            suggestions.append(f"Focus on high priority task: {high_priority[0].content}")
        
        # Suggestion 3: Context-based suggestions
        context_keywords = {
            'implement': ['write tests', 'add documentation', 'create examples'],
            'fix': ['add regression tests', 'update documentation', 'verify related functionality'],
            'create': ['add error handling', 'write unit tests', 'update README'],
            'update': ['check backward compatibility', 'update changelog', 'notify users']
        }
        
        for keyword, related_tasks in context_keywords.items():
            if keyword in current_context.lower():
                for task in related_tasks:
                    if not any(task in todo.content.lower() for todo in self.state.todos):
                        suggestions.append(f"Consider: {task}")
                break
        
        # Suggestion 4: Overdue tasks
        now = datetime.now()
        overdue_tasks = [
            todo for todo in pending_todos 
            if todo.due_date and todo.due_date < now
        ]
        if overdue_tasks:
            suggestions.append(f"Address overdue task: {overdue_tasks[0].content}")
        
        # Suggestion 5: Related tasks
        if in_progress_todos and in_progress_todos[0].related_tasks:
            related_ids = in_progress_todos[0].related_tasks
            related_todos = [todo for todo in self.state.todos if todo.id in related_ids]
            if related_todos:
                suggestions.append(f"Work on related task: {related_todos[0].content}")
        
        return suggestions[:3]  # Return top 3 suggestions

    def get_smart_prioritization_suggestions(self) -> list[tuple[str, str]]:
        """Get suggestions for reprioritizing tasks."""
        suggestions = []
        
        now = datetime.now()
        
        # Find tasks that might need priority adjustment using cache
        for todo in self._get_todos_by_status(TodoStatus.PENDING):
                # Due soon tasks
                if todo.due_date:
                    time_until_due = (todo.due_date - now).total_seconds()
                    if time_until_due < 86400:  # Less than 24 hours
                        if todo.priority != TodoPriority.HIGH:
                            suggestions.append((todo.id, f"Increase priority - due soon: {todo.content}"))
                
                # Stale tasks
                if todo.created_at:
                    age = (now - todo.created_at).total_seconds()
                    if age > 604800:  # Older than 7 days
                        if todo.priority in [TodoPriority.LOW, TodoPriority.MEDIUM]:
                            suggestions.append((todo.id, f"Consider increasing priority - stale task: {todo.content}"))
        
        # Check for priority inversion (high priority tasks blocked by lower priority ones) using cache
        high_priority_pending = self._get_todos_by_status(TodoStatus.PENDING)
        high_priority_pending = [todo for todo in high_priority_pending if todo.priority == TodoPriority.HIGH]
        
        in_progress_low = self._get_todos_by_status(TodoStatus.IN_PROGRESS)
        in_progress_low = [todo for todo in in_progress_low if todo.priority in [TodoPriority.LOW, TodoPriority.MEDIUM]]
        
        if high_priority_pending and in_progress_low:
            suggestions.append((
                high_priority_pending[0].id,
                f"Priority inversion: High priority task waiting while lower priority task in progress"
            ))
        
        return suggestions[:3]  # Return top 3 suggestions

    def apply_smart_prioritization(self) -> TodoResult:
        """Automatically adjust task priorities based on smart analysis."""
        suggestions = self.get_smart_prioritization_suggestions()
        
        if not suggestions:
            return TodoResult(
                message="No priority adjustments needed",
                todos=self.state.todos,
                total_count=len(self.state.todos),
            )
        
        # Apply priority adjustments
        for todo_id, reason in suggestions:
            todo_to_update = None
            for todo in self.state.todos:
                if todo.id == todo_id:
                    todo_to_update = todo
                    break
            
            if todo_to_update:
                # Increase priority (but don't go beyond HIGH)
                if todo_to_update.priority == TodoPriority.LOW:
                    todo_to_update.priority = TodoPriority.MEDIUM
                elif todo_to_update.priority == TodoPriority.MEDIUM:
                    todo_to_update.priority = TodoPriority.HIGH
                
                todo_to_update.updated_at = datetime.now()
        
        self._auto_save_after_operation()
        
        return TodoResult(
            message=f"Applied smart prioritization to {len(suggestions)} tasks",
            todos=self.state.todos,
            total_count=len(self.state.todos),
        )

    def get_priority_score(self, todo: TodoItem) -> float:
        """Calculate a priority score for dynamic prioritization."""
        score = 0.0
        
        # Base score by priority level
        priority_scores = {
            TodoPriority.HIGH: 100.0,
            TodoPriority.MEDIUM: 50.0,
            TodoPriority.LOW: 25.0
        }
        score += priority_scores.get(todo.priority, 0.0)
        
        # Time-based adjustments
        now = datetime.now()
        if todo.due_date:
            time_until_due = (todo.due_date - now).total_seconds()
            if time_until_due < 0:  # Overdue
                score += 200.0
            elif time_until_due < 86400:  # Due soon (24 hours)
                score += 150.0
            elif time_until_due < 172800:  # Due in 2 days
                score += 75.0
        
        # Age-based adjustments (older tasks get higher priority)
        if todo.created_at:
            age = (now - todo.created_at).total_seconds()
            if age > 604800:  # Older than 7 days
                score += 50.0
            elif age > 259200:  # Older than 3 days
                score += 25.0
        
        # Status adjustments
        if todo.status == TodoStatus.IN_PROGRESS:
            score += 100.0  # Tasks already in progress get priority
        
        # Auto-tracked tasks get slight priority boost
        if todo.auto_tracked:
            score += 10.0
        
        return score

    def get_dynamic_priority_order(self) -> list[TodoItem]:
        """Get todos ordered by dynamic priority score."""
        # Calculate scores for all pending and in-progress todos
        todos_with_scores = []
        for todo in self.state.todos:
            if todo.status in [TodoStatus.PENDING, TodoStatus.IN_PROGRESS]:
                score = self.get_priority_score(todo)
                todos_with_scores.append((score, todo))
        
        # Sort by score (descending)
        todos_with_scores.sort(reverse=True, key=lambda x: x[0])
        
        # Return just the todos in priority order
        return [todo for score, todo in todos_with_scores]

    def _get_persistence_path(self) -> Path:
        """Get the full path for todo persistence file."""
        expanded_path = os.path.expanduser(self.config.persistence_file)
        return Path(expanded_path)

    def _save_todos(self) -> None:
        """Save todos to persistent storage."""
        if not self.config.persistence_enabled:
            return
        
        try:
            persistence_path = self._get_persistence_path()
            # Ensure directory exists
            persistence_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Convert todos to JSON-serializable format
            todos_data = []
            for todo in self.state.todos:
                todo_dict = todo.model_dump()
                # Convert datetime objects to ISO format strings
                if todo_dict.get('created_at'):
                    todo_dict['created_at'] = todo_dict['created_at'].isoformat()
                if todo_dict.get('updated_at'):
                    todo_dict['updated_at'] = todo_dict['updated_at'].isoformat()
                if todo_dict.get('due_date'):
                    todo_dict['due_date'] = todo_dict['due_date'].isoformat()
                todos_data.append(todo_dict)
            
            # Write to file
            with open(persistence_path, 'w', encoding='utf-8') as f:
                json.dump(todos_data, f, indent=2)
                
        except Exception as e:
            # Don't fail the operation if persistence fails
            # Log error to console for debugging
            print(f"Warning: Failed to save todos: {e}")

    def _load_todos(self) -> None:
        """Load todos from persistent storage."""
        if not self.config.persistence_enabled:
            return
        
        try:
            persistence_path = self._get_persistence_path()
            if persistence_path.exists():
                with open(persistence_path, 'r', encoding='utf-8') as f:
                    todos_data = json.load(f)
                
                # Convert back to TodoItem objects
                loaded_todos = []
                for todo_dict in todos_data:
                    # Convert ISO format strings back to datetime objects
                    if 'created_at' in todo_dict and isinstance(todo_dict['created_at'], str):
                        todo_dict['created_at'] = datetime.fromisoformat(todo_dict['created_at'])
                    if 'updated_at' in todo_dict and isinstance(todo_dict['updated_at'], str):
                        todo_dict['updated_at'] = datetime.fromisoformat(todo_dict['updated_at'])
                    if 'due_date' in todo_dict and todo_dict['due_date'] and isinstance(todo_dict['due_date'], str):
                        todo_dict['due_date'] = datetime.fromisoformat(todo_dict['due_date'])
                    
                    try:
                        todo_item = TodoItem(**todo_dict)
                        loaded_todos.append(todo_item)
                    except Exception as e:
                        print(f"Warning: Failed to load todo {todo_dict.get('id', 'unknown')}: {e}")
                
                # Update state with loaded todos
                self.state.todos = loaded_todos
                
        except Exception as e:
            # Don't fail if loading fails
            print(f"Warning: Failed to load todos: {e}")

    def initialize_with_persistence(self) -> None:
        """Initialize the todo system with persistence support."""
        self._load_todos()

    def _auto_save_after_operation(self) -> None:
        """Automatically save todos after any operation if persistence is enabled."""
        if self.config.persistence_enabled:
            self._save_todos()
    
    def _rebuild_caches(self) -> None:
        """Rebuild all caches for faster lookups."""
        state = self.state
        state._index_cache = {todo.id: todo for todo in state.todos}
        state._priority_cache = {}
        state._status_cache = {}
        
        for priority in TodoPriority:
            state._priority_cache[priority] = [todo for todo in state.todos if todo.priority == priority]
        
        for status in TodoStatus:
            state._status_cache[status] = [todo for todo in state.todos if todo.status == status]
        
        state._cache_dirty = False
    
    def _get_todo_by_id(self, todo_id: str) -> TodoItem | None:
        """Get todo by ID using cache for faster lookup."""
        if not self.state._index_cache or self.state._cache_dirty:
            self._rebuild_caches()
        
        return self.state._index_cache.get(todo_id)
    
    def _get_todos_by_priority(self, priority: TodoPriority) -> list[TodoItem]:
        """Get todos by priority using cache."""
        if not self.state._priority_cache or self.state._cache_dirty:
            self._rebuild_caches()
        
        return self.state._priority_cache.get(priority, [])
    
    def _get_todos_by_status(self, status: TodoStatus) -> list[TodoItem]:
        """Get todos by status using cache."""
        if not self.state._status_cache or self.state._cache_dirty:
            self._rebuild_caches()
        
        return self.state._status_cache.get(status, [])
    
    def _mark_cache_dirty(self) -> None:
        """Mark cache as dirty to force rebuild on next access."""
        self.state._cache_dirty = True
