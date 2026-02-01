#!/usr/bin/env python3
"""
Test 9a: Generic Tool Provider

Provides a simple tool tagged with "generic-tool" for filter-based tests.
This allows test_009_context_with_filter_mesh.py to test the race condition
when filter is specified with mesh delegation.

Usage:
    meshctl start examples/prompt-template-examples/test_009_generic_tool_provider.py
"""

import mesh
from fastmcp import FastMCP
from pydantic import BaseModel, Field

app = FastMCP("GenericToolProvider")


class MemoryRecallResult(BaseModel):
    """Result from memory recall."""

    memories: list[str] = Field(default_factory=list, description="Recalled memories")
    source: str = Field(
        default="generic-tool-provider", description="Source of memories"
    )


@app.tool()
@mesh.tool(
    capability="memory_recall",
    description="Recall memories for a user (generic tool for testing)",
    tags=["generic-tool", "memory"],  # <-- Tagged for filter matching
    version="1.0.0",
)
def memory_recall(
    user_email: str,
    avatar_id: str = "test",
    limit: int = 5,
) -> MemoryRecallResult:
    """
    Recall memories for a user.

    This is a simple mock tool for testing filter-based LLM injection.
    It's tagged with "generic-tool" so test_009 can filter for it.
    """
    return MemoryRecallResult(
        memories=[
            f"Memory 1 for {user_email}",
            f"Memory 2 for {user_email}",
            "User prefers concise responses",
        ],
        source="test_009_generic_tool_provider",
    )


@mesh.agent(
    name="generic-tool-provider",
    version="1.0.0",
    description="Provides generic tools for filter-based LLM tests",
    http_port=9099,
    enable_http=True,
    auto_run=True,
)
class GenericToolProviderAgent:
    """Agent providing generic tools for testing."""

    pass


if __name__ == "__main__":
    app.run()
