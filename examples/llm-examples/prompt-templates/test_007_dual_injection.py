#!/usr/bin/env python3
"""
Test 7: Dual Agent Injection (LLM + MCP Agent)

Validates that both MeshLlmAgent and McpMeshAgent can be injected into the same function.
The function calls the LLM first, then enriches the response with data from an MCP agent.
"""

import mesh
from fastmcp import FastMCP
from pydantic import BaseModel

app = FastMCP("Dual Injection Test")


class AnalysisResult(BaseModel):
    """Initial LLM analysis result."""

    analysis: str
    recommendations: list[str]


class EnrichedResult(BaseModel):
    """Enriched result with MCP agent data."""

    analysis: str
    recommendations: list[str]
    timestamp: str
    system_info: str


@app.tool()
@mesh.llm(
    system_prompt="file://prompts/dual_injection.jinja2",
    filter={"tags": ["system"]},  # Will get system agent tools for LLM
    provider="claude",
    model="anthropic/claude-sonnet-4-5",
)
@mesh.tool(
    capability="dual_injection",
    tags=["prompt-template", "test-007"],
    dependencies=[
        {
            "capability": "date_service",
            "tags": ["system", "time"],
        },
    ],
)
async def analyze_with_enrichment(
    query: str,
    llm: mesh.MeshLlmAgent = None,
    date_service: mesh.McpMeshAgent = None,
) -> EnrichedResult:
    """
    Analyze query with LLM and enrich with MCP agent data.

    This function demonstrates dual injection:
    1. Calls LLM agent to get initial analysis (with system tools)
    2. Calls MCP agent (date_service) directly to get current timestamp
    3. Enriches LLM result with MCP agent data
    4. Returns enriched result

    Both llm (MeshLlmAgent) and date_service (McpMeshAgent) are injected!
    """
    # Step 1: Get LLM analysis (LLM has access to system tools via filter)
    llm_result: AnalysisResult = await llm(query)

    # Step 2: Call MCP agent directly to get current time
    # The date_service is a direct McpMeshAgent dependency (not via LLM filter)
    timestamp = "N/A"
    system_info = "N/A"

    if date_service is not None:
        try:
            # Call the date_service directly - it's a callable proxy
            time_data = await date_service()
            # date_service returns a string directly
            timestamp = str(time_data) if time_data else "N/A"
            # Also try to extract system info from any tools the LLM used
            system_info = "System analysis completed with date enrichment"
        except Exception as e:
            timestamp = f"Error: {e}"
            system_info = "Error getting system info"

    # Step 3: Enrich the LLM result with direct MCP agent data
    enriched = EnrichedResult(
        analysis=llm_result.analysis,
        recommendations=llm_result.recommendations,
        timestamp=timestamp,
        system_info=system_info,
    )

    return enriched


@mesh.agent(
    name="test-pt-007-dual-injection",
    version="1.0.0",
    description="Test agent for dual injection (LLM + MCP agent)",
    http_port=8080,
    enable_http=True,
    auto_run=True,
)
class DualInjectionTestAgent:
    """Test agent configuration."""

    pass
