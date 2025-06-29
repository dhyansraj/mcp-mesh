"""
Abstract base class for pipeline steps.

Shared base class used by both startup and heartbeat pipeline steps.
"""

import logging
from abc import ABC, abstractmethod
from typing import Any

from .pipeline_types import PipelineResult


class PipelineStep(ABC):
    """
    Abstract base class for pipeline steps.

    Each step performs a specific operation and can access/modify
    the shared pipeline context.
    """

    def __init__(self, name: str, required: bool = True, description: str = ""):
        self.name = name
        self.required = required
        self.description = description
        self.logger = logging.getLogger(f"{__name__}.{name}")

    @abstractmethod
    async def execute(self, context: dict[str, Any]) -> PipelineResult:
        """
        Execute this pipeline step.

        Args:
            context: Shared pipeline context that can be read/modified

        Returns:
            Result of step execution
        """
        pass

    def __str__(self) -> str:
        return f"PipelineStep(name='{self.name}', required={self.required})"
