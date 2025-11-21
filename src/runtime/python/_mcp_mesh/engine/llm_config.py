"""
LLM configuration dataclass.

Consolidates LLM-related configuration into a single type-safe structure.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class LLMConfig:
    """
    Configuration for MeshLlmAgent.

    Consolidates provider, model, and runtime settings into a single type-safe structure.
    """

    provider: str = "claude"
    """LLM provider (e.g., 'claude', 'openai', 'gemini')"""

    model: str = "claude-3-5-sonnet-20241022"
    """Model name for the provider"""

    api_key: str = ""
    """API key for the provider (uses environment variable if empty)"""

    max_iterations: int = 10
    """Maximum iterations for the agentic loop"""

    system_prompt: Optional[str] = None
    """Optional system prompt to prepend to all interactions"""

    def __post_init__(self):
        """Validate configuration after initialization."""
        if self.max_iterations < 1:
            raise ValueError("max_iterations must be >= 1")
        if not self.provider:
            raise ValueError("provider cannot be empty")
        if not self.model:
            raise ValueError("model cannot be empty")
