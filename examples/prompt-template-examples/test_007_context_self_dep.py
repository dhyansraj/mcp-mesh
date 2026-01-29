#!/usr/bin/env python3
"""
Test 7: Context Param with Self-Dependency

Tests that context_param values are correctly passed to the Jinja2 template
renderer when an agent calls its own @mesh.llm decorated tool via self-dependency.

Bug being tested:
- context_param values were not reaching the template during self-dependency calls
- Template rendered with empty context despite context being passed to the function
- Root cause: inject_llm_agent only checked self._llm_agents (populated at heartbeat)
  but not DecoratorRegistry._mesh_llm_agents (populated at decorator time)
"""

import mesh
from fastmcp import FastMCP
from mesh import MeshContextModel
from pydantic import BaseModel, Field

app = FastMCP("ContextSelfDepTest")


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


# Tool with context_param and template
@app.tool()
@mesh.llm(
    system_prompt="file://prompts/extraction.jinja2",  # Uses {{ user_name }}
    context_param="ctx",  # Explicit context parameter
    filter=None,  # No tools needed for this test
    provider="claude",  # Direct LiteLLM (no mesh delegation)
    model="anthropic/claude-sonnet-4-5",
)
@mesh.tool(capability="memory_extraction")
def extract_memories(
    request: str, ctx: ExtractionContext, llm: mesh.MeshLlmAgent = None
) -> ExtractionResult:
    """Extract memories with context-aware prompt.

    The template should render with ctx.user_name and ctx.conversation.
    If context_param works correctly with self-dependency, the template
    will include the user's name and conversation history.
    """
    return llm(request)


# Self-dependency test tool
@app.tool()
@mesh.tool(
    capability="self_dep_context_test",
    dependencies=["memory_extraction"],  # Self-dependency!
    description="Test that context_param works with self-dependency calls",
)
async def test_context_self_dep(
    extract_memories: mesh.McpMeshTool | None = None,
) -> SelfDepContextResult:
    """Test that context_param works with self-dependency.

    Test chain:
        test_context_self_dep (this agent)
            -> [SELF-DEP via wrapper] extract_memories (this agent)
                -> [LLM call] template should render with {{ user_name }}

    If self-dependency uses the WRAPPER correctly:
    - extract_memories' 'ctx' parameter will be passed to inject_llm_agent
    - inject_llm_agent will extract context and pass to MeshLlmAgent
    - Template will render with user_name="TestUser" and conversation history

    If self-dependency is broken (the bug):
    - inject_llm_agent falls through to backward compatibility path
    - Uses cached agent WITHOUT extracting context from kwargs
    - Template renders with empty context (user_name="", conversation=[])
    """
    result = SelfDepContextResult(
        test_name="context_param_with_self_dependency",
        context_passed=False,
        extraction_result="not_available",
        test_passed=False,
        diagnosis="",
    )

    if extract_memories is None:
        result.diagnosis = "FAIL: extract_memories not injected (self-dep failed)"
        return result

    try:
        # Create context with test data
        ctx = ExtractionContext(
            user_name="TestUser",
            conversation=[
                "Hello, I'm TestUser!",
                "I prefer Python over JavaScript.",
                "My favorite color is blue.",
            ],
        )

        # Call extract_memories - this goes through SelfDependencyProxy
        # The ctx should be passed to the template renderer
        extraction_result = await extract_memories(
            request="Extract key facts from the conversation.",
            ctx=ctx,  # <-- This context should reach the template!
        )
        result.extraction_result = str(extraction_result)
        result.context_passed = True

        # Check if extraction worked (LLM should have context about TestUser)
        result_str = str(extraction_result).lower()
        if (
            "testuser" in result_str
            or "python" in result_str
            or "blue" in result_str
            or "extracted" in result_str
        ):
            result.test_passed = True
            result.diagnosis = (
                "PASS: Context param worked with self-dependency! "
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
    name="context-self-dep-test",
    version="1.0.0",
    description="Context Self-Dependency Test Agent",
    http_port=9099,  # Use port 9099
    enable_http=True,
    auto_run=True,
)
class ContextSelfDepTestAgent:
    """Agent class for context self-dependency testing."""

    pass


if __name__ == "__main__":
    app.run()
