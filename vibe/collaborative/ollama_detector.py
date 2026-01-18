"""
Ollama Detection and Configuration for Collaborative Mode

This module handles automatic detection of Ollama availability
and configuration based on environment variables.

Supports multiple specialized models:
- VIBE_CODE_MODEL: For code implementation (default: deepseek-coder-v2:latest)
- VIBE_REVIEW_MODEL: For code review (default: qwq:latest)
- VIBE_DOCS_MODEL: For documentation and git control (default: llama3.2:latest)
- VIBE_LOCAL_MODEL: Fallback for all tasks if specific models not set
"""

import os
import requests
from typing import Optional, Tuple, Dict
from dataclasses import dataclass
from enum import StrEnum, auto


class ModelRole(StrEnum):
    """Specialized model roles for different task types."""
    PLANNING = auto()  # Planning and coordination (normally Devstral)
    CODE = auto()      # Code implementation
    REVIEW = auto()    # Code review
    DOCS = auto()      # Documentation and git


@dataclass
class OllamaStatus:
    """Status information about Ollama availability."""
    available: bool
    endpoint: str
    local_model: Optional[str]
    error_message: Optional[str] = None


DEFAULT_OLLAMA_ENDPOINT = "http://localhost:11434"
OLLAMA_API_GENERATE = "/api/generate"
OLLAMA_API_TAGS = "/api/tags"

# Default models for each role
DEFAULT_MODELS = {
    ModelRole.PLANNING: None,  # Default to Devstral via Mistral API
    ModelRole.CODE: "deepseek-coder-v2:latest",
    ModelRole.REVIEW: "qwq:latest",
    ModelRole.DOCS: "llama3.2:latest",
}


def get_local_model_from_env() -> Optional[str]:
    """
    Get the local model name from VIBE_LOCAL_MODEL environment variable.
    This is the fallback if specific role models aren't set.

    Returns:
        The model name if set, None otherwise.
    """
    return os.environ.get("VIBE_LOCAL_MODEL")


def get_model_for_role(role: ModelRole) -> Optional[str]:
    """
    Get the configured model for a specific role.

    Checks environment variables in this order:
    1. VIBE_{ROLE}_MODEL (e.g., VIBE_CODE_MODEL)
    2. VIBE_LOCAL_MODEL (fallback)
    3. None if neither is set

    Args:
        role: The model role (CODE, REVIEW, or DOCS)

    Returns:
        The model name for this role, or None if not configured
    """
    # Check role-specific env var
    role_env_var = f"VIBE_{role.value.upper()}_MODEL"
    role_model = os.environ.get(role_env_var)
    if role_model:
        return role_model

    # Fallback to VIBE_LOCAL_MODEL
    return get_local_model_from_env()


def get_all_configured_models() -> Dict[ModelRole, Optional[str]]:
    """
    Get all configured models for each role.

    Returns:
        Dictionary mapping roles to their configured models
    """
    return {
        ModelRole.PLANNING: get_model_for_role(ModelRole.PLANNING),
        ModelRole.CODE: get_model_for_role(ModelRole.CODE),
        ModelRole.REVIEW: get_model_for_role(ModelRole.REVIEW),
        ModelRole.DOCS: get_model_for_role(ModelRole.DOCS),
    }


def get_planning_model() -> Optional[str]:
    """
    Get the planning model from VIBE_PLANNING_MODEL environment variable.

    Returns None if not set, which means use Devstral via Mistral API (default).
    Does NOT fall back to VIBE_LOCAL_MODEL.

    Returns:
        The planning model name if set, None for Devstral default
    """
    return os.environ.get("VIBE_PLANNING_MODEL")


def is_fully_local_mode() -> bool:
    """
    Check if running in fully local mode (no Mistral API needed).

    Returns:
        True if VIBE_PLANNING_MODEL is set (all models via Ollama)
    """
    return get_planning_model() is not None


def get_ollama_endpoint() -> str:
    """
    Get the Ollama endpoint, allowing override via environment variable.

    Returns:
        The Ollama API endpoint URL.
    """
    return os.environ.get("VIBE_OLLAMA_ENDPOINT", DEFAULT_OLLAMA_ENDPOINT)


def check_ollama_availability(timeout: float = 2.0) -> OllamaStatus:
    """
    Check if Ollama is running and available.

    Args:
        timeout: Request timeout in seconds.

    Returns:
        OllamaStatus with availability information.
    """
    endpoint = get_ollama_endpoint()
    local_model = get_local_model_from_env()

    try:
        # Try to hit the Ollama API tags endpoint to check if it's running
        response = requests.get(
            f"{endpoint}{OLLAMA_API_TAGS}",
            timeout=timeout
        )
        response.raise_for_status()

        # Ollama is running - check if the requested model is available
        if local_model:
            models_data = response.json()
            available_models = [m.get("name", "") for m in models_data.get("models", [])]

            # Check if the model is available (with or without tag)
            model_found = any(
                local_model.lower() in m.lower() or m.lower().startswith(local_model.lower().split(":")[0])
                for m in available_models
            )

            if not model_found:
                return OllamaStatus(
                    available=True,
                    endpoint=endpoint,
                    local_model=local_model,
                    error_message=f"Model '{local_model}' not found. Available: {', '.join(available_models[:5])}"
                )

        return OllamaStatus(
            available=True,
            endpoint=endpoint,
            local_model=local_model
        )

    except requests.exceptions.ConnectionError:
        return OllamaStatus(
            available=False,
            endpoint=endpoint,
            local_model=local_model,
            error_message="Ollama is not running. Start with 'ollama serve'"
        )
    except requests.exceptions.Timeout:
        return OllamaStatus(
            available=False,
            endpoint=endpoint,
            local_model=local_model,
            error_message="Ollama connection timed out"
        )
    except requests.exceptions.RequestException as e:
        return OllamaStatus(
            available=False,
            endpoint=endpoint,
            local_model=local_model,
            error_message=f"Ollama connection error: {str(e)}"
        )


def should_enable_collaborative_mode() -> Tuple[bool, Optional[str]]:
    """
    Determine if collaborative mode should be auto-enabled.

    Collaborative mode is auto-enabled when:
    1. Any VIBE model env var is set (VIBE_LOCAL_MODEL, VIBE_CODE_MODEL, etc.), AND
    2. Ollama is available

    Returns:
        Tuple of (should_enable, reason_message)
    """
    # Check if any model is configured
    configured_models = get_all_configured_models()
    has_any_model = any(model is not None for model in configured_models.values())

    if not has_any_model:
        return False, None

    status = check_ollama_availability()

    if status.available:
        # Count how many specialized models are configured
        model_count = sum(1 for m in configured_models.values() if m is not None)
        if model_count == 1:
            # Single model mode
            model_name = next(m for m in configured_models.values() if m is not None)
            return True, f"Local model '{model_name}' detected via Ollama"
        else:
            # Multi-model mode
            return True, f"Multi-model collaboration enabled ({model_count} models configured)"
    else:
        return False, status.error_message


def get_ollama_generate_endpoint() -> str:
    """Get the full Ollama generate API endpoint."""
    return f"{get_ollama_endpoint()}{OLLAMA_API_GENERATE}"
