"""
Test 2: LLM Agent with Complex Nested Response (LLM-002)

This test verifies that our refactorings (ResponseParser, LLMConfig, enhanced errors)
work correctly with complex nested Pydantic models.
"""

import mesh
from fastmcp import FastMCP
from pydantic import BaseModel

app = FastMCP("Complex Response Test Agent")


class Author(BaseModel):
    """Nested author information."""

    name: str
    expertise: list[str]
    confidence_score: float


class Source(BaseModel):
    """Nested source information."""

    title: str
    url: str
    relevance: float


class AnalysisResult(BaseModel):
    """Complex nested response structure."""

    summary: str
    key_points: list[str]
    sentiment: str  # positive, negative, neutral
    author: Author
    sources: list[Source]
    metadata: dict[str, str | int | float]
    confidence: float


@app.tool()
@mesh.llm(
    filter=None,  # No tools
    provider="claude",
    model="anthropic/claude-sonnet-4-5",
    max_iterations=5,
    system_prompt=(
        "You are an expert analyst. "
        "Provide detailed analysis with nested structured data. "
        "Always include author info, sources, and metadata."
    ),
)
@mesh.tool(capability="complex_analysis", tags=["llm", "analysis", "test"])
def analyze_topic(topic: str, llm: mesh.MeshLlmAgent = None) -> AnalysisResult:
    """
    Analyze a topic with complex nested response.

    This function tests:
    1. Complex nested Pydantic model parsing
    2. ResponseParser with nested structures
    3. JSON schema generation for complex types
    4. Enhanced error context if parsing fails
    5. Debug logging with complex responses
    """
    return llm(f"Analyze this topic in detail: {topic}")


@mesh.agent(
    name="complex-response-test",
    version="1.0.0",
    description="Test agent for complex nested response parsing",
    http_port=9002,
    enable_http=True,
    auto_run=True,
)
class ComplexResponseTestAgent:
    """Test agent configuration."""

    pass
