"""
LLM configuration dataclass.

Consolidates LLM-related configuration into a single type-safe structure.
"""

from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class LLMConfig:
    """
    Configuration for MeshLlmAgent.

    Consolidates provider, model, and runtime settings into a single type-safe structure.
    Mesh-delegated only: provider must be a dict describing the upstream
    @mesh.llm_provider to bind against.
    """

    provider: dict[str, Any] = None
    """LLM provider filter (mesh delegation).
       Format: {"capability": "llm", "tags": ["claude"], "version": ">=1.0.0"}"""

    model: Optional[str] = None
    """Optional model override sent to the provider (e.g., "anthropic/claude-haiku-4").
       When set, the consumer requests this specific model from the provider; otherwise
       the provider uses its decorator-time default."""

    max_iterations: int = 10
    """Maximum iterations for the agentic loop"""

    system_prompt: Optional[str] = None
    """Optional system prompt to prepend to all interactions"""

    output_mode: Optional[str] = None
    """Output mode override: 'strict', 'hint', or 'text'. If None, auto-detected by handler."""

    def __post_init__(self):
        """Validate configuration after initialization."""
        if self.max_iterations < 1:
            raise ValueError("max_iterations must be >= 1")
        if self.provider is None:
            raise ValueError("provider cannot be empty")
        if not isinstance(self.provider, dict):
            raise TypeError(
                f"provider must be a dict for mesh delegation (got {type(self.provider).__name__}). "
                f"Direct LLM mode was removed in v2; use @mesh.llm(provider={{'capability': 'llm', 'tags': [...]}})."
            )

        # Validate output_mode if provided
        if self.output_mode and self.output_mode not in ("strict", "hint", "text"):
            raise ValueError(
                f"output_mode must be 'strict', 'hint', or 'text', got '{self.output_mode}'"
            )
