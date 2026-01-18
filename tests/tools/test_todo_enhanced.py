from __future__ import annotations

import json
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from vibe.core.tools.builtins.todo import (
    AutoTaskTrackingMiddleware,
    Todo,
    TodoArgs,
    TodoConfig,
    TodoItem,
    TodoPriority,
    TodoResult,
    TodoState,
    TodoStatus,
)


class TestEnhancedTodoDataModel:
    """Test the enhanced todo data model with new fields."""
    
    def test_todo_item_creation_with_new_fields(self):
        """Test creating a todo item with all new fields."""
        now = datetime.now()
        due_date = now + timedelta(days=1)
        
        todo = TodoItem(
            id="test1",
            content="Test task",
            status=TodoStatus.PENDING,
            priority=TodoPriority.HIGH,
            created_at=now,
            updated_at=now,
            due_date=due_date,
            tags=["test", "enhanced"],
            related_tasks=["task2", "task3"],
            context="Test context",
            auto_tracked=True
        )
        
        assert todo.id == "test1"
        assert todo.content == "Test task"
        assert todo.status == TodoStatus.PENDING
        assert todo.priority == TodoPriority.HIGH
        assert todo.created_at == now
        assert todo.updated_at == now
        assert todo.due_date == due_date
        assert todo.tags == ["test", "enhanced"]
        assert todo.related_tasks == ["task2", "task3"]
        assert todo.context == "Test context"
        assert todo.auto_tracked is True
    
    def test_todo_item_defaults(self):
        """Test that new fields have proper defaults."""
        todo = TodoItem(
            id="test2",
            content="Simple task"
        )
        
        assert todo.status == TodoStatus.PENDING
        assert todo.priority == TodoPriority.MEDIUM
        assert todo.created_at is not None
        assert todo.updated_at is not None
        assert todo.due_date is None
        assert todo.tags == []
        assert todo.related_tasks == []
        assert todo.context is None
        assert todo.auto_tracked is False


class TestPartialUpdateAPI:
    """Test the new partial update API methods."""
    
    @pytest.fixture
    def todo_tool(self) -> Todo:
        """Create a todo tool for testing."""
        config = TodoConfig(persistence_enabled=False)
        state = TodoState()
        return Todo(config=config, state=state)
    
    @pytest.mark.asyncio
    async def test_add_todo(self, todo_tool: Todo):
        """Test adding a single todo."""
        new_todo = TodoItem(
            id="add1",
            content="Added task",
            priority=TodoPriority.HIGH
        )
        
        args = TodoArgs(action="add", todo_item=new_todo)
        result = await todo_tool.run(args)
        
        assert result.message == "Added todo: Added task"
        assert len(result.todos) == 1
        assert result.todos[0].id == "add1"
        assert result.todos[0].status == TodoStatus.PENDING
    
    @pytest.mark.asyncio
    async def test_update_todo(self, todo_tool: Todo):
        """Test updating a todo."""
        # First add a todo
        todo_tool._add_todo(TodoItem(id="update1", content="Original"))
        
        # Now update it
        updates = {"content": "Updated content", "priority": TodoPriority.HIGH.value}
        args = TodoArgs(action="update", todo_id="update1", updates=updates)
        result = await todo_tool.run(args)
        
        assert result.message == "Updated todo: Updated content"
        assert len(result.todos) == 1
        assert result.todos[0].content == "Updated content"
        assert result.todos[0].priority == TodoPriority.HIGH
    
    @pytest.mark.asyncio
    async def test_remove_todo(self, todo_tool: Todo):
        """Test removing a todo."""
        # Add a todo first
        todo_tool._add_todo(TodoItem(id="remove1", content="To be removed"))
        assert len(todo_tool.state.todos) == 1
        
        # Remove it
        args = TodoArgs(action="remove", todo_id="remove1")
        result = await todo_tool.run(args)
        
        assert result.message == "Removed todo: remove1"
        assert len(result.todos) == 0
    
    @pytest.mark.asyncio
    async def test_complete_todo(self, todo_tool: Todo):
        """Test completing a todo."""
        # Add a todo first
        todo_tool._add_todo(TodoItem(id="complete1", content="To be completed"))
        
        # Complete it
        args = TodoArgs(action="complete", todo_id="complete1")
        result = await todo_tool.run(args)
        
        assert result.message == "Completed todo: To be completed"
        assert result.todos[0].status == TodoStatus.COMPLETED
    
    @pytest.mark.asyncio
    async def test_backward_compatibility(self, todo_tool: Todo):
        """Test that old read/write API still works."""
        # Test write
        todos = [
            TodoItem(id="old1", content="Old task 1"),
            TodoItem(id="old2", content="Old task 2")
        ]
        args = TodoArgs(action="write", todos=todos)
        result = await todo_tool.run(args)
        
        assert result.message == "Updated 2 todos"
        assert len(result.todos) == 2
        
        # Test read
        args = TodoArgs(action="read")
        result = await todo_tool.run(args)
        
        assert result.message == "Retrieved 2 todos"
        assert len(result.todos) == 2


class TestAutomaticTaskTracking:
    """Test the automatic task tracking middleware."""
    
    @pytest.fixture
    def todo_tool(self) -> Todo:
        """Create a todo tool for testing."""
        config = TodoConfig(persistence_enabled=False)
        state = TodoState()
        return Todo(config=config, state=state)
    
    @pytest.fixture
    def middleware(self, todo_tool: Todo) -> AutoTaskTrackingMiddleware:
        """Create middleware for testing."""
        return todo_tool.create_auto_tracking_middleware()
    
    def test_middleware_initialization(self, middleware: AutoTaskTrackingMiddleware):
        """Test that middleware is properly initialized."""
        assert middleware.todo_tool is not None
        assert len(middleware.tracked_actions) > 0
        assert "bash" in middleware.tracked_actions
    
    @pytest.mark.asyncio
    async def test_before_turn_with_action_words(self, middleware: AutoTaskTrackingMiddleware):
        """Test that middleware creates tasks for messages with action words."""
        from vibe.core.middleware import ConversationContext, MiddlewareResult
        from vibe.core.types import LLMMessage, Role
        
        # Create a context with a user message containing action words
        messages = [
            LLMMessage(role=Role.system, content="System prompt"),
            LLMMessage(role=Role.user, content="Please implement the new feature")
        ]
        
        # Mock stats and config
        class MockStats:
            pass
        
        class MockConfig:
            pass
        
        context = ConversationContext(
            messages=messages,
            stats=MockStats(),
            config=MockConfig()
        )
        
        # Call before_turn
        result = await middleware.before_turn(context)
        
        # Check that it returns continue action
        assert result.action == "continue"
        
        # Check that a task was created (if the message contains action words)
        todo_tool = middleware.todo_tool
        auto_tracked_todos = [todo for todo in todo_tool.state.todos if todo.auto_tracked]
        assert len(auto_tracked_todos) > 0
    
    @pytest.mark.asyncio
    async def test_after_turn_with_tool_usage(self, middleware: AutoTaskTrackingMiddleware):
        """Test that middleware tracks tool usage."""
        from vibe.core.middleware import ConversationContext, MiddlewareResult
        from vibe.core.types import LLMMessage, Role
        
        # Create a context with tool usage
        messages = [
            LLMMessage(role=Role.system, content="System prompt"),
            LLMMessage(role=Role.assistant, content='Using tool: <tool_call>bash{"command": "ls"}')
        ]
        
        # Mock stats and config
        class MockStats:
            pass
        
        class MockConfig:
            pass
        
        context = ConversationContext(
            messages=messages,
            stats=MockStats(),
            config=MockConfig()
        )
        
        # Call after_turn
        result = await middleware.after_turn(context)
        
        # Check that it returns continue action
        assert result.action == "continue"
        
        # Check that tool usage was tracked
        todo_tool = middleware.todo_tool
        bash_todos = [todo for todo in todo_tool.state.todos if "bash" in todo.tags]
        assert len(bash_todos) > 0


class TestContextAwareSuggestions:
    """Test context-aware suggestion functionality."""
    
    @pytest.fixture
    def todo_tool(self) -> Todo:
        """Create a todo tool with some sample data."""
        config = TodoConfig(persistence_enabled=False)
        state = TodoState()
        tool = Todo(config=config, state=state)
        
        # Add some sample todos
        now = datetime.now()
        tool._add_todo(TodoItem(
            id="suggest1",
            content="Implement feature X",
            status=TodoStatus.IN_PROGRESS,
            priority=TodoPriority.HIGH,
            created_at=now - timedelta(days=1)
        ))
        tool._add_todo(TodoItem(
            id="suggest2",
            content="Write documentation",
            status=TodoStatus.PENDING,
            priority=TodoPriority.MEDIUM,
            due_date=now + timedelta(hours=2)
        ))
        tool._add_todo(TodoItem(
            id="suggest3",
            content="Fix bug Y",
            status=TodoStatus.PENDING,
            priority=TodoPriority.LOW,
        ))
        # Manually set created_at to simulate old task
        tool.state.todos[-1].created_at = now - timedelta(days=8)
        tool._add_todo(TodoItem(
            id="suggest4",
            content="Urgent fix",
            status=TodoStatus.PENDING,
            priority=TodoPriority.HIGH,
            created_at=now
        ))
        
        return tool
    
    def test_context_aware_suggestions(self, todo_tool: Todo):
        """Test getting context-aware suggestions."""
        suggestions = todo_tool.get_context_aware_suggestions("implement new feature")
        
        assert len(suggestions) > 0
        assert any("in-progress" in suggestion.lower() for suggestion in suggestions)
        assert any("high priority" in suggestion.lower() for suggestion in suggestions)
    
    def test_smart_prioritization_suggestions(self, todo_tool: Todo):
        """Test getting smart prioritization suggestions."""
        suggestions = todo_tool.get_smart_prioritization_suggestions()
        
        # Should suggest increasing priority for the task due soon
        assert len(suggestions) > 0
        assert any("due soon" in suggestion[1].lower() for suggestion in suggestions)
    
    def test_priority_score_calculation(self, todo_tool: Todo):
        """Test priority score calculation."""
        now = datetime.now()
        
        # Test different scenarios
        in_progress_todo = TodoItem(
            id="test",
            content="Test",
            status=TodoStatus.IN_PROGRESS,
            priority=TodoPriority.MEDIUM,
            created_at=now
        )
        
        overdue_todo = TodoItem(
            id="test2",
            content="Test 2",
            status=TodoStatus.PENDING,
            priority=TodoPriority.LOW,
            created_at=now - timedelta(days=10),
            due_date=now - timedelta(hours=1)
        )
        
        in_progress_score = todo_tool.get_priority_score(in_progress_todo)
        overdue_score = todo_tool.get_priority_score(overdue_todo)
        
        # In progress should have higher score
        assert in_progress_score > 100  # Base medium priority (50) + in progress bonus (100)
        assert overdue_score > 200  # Base low priority (25) + overdue bonus (200)
    
    def test_dynamic_priority_order(self, todo_tool: Todo):
        """Test dynamic priority ordering."""
        ordered_todos = todo_tool.get_dynamic_priority_order()
        
        # Should be ordered by priority score
        assert len(ordered_todos) == 4
        # First should be the in-progress high priority task
        assert ordered_todos[0].id == "suggest1"


class TestTaskPersistence:
    """Test task persistence functionality."""
    
    @pytest.fixture
    def temp_file(self) -> str:
        """Create a temporary file for testing persistence."""
        with tempfile.NamedTemporaryFile(delete=False, suffix=".json") as f:
            return f.name
    
    def test_persistence_save_and_load(self, temp_file: str):
        """Test saving and loading todos."""
        # Create todo tool with persistence enabled
        config = TodoConfig(persistence_enabled=True, persistence_file=temp_file)
        state = TodoState()
        tool = Todo(config=config, state=state)
        
        # Add some todos
        tool._add_todo(TodoItem(id="persist1", content="Persistent task 1"))
        tool._add_todo(TodoItem(id="persist2", content="Persistent task 2"))
        
        # Save todos
        tool._save_todos()
        
        # Verify file was created and contains data
        assert Path(temp_file).exists()
        with open(temp_file, 'r') as f:
            data = json.load(f)
            assert len(data) == 2
            assert data[0]['id'] == "persist1"
        
        # Create new tool and load
        new_state = TodoState()
        new_tool = Todo(config=config, state=new_state)
        new_tool._load_todos()
        
        assert len(new_tool.state.todos) == 2
        assert new_tool.state.todos[0].id == "persist1"
        
        # Clean up
        Path(temp_file).unlink()
    
    def test_persistence_disabled(self):
        """Test that persistence can be disabled."""
        config = TodoConfig(persistence_enabled=False)
        state = TodoState()
        tool = Todo(config=config, state=state)
        
        # Add a todo
        tool._add_todo(TodoItem(id="no_persist", content="No persistence"))
        
        # Try to save (should do nothing)
        tool._save_todos()
        
        # State should still have the todo
        assert len(tool.state.todos) == 1
    
    def test_auto_save_after_operations(self, temp_file: str):
        """Test that auto-save works after operations."""
        config = TodoConfig(persistence_enabled=True, persistence_file=temp_file)
        state = TodoState()
        tool = Todo(config=config, state=state)
        
        # Perform operations that should trigger auto-save
        tool._add_todo(TodoItem(id="auto1", content="Auto save test"))
        
        # Verify file exists and has data
        assert Path(temp_file).exists()
        with open(temp_file, 'r') as f:
            data = json.load(f)
            assert len(data) == 1
        
        # Clean up
        Path(temp_file).unlink()


class TestSmartPrioritization:
    """Test smart prioritization functionality."""
    
    @pytest.fixture
    def todo_tool(self) -> Todo:
        """Create a todo tool with sample data for prioritization testing."""
        config = TodoConfig(persistence_enabled=False)
        state = TodoState()
        tool = Todo(config=config, state=state)
        
        now = datetime.now()
        
        # Add todos with different characteristics
        tool._add_todo(TodoItem(
            id="prio1",
            content="High priority task",
            status=TodoStatus.PENDING,
            priority=TodoPriority.HIGH,
            created_at=now - timedelta(days=1)
        ))
        
        tool._add_todo(TodoItem(
            id="prio2",
            content="Due soon task",
            status=TodoStatus.PENDING,
            priority=TodoPriority.LOW,
            due_date=now + timedelta(hours=1)  # Due in 1 hour
        ))
        
        tool._add_todo(TodoItem(
            id="prio3",
            content="Old task",
            status=TodoStatus.PENDING,
            priority=TodoPriority.MEDIUM,
        ))
        # Manually set created_at to simulate old task
        tool.state.todos[-1].created_at = now - timedelta(days=10)
        
        tool._add_todo(TodoItem(
            id="prio4",
            content="In progress task",
            status=TodoStatus.IN_PROGRESS,
            priority=TodoPriority.MEDIUM
        ))
        
        return tool
    
    def test_apply_smart_prioritization(self, todo_tool: Todo):
        """Test applying smart prioritization."""
        result = todo_tool.apply_smart_prioritization()
        
        assert "Applied smart prioritization" in result.message
        
        # Check that priorities were adjusted
        due_soon_todo = next(todo for todo in todo_tool.state.todos if todo.id == "prio2")
        old_todo = next(todo for todo in todo_tool.state.todos if todo.id == "prio3")
        
        # The due soon task should have been prioritized up from LOW
        assert due_soon_todo.priority != TodoPriority.LOW
        
        # The old task should have been prioritized up from MEDIUM
        assert old_todo.priority == TodoPriority.HIGH
    
    def test_priority_inversion_detection(self, todo_tool: Todo):
        """Test detection of priority inversion."""
        suggestions = todo_tool.get_smart_prioritization_suggestions()
        
        # Should detect that high priority task is pending while medium priority is in progress
        inversion_suggestions = [s for s in suggestions if "inversion" in s[1].lower()]
        assert len(inversion_suggestions) > 0


class TestBackwardCompatibility:
    """Test backward compatibility with existing todo functionality."""
    
    @pytest.mark.asyncio
    async def test_original_api_still_works(self):
        """Test that the original read/write API still works."""
        config = TodoConfig(persistence_enabled=False)
        state = TodoState()
        tool = Todo(config=config, state=state)
        
        # Test write with original API
        todos = [
            TodoItem(id="old1", content="Old task 1"),
            TodoItem(id="old2", content="Old task 2", priority=TodoPriority.HIGH)
        ]
        
        args = TodoArgs(action="write", todos=todos)
        result = await tool.run(args)
        
        assert result.message == "Updated 2 todos"
        assert len(result.todos) == 2
        assert result.todos[0].id == "old1"
        assert result.todos[1].priority == TodoPriority.HIGH
        
        # Test read with original API
        args = TodoArgs(action="read")
        result = await tool.run(args)
        
        assert result.message == "Retrieved 2 todos"
        assert len(result.todos) == 2
    
    def test_new_fields_optional(self):
        """Test that new fields are optional and don't break existing code."""
        # Create todo with only old fields
        old_todo = TodoItem(
            id="compat1",
            content="Compatible task",
            status=TodoStatus.PENDING,
            priority=TodoPriority.MEDIUM
        )
        
        # Should work fine
        assert old_todo.id == "compat1"
        assert old_todo.content == "Compatible task"
        assert old_todo.status == TodoStatus.PENDING
        assert old_todo.priority == TodoPriority.MEDIUM
        
        # New fields should have defaults
        assert old_todo.created_at is not None
        assert old_todo.updated_at is not None
        assert old_todo.due_date is None
        assert old_todo.tags == []
        assert old_todo.auto_tracked is False


class TestErrorHandling:
    """Test error handling in enhanced todo system."""
    
    @pytest.fixture
    def todo_tool(self) -> Todo:
        """Create a todo tool for testing."""
        config = TodoConfig(persistence_enabled=False)
        state = TodoState()
        return Todo(config=config, state=state)
    
    def test_add_duplicate_todo(self, todo_tool: Todo):
        """Test error handling for duplicate todo IDs."""
        # Add a todo
        todo_tool._add_todo(TodoItem(id="dup1", content="First"))
        
        # Try to add another with same ID
        with pytest.raises(Exception) as exc_info:
            todo_tool._add_todo(TodoItem(id="dup1", content="Duplicate"))
        
        assert "already exists" in str(exc_info.value)
    
    def test_update_nonexistent_todo(self, todo_tool: Todo):
        """Test error handling for updating non-existent todo."""
        with pytest.raises(Exception) as exc_info:
            todo_tool._update_todo("nonexistent", {"content": "New content"})
        
        assert "not found" in str(exc_info.value)
    
    def test_remove_nonexistent_todo(self, todo_tool: Todo):
        """Test error handling for removing non-existent todo."""
        with pytest.raises(Exception) as exc_info:
            todo_tool._remove_todo("nonexistent")
        
        assert "not found" in str(exc_info.value)
    
    def test_complete_already_completed(self, todo_tool: Todo):
        """Test error handling for completing already completed todo."""
        # Add and complete a todo
        todo_tool._add_todo(TodoItem(id="complete_twice", content="Test"))
        todo_tool._complete_todo("complete_twice")
        
        # Try to complete again
        with pytest.raises(Exception) as exc_info:
            todo_tool._complete_todo("complete_twice")
        
        assert "already completed" in str(exc_info.value)
    
    def test_invalid_field_update(self, todo_tool: Todo):
        """Test error handling for invalid field updates."""
        # Add a todo
        todo_tool._add_todo(TodoItem(id="invalid", content="Test"))
        
        # Try to update with invalid field
        with pytest.raises(Exception) as exc_info:
            todo_tool._update_todo("invalid", {"nonexistent_field": "value"})
        
        assert "Invalid field" in str(exc_info.value)
    
    def test_max_todos_limit(self, todo_tool: Todo):
        """Test that max todos limit is enforced."""
        config = todo_tool.config
        config.max_todos = 2
        
        # Add up to limit
        todo_tool._add_todo(TodoItem(id="limit1", content="First"))
        todo_tool._add_todo(TodoItem(id="limit2", content="Second"))
        
        # Try to add one more
        with pytest.raises(Exception) as exc_info:
            todo_tool._add_todo(TodoItem(id="limit3", content="Third"))
        
        assert "Cannot store more than" in str(exc_info.value)