from __future__ import annotations

from pathlib import Path

from vibe.collaborative import CollaborativeAgent
from vibe.collaborative.task_manager import TaskType


def main() -> None:
    # Initialize the collaborative agent
    project_root = Path(
        "/home/rowen/github-branches/vibe/mistral-vibe/examples/test_project"
    )
    project_root.mkdir(exist_ok=True)

    agent = CollaborativeAgent(project_root)

    print("=== Vibe Collaborative Framework Demo ===")
    print(f"Project Root: {project_root}")
    print(f"Models Configured: {agent.get_project_status()['models']}")
    print()

    # Start a new project
    print("Starting new project...")
    project_result = agent.start_project(
        project_name="Collaborative Demo App",
        project_description="A simple web application with user authentication and data visualization",
    )

    print(f"Project Status: {project_result['status']}")
    print(f"Development Plan: {project_result['development_plan'][:200]}...")
    print()

    # Get current project status
    status = agent.get_project_status()
    print(
        f"Current Status: {status['pending_tasks']} pending, {status['completed_tasks']} completed"
    )
    print()

    # Execute the first few tasks
    print("Executing tasks...")
    for i in range(3):
        result = agent.execute_next_task()
        if result["status"] == "completed":
            print(f"Task {i + 1} completed: {result['task_id']}")
            print(f"Result preview: {str(result['result'])[:100]}...")
        else:
            print(f"No more tasks: {result['message']}")
            break

    print()

    # Add a custom task
    print("Adding custom documentation task...")
    doc_task_id = agent.add_custom_task(
        task_type=TaskType.DOCUMENTATION,
        description="Write comprehensive API documentation for the authentication module",
        priority=2,
    )
    print(f"Added documentation task: {doc_task_id}")

    # Execute the documentation task
    doc_result = agent.execute_next_task()
    if doc_result["status"] == "completed":
        print("Documentation task completed!")
        print(f"Documentation preview: {str(doc_result['result'])[:150]}...")

    print()

    # Get collaboration summary
    summary = agent.get_collaboration_summary()
    print("=== Collaboration Summary ===")
    print(f"Project: {summary['project']['project_name']}")
    print(f"Total Tasks: {summary['collaboration_stats']['total_tasks']}")
    print(f"Completed: {summary['collaboration_stats']['completed_tasks']}")
    print(f"Planner Tasks: {summary['collaboration_stats']['planner_tasks']}")
    print(f"Implementer Tasks: {summary['collaboration_stats']['implementer_tasks']}")
    print(f"Models Used: {summary['models_used']}")

    print("\nDemo completed successfully!")


if __name__ == "__main__":
    main()
