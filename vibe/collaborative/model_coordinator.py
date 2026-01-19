"""Model Coordinator for Dual-Model Collaboration.

Handles communication and coordination between Devstral-2 and a local model via Ollama.
Supports VIBE_LOCAL_MODEL environment variable for seamless configuration.
"""

from __future__ import annotations

from datetime import datetime
import json
from logging import getLogger
import os
from pathlib import Path
from typing import Any

import requests

from vibe.collaborative.ollama_detector import (
    OllamaStatus,
    check_ollama_availability,
    get_local_model_from_env,
    get_ollama_generate_endpoint,
)
from vibe.collaborative.prompts import (
    DOCS_SYSTEM_PROMPT,
    IMPLEMENTER_SYSTEM_PROMPT,
    PLANNER_SYSTEM_PROMPT,
    REVIEWER_SYSTEM_PROMPT,
)
from vibe.collaborative.task_manager import (
    CollaborativeTask,
    ModelRole,
    TaskManager,
    TaskStatus,
    TaskType,
)

logger = getLogger(__name__)


class ModelConfig:
    """Configuration for a model endpoint."""

    def __init__(
        self, model_name: str, endpoint: str, api_key: str | None = None
    ) -> None:
        self.model_name = model_name
        self.endpoint = endpoint
        self.api_key = api_key
        self.headers = {"Content-Type": "application/json"}
        if api_key:
            self.headers["Authorization"] = f"Bearer {api_key}"


class ModelCoordinator:
    """Coordinates communication between multiple models."""

    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root
        self.task_manager = TaskManager(project_root)
        self.models: dict[ModelRole, ModelConfig] = {}
        self.config_file = project_root / ".vibe" / "model_config.json"

        # Load or create default configuration
        self._load_or_create_config()

    def _load_or_create_config(self) -> None:
        """Load existing config or create default configuration."""
        if self.config_file.exists():
            try:
                with open(self.config_file) as f:
                    config_data = json.load(f)
                    for role_name, model_config in config_data.items():
                        role = ModelRole(role_name)
                        self.models[role] = ModelConfig(
                            model_name=model_config["model_name"],
                            endpoint=model_config["endpoint"],
                            api_key=model_config.get("api_key"),
                        )
            except (json.JSONDecodeError, KeyError) as e:
                logger.warning("Could not load model config: %s", e)
                self._create_default_config()
        else:
            self._create_default_config()

    def _create_default_config(self) -> None:
        """Create default model configuration.

        Uses VIBE_LOCAL_MODEL environment variable if set for the implementer model.
        """
        # Check for local model from environment variable
        local_model = get_local_model_from_env()
        ollama_endpoint = get_ollama_generate_endpoint()

        # Use environment variable model if set, otherwise use default
        implementer_model = local_model if local_model else "deepseek-coder-v2"

        # Load other roles from env or defaults
        reviewer_model = os.getenv("VIBE_REVIEW_MODEL", "qwq")
        docs_model = os.getenv("VIBE_DOCS_MODEL", "llama3.2")

        # Default configuration for local Ollama setup
        default_config = {
            ModelRole.PLANNER.value: {
                "model_name": "devstral-2",
                "endpoint": "http://localhost:11434/api/generate",
                "api_key": None,
            },
            ModelRole.IMPLEMENTER.value: {
                "model_name": implementer_model,
                "endpoint": ollama_endpoint,
                "api_key": None,
            },
            ModelRole.REVIEWER.value: {
                "model_name": reviewer_model,
                "endpoint": ollama_endpoint,
                "api_key": None,
            },
            ModelRole.DOCS.value: {
                "model_name": docs_model,
                "endpoint": ollama_endpoint,
                "api_key": None,
            },
        }

        # Save the configuration
        try:
            with open(self.config_file, "w") as f:
                json.dump(default_config, f, indent=2)
        except OSError as e:
            logger.warning(
                "Could not save default model config to %s: %s", self.config_file, e
            )

        # Load the configuration into memory
        for role_name, model_config in default_config.items():
            role = ModelRole(role_name)
            self.models[role] = ModelConfig(
                model_name=model_config["model_name"],
                endpoint=model_config["endpoint"],
                api_key=model_config.get("api_key"),
            )

    def update_model_config(
        self,
        role: ModelRole,
        model_name: str,
        endpoint: str,
        api_key: str | None = None,
    ) -> None:
        """Update configuration for a specific model role."""
        self.models[role] = ModelConfig(model_name, endpoint, api_key)

        # Save the updated configuration
        config_data: dict[str, dict[str, str | None]] = {}
        for model_role, model_config in self.models.items():
            config_data[model_role.value] = {
                "model_name": model_config.model_name,
                "endpoint": model_config.endpoint,
                "api_key": model_config.api_key,
            }

        try:
            with open(self.config_file, "w") as f:
                json.dump(config_data, f, indent=2)
        except OSError as e:
            logger.warning("Could not save model config to %s: %s", self.config_file, e)

    def query_model(
        self,
        role: ModelRole,
        prompt: str,
        context: dict | None = None,
        system_prompt: str | None = None,
    ) -> str:
        """Query a specific model with a prompt."""
        if role not in self.models:
            raise ValueError(f"No model configured for role: {role}")

        model_config = self.models[role]

        # Prepare the payload based on the endpoint type
        if "ollama" in model_config.endpoint:
            # Ollama API format
            payload = {
                "model": model_config.model_name,
                "prompt": prompt,
                "stream": False,
            }
            if context:
                payload["context"] = context
            if system_prompt:
                payload["system"] = system_prompt
        else:
            # Generic LLM API format
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})

            payload = {
                "model": model_config.model_name,
                "messages": messages,
                "temperature": 0.7,
            }

        try:
            response = requests.post(
                model_config.endpoint,
                headers=model_config.headers,
                json=payload,
                timeout=30,
            )
            response.raise_for_status()

            if "ollama" in model_config.endpoint:
                return response.json()["response"]
            else:
                return response.json()["choices"][0]["message"]["content"]

        except requests.RequestException as e:
            logger.warning("Error querying %s model: %s", role.value, e)
            return f"Error: Could not query {role.value} model - {e!s}"

    def start_collaborative_session(
        self, project_description: str
    ) -> list[dict[str, Any]] | str:
        """Start a new collaborative development session by generating a plan.

        Returns the generated plan as a parsed Python object.
        """
        # Step 1: Create planning task for Devstral-2
        self.task_manager.create_task(
            task_type=TaskType.PLANNING,
            description=f"Create development plan for: {project_description}",
            priority=1,
        )

        # Step 2: Auto-assign tasks (specifically, the planning task)
        self.task_manager.auto_assign_tasks()

        # Step 3: Get the planning task
        next_task_result = self.task_manager.get_next_task()
        if not next_task_result:
            return "No planning tasks available for execution."

        task_id, planning_task = next_task_result

        # Step 4: Execute the planning task
        if planning_task.assigned_to == ModelRole.PLANNER:
            plan_json_str = self._execute_planning_task(planning_task.description)
            self.task_manager.complete_task(task_id)  # Mark planning task as complete

            try:
                # Parse the plan JSON and return it
                plan_data = json.loads(plan_json_str)
                # Basic validation for plan structure
                if (
                    not isinstance(plan_data, dict)
                    or "tasks" not in plan_data
                    or not isinstance(plan_data["tasks"], list)
                ):
                    logger.warning(
                        "Generated plan does not have expected 'tasks' list. Returning raw JSON."
                    )
                    return plan_json_str

                # Check for "name" and "task_type" in each task, required for start_ralph_loop
                for task in plan_data["tasks"]:
                    if (
                        not isinstance(task, dict)
                        or "name" not in task
                        or "task_type" not in task
                    ):
                        logger.warning(
                            "Generated plan task missing 'name' or 'task_type'. Returning raw JSON."
                        )
                        return plan_json_str

                return plan_data["tasks"]  # Return the list of tasks from the plan
            except json.JSONDecodeError as e:
                logger.warning("Error parsing plan JSON from planner: %s", e)
                return plan_json_str  # Return raw JSON if parsing fails

        return "No planning tasks available for execution."

    def _execute_planning_task(self, task_description: str) -> str:
        """Execute a planning task using the planner model."""
        prompt = f"""You are an expert software architect. Please create a comprehensive development plan for the following project:

{task_description}

Your plan should include:
1. Overall architecture and components
2. Detailed task breakdown
3. Dependencies between tasks
4. Estimated priorities
5. Any technical considerations or challenges

Please provide the plan in JSON format with the following structure:
{{
  "project_name": "string",
  "architecture": "string",
  "tasks": [
    {{
      "name": "string",
      "type": "PLANNING|ARCHITECTURE|CODE_IMPLEMENTATION|DOCUMENTATION|CODE_REVIEW|REFACTORING|TESTING|MAINTENANCE|REPOSITORY_HYGIENE",
      "description": "string",
      "priority": 1-5,
      "dependencies": ["task_names"]
    }}
  ],
  "technical_considerations": "string"
}}"""

        plan_json = self.query_model(
            ModelRole.PLANNER, prompt, system_prompt=PLANNER_SYSTEM_PROMPT
        )

        return plan_json

    def _create_implementation_tasks_from_plan(self, plan_json: str) -> None:
        """Create implementation tasks based on a development plan."""
        try:
            plan = json.loads(plan_json)

            task_name_to_id: dict[str, str] = {}
            dependency_names_by_task: dict[str, list[str]] = {}

            # Create a task for each item in the plan
            for task_info in plan.get("tasks", []):
                task_type = TaskType[task_info["type"]]
                task_description = task_info["description"]
                priority = task_info.get("priority", 3)

                task_id = self.task_manager.create_task(
                    task_type=task_type,
                    description=task_description,
                    priority=priority,
                    dependencies=[],
                )

                task_name = task_info.get("name")
                if task_name:
                    task_name_to_id[task_name] = task_id

                raw_dependencies = task_info.get("dependencies") or []
                dependency_names_by_task[task_id] = [
                    dep for dep in raw_dependencies if isinstance(dep, str)
                ]

            for task_id, dependency_names in dependency_names_by_task.items():
                resolved_dependencies = [
                    task_name_to_id[name]
                    for name in dependency_names
                    if name in task_name_to_id
                ]
                if resolved_dependencies:
                    self.task_manager.set_task_dependencies(
                        task_id, resolved_dependencies
                    )

            # Auto-assign the new tasks after dependencies are wired up
            self.task_manager.auto_assign_tasks()

        except json.JSONDecodeError as e:
            logger.warning("Error parsing plan JSON: %s", e)

    def execute_next_task(self) -> tuple[str | None, str | None]:
        """Execute the next available task in the queue."""
        task_result = self.task_manager.get_next_task()

        if not task_result:
            return None, "No tasks available"

        task_id, task = task_result
        return self.execute_task(task_id)

    def execute_task(self, task_id: str) -> tuple[str, str]:
        """Execute a specific task by ID."""
        if task_id not in self.task_manager.tasks:
            return task_id, f"Task {task_id} not found"

        task = self.task_manager.tasks[task_id]
        task_output = None  # Initialize task_output

        # Set task status to IN_PROGRESS
        # Use a lock-safe update if possible, but accessing task object directly
        # and saving relies on TaskManager's internal lock now?
        # No, TaskManager methods are locked, but direct property access isn't.
        # We should use a method to update status or accept that we update the object and call _save_tasks (which is locked).
        # But _save_tasks iterates *all* tasks. If we modify one here, and another thread modifies another one...
        # Python dicts are thread-safe for single ops, but we need atomic update.
        # Ideally TaskManager should expose update_task_status(tid, status).
        # For now, let's assume single-writer per task due to assignment.

        task.status = TaskStatus.IN_PROGRESS
        task.updated_at = datetime.now()
        self.task_manager._save_tasks()  # This is locked!

        try:
            if task.assigned_to == ModelRole.PLANNER:
                # Planning/architecture/review task
                task_output = self._execute_planner_task(task)
            elif task.assigned_to == ModelRole.IMPLEMENTER:
                # Implementation task
                task_output = self._execute_implementer_task(task)
            elif task.assigned_to == ModelRole.REVIEWER:
                # Review task
                task_output = self._execute_reviewer_task(task)
            elif task.assigned_to == ModelRole.DOCS:
                # Documentation/Hygiene task
                task_output = self._execute_docs_task(task)
            else:
                raise ValueError("Task not assigned to any model")

            # After model execution, perform verification
            if self._verify_task_completion(task, task_output):
                self.task_manager.complete_task(task_id)
                return task_id, task_output
            else:
                self.task_manager.tasks[task_id].status = TaskStatus.DEBUGGING
                self.task_manager.tasks[task_id].updated_at = datetime.now()
                self.task_manager._save_tasks()  # Save updated status
                return (
                    task_id,
                    f"Verification failed. Task set to DEBUGGING. Output: {task_output}",
                )

        except Exception as e:
            logger.error("Error executing task %s: %s", task_id, e)
            self.task_manager.tasks[task_id].status = TaskStatus.DEBUGGING
            self.task_manager.tasks[task_id].updated_at = datetime.now()
            self.task_manager._save_tasks()  # Save updated status
            return task_id, f"Task execution failed. Set to DEBUGGING. Error: {e}"

    def _execute_planner_task(self, task: CollaborativeTask) -> str:
        """Execute a task assigned to the planner model."""
        prompt = self._create_task_prompt(task)
        return self.query_model(
            ModelRole.PLANNER, prompt, system_prompt=PLANNER_SYSTEM_PROMPT
        )

    def _execute_implementer_task(self, task: CollaborativeTask) -> str:
        """Execute a task assigned to the implementer model."""
        prompt = self._create_task_prompt(task)
        return self.query_model(
            ModelRole.IMPLEMENTER, prompt, system_prompt=IMPLEMENTER_SYSTEM_PROMPT
        )

    def _execute_reviewer_task(self, task: CollaborativeTask) -> str:
        """Execute a task assigned to the reviewer model."""
        prompt = self._create_task_prompt(task)
        return self.query_model(
            ModelRole.REVIEWER, prompt, system_prompt=REVIEWER_SYSTEM_PROMPT
        )

    def _execute_docs_task(self, task: CollaborativeTask) -> str:
        """Execute a task assigned to the docs model."""
        prompt = self._create_task_prompt(task)
        return self.query_model(
            ModelRole.DOCS, prompt, system_prompt=DOCS_SYSTEM_PROMPT
        )

    def _create_task_prompt(self, task: CollaborativeTask) -> str:
        """Create a prompt for executing a specific task."""
        base_prompt = f"""Task: {task.description}

Task Type: {task.task_type.name}
Priority: {task.priority}
"""

        if task.dependencies:
            base_prompt += f"\nDependencies: {', '.join(task.dependencies)}"

        base_prompt += "\n\nPlease complete this task:"

        # Add task-specific instructions
        if task.task_type == TaskType.CODE_IMPLEMENTATION:
            base_prompt += "\n\nWrite clean, well-documented code. Follow best practices and include appropriate tests."
        elif task.task_type == TaskType.DOCUMENTATION:
            base_prompt += "\n\nWrite comprehensive documentation. Include examples, usage instructions, and technical details."
        elif task.task_type == TaskType.CODE_REVIEW:
            base_prompt += "\n\nPerform a thorough code review. Check for bugs, security issues, performance problems, and adherence to best practices."

        return base_prompt

    def _verify_task_completion(
        self, task: CollaborativeTask, task_output: str
    ) -> bool:
        """Verify if a task has been successfully completed.

        This is a placeholder for actual verification logic (e.g., running tests, lints).
        """
        logger.info(f"Verifying task {task.task_id} of type {task.task_type.name}...")
        # TODO: Implement actual verification logic based on task type
        # For now, assume successful completion
        return True

    def get_project_status(self) -> dict:
        """Get the current status of the collaborative project."""
        return {
            "task_status": self.task_manager.get_task_status(),
            "models_configured": {
                role.value: config.model_name for role, config in self.models.items()
            },
            "pending_tasks": len(self.task_manager.task_queue),
            "completed_tasks": len(self.task_manager.completed_tasks),
        }

    def check_ollama_status(self) -> OllamaStatus:
        """Check if Ollama is available and return status."""
        return check_ollama_availability()

    def get_local_model_name(self) -> str | None:
        """Get the configured local model name from VIBE_LOCAL_MODEL."""
        return get_local_model_from_env()

    def refresh_config_from_env(self) -> None:
        """Refresh model configuration from environment variables.

        This allows dynamic reconfiguration when VIBE_LOCAL_MODEL changes.
        """
        local_model = get_local_model_from_env()
        ollama_endpoint = get_ollama_generate_endpoint()

        if local_model:
            self.update_model_config(
                ModelRole.IMPLEMENTER, local_model, ollama_endpoint
            )

        if review_model := os.getenv("VIBE_REVIEW_MODEL"):
            self.update_model_config(ModelRole.REVIEWER, review_model, ollama_endpoint)

        if docs_model := os.getenv("VIBE_DOCS_MODEL"):
            self.update_model_config(ModelRole.DOCS, docs_model, ollama_endpoint)

    def get_implementer_model_info(self) -> dict[str, object]:
        """Get information about the implementer model configuration."""
        implementer = self.models.get(ModelRole.IMPLEMENTER)
        if not implementer:
            return {"configured": False}

        return {
            "configured": True,
            "model_name": implementer.model_name,
            "endpoint": implementer.endpoint,
            "from_env": get_local_model_from_env() is not None,
        }
