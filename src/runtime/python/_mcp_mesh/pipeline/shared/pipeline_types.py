"""
Core pipeline types and result containers.

Shared infrastructure used by both startup and heartbeat pipelines.
"""

import logging
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Optional


class PipelineStatus(Enum):
    """Status of pipeline execution."""

    SUCCESS = "success"
    FAILED = "failed"
    PARTIAL = "partial"
    SKIPPED = "skipped"


class PipelineResult:
    """Result container for pipeline execution."""

    def __init__(
        self,
        status: PipelineStatus = PipelineStatus.SUCCESS,
        message: str = "",
        context: Optional[dict[str, Any]] = None,
        errors: Optional[list[str]] = None,
    ):
        self.status = status
        self.message = message
        self.context = context or {}
        self.errors = errors or []
        self.timestamp = datetime.now(UTC)

    def add_error(self, error: str) -> None:
        """Add an error to the result."""
        self.errors.append(error)
        if self.status == PipelineStatus.SUCCESS:
            self.status = PipelineStatus.FAILED

    def add_context(self, key: str, value: Any) -> None:
        """Add context data to the result."""
        self.context[key] = value

    def is_success(self) -> bool:
        """Check if the result represents success."""
        return self.status == PipelineStatus.SUCCESS

    def __str__(self) -> str:
        return f"PipelineResult(status={self.status.value}, message='{self.message}', errors={len(self.errors)})"
