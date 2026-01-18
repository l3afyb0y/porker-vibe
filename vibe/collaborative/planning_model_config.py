"""
Planning Model Configuration

Handles configuration when VIBE_PLANNING_MODEL is set to use a local
planning model via Ollama instead of Devstral via Mistral API.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from vibe.collaborative.ollama_detector import (
    get_planning_model,
    get_ollama_endpoint,
    is_fully_local_mode,
)
from vibe.core.config import ProviderConfig, ModelConfig, Backend

if TYPE_CHECKING:
    from vibe.core.config import VibeConfig


def configure_planning_model(config: "VibeConfig") -> "VibeConfig":
    """
    Configure Vibe to use a local planning model via Ollama if VIBE_PLANNING_MODEL is set.

    Args:
        config: The VibeConfig to modify

    Returns:
        Modified config with Ollama planning model configured
    """
    planning_model = get_planning_model()

    if not planning_model:
        # No local planning model configured, use default (Devstral via Mistral API)
        return config

    # Add Ollama provider if not already present
    ollama_provider_exists = any(p.name == "ollama" for p in config.providers)

    if not ollama_provider_exists:
        ollama_endpoint = get_ollama_endpoint()
        ollama_provider = ProviderConfig(
            name="ollama",
            api_base=f"{ollama_endpoint}/v1",  # Ollama has OpenAI-compatible API
            api_key_env_var="",  # Ollama doesn't require API key
            backend=Backend.GENERIC,
            api_style="openai",
        )
        config.providers.append(ollama_provider)

    # Check if planning model already exists in config
    planning_model_exists = any(
        m.alias == "planning-local" for m in config.models
    )

    if not planning_model_exists:
        # Add the planning model
        planning_model_config = ModelConfig(
            name=planning_model,
            provider="ollama",
            alias="planning-local",
            input_price=0.0,  # Local model, no cost
            output_price=0.0,
        )
        config.models.append(planning_model_config)

    # Switch active model to the local planning model
    config.active_model = "planning-local"

    return config


def get_planning_model_status() -> dict:
    """
    Get status information about planning model configuration.

    Returns:
        Dictionary with planning model status
    """
    planning_model = get_planning_model()

    return {
        "is_local": planning_model is not None,
        "model_name": planning_model,
        "fully_local_mode": is_fully_local_mode(),
        "endpoint": get_ollama_endpoint() if planning_model else None,
    }
