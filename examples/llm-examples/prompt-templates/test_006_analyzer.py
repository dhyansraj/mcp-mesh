#!/usr/bin/env python3
"""
Test 6 - Part 1: Document Analyzer (LLM Chain Test)

This is the specialist LLM that the orchestrator will call.
Validates Field descriptions flow through to calling LLMs.
"""

import mesh
from fastmcp import FastMCP
from mesh import MeshContextModel
from pydantic import BaseModel, Field

app = FastMCP("Document Analyzer")


class AnalysisContext(MeshContextModel):
    """Context for document analysis."""

    user_name: str = Field(description="Name of user requesting analysis")
    document_type: str = Field(description="Type of document: pdf, docx, txt, markdown")
    analysis_type: str = Field(
        description="Analysis type: summary, sentiment, entities, keywords"
    )


class AnalysisResult(BaseModel):
    summary: str
    key_points: list[str]
    confidence: float


@app.tool()
@mesh.llm(
    system_prompt="file://prompts/analyzer.jinja2",
    filter=None,
    provider="claude",
    model="anthropic/claude-sonnet-4-5",
    context_param="ctx",
)
@mesh.tool(
    capability="document_analysis", tags=["prompt-template", "test-006-analyzer"]
)
def analyze_document(
    content: str, ctx: AnalysisContext, llm: mesh.MeshLlmAgent = None
) -> AnalysisResult:
    """Analyze documents with context-aware prompting."""
    return llm(content)


@mesh.agent(
    name="test-pt-006-analyzer",
    version="1.0.0",
    description="Test agent for document analysis with enhanced schemas",
    http_port=8080,
    enable_http=True,
    auto_run=True,
)
class AnalyzerTestAgent:
    """Test agent configuration."""

    pass
