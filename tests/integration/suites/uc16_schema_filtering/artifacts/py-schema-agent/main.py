#!/usr/bin/env python3
"""Test agent for verifying MCP schema filtering.

Tools have mesh-injected parameters that should NOT appear in the external schema.
"""
import mesh
from fastmcp import FastMCP

app = FastMCP("py-schema-agent")


@app.tool()
@mesh.tool(capability="schema.greet", description="Simple greeting")
def greet(name: str) -> str:
    """Greet someone by name."""
    return f"Hello {name}"


@app.tool()
@mesh.tool(
    capability="schema.with_dep",
    description="Tool with injected dependency",
    dependencies=[{"capability": "some_service"}],
)
async def with_dep(query: str, svc: mesh.McpMeshTool = None) -> str:
    """Perform a query using an injected service."""
    return f"Result for {query}"


@app.tool()
@mesh.tool(capability="schema.with_llm", description="Tool with injected LLM agent")
async def with_llm(prompt: str, llm: mesh.MeshLlmAgent = None) -> str:
    """Generate a response for the given prompt."""
    return f"LLM result for {prompt}"


@mesh.agent(name="py-schema-agent", auto_run=True)
class SchemaAgent:
    pass
