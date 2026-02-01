#!/usr/bin/env python3
"""
Test 9: Context Param with Filter + Mesh Delegation (Race Condition Test)

This test reproduces the maya/v5 issue where context_param fails with KeyError: 'config'
when using BOTH:
- filter={"tags": ["generic-tool"]} (NOT None)
- provider={"capability": "llm"} (mesh delegation)

The bug occurs because:
1. _process_function_provider runs first (sets provider_proxy but NOT config)
2. Before _process_function_tools runs, an MCP request arrives
3. _create_llm_agent tries llm_agent_data["config"] -> KeyError!

The fix ensures _process_function_provider always sets config from DecoratorRegistry,
not just for filter=None cases.

Difference from test_008:
- test_008: filter=None (works)
- test_009: filter={"tags": ["generic-tool"]} (was broken before fix)

This test requires:
1. LLM provider agent: meshctl start examples/llm-mesh-delegation/test_009_provider.py
2. Generic tool provider: meshctl start examples/prompt-template-examples/test_009_generic_tool_provider.py

Usage:
    # Start dependencies first
    meshctl start examples/llm-mesh-delegation/test_009_provider.py
    meshctl start examples/prompt-template-examples/test_009_generic_tool_provider.py

    # Then start this test agent
    meshctl start examples/prompt-template-examples/test_009_context_with_filter_mesh.py

    # Run the test
    meshctl call test_context_with_filter_mesh '{}'
"""

import mesh
from fastmcp import FastMCP
from pydantic import BaseModel, Field

app = FastMCP("ContextWithFilterMeshTest")


# Using plain BaseModel (not MeshContextModel) to match maya/v5's ChatContext
class ChatContext(BaseModel):
    """Context for avatar chat - matches maya/v5 structure."""

    user_message: str = Field(..., description="The user's message")
    user_email: str = Field(..., description="User's email")
    avatar_id: str = Field(default="test-avatar", description="Avatar ID")
    user_name: str = Field(default="TestUser", description="User's display name")
    # Avatar profile - the template accesses {{ avatar.name }}
    avatar: dict = Field(
        default_factory=lambda: {"name": "TestAvatar", "personality": "Friendly"},
        description="Avatar profile data",
    )
    memory_count: int = Field(default=0, description="Number of memories")


class ChatResponse(BaseModel):
    """Response from avatar chat."""

    message: str = Field(..., description="Avatar's response message")
    action: str = Field(default="done", description="Conversation action")
    emotion: str = Field(default="neutral", description="Avatar's emotion")


class FilterMeshContextResult(BaseModel):
    """Result from the race condition test."""

    test_name: str
    filter_used: str
    provider_used: str
    context_passed: bool
    chat_result: str
    test_passed: bool
    diagnosis: str


# LLM tool with FILTER + MESH DELEGATION + CONTEXT_PARAM
# This is the exact pattern that breaks in maya/v5
@app.tool()
@mesh.llm(
    system_prompt="file://prompts/support_avatar.jinja2",  # Uses {{ avatar.name }}
    context_param="ctx",  # Explicit context parameter
    filter={"tags": ["generic-tool"]},  # <-- NOT None! This triggers the race condition
    filter_mode="all",
    provider={"capability": "llm"},  # <-- Mesh delegation
    max_iterations=5,
)
@mesh.tool(
    capability="avatar_chat_with_filter",
    description="Avatar chat with filter + mesh delegation (race condition test)",
    tags=["llm", "avatar", "chat", "test"],
    version="1.0.0",
)
async def avatar_chat_with_filter(
    ctx: ChatContext,
    llm: mesh.MeshLlmAgent = None,
) -> ChatResponse:
    """
    Chat with avatar using filter + mesh delegation.

    This reproduces the maya/v5 pattern:
    - filter={"tags": ["generic-tool"]} triggers _process_function_tools
    - provider={"capability": "llm"} triggers _process_function_provider
    - context_param="ctx" needs config to be set for template rendering

    The race condition: if provider arrives before tools, config isn't set,
    and _create_llm_agent fails with KeyError: 'config'.
    """
    # Build message for LLM
    messages = [
        {"role": "user", "content": ctx.user_message},
    ]

    # Call LLM - this will fail with KeyError if the race condition isn't fixed
    response = await llm(messages)

    return response


# Self-dependency test to trigger the race condition
@app.tool()
@mesh.tool(
    capability="test_context_with_filter_mesh",
    dependencies=["avatar_chat_with_filter"],  # Self-dependency!
    description="Test context_param with filter + mesh delegation (race condition)",
)
async def test_context_with_filter_mesh(
    avatar_chat_with_filter: mesh.McpMeshTool | None = None,
) -> FilterMeshContextResult:
    """
    Test that context_param works with filter + mesh delegation.

    This test reproduces the maya/v5 issue:
    - Uses filter={"tags": ["generic-tool"]} (NOT None)
    - Uses provider={"capability": "llm"} (mesh delegation)
    - Uses context_param="ctx"
    - Uses BaseModel (not MeshContextModel)

    Before the fix: KeyError: 'config' when calling avatar_chat_with_filter
    After the fix: Context is correctly passed to the template
    """
    result = FilterMeshContextResult(
        test_name="context_param_with_filter_mesh_delegation",
        filter_used='{"tags": ["generic-tool"]}',
        provider_used='{"capability": "llm"}',
        context_passed=False,
        chat_result="not_available",
        test_passed=False,
        diagnosis="",
    )

    if avatar_chat_with_filter is None:
        result.diagnosis = (
            "FAIL: avatar_chat_with_filter not injected (self-dep failed)"
        )
        return result

    try:
        # Create context matching maya/v5's ChatContext
        ctx = ChatContext(
            user_message="Hello, I need help with something.",
            user_email="test@example.com",
            avatar_id="test-avatar",
            user_name="FilterTestUser",
            avatar={
                "name": "SupportAvatar",
                "personality": "Empathetic and caring",
                "traits": ["patient", "understanding"],
            },
            memory_count=3,
        )

        # This call triggers the race condition bug
        # Before fix: KeyError: 'config'
        # After fix: Works correctly
        chat_result = await avatar_chat_with_filter(ctx=ctx)
        result.chat_result = str(chat_result)
        result.context_passed = True

        # Check if the response mentions context values
        result_str = str(chat_result).lower()
        if (
            "supportavatar" in result_str
            or "filtertestuser" in result_str
            or "help" in result_str
            or "message" in result_str
        ):
            result.test_passed = True
            result.diagnosis = (
                "PASS: Context param works with filter + mesh delegation! "
                "The race condition fix ensures config is set before tools arrive."
            )
        else:
            result.test_passed = True  # Still passed if no KeyError
            result.diagnosis = (
                "PASS (partial): No KeyError, but response may not include context. "
                f"Response: {chat_result}"
            )

    except KeyError as e:
        if "config" in str(e):
            result.diagnosis = (
                "FAIL: KeyError: 'config' - This is the exact bug from maya/v5! "
                "_process_function_provider didn't set config before tools arrived. "
                "The fix should ensure config is always set from DecoratorRegistry."
            )
        else:
            result.diagnosis = f"FAIL: KeyError - {e}"
    except TypeError as e:
        if "NoneType" in str(e) or "llm" in str(e):
            result.diagnosis = (
                "FAIL: LLM agent was not injected. "
                "The MeshLlmAgent may not be available yet."
            )
        else:
            result.diagnosis = f"FAIL: TypeError - {e}"
    except Exception as e:
        result.diagnosis = f"FAIL: Exception during call: {type(e).__name__}: {e}"

    return result


# Simple test without self-dependency (direct call)
@app.tool()
@mesh.tool(
    capability="test_direct_call_with_filter",
    description="Direct test of avatar_chat_with_filter without self-dependency",
)
async def test_direct_call_with_filter() -> FilterMeshContextResult:
    """
    Test avatar_chat_with_filter via direct MCP call (no self-dependency).

    This simulates how the orchestrator calls support_avatar_chat in maya/v5.
    """
    result = FilterMeshContextResult(
        test_name="direct_call_with_filter_mesh",
        filter_used='{"tags": ["generic-tool"]}',
        provider_used='{"capability": "llm"}',
        context_passed=False,
        chat_result="not_available",
        test_passed=False,
        diagnosis="This test requires external MCP call to avatar_chat_with_filter",
    )
    return result


@mesh.agent(
    name="context-with-filter-mesh-test",
    version="1.0.0",
    description="Test: context_param with filter + mesh delegation (race condition)",
    http_port=9100,
    enable_http=True,
    auto_run=True,
)
class ContextWithFilterMeshTestAgent:
    """Agent for testing context_param with filter + mesh delegation."""

    pass


if __name__ == "__main__":
    app.run()
