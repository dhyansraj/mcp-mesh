#!/usr/bin/env python3
"""
Test 4a: System Analyst LLM Agent (Specialist)

This LLM agent specializes in system analysis.
It uses system tools and provides analysis as a capability to other agents.
"""

import mesh
from fastmcp import FastMCP
from pydantic import BaseModel

app = FastMCP("System Analyst LLM Agent")


class SystemAnalysisResult(BaseModel):
    """Type-safe analysis result - used by orchestrator."""

    summary: str
    current_time: str
    uptime: str
    system_health: str
    confidence: float
    detailed_findings: list[str] = []


@app.tool()
@mesh.llm(
    filter=[
        {"capability": "date_service"},
        {"capability": "info", "tags": ["system", "general"]},
        {"capability": "uptime_info"},
    ],
    filter_mode="all",
    provider="claude",
    model="anthropic/claude-sonnet-4-5",
    max_iterations=10,
    system_prompt="""You are a system analysis expert.
    Use available system tools to gather information and provide comprehensive analysis.
    Always include:
    - Current timestamp
    - System uptime
    - Overall health assessment
    - Key findings

    Be thorough and use multiple tools to gather complete information.""",
)
@mesh.tool(capability="system_analysis", tags=["llm", "analysis", "expert"])
def analyze_system(
    request: str = "Provide complete system analysis", llm: mesh.MeshLlmAgent = None
) -> SystemAnalysisResult:
    """
    Perform comprehensive system analysis.

    This LLM agent:
    1. Uses system tools (date, info, uptime)
    2. Provides analysis capability to other agents
    3. Returns type-safe Pydantic model
    """
    return llm(request)


@mesh.agent(
    name="system-analyst-llm",
    version="1.0.0",
    description="Specialist LLM for system analysis",
    http_port=9004,
    enable_http=True,
    auto_run=True,
)
class SystemAnalystLLMAgent:
    """System analyst configuration."""

    pass
