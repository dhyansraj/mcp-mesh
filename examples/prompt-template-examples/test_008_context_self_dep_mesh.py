#!/usr/bin/env python3
"""
Test 8: Context Param with Self-Dependency (Mesh Delegation)

Tests that context_param values are correctly passed to the Jinja2 template
renderer when an agent calls its own @mesh.llm decorated tool via self-dependency,
using mesh delegation to an LLM provider agent.

This test requires an LLM provider agent to be running:
    meshctl start examples/llm-mesh-delegation/test_009_provider.py

Difference from test_007:
- test_007: Uses direct LiteLLM (provider="claude")
- test_008: Uses mesh delegation (provider={"capability": "llm"})
"""

import mesh
from fastmcp import FastMCP
from mesh import MeshContextModel
from pydantic import BaseModel, Field

app = FastMCP("ContextSelfDepMeshTest")


class ExtractionContext(MeshContextModel):
    """Context for memory extraction."""

    user_name: str = Field(description="User's name for personalization")
    conversation: list[str] = Field(
        default_factory=list, description="Conversation history"
    )


class ExtractionResult(BaseModel):
    """Result from memory extraction."""

    extracted_memories: list[str] = Field(description="List of extracted memories")
    context_received: bool = Field(description="Whether context was received")
    user_name_in_template: str = Field(description="User name that template received")


class SelfDepContextResult(BaseModel):
    """Result from self-dependency context test."""

    test_name: str
    context_passed: bool
    extraction_result: str
    test_passed: bool
    diagnosis: str


# Tool with context_param and template - using MESH DELEGATION
@app.tool()
@mesh.llm(
    system_prompt="file://prompts/extraction.jinja2",  # Uses {{ user_name }}
    context_param="ctx",  # Explicit context parameter
    filter=None,  # No tools needed for this test
    provider={"capability": "llm"},  # Mesh delegation to LLM provider
)
@mesh.tool(capability="memory_extraction_mesh")
def extract_memories_mesh(
    request: str, ctx: ExtractionContext, llm: mesh.MeshLlmAgent = None
) -> ExtractionResult:
    """Extract memories with context-aware prompt via mesh delegation.

    The template should render with ctx.user_name and ctx.conversation.
    If context_param works correctly with self-dependency, the template
    will include the user's name and conversation history.
    """
    return llm(request)


# Self-dependency test tool
@app.tool()
@mesh.tool(
    capability="self_dep_context_mesh_test",
    dependencies=["memory_extraction_mesh"],  # Self-dependency!
    description="Test that context_param works with self-dependency (mesh delegation)",
)
async def test_context_self_dep_mesh(
    extract_memories_mesh: mesh.McpMeshTool | None = None,
) -> SelfDepContextResult:
    """Test that context_param works with self-dependency using mesh delegation.

    Test chain:
        test_context_self_dep_mesh (this agent)
            -> [SELF-DEP via wrapper] extract_memories_mesh (this agent)
                -> [MESH DELEGATION] LLM provider agent
                    -> [LLM call] template should render with {{ user_name }}

    This tests the mesh delegation path where:
    - provider={"capability": "llm"} triggers mesh delegation
    - _process_function_provider is called (not _process_function_tools)
    - The fix ensures _mesh_create_context_agent factory is set
    """
    result = SelfDepContextResult(
        test_name="context_param_with_self_dependency_mesh",
        context_passed=False,
        extraction_result="not_available",
        test_passed=False,
        diagnosis="",
    )

    if extract_memories_mesh is None:
        result.diagnosis = "FAIL: extract_memories_mesh not injected (self-dep failed)"
        return result

    try:
        # Create context with test data
        ctx = ExtractionContext(
            user_name="MeshTestUser",
            conversation=[
                "Hello, I'm MeshTestUser!",
                "I love using mesh delegation.",
                "My favorite framework is MCP Mesh.",
            ],
        )

        # Call extract_memories_mesh - this goes through SelfDependencyProxy
        # The ctx should be passed to the template renderer
        extraction_result = await extract_memories_mesh(
            request="Extract key facts from the conversation.",
            ctx=ctx,  # <-- This context should reach the template!
        )
        result.extraction_result = str(extraction_result)
        result.context_passed = True

        # Check if extraction worked (LLM should have context about MeshTestUser)
        result_str = str(extraction_result).lower()
        if (
            "meshtestuser" in result_str
            or "mesh" in result_str
            or "delegation" in result_str
            or "extracted" in result_str
        ):
            result.test_passed = True
            result.diagnosis = (
                "PASS: Context param worked with self-dependency (mesh delegation)! "
                "Template received user_name and conversation context."
            )
        else:
            result.test_passed = False
            result.diagnosis = (
                f"POSSIBLE FAIL: Extraction result doesn't mention context values. "
                f"Template may have received empty context. Result: {extraction_result}"
            )

    except TypeError as e:
        if "NoneType" in str(e) or "llm" in str(e):
            result.diagnosis = (
                "FAIL: LLM agent was not injected. "
                "inject_llm_agent may not be extracting context from kwargs."
            )
        else:
            result.diagnosis = f"FAIL: TypeError - {e}"
    except Exception as e:
        result.diagnosis = f"FAIL: Exception during self-dep call: {e}"

    return result


# Agent configuration for HTTP transport
@mesh.agent(
    name="context-self-dep-mesh-test",
    version="1.0.0",
    description="Context Self-Dependency Test Agent (Mesh Delegation)",
    http_port=9098,  # Use port 9098 (different from test_007)
    enable_http=True,
    auto_run=True,
)
class ContextSelfDepMeshTestAgent:
    """Agent class for context self-dependency testing with mesh delegation."""

    pass


if __name__ == "__main__":
    app.run()
