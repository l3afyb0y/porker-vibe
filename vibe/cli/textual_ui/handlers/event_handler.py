from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
import traceback
from typing import TYPE_CHECKING

from vibe.cli.textual_ui.widgets.compact import CompactMessage
from vibe.cli.textual_ui.widgets.messages import AssistantMessage, ReasoningMessage
from vibe.cli.textual_ui.widgets.no_markup_static import NoMarkupStatic
from vibe.cli.textual_ui.widgets.tools import ToolCallMessage, ToolResultMessage
from vibe.core.types import (
    AssistantEvent,
    BaseEvent,
    CompactEndEvent,
    CompactStartEvent,
    ReasoningEvent,
    ToolCallEvent,
    ToolResultEvent,
)
from vibe.core.utils import TaggedText

if TYPE_CHECKING:
    from vibe.cli.textual_ui.widgets.loading import LoadingWidget


class EventHandler:
    def __init__(
        self,
        mount_callback: Callable,
        scroll_callback: Callable,
        todo_update_callback: Callable,
        get_tools_collapsed: Callable[[], bool],
        get_todos_collapsed: Callable[[], bool],
    ) -> None:
        self.mount_callback = mount_callback
        self.scroll_callback = scroll_callback
        self.todo_update_callback = todo_update_callback

        self.get_tools_collapsed = get_tools_collapsed
        self.get_todos_collapsed = get_todos_collapsed
        self.current_tool_call: ToolCallMessage | None = None
        self.current_compact: CompactMessage | None = None

        # Set up error log file - always in ~/.vibe
        self.error_log_path = Path.home() / ".vibe" / "error.log"
        self.error_log_path.parent.mkdir(parents=True, exist_ok=True)

    def log_error(self, error: Exception, context: str = "") -> None:
        """Log error with full traceback to file."""
        try:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with open(self.error_log_path, "a", encoding="utf-8") as f:
                f.write(f"\n{'=' * 80}\n")
                f.write(f"[{timestamp}] Error in {context}\n")
                f.write(f"{'=' * 80}\n")
                f.write(f"Error Type: {type(error).__name__}\n")
                f.write(f"Error Message: {error!s}\n")
                f.write("\nTraceback:\n")
                f.write(traceback.format_exc())
                f.write(f"\n{'=' * 80}\n")
        except Exception:
            # If logging fails, don't crash the app
            pass

    async def handle_event(
        self,
        event: BaseEvent,
        loading_active: bool = False,
        loading_widget: LoadingWidget | None = None,
    ) -> ToolCallMessage | None:
        match event:
            case ToolCallEvent():
                return await self._handle_tool_call(event, loading_widget)
            case ToolResultEvent():
                sanitized_event = self._sanitize_event(event)
                await self._handle_tool_result(sanitized_event)
                try:
                    await self.todo_update_callback()
                except Exception as e:
                    self.log_error(e, "todo_update_callback after ToolResultEvent")
                    # Show error in TUI
                    from vibe.cli.textual_ui.widgets.messages import ErrorMessage

                    error_msg = ErrorMessage(
                        f"Error updating todos: {type(e).__name__}: {e!s}\n"
                        "See ~/.vibe/error.log for full traceback",
                        collapsed=self.get_tools_collapsed(),
                    )
                    await self.mount_callback(error_msg)
            case ReasoningEvent():
                await self._handle_reasoning_message(event)
            case AssistantEvent():
                await self._handle_assistant_message(event)
            case CompactStartEvent():
                await self._handle_compact_start()
            case CompactEndEvent():
                await self._handle_compact_end(event)
            case _:
                await self._handle_unknown_event(event)
        return None

    def _sanitize_event(self, event: ToolResultEvent) -> ToolResultEvent:
        if isinstance(event, ToolResultEvent):
            return ToolResultEvent(
                tool_name=event.tool_name,
                tool_class=event.tool_class,
                result=event.result,
                error=TaggedText.from_string(event.error).message
                if event.error
                else None,
                skipped=event.skipped,
                skip_reason=TaggedText.from_string(event.skip_reason).message
                if event.skip_reason
                else None,
                duration=event.duration,
                tool_call_id=event.tool_call_id,
            )
        return event

    async def _handle_tool_call(
        self, event: ToolCallEvent, loading_widget: LoadingWidget | None = None
    ) -> ToolCallMessage | None:
        tool_call = ToolCallMessage(event)

        if loading_widget and event.tool_class:
            from vibe.core.tools.ui import ToolUIDataAdapter

            adapter = ToolUIDataAdapter(event.tool_class)
            status_text = adapter.get_status_text()
            loading_widget.set_status(status_text)

        await self.mount_callback(tool_call)

        self.current_tool_call = tool_call
        return tool_call

    async def _handle_tool_result(self, event: ToolResultEvent) -> None:
        tools_collapsed = self.get_tools_collapsed()
        tool_result = ToolResultMessage(
            event, self.current_tool_call, collapsed=tools_collapsed
        )
        await self.mount_callback(tool_result)

        self.current_tool_call = None

    async def _handle_assistant_message(self, event: AssistantEvent) -> None:
        await self.mount_callback(AssistantMessage(event.content))

    async def _handle_reasoning_message(self, event: ReasoningEvent) -> None:
        tools_collapsed = self.get_tools_collapsed()
        await self.mount_callback(
            ReasoningMessage(event.content, collapsed=tools_collapsed)
        )

    async def _handle_compact_start(self) -> None:
        compact_msg = CompactMessage()
        self.current_compact = compact_msg
        await self.mount_callback(compact_msg)

    async def _handle_compact_end(self, event: CompactEndEvent) -> None:
        if self.current_compact:
            self.current_compact.set_complete(
                old_tokens=event.old_context_tokens, new_tokens=event.new_context_tokens
            )
            self.current_compact = None

    async def _handle_unknown_event(self, event: BaseEvent) -> None:
        await self.mount_callback(NoMarkupStatic(str(event), classes="unknown-event"))

    def stop_current_tool_call(self) -> None:
        if self.current_tool_call:
            self.current_tool_call.stop_spinning()
            self.current_tool_call = None

    def stop_current_compact(self) -> None:
        if self.current_compact:
            self.current_compact.stop_spinning(success=False)
            self.current_compact = None
