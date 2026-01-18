"""
Delegate to Local Model Tool

This tool allows Devstral to delegate tasks to the local model (e.g., Deepseek-Coder-v2)
for implementation, documentation, and maintenance tasks.
"""
from __future__ import annotations

from enum import StrEnum, auto
from typing import ClassVar, Optional
from pathlib import Path

from pydantic import BaseModel, Field

from vibe.core.tools.base import (
    BaseTool,
    BaseToolConfig,
    BaseToolState,
    ToolError,
    ToolPermission,
)
from vibe.core.tools.ui import ToolCallDisplay, ToolResultDisplay, ToolUIData
from vibe.core.types import ToolCallEvent, ToolResultEvent

from vibe.collaborative.ollama_detector import (
    get_local_model_from_env,
    get_ollama_endpoint,
    check_ollama_availability,
    get_model_for_role,
    get_all_configured_models,
    ModelRole as OllamaModelRole,
)


class DelegateTaskType(StrEnum):
    """Types of tasks that can be delegated to the local model."""
    CODE = auto()           # Write or modify code
    DOCUMENTATION = auto()  # Write or update documentation
    REFACTOR = auto()       # Refactor existing code
    GITIGNORE = auto()      # Update .gitignore
    CLEANUP = auto()        # Clean up project files
    TEST = auto()           # Write tests
    REVIEW = auto()         # Review existing code


# Map task types to model roles
TASK_TO_MODEL_ROLE = {
    DelegateTaskType.CODE: OllamaModelRole.CODE,
    DelegateTaskType.REFACTOR: OllamaModelRole.CODE,
    DelegateTaskType.TEST: OllamaModelRole.CODE,
    DelegateTaskType.REVIEW: OllamaModelRole.REVIEW,
    DelegateTaskType.DOCUMENTATION: OllamaModelRole.DOCS,
    DelegateTaskType.GITIGNORE: OllamaModelRole.DOCS,
    DelegateTaskType.CLEANUP: OllamaModelRole.DOCS,
}


class DelegateArgs(BaseModel):
    """Arguments for delegating a task to the local model."""
    task_type: DelegateTaskType = Field(
        description="Type of task: 'code', 'documentation', 'refactor', 'gitignore', 'cleanup', 'test', or 'review'"
    )
    instruction: str = Field(
        description="Detailed instructions for the local model to execute"
    )
    context: Optional[str] = Field(
        default=None,
        description="Additional context like file contents, requirements, or constraints"
    )
    file_path: Optional[str] = Field(
        default=None,
        description="Target file path if the task involves a specific file"
    )


class DelegateResult(BaseModel):
    """Result from the local model."""
    success: bool
    model_used: str
    task_type: str
    response: str
    file_path: Optional[str] = None


class DelegateConfig(BaseToolConfig):
    """Configuration for the delegate tool."""
    permission: ToolPermission = ToolPermission.ALWAYS
    timeout: int = 120  # seconds


class DelegateState(BaseToolState):
    """State for the delegate tool."""
    last_task_type: Optional[str] = None
    tasks_delegated: int = 0


class DelegateToLocal(
    BaseTool[DelegateArgs, DelegateResult, DelegateConfig, DelegateState],
    ToolUIData[DelegateArgs, DelegateResult],
):
    """
    Delegate implementation tasks to specialized local models.

    USE THIS TOOL for:
    - Writing new code or modifying existing code → CODE model
    - Creating or updating documentation (README, docstrings, comments) → DOCS model
    - Refactoring code for better structure → CODE model
    - Reviewing existing code for quality/issues → REVIEW model
    - Updating .gitignore files → DOCS model
    - Cleaning up project files and organization → DOCS model
    - Writing tests → CODE model

    Different task types route to different specialized models automatically.
    You (Devstral) focus on planning, architecture, and coordination.
    """

    description: ClassVar[str] = (
        "Delegate tasks to specialized local models. Routes automatically: "
        "code/refactor/tests → CODE model, "
        "docs/gitignore/cleanup → DOCS model, "
        "review → REVIEW model. "
        "You handle planning and coordination."
    )

    @classmethod
    def get_call_display(cls, event: ToolCallEvent) -> ToolCallDisplay:
        if not isinstance(event.args, DelegateArgs):
            return ToolCallDisplay(summary="Delegating task")

        args = event.args
        task_descriptions = {
            DelegateTaskType.CODE: "Writing code",
            DelegateTaskType.DOCUMENTATION: "Writing documentation",
            DelegateTaskType.REFACTOR: "Refactoring code",
            DelegateTaskType.GITIGNORE: "Updating .gitignore",
            DelegateTaskType.CLEANUP: "Cleaning up project",
            DelegateTaskType.TEST: "Writing tests",
            DelegateTaskType.REVIEW: "Reviewing code",
        }

        desc = task_descriptions.get(args.task_type, "Delegating task")

        # Get the model that will handle this task
        model_role = TASK_TO_MODEL_ROLE.get(args.task_type)
        if model_role:
            model = get_model_for_role(model_role)
            if model:
                model_short = model.split(':')[0]  # Show just model name, not tag
                desc = f"{model_short}: {desc}"

        if args.file_path:
            desc += f" ({args.file_path})"

        return ToolCallDisplay(summary=desc)

    @classmethod
    def get_result_display(cls, event: ToolResultEvent) -> ToolResultDisplay:
        if not isinstance(event.result, DelegateResult):
            return ToolResultDisplay(success=True, message="Task completed")

        result = event.result
        status = "completed" if result.success else "failed"
        return ToolResultDisplay(
            success=result.success,
            message=f"Local model ({result.model_used}) {status}: {result.task_type}"
        )

    @classmethod
    def get_status_text(cls) -> str:
        return "Delegating to local model"

    async def run(self, args: DelegateArgs) -> DelegateResult:
        import requests

        # Check Ollama availability
        status = check_ollama_availability()
        if not status.available:
            raise ToolError(
                f"Local model not available: {status.error_message}. "
                "Start Ollama with 'ollama serve'"
            )

        # Determine which model to use based on task type
        model_role = TASK_TO_MODEL_ROLE.get(args.task_type)
        if not model_role:
            raise ToolError(f"Unknown task type: {args.task_type}")

        local_model = get_model_for_role(model_role)
        if not local_model:
            # Provide helpful error message about which env var to set
            role_env_var = f"VIBE_{model_role.value.upper()}_MODEL"
            raise ToolError(
                f"No model configured for {args.task_type} tasks. "
                f"Set {role_env_var} or VIBE_LOCAL_MODEL environment variable. "
                f"Example: export {role_env_var}='deepseek-coder-v2:latest'"
            )

        # Build the prompt for the local model
        prompt = self._build_prompt(args)

        # Query the local model
        try:
            endpoint = f"{get_ollama_endpoint()}/api/generate"
            response = requests.post(
                endpoint,
                json={
                    "model": local_model,
                    "prompt": prompt,
                    "stream": False,
                },
                timeout=self.config.timeout,
            )
            response.raise_for_status()

            result_data = response.json()
            model_response = result_data.get("response", "")

            # Update state
            self.state.last_task_type = args.task_type.value
            self.state.tasks_delegated += 1

            return DelegateResult(
                success=True,
                model_used=local_model,
                task_type=args.task_type.value,
                response=model_response,
                file_path=args.file_path,
            )

        except requests.exceptions.Timeout:
            raise ToolError(
                f"Local model timed out after {self.config.timeout} seconds. "
                "The task may be too complex or the model may be slow."
            )
        except requests.exceptions.RequestException as e:
            raise ToolError(f"Failed to communicate with local model: {str(e)}")

    def _build_prompt(self, args: DelegateArgs) -> str:
        """Build a detailed prompt for the local model."""

        task_instructions = {
            DelegateTaskType.CODE: (
                "You are a code implementation specialist. Write clean, efficient, "
                "well-documented code. Follow best practices and include appropriate "
                "error handling."
            ),
            DelegateTaskType.DOCUMENTATION: (
                "You are a documentation specialist. Write clear, comprehensive "
                "documentation. Include examples, usage instructions, and explain "
                "the purpose and behavior."
            ),
            DelegateTaskType.REFACTOR: (
                "You are a refactoring specialist. Improve code structure, readability, "
                "and maintainability while preserving functionality. Explain your changes."
            ),
            DelegateTaskType.REVIEW: (
                "You are a code review specialist. Analyze the code for bugs, "
                "security issues, performance problems, readability, and adherence "
                "to best practices. Provide specific, actionable feedback."
            ),
            DelegateTaskType.GITIGNORE: (
                "You are a repository hygiene specialist. Update the .gitignore file "
                "appropriately. Include common patterns for the project type and any "
                "specific files that should be ignored."
            ),
            DelegateTaskType.CLEANUP: (
                "You are a project organization specialist. Help clean up and organize "
                "project files. Suggest removals, reorganizations, and improvements."
            ),
            DelegateTaskType.TEST: (
                "You are a testing specialist. Write comprehensive tests with good "
                "coverage. Include edge cases, error conditions, and clear test names."
            ),
        }

        role_instruction = task_instructions.get(
            args.task_type,
            "You are a helpful coding assistant."
        )

        prompt_parts = [
            role_instruction,
            "",
            "## Task",
            args.instruction,
        ]

        if args.file_path:
            prompt_parts.extend([
                "",
                f"## Target File: {args.file_path}",
            ])

        if args.context:
            prompt_parts.extend([
                "",
                "## Context",
                args.context,
            ])

        prompt_parts.extend([
            "",
            "## Instructions",
            "- Provide the complete solution",
            "- If writing code, include the full file content",
            "- If updating a file, show the complete updated version",
            "- Explain your approach briefly",
        ])

        return "\n".join(prompt_parts)
