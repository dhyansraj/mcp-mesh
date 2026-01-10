#!/usr/bin/env python3
"""
LLM Agent with Dependencies Example

Demonstrates an agent that has BOTH:
- Static dependencies via @mesh.tool(dependencies=[...])
- LLM provider via @mesh.llm(provider={...})

This tests that meshctl status shows both Dependencies AND LLM Providers sections.
"""

import mesh
from fastmcp import FastMCP
from pydantic import BaseModel

app = FastMCP("LLM With Deps Agent")


class AnalysisResponse(BaseModel):
    """Response from analysis tasks."""

    summary: str
    timestamp: str
    system_info: str
    status: str = "success"


@app.tool()
@mesh.llm(
    # Filter for multiple tools - will resolve ALL matching tools
    filter=[
        {"capability": "time_service"},  # Time-related tools
        {"capability": "info"},  # System info tools
        {"capability": "math_service"},  # Math tools
    ],
    filter_mode="all",  # Return ALL matching tools, not just best match
    provider={
        "capability": "llm",
        "tags": ["llm", "+openai"],  # Prefer OpenAI provider
    },
    max_iterations=5,
    system_prompt="You are a helpful assistant that analyzes data with timestamps and system info.",
)
@mesh.tool(
    capability="smart_analysis",
    tags=["analysis", "llm", "smart"],
    version="1.0.0",
    dependencies=[
        {"capability": "time_service", "tags": ["system"]},
        {"capability": "info", "tags": ["system"]},
    ],
)
async def smart_analyze(
    query: str,
    time_service: mesh.McpMeshAgent = None
) -> AnalysisResponse:

    timestamp = await time_service()

    # Get system info from dependency
    system_info = "unknown"
    if info:
        try:
            system_info = str(await info())
        except Exception:
            pass

    # Use LLM for analysis if available
    if llm:
        result = await llm(
            f"Analyze: {query}. Current time: {timestamp}. System info: {system_info}"
        )
        return AnalysisResponse(
            summary=str(result),
            timestamp=timestamp,
            system_info=system_info,
            status="completed_with_llm",
        )

    # Fallback without LLM
    return AnalysisResponse(
        summary=f"Analysis of: {query}",
        timestamp=timestamp,
        system_info=system_info,
        status="completed_without_llm",
    )


@app.tool()
@mesh.tool(
    capability="simple_report",
    tags=["report"],
    version="1.0.0",
    dependencies=["time_service"],  # Simple string dependency
)
async def generate_simple_report(
    title: str,
    time_service: mesh.McpMeshAgent = None,
) -> dict:
    """Generate a simple timestamped report using time_service dependency."""
    timestamp = "unknown"
    if time_service:
        try:
            timestamp = await time_service()
        except Exception:
            pass

    return {
        "title": title,
        "generated_at": timestamp,
        "agent": "llm-with-deps",
    }


@mesh.agent(
    name="llm-with-deps",
    version="1.0.0",
    description="LLM agent that also has static dependencies",
    http_port=8087,
    enable_http=True,
    auto_run=True,
)
class LlmWithDepsAgent:
    """
    Agent demonstrating both LLM provider and static dependencies.

    meshctl status should show:
    - Capabilities section
    - Dependencies section (from @mesh.tool dependencies)
    - LLM Tool Filters section (from @mesh.llm filter)
    - LLM Providers section (from @mesh.llm provider)
    """

    pass
