#!/usr/bin/env python3
"""
Test 6 - Part 2: Orchestrator (LLM Chain Test)

This orchestrator calls the document analyzer.
Validates that enhanced schemas with Field descriptions help the LLM construct proper contexts.
"""

import mesh
from fastmcp import FastMCP
from pydantic import BaseModel

app = FastMCP("Document Analysis Orchestrator")


class OrchestratorResult(BaseModel):
    status: str
    summary: str
    analysis_details: str


@app.tool()
@mesh.llm(
    system_prompt="file://prompts/orchestrator_chain.jinja2",
    filter={"capability": "document_analysis"},
    provider="claude",
    model="anthropic/claude-sonnet-4-5",
    max_iterations=10,  # Allow multiple tool calls
)
@mesh.tool(
    capability="orchestration", tags=["prompt-template", "test-006-orchestrator"]
)
def orchestrate_analysis(
    request: str, llm: mesh.MeshLlmAgent = None
) -> OrchestratorResult:
    """
    Orchestrate document analysis by delegating to analyzer.

    The calling LLM should see enhanced schema with Field descriptions
    for AnalysisContext, helping it construct proper context objects.
    """
    return llm(request)


@mesh.agent(
    name="test-pt-006-orchestrator",
    version="1.0.0",
    description="Test agent for LLM chain orchestration with enhanced schemas",
    http_port=8080,
    enable_http=True,
    auto_run=True,
)
class OrchestratorTestAgent:
    """Test agent configuration."""

    pass
