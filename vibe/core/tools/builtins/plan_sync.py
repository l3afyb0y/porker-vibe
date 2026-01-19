"""PlanSync Tool - Synchronize todos with PLAN.md

Helps agents manage the relationship between high-level planning (PLAN.md)
and immediate task tracking (todos).
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING, ClassVar, final

from pydantic import BaseModel, Field

from vibe.core.tools.base import BaseTool, BaseToolConfig, BaseToolState, ToolPermission
from vibe.core.tools.ui import ToolCallDisplay, ToolResultDisplay, ToolUIData

if TYPE_CHECKING:
    from vibe.core.types import ToolCallEvent, ToolResultEvent


class PlanSyncAction(StrEnum):
    """Actions for the PlanSync tool."""

    READ = "read"
    GET_NEXT_STEPS = "get_next_steps"


class PlanSyncArgs(BaseModel):
    """Arguments for the PlanSync tool."""

    action: PlanSyncAction = Field(
        description="Action to perform: 'read' to read PLAN.md, 'get_next_steps' to extract next steps from PLAN.md"
    )


class PlanSyncResult(BaseModel):
    """Result from the PlanSync tool."""

    action: PlanSyncAction
    content: str | None = Field(
        default=None, description="Content from PLAN.md (if action was 'read')"
    )
    next_steps: list[str] | None = Field(
        default=None, description="List of next steps (if action was 'get_next_steps')"
    )
    message: str = Field(description="Status message")


class PlanSyncConfig(BaseToolConfig):
    """Configuration for the PlanSync tool."""

    permission: ToolPermission = ToolPermission.ALWAYS


class PlanSyncState(BaseToolState):
    """State for the PlanSync tool."""

    pass


class PlanSync(
    BaseTool[PlanSyncArgs, PlanSyncResult, PlanSyncConfig, PlanSyncState],
    ToolUIData[PlanSyncArgs, PlanSyncResult],
):
    """Synchronize todos with PLAN.md - the project's high-level planning document.

    Use this tool to:
    - Read the current PLAN.md to understand project goals and status
    - Extract "Next Steps" from PLAN.md to create new todos
    - Keep your immediate work (todos) aligned with long-term plans (PLAN.md)

    Workflow:
    1. When all todos are complete, use action='get_next_steps' to see what to work on next
    2. Create new todos based on the next steps from PLAN.md
    3. Periodically read PLAN.md to stay aligned with project goals
    4. Update PLAN.md (using Write tool) as the project evolves
    """

    description: ClassVar[str] = (
        "Synchronize todos with PLAN.md by reading the plan or extracting next steps. "
        "Helps maintain alignment between immediate work and long-term project goals."
    )

    @final
    async def run(self, args: PlanSyncArgs) -> PlanSyncResult:
        # Get the plan document manager from the agent's context
        if not hasattr(self, "_plan_document_manager"):
            return PlanSyncResult(
                action=args.action, message="Plan document manager not initialized"
            )

        if args.action == PlanSyncAction.READ:
            content = self._plan_document_manager.read()
            if content is None:
                return PlanSyncResult(
                    action=PlanSyncAction.READ,
                    content=None,
                    message="PLAN.md does not exist. Consider creating it to guide your work.",
                )
            return PlanSyncResult(
                action=PlanSyncAction.READ,
                content=content,
                message=f"Read PLAN.md ({len(content)} characters)",
            )

        if args.action == PlanSyncAction.GET_NEXT_STEPS:
            if not self._plan_document_manager.exists:
                return PlanSyncResult(
                    action=PlanSyncAction.GET_NEXT_STEPS,
                    next_steps=[],
                    message="PLAN.md does not exist. Create it first to define next steps.",
                )

            next_steps = self._plan_document_manager.extract_next_steps()
            return PlanSyncResult(
                action=PlanSyncAction.GET_NEXT_STEPS,
                next_steps=next_steps,
                message=f"Extracted {len(next_steps)} next steps from PLAN.md",
            )

        return PlanSyncResult(
            action=args.action,
            message=f"Unknown action: {args.action}. Use 'read' or 'get_next_steps'.",
        )

    def get_call_display(self, event: ToolCallEvent) -> ToolCallDisplay:
        """Display format for tool call in TUI."""
        # Use event.args directly - it's already validated
        if not isinstance(event.args, PlanSyncArgs):
            return ToolCallDisplay(
                title="Sync with PLAN.md", detail="Invalid arguments type"
            )

        args = event.args

        if args.action == PlanSyncAction.READ:
            detail = "Reading PLAN.md"
        elif args.action == PlanSyncAction.GET_NEXT_STEPS:
            detail = "Extracting next steps from PLAN.md"
        else:
            detail = f"Action: {args.action}"

        return ToolCallDisplay(title="Sync with PLAN.md", detail=detail)

    def get_result_display(self, event: ToolResultEvent) -> ToolResultDisplay:
        """Display format for tool result in TUI."""
        if event.error:
            return ToolResultDisplay(detail=f"Error: {event.error}")

        result = PlanSyncResult.model_validate_json(event.result)
        return ToolResultDisplay(detail=result.message)
