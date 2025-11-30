"""
LLM configuration dataclass.

Consolidates LLM-related configuration into a single type-safe structure.
"""

from dataclasses import dataclass
from typing import Any, Dict, Optional, Union


@dataclass
class LLMConfig:
    """
    Configuration for MeshLlmAgent.

    Consolidates provider, model, and runtime settings into a single type-safe structure.
    Supports both direct LiteLLM providers (string) and mesh delegation (dict).
    """

    provider: Union[str, dict[str, Any]] = "claude"
    """LLM provider - string for direct LiteLLM (e.g., 'claude', 'openai') or dict for mesh delegation
       Mesh delegation format: {"capability": "llm", "tags": ["claude"], "version": ">=1.0.0"}"""

    model: str = "claude-3-5-sonnet-20241022"
    """Model name for the provider (only used with string provider for direct LiteLLM)"""

    api_key: str = ""
    """API key for the provider (uses environment variable if empty, only used with string provider)"""

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
        if not self.provider:
            raise ValueError("provider cannot be empty")

        # Only validate model for string providers (not needed for mesh delegation)
        if isinstance(self.provider, str) and not self.model:
            raise ValueError("model cannot be empty when using string provider")

        # Validate output_mode if provided
        if self.output_mode and self.output_mode not in ("strict", "hint", "text"):
            raise ValueError(
                f"output_mode must be 'strict', 'hint', or 'text', got '{self.output_mode}'"
            )
