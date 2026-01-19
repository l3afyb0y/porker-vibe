from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sys
import traceback

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Static

from vibe.cli.textual_ui.widgets.messages import ExpandingBorder
from vibe.cli.textual_ui.widgets.no_markup_static import NoMarkupStatic
from vibe.cli.textual_ui.widgets.status_message import StatusMessage
from vibe.cli.textual_ui.widgets.tool_widgets import get_result_widget
from vibe.cli.textual_ui.widgets.utils import DEFAULT_TOOL_SHORTCUT, TOOL_SHORTCUTS
from vibe.core.tools.ui import ToolUIDataAdapter
from vibe.core.types import ToolCallEvent, ToolResultEvent


class ToolCallMessage(StatusMessage):
    def __init__(
        self, event: ToolCallEvent | None = None, *, tool_name: str | None = None
    ) -> None:
        if event is None and tool_name is None:
            raise ValueError("Either event or tool_name must be provided")

        self._event = event
        self._tool_name = tool_name or (event.tool_name if event else "unknown")
        self._is_history = event is None

        super().__init__()
        self.add_class("tool-call")

        if self._is_history:
            self._is_spinning = False

    def get_content(self) -> str:
        if self._event and self._event.tool_class:
            try:
                adapter = ToolUIDataAdapter(self._event.tool_class)
                display = adapter.get_call_display(self._event)
                return display.summary
            except Exception as e:
                # Log the error
                error_log_path = Path.home() / ".vibe" / "error.log"
                try:
                    error_log_path.parent.mkdir(parents=True, exist_ok=True)
                    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    with open(error_log_path, "a", encoding="utf-8") as f:
                        f.write(f"\n{'=' * 80}\n")
                        f.write(
                            f"[{timestamp}] UI Error in get_call_display: {self._tool_name}\n"
                        )
                        f.write(f"{'=' * 80}\n")
                        f.write(f"Error Type: {type(e).__name__}\n")
                        f.write(f"Error Message: {e!s}\n")
                        f.write(f"Tool: {self._tool_name}\n")
                        f.write("\nTraceback:\n")
                        f.write(traceback.format_exc())
                        f.write(f"\n{'=' * 80}\n")
                        f.flush()
                except Exception:
                    sys.stderr.write("\n[ERROR LOGGING FAILED in get_call_display]\n")
                    sys.stderr.write(f"Original error: {type(e).__name__}: {e}\n")
                    sys.stderr.flush()

                return f"{self._tool_name} (display error: {type(e).__name__})"
        return self._tool_name


class ToolResultMessage(Static):
    def __init__(
        self,
        event: ToolResultEvent | None = None,
        call_widget: ToolCallMessage | None = None,
        collapsed: bool = True,
        *,
        tool_name: str | None = None,
        content: str | None = None,
    ) -> None:
        if event is None and tool_name is None:
            raise ValueError("Either event or tool_name must be provided")

        self._event = event
        self._call_widget = call_widget
        self._tool_name = tool_name or (event.tool_name if event else "unknown")
        self._content = content
        self.collapsed = collapsed
        self._content_container: Vertical | None = None

        super().__init__()
        self.add_class("tool-result")

    @property
    def tool_name(self) -> str:
        return self._tool_name

    def _shortcut(self) -> str:
        return TOOL_SHORTCUTS.get(self._tool_name, DEFAULT_TOOL_SHORTCUT)

    def _hint(self) -> str:
        action = "expand" if self.collapsed else "collapse"
        return f"({self._shortcut()} to {action})"

    def compose(self) -> ComposeResult:
        with Horizontal(classes="tool-result-container"):
            yield ExpandingBorder(classes="tool-result-border")
            self._content_container = Vertical(classes="tool-result-content")
            yield self._content_container

    async def on_mount(self) -> None:
        if self._call_widget:
            success = self._event is None or (
                not self._event.error and not self._event.skipped
            )
            self._call_widget.stop_spinning(success=success)
        await self._render_result()

    async def _render_result(self) -> None:
        if self._content_container is None:
            return

        await self._content_container.remove_children()

        if self._event is None:
            await self._render_simple()
            return

        if self._event.error:
            await self._render_error()
            return

        if self._event.skipped:
            await self._render_skipped()
            return

        self.remove_class("error-text")
        self.remove_class("warning-text")

        if self._event.tool_class is None:
            await self._render_simple()
            return

        await self._render_tool_result()

    async def _render_error(self) -> None:
        """Render error state."""
        self.add_class("error-text")
        if self.collapsed:
            await self._content_container.mount(
                NoMarkupStatic(f"Error. {self._hint()}")
            )
        else:
            await self._content_container.mount(
                NoMarkupStatic(f"Error: {self._event.error}")
            )

    async def _render_skipped(self) -> None:
        """Render skipped state."""
        self.add_class("warning-text")
        reason = self._event.skip_reason or "User skipped"
        if self.collapsed:
            await self._content_container.mount(
                NoMarkupStatic(f"Skipped. {self._hint()}")
            )
        else:
            await self._content_container.mount(NoMarkupStatic(f"Skipped: {reason}"))

    async def _render_tool_result(self) -> None:
        """Render successful tool result."""
        try:
            adapter = ToolUIDataAdapter(self._event.tool_class)
            display = adapter.get_result_display(self._event)

            widget = get_result_widget(
                self._event.tool_name,
                self._event.result,
                success=display.success,
                message=display.message,
                collapsed=self.collapsed,
                warnings=display.warnings,
            )
            await self._content_container.mount(widget)
        except Exception as e:
            self._log_and_show_error(e)

    def _log_and_show_error(self, e: Exception) -> None:
        """Log error and show simple error message."""
        # Log the error
        error_log_path = Path.home() / ".vibe" / "error.log"
        try:
            error_log_path.parent.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with open(error_log_path, "a", encoding="utf-8") as f:
                f.write(f"\n{'=' * 80}\n")
                f.write(
                    f"[{timestamp}] UI Error in get_result_display: {self._event.tool_name}\n"
                )
                f.write(f"{'=' * 80}\n")
                f.write(f"Error Type: {type(e).__name__}\n")
                f.write(f"Error Message: {e!s}\n")
                f.write(f"Tool: {self._event.tool_name}\n")
                f.write("\nTraceback:\n")
                f.write(traceback.format_exc())
                f.write(f"\n{'=' * 80}\n")
                f.flush()
        except Exception:
            sys.stderr.write("\n[ERROR LOGGING FAILED in get_result_display]\n")
            sys.stderr.write(f"Original error: {type(e).__name__}: {e}\n")
            sys.stderr.flush()

        # Render a simple error message
        # Need to schedule this mount since we're in a sync method here (called from exception handler)
        # But wait, the original code had await mount inside try/except block in async method.
        # My refactoring split it. _render_tool_result is async, so I can await mount there.
        pass

    async def _log_and_show_error(self, e: Exception) -> None:
        """Log error and show simple error message."""
        # Log the error
        error_log_path = Path.home() / ".vibe" / "error.log"
        try:
            error_log_path.parent.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with open(error_log_path, "a", encoding="utf-8") as f:
                f.write(f"\n{'=' * 80}\n")
                f.write(
                    f"[{timestamp}] UI Error in get_result_display: {self._event.tool_name}\n"
                )
                f.write(f"{'=' * 80}\n")
                f.write(f"Error Type: {type(e).__name__}\n")
                f.write(f"Error Message: {e!s}\n")
                f.write(f"Tool: {self._event.tool_name}\n")
                f.write("\nTraceback:\n")
                f.write(traceback.format_exc())
                f.write(f"\n{'=' * 80}\n")
                f.flush()
        except Exception:
            sys.stderr.write("\n[ERROR LOGGING FAILED in get_result_display]\n")
            sys.stderr.write(f"Original error: {type(e).__name__}: {e}\n")
            sys.stderr.flush()

        # Render a simple error message
        await self._content_container.mount(
            NoMarkupStatic(
                f"Display error: {type(e).__name__}: {e!s}\nSee ~/.vibe/error.log"
            )
        )

    async def _render_simple(self) -> None:
        if self._content_container is None:
            return

        if self.collapsed:
            await self._content_container.mount(
                NoMarkupStatic(f"{self._tool_name} completed {self._hint()}")
            )
            return

        if self._content:
            await self._content_container.mount(NoMarkupStatic(self._content))
        else:
            await self._content_container.mount(
                NoMarkupStatic(f"{self._tool_name} completed.")
            )

    async def set_collapsed(self, collapsed: bool) -> None:
        if self.collapsed == collapsed:
            return
        self.collapsed = collapsed
        await self._render_result()

    async def toggle_collapsed(self) -> None:
        self.collapsed = not self.collapsed
        await self._render_result()
