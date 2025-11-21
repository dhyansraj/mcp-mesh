#!/usr/bin/env python3
"""
Test 6: Document Analyzer Agent

Provides document analysis with context-aware prompting.
"""

import mesh
from fastmcp import FastMCP
from mesh import MeshContextModel
from pydantic import BaseModel, Field

app = FastMCP("Document Analyzer")


class AnalysisContext(MeshContextModel):
    """Context for document analysis."""

    user_name: str = Field(description="Name of user requesting analysis")
    document_type: str = Field(description="Type of document: pdf, docx, txt")
    analysis_type: str = Field(
        description="Analysis type: summary, sentiment, entities"
    )


class AnalysisResult(BaseModel):
    findings: str
    confidence: str


@app.tool()
@mesh.llm(
    system_prompt="file://prompts/analyzer.jinja2",
    filter=None,
    provider="claude",
    model="anthropic/claude-sonnet-4-5",  # LiteLLM requires vendor prefix
)
@mesh.tool(capability="document_analysis", tags=["llm", "analysis"])
def analyze_document(
    content: str, ctx: AnalysisContext, llm: mesh.MeshLlmAgent = None
) -> AnalysisResult:
    """Analyze document with context."""
    return llm(content)


# Agent configuration for HTTP transport
@mesh.agent(
    name="document-analyzer",
    version="1.0.0",
    description="Document Analyzer Agent",
    http_port=9097,  # Use port 9097
    enable_http=True,
    auto_run=True,
)
class DocumentAnalyzerAgent:
    """Agent class for document analysis."""

    pass


if __name__ == "__main__":
    app.run()
