"""Collaborative Framework for Multi-Model Development.

This module implements a collaborative system with flexible model configuration:

Operating Modes:
1. Fully Local: All models via Ollama (set VIBE_PLANNING_MODEL)
2. Hybrid: Devstral for planning, local for implementation (default)
3. Single Model: One local model for all implementation tasks

Environment Variables:

Planning Model (Optional - enables fully local mode):
- VIBE_PLANNING_MODEL: Local model for planning (e.g., "qwen2.5-coder:32b")
  If not set: Uses Devstral via Mistral API (default)

Implementation Models (Recommended for multi-model):
- VIBE_CODE_MODEL: For code implementation (e.g., "deepseek-coder-v2:latest")
- VIBE_REVIEW_MODEL: For code review (e.g., "qwq:latest")
- VIBE_DOCS_MODEL: For documentation and git (e.g., "llama3.2:latest")

Fallback (Single Model Mode):
- VIBE_LOCAL_MODEL: One model for all implementation tasks

Configuration:
- VIBE_OLLAMA_ENDPOINT: Custom Ollama endpoint (default: http://localhost:11434)

Models are loaded on-demand by Ollama, so you can configure multiple without
loading them all at once. Collaborative mode auto-enables when any model is set.
"""

from __future__ import annotations

from vibe.collaborative.collaborative_agent import CollaborativeAgent
from vibe.collaborative.collaborative_router import CollaborativeRouter
from vibe.collaborative.model_coordinator import ModelCoordinator
from vibe.collaborative.ollama_detector import (
    OllamaStatus,
    check_ollama_availability,
    get_local_model_from_env,
    get_planning_model,
    is_fully_local_mode,
    should_enable_collaborative_mode,
)
from vibe.collaborative.ollama_manager import (
    cleanup_ollama,
    ensure_ollama_running,
    get_ollama_manager,
)
from vibe.collaborative.planning_model_config import (
    configure_planning_model,
    get_planning_model_status,
)
from vibe.collaborative.task_manager import TaskManager
from vibe.collaborative.vibe_integration import CollaborativeVibeIntegration

__all__ = [
    "CollaborativeAgent",
    "CollaborativeRouter",
    "CollaborativeVibeIntegration",
    "ModelCoordinator",
    "OllamaStatus",
    "TaskManager",
    "check_ollama_availability",
    "cleanup_ollama",
    "configure_planning_model",
    "ensure_ollama_running",
    "get_local_model_from_env",
    "get_ollama_manager",
    "get_planning_model",
    "get_planning_model_status",
    "is_fully_local_mode",
    "should_enable_collaborative_mode",
]
