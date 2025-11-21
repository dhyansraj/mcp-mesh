#!/usr/bin/env python3
"""
Test 4b: Orchestrator LLM Agent

This LLM agent orchestrates complex workflows by delegating to specialist LLM agents.
This is LLM calling LLM - the most advanced composition pattern.
"""

import mesh
from fastmcp import FastMCP
from pydantic import BaseModel

app = FastMCP("Orchestrator LLM Agent")


class OrchestratorResponse(BaseModel):
    """High-level orchestration result."""

    status: str  # "success", "partial", "failed"
    executive_summary: str
    analysis_confidence: float
    timestamp: str
    detailed_report: str = ""


@app.tool()
@mesh.llm(
    filter=[
        {"capability": "system_analysis", "tags": ["llm", "expert"]},
    ],
    filter_mode="all",
    provider="claude",
    model="anthropic/claude-sonnet-4-5",
    max_iterations=10,
    system_prompt="""You are a senior orchestrator managing specialist AI agents.
    You have access to expert system analysis capabilities.

    When asked for system reports:
    1. Delegate detailed analysis to the system_analysis specialist
    2. Review the specialist's findings
    3. Provide executive-level summary
    4. Make recommendations

    Always mention which specialists you consulted.""",
)
@mesh.tool(capability="orchestration", tags=["llm", "coordinator"])
def orchestrate(task: str, llm: mesh.MeshLlmAgent = None) -> OrchestratorResponse:
    """
    Orchestrate complex tasks using specialist LLM agents.

    This tests:
    1. LLM agent depending on another LLM agent
    2. Nested agentic loops
    3. Type-safe Pydantic model composition
    4. Tool execution across multiple LLM layers
    """
    return llm(task)


@mesh.agent(
    name="orchestrator-llm",
    version="1.0.0",
    description="Orchestrator LLM coordinating specialist agents",
    http_port=9005,
    enable_http=True,
    auto_run=True,
)
class OrchestratorLLMAgent:
    """Orchestrator configuration."""

    pass
