#!/usr/bin/env python3
"""
PT-008: LLM Provider Registration Test

Tests that @mesh.llm_provider correctly:
1. Registers as MCP tool (@app.tool)
2. Registers in mesh network (@mesh.tool with capability="llm")
3. Accepts MeshLlmRequest and returns string
4. Can be called directly via MCP

This is the foundation for Phase 2 - proving the provider side works
before implementing consumer side in Phase 3.
"""

import mesh
from fastmcp import FastMCP

app = FastMCP("LLM Provider Test")


@mesh.llm_provider(
    model="anthropic/claude-sonnet-4-5",
    capability="llm",
    tags=["claude", "test", "+budget"],
    version="1.0.0",
)
def claude_provider():
    """
    Zero-code LLM provider using @mesh.llm_provider decorator.

    This decorator should automatically:
    - Apply @app.tool() for MCP registration
    - Apply @mesh.tool() for mesh network DI
    - Generate process_chat(request: MeshLlmRequest) -> str function
    - Wrap LiteLLM with error handling
    """
    pass  # Implementation is in the decorator


# Agent configuration for HTTP transport
@mesh.agent(
    name="llm-provider-test",
    version="1.0.0",
    description="PT-008: LLM Provider Registration Test",
    http_port=9019,  # PT-008 port
    enable_http=True,
    auto_run=True,
)
class LlmProviderTestAgent:
    """Agent class for LLM provider testing."""

    pass


if __name__ == "__main__":
    app.run()
