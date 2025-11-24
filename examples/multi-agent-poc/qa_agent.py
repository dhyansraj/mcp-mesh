#!/usr/bin/env python3
"""
QA Agent - Quality Assurance specialist

This agent acts as a quality assurance specialist that:
- Runs test suites
- Reviews code quality
- Checks documentation
- Identifies issues and suggests improvements

Tags: ["qa", "testing", "quality", "specialist"]
"""

from typing import Any, Dict, List

import mesh
from fastmcp import FastMCP
from pydantic import BaseModel, Field

app = FastMCP("QA Agent")


class QAResponse(BaseModel):
    """Response from QA validation."""

    status: str = Field(
        ...,
        description="Overall QA status: 'passed', 'passed_with_suggestions', or 'failed'",
    )
    test_results: Dict[str, Any] = Field(
        default_factory=dict,
        description="Test execution results (exit code, output, test count, etc.)",
    )
    code_quality_score: float = Field(
        ..., description="Overall code quality score from 0.0 to 10.0"
    )
    issues_found: List[str] = Field(
        default_factory=list, description="List of issues or problems identified"
    )
    suggestions: List[str] = Field(
        default_factory=list, description="List of suggestions for improvement"
    )
    strengths: List[str] = Field(
        default_factory=list, description="List of positive aspects and strengths"
    )
    summary: str = Field(..., description="Overall summary of the QA assessment")


@app.tool()
@mesh.llm(
    filter={"tags": ["executor", "tools"]},  # Same tools as developer
    filter_mode="all",
    provider={
        "capability": "llm",
        "tags": ["llm", "+claude"],
    },  # Mesh delegation with Claude preference
    model="anthropic/claude-sonnet-4-5",
    max_iterations=20,
    system_prompt="file://prompts/qa.jinja2",
)
@mesh.tool(
    capability="quality_assurance",
    tags=["qa", "testing", "quality", "specialist"],
    version="1.0.0",
)
def validate(context: str, llm: mesh.MeshLlmAgent = None) -> QAResponse:
    """
    Perform quality assurance validation on code.

    This function provides comprehensive QA services:
    - Test execution and validation
    - Code quality review
    - Documentation assessment
    - Issue identification
    - Improvement suggestions

    The LLM has access to executor tools via mesh filtering:
    - bash: Run tests, linters, static analysis
    - read_file: Review code files
    - grep_files: Search for patterns

    Args:
        context: Context about what to validate (e.g., "Review the prime_calculator.py
                 implementation and run its test suite")
        llm: Injected MeshLlmAgent (connects to Claude via mesh)

    Returns:
        QAResponse with validation results
    """
    return llm(context)


@mesh.agent(
    name="qa-agent",
    version="1.0.0",
    description="QA Agent - Quality Assurance specialist for testing and code review",
    http_port=9103,
    enable_http=True,
    auto_run=True,
)
class QAAgent:
    """QA agent that provides quality assurance and testing capabilities."""

    pass
