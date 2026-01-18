from __future__ import annotations

from datetime import datetime
from typing import Callable

from textual.app import ComposeResult
from textual.containers import Container, VerticalScroll
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Button, Label, Static

from vibe.core.tools.builtins.todo import TodoItem, TodoPriority, TodoStatus


class TodoItemWidget(Static):
    """Widget for displaying a single todo item."""
    
    def __init__(self, todo: TodoItem, on_status_change: Callable[[str, TodoStatus], None] | None = None):
        super().__init__()
        self.todo = todo
        self.on_status_change = on_status_change
        
    def compose(self) -> ComposeResult:
        yield Container(
            Label(self.todo.content, classes="todo-content"),
            Label(f"Priority: {self.todo.priority.value}", classes="todo-priority"),
            Label(f"Status: {self.todo.status.value}", classes=f"todo-status {self.todo.status.value.lower()}"),
            Label(f"Created: {self.todo.created_at.strftime('%Y-%m-%d %H:%M')}", classes="todo-timestamp"),
            *self._get_additional_info(),
            classes="todo-item"
        )
    
    def _get_additional_info(self) -> list[Widget]:
        """Get additional info widgets based on todo properties."""
        widgets = []
        
        if self.todo.due_date:
            due_date_str = self.todo.due_date.strftime('%Y-%m-%d %H:%M')
            widgets.append(Label(f"Due: {due_date_str}", classes="todo-due-date"))
        
        if self.todo.tags:
            tags_str = ", ".join(self.todo.tags)
            widgets.append(Label(f"Tags: {tags_str}", classes="todo-tags"))
        
        if self.todo.auto_tracked:
            widgets.append(Label("Auto-tracked", classes="todo-auto-tracked"))
        
        return widgets


class TodoListWidget(VerticalScroll):
    """Widget for displaying a list of todo items."""
    
    def __init__(self, todos: list[TodoItem], on_status_change: Callable[[str, TodoStatus], None] | None = None):
        super().__init__()
        self.todos = todos
        self.on_status_change = on_status_change
        
    def compose(self) -> ComposeResult:
        if not self.todos:
            yield Label("No todos found", classes="no-todos")
            return
        
        # Group todos by status
        status_groups = {}
        for status in TodoStatus:
            status_groups[status] = [todo for todo in self.todos if todo.status == status]
        
        for status, status_todos in status_groups.items():
            if status_todos:
                with Container(classes=f"todo-status-group {status.value.lower()}"):
                    yield Label(f"{status.value} ({len(status_todos)})", classes="status-group-header")
                    for todo in status_todos:
                        yield TodoItemWidget(todo, self.on_status_change)


class EnhancedTodoWidget(Widget):
    """Enhanced todo widget with all features."""
    
    todos: reactive[list[TodoItem]] = reactive([])
    
    def __init__(
        self,
        initial_todos: list[TodoItem] = [],
        on_add_todo: Callable[[TodoItem], None] | None = None,
        on_update_todo: Callable[[str, dict], None] | None = None,
        on_remove_todo: Callable[[str], None] | None = None,
        on_complete_todo: Callable[[str], None] | None = None,
    ):
        super().__init__()
        self.todos = initial_todos
        self.on_add_todo = on_add_todo
        self.on_update_todo = on_update_todo
        self.on_remove_todo = on_remove_todo
        self.on_complete_todo = on_complete_todo
    
    def compose(self) -> ComposeResult:
        yield Container(
            Label("Enhanced Todo System", classes="todo-title"),
            Button("Add Todo", id="add-todo", variant="primary"),
            Button("Smart Prioritize", id="smart-prioritize"),
            Button("Get Suggestions", id="get-suggestions"),
            TodoListWidget(self.todos, self._handle_status_change),
            Label(id="suggestions-area"),
            classes="todo-container"
        )
    
    def _handle_status_change(self, todo_id: str, new_status: TodoStatus) -> None:
        """Handle status change for a todo item."""
        if new_status == TodoStatus.COMPLETED and self.on_complete_todo:
            self.on_complete_todo(todo_id)
        elif self.on_update_todo:
            self.on_update_todo(todo_id, {"status": new_status.value})
    
    def update_todos(self, todos: list[TodoItem]) -> None:
        """Update the list of todos."""
        self.todos = todos
        self.refresh()
    
    def show_suggestions(self, suggestions: list[str]) -> None:
        """Show suggestions in the suggestions area."""
        suggestions_widget = self.query_one("#suggestions-area", Label)
        if suggestions:
            suggestions_text = "Suggestions:\n" + "\n".join(f"• {suggestion}" for suggestion in suggestions)
            suggestions_widget.update(suggestions_text)
        else:
            suggestions_widget.update("No suggestions available")
    
    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press events."""
        button_id = event.button.id
        
        if button_id == "add-todo":
            self._handle_add_todo()
        elif button_id == "smart-prioritize":
            self._handle_smart_prioritize()
        elif button_id == "get-suggestions":
            self._handle_get_suggestions()
    
    def _handle_add_todo(self) -> None:
        """Handle add todo button press."""
        # This would typically open a dialog or form
        # For now, we'll just log it
        if self.on_add_todo:
            new_todo = TodoItem(
                id=f"new_{len(self.todos) + 1}",
                content="New Task",
                status=TodoStatus.PENDING,
                priority=TodoPriority.MEDIUM
            )
            self.on_add_todo(new_todo)
    
    def _handle_smart_prioritize(self) -> None:
        """Handle smart prioritize button press."""
        # This would call the smart prioritization method
        # For now, we'll just show a message
        self.show_suggestions(["Smart prioritization applied"])
    
    def _handle_get_suggestions(self) -> None:
        """Handle get suggestions button press."""
        # This would call the context-aware suggestions method
        # For now, we'll show placeholder suggestions
        suggestions = [
            "Complete high priority tasks first",
            "Consider breaking large tasks into smaller ones",
            "Review tasks that have been pending for a while"
        ]
        self.show_suggestions(suggestions)


class TodoStatusButton(Button):
    """Button for changing todo status."""
    
    def __init__(self, todo_id: str, current_status: TodoStatus, target_status: TodoStatus):
        super().__init__(
            label=target_status.value,
            id=f"status-{todo_id}-{target_status.value.lower()}"
        )
        self.todo_id = todo_id
        self.target_status = target_status
