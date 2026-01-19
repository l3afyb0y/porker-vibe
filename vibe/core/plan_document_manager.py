"""Manages the project's PLAN.md file for high-level goals and milestones."""

from __future__ import annotations

from pathlib import Path


class PlanDocumentManager:
    """Manages PLAN.md - a markdown file containing the project's high-level plan.

    This is different from PlanManager which handles structured hierarchical plans.
    PLAN.md is a human-readable document that guides the agent's work.
    """

    def __init__(self, project_path: Path) -> None:
        self.project_path = project_path
        self._plan_file_path = project_path / "PLAN.md"

    @property
    def exists(self) -> bool:
        """Check if PLAN.md exists."""
        return self._plan_file_path.exists()

    def read(self) -> str | None:
        """Read the contents of PLAN.md."""
        if not self.exists:
            return None

        try:
            return self._plan_file_path.read_text(encoding="utf-8")
        except OSError:
            return None

    def write(self, content: str) -> None:
        """Write content to PLAN.md."""
        self._plan_file_path.write_text(content, encoding="utf-8")

    def ensure_initialized(self) -> None:
        """Ensure PLAN.md exists with a basic template if it doesn't."""
        if self.exists:
            return

        template = """# Project Plan

## Current Status
Work in progress.

## Architecture
To be documented.

## Milestones
- [ ] Initial setup

## Current Blockers
None.

## Next Steps
1. Define project goals
2. Create initial architecture
"""
        self.write(template)

    def extract_next_steps(self) -> list[str]:
        """Extract the 'Next Steps' section from PLAN.md as a list of step descriptions."""
        content = self.read()
        if not content:
            return []

        lines = content.split("\n")
        in_next_steps = False
        steps = []

        for line in lines:
            line_stripped = line.strip()

            if line_stripped.startswith("## Next Steps"):
                in_next_steps = True
                continue

            if in_next_steps and line_stripped.startswith("##"):
                break

            if in_next_steps:
                step = self._parse_list_item(line_stripped)
                if step:
                    steps.append(step)

        return steps

    def _parse_list_item(self, line: str) -> str | None:
        """Parse a markdown list item, removing markers and checkboxes."""
        list_markers = ("-", "*", "1.", "2.", "3.", "4.", "5.", "6.", "7.", "8.", "9.")

        if not line.startswith(list_markers):
            return None

        step = line
        # Remove markdown checkbox
        step = step.replace("[ ]", "").replace("[x]", "")

        # Remove list markers
        for marker in list_markers:
            if step.startswith(marker):
                step = step[len(marker) :].strip()
                break

        return step if step else None
