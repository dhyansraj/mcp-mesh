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

    provider: Optional[dict[str, Any]] = None
    """LLM provider filter (mesh delegation).
       Format: {"capability": "llm", "tags": ["+claude"], "version": ">=1.0.0"}"""

    model: Optional[str] = None
    """Optional model override sent to the provider (e.g., "anthropic/claude-haiku-4").
       When set, the consumer requests this specific model from the provider; otherwise
       the provider uses its decorator-time default."""

    max_iterations: Optional[int] = None
    """Maximum iterations for the agentic loop.

       ``None`` means "not explicitly configured" (issue #1356): the consumer's
       own loop uses ``effective_max_iterations`` (10), and nothing is forwarded
       to the provider so the provider's own MESH_LLM_MAX_ITERATIONS / default
       applies. Any non-None value is treated as an explicit user setting and IS
       forwarded on the wire."""

    system_prompt: Optional[str] = None
    """Optional system prompt to prepend to all interactions"""

    output_mode: Optional[str] = None
    """Output mode override: 'strict', 'hint', or 'text'. If None, auto-detected by handler."""

    @property
    def effective_max_iterations(self) -> int:
        """Iteration cap for the consumer's own loop (default 10 when unset)."""
        return self.max_iterations if self.max_iterations is not None else 10

    @property
    def max_iterations_explicit(self) -> bool:
        """True when a cap was explicitly configured (decorator arg or env)."""
        return self.max_iterations is not None

    def __post_init__(self):
        """Validate configuration after initialization."""
        if self.max_iterations is not None and self.max_iterations < 1:
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
