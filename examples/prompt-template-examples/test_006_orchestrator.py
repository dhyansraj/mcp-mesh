#!/usr/bin/env python3
"""
Test 6: Orchestrator Agent

Orchestrates document analysis by calling analyzer agent.
"""

import mesh
from fastmcp import FastMCP
from pydantic import BaseModel

app = FastMCP("Orchestrator")


class OrchestratorResult(BaseModel):
    status: str
    analysis: str


@app.tool()
@mesh.llm(
    system_prompt="file://prompts/orchestrator_chain.jinja2",
    filter=[{"capability": "document_analysis"}],  # Will see analyze_document tool
    filter_mode="all",
    provider="claude",
    model="anthropic/claude-sonnet-4-5",  # LiteLLM requires vendor prefix
)
@mesh.tool(capability="orchestration")
def orchestrate_analysis(
    request: str, llm: mesh.MeshLlmAgent = None
) -> OrchestratorResult:
    """Orchestrate document analysis."""
    # Calling LLM should see enhanced schema with Field descriptions
    # for AnalysisContext, helping it construct proper context
    return llm(request)


# Agent configuration for HTTP transport
@mesh.agent(
    name="orchestrator-chain",
    version="1.0.0",
    description="Orchestrator Chain Agent",
    http_port=9098,  # Use port 9098
    enable_http=True,
    auto_run=True,
)
class OrchestratorAgent:
    """Agent class for orchestration."""

    pass


if __name__ == "__main__":
    app.run()
