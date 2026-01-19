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


class SelfDepTestResult(BaseModel):
    """Result from self-dependency test."""

    test_name: str
    self_dep_target: str
    orchestration_result: str
    test_passed: bool
    diagnosis: str


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


# ===== SELF-DEPENDENCY TEST =====
# Tests that self-dependencies work with @mesh.llm decorated functions


@app.tool()
@mesh.tool(
    capability="self_dep_llm_test",
    dependencies=["orchestration"],  # Self-dependency: same agent!
    description="Test self-dependency with @mesh.llm decorated function",
)
async def test_self_dependency_llm(
    orchestrate_analysis: mesh.McpMeshTool | None = None,
) -> SelfDepTestResult:
    """
    Test self-dependency injection with @mesh.llm decorated functions.

    This tool depends on 'orchestrate_analysis' which is in the SAME agent.
    'orchestrate_analysis' is decorated with @mesh.llm and needs MeshLlmAgent injected.

    Test chain:
        test_self_dependency_llm (orchestrator)
            → [SELF-DEP via wrapper] orchestrate_analysis (orchestrator)
                → [LLM call with tools] analyze_document (analyzer agent)

    If self-dependency uses the WRAPPER:
    - orchestrate_analysis's 'llm' parameter will be injected
    - The LLM call will work and return structured result

    If self-dependency uses the ORIGINAL function:
    - orchestrate_analysis's 'llm' parameter will be None
    - Will raise an error when trying to call llm(request)
    """
    result = SelfDepTestResult(
        test_name="self_dependency_with_mesh_llm",
        self_dep_target="orchestrate_analysis",
        orchestration_result="not_available",
        test_passed=False,
        diagnosis="",
    )

    if orchestrate_analysis is None:
        result.diagnosis = "FAIL: orchestrate_analysis not injected (self-dep failed)"
        return result

    try:
        # Call orchestrate_analysis - this goes through SelfDependencyProxy
        # If wrapper is used: llm will be injected, we get orchestration result
        # If original is used: llm will be None, we get an error
        orch_result = await orchestrate_analysis(
            request="Briefly analyze: Self-dependency test for MCP Mesh."
        )
        result.orchestration_result = str(orch_result)

        # Check if the LLM call worked (nested dependency)
        if (
            "status" in str(orch_result).lower()
            or "analysis" in str(orch_result).lower()
        ):
            result.test_passed = True
            result.diagnosis = (
                "PASS: Self-dependency with @mesh.llm worked! "
                "LLM agent was properly injected via wrapper."
            )
        else:
            result.test_passed = False
            result.diagnosis = f"UNKNOWN: Unexpected response format: {orch_result}"

    except TypeError as e:
        if "NoneType" in str(e) or "llm" in str(e):
            result.diagnosis = (
                "FAIL: LLM agent was not injected. "
                "SelfDependencyProxy may be using original function instead of wrapper."
            )
        else:
            result.diagnosis = f"FAIL: TypeError - {e}"
    except Exception as e:
        result.diagnosis = f"FAIL: Exception during self-dep call: {e}"

    return result


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
