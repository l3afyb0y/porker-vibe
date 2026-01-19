"""Planning models for the agent's hierarchical plan."""

from __future__ import annotations

from enum import StrEnum, auto
import time
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class ItemStatus(StrEnum):
    """Represents the status of a planning item."""

    PENDING = auto()
    IN_PROGRESS = auto()
    COMPLETED = auto()
    BLOCKED = auto()
    FAILED = auto()
    SKIPPED = auto()


class PlanItem(BaseModel):
    """Base model for any item in the agent's plan."""

    id: UUID = Field(
        default_factory=uuid4, description="Unique identifier for the item."
    )
    name: str = Field(..., description="A brief name or title for the item.")
    description: str | None = Field(
        None, description="Detailed description of the item."
    )
    status: ItemStatus = Field(
        ItemStatus.PENDING, description="Current status of the item."
    )
    dependencies: list[UUID] = Field(
        default_factory=list,
        description="List of IDs of other items that must be completed before this one.",
    )
    assigned_to: str | None = Field(
        None, description="The agent or tool responsible for this item."
    )
    output_expectations: str | None = Field(
        None, description="What the expected output or result of this item should be."
    )
    created_at: float = Field(
        default_factory=time.time, description="Timestamp when the item was created."
    )
    updated_at: float = Field(
        default_factory=time.time,
        description="Timestamp when the item was last updated.",
    )


class Subtask(PlanItem):
    """A granular step within a Task."""


class Task(PlanItem):
    """A manageable unit of work, composed of subtasks."""

    subtasks: list[Subtask] = Field(
        default_factory=list, description="List of subtasks that compose this task."
    )
    effort_estimate: str | None = Field(
        None, description="Estimated effort for the task (e.g., '1h', '1d')."
    )
    priority: int | None = Field(
        None, description="Priority level, higher number means higher priority."
    )


class Epic(PlanItem):
    """A larger feature or phase, composed of tasks."""

    tasks: list[Task] = Field(
        default_factory=list, description="List of tasks that compose this epic."
    )


class AgentPlan(BaseModel):
    """The complete hierarchical plan for the agent's goal."""

    plan_id: UUID = Field(
        default_factory=uuid4, description="Unique identifier for the entire plan."
    )
    goal: str = Field(..., description="The overarching goal of the plan.")
    epics: list[Epic] = Field(
        default_factory=list, description="List of epics that compose the goal."
    )
    created_at: float = Field(
        default_factory=time.time, description="Timestamp when the plan was created."
    )
    last_updated: float = Field(
        default_factory=time.time,
        description="Timestamp when the plan was last updated.",
    )
