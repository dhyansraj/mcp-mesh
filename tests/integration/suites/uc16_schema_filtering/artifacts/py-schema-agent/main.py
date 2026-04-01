#!/usr/bin/env python3
"""Test agent for comprehensive MCP schema filtering verification.

Tests all parameter combinations to ensure mesh-injected parameters
(McpMeshTool, MeshLlmAgent) are hidden from MCP tool schemas.
"""
import mesh
from fastmcp import FastMCP
from pydantic import BaseModel, Field

app = FastMCP("py-schema-agent")


# === Case 1: No params ===
@app.tool()
@mesh.tool(capability="schema.t01", description="No parameters")
def t01_no_params() -> str:
    return "ok"


# === Case 2: One param ===
@app.tool()
@mesh.tool(capability="schema.t02", description="Single parameter")
def t02_one_param(name: str) -> str:
    return f"Hello {name}"


# === Case 3: Multiple params ===
@app.tool()
@mesh.tool(capability="schema.t03", description="Multiple parameters")
def t03_multi_params(a: str, b: int, c: bool) -> str:
    return f"{a} {b} {c}"


# === Case 4: With defaults ===
@app.tool()
@mesh.tool(capability="schema.t04", description="Parameters with defaults")
def t04_with_defaults(a: str, b: int = 5) -> str:
    return f"{a} {b}"


# === Case 5: McpMeshTool only ===
@app.tool()
@mesh.tool(
    capability="schema.t05",
    description="Injectable only",
    dependencies=[{"capability": "dep_a"}],
)
async def t05_meshtool_only(svc: mesh.McpMeshTool = None) -> str:
    return "ok"


# === Case 6: Normal then McpMeshTool ===
@app.tool()
@mesh.tool(
    capability="schema.t06",
    description="Normal then injectable",
    dependencies=[{"capability": "dep_a"}],
)
async def t06_normal_then_meshtool(query: str, svc: mesh.McpMeshTool = None) -> str:
    return f"Result for {query}"


# === Case 7: McpMeshTool then normal ===
@app.tool()
@mesh.tool(
    capability="schema.t07",
    description="Injectable then normal",
    dependencies=[{"capability": "dep_a"}],
)
async def t07_meshtool_then_normal(
    svc: mesh.McpMeshTool = None, query: str = "default"
) -> str:
    return f"Result for {query}"


# === Case 8: Multiple McpMeshTool ===
@app.tool()
@mesh.tool(
    capability="schema.t08",
    description="Multiple injectables",
    dependencies=[{"capability": "dep_a"}, {"capability": "dep_b"}],
)
async def t08_multi_meshtool(
    q: str, a: mesh.McpMeshTool = None, b: mesh.McpMeshTool = None
) -> str:
    return f"Result for {q}"


# === Case 9: Normal + McpMeshTool + defaults ===
@app.tool()
@mesh.tool(
    capability="schema.t09",
    description="Mixed with defaults",
    dependencies=[{"capability": "dep_a"}],
)
async def t09_normal_meshtool_defaults(
    q: str, n: int = 5, svc: mesh.McpMeshTool = None
) -> str:
    return f"{q} {n}"


# === Case 10: MeshLlmAgent only (with @mesh.llm) ===
@app.tool()
@mesh.llm(provider={"capability": "llm"}, max_iterations=1)
@mesh.tool(capability="schema.t10", description="LLM injectable only")
async def t10_llm_only(llm: mesh.MeshLlmAgent = None) -> str:
    return "ok"


# === Case 11: Normal then MeshLlmAgent (with @mesh.llm) ===
@app.tool()
@mesh.llm(provider={"capability": "llm"}, max_iterations=1)
@mesh.tool(capability="schema.t11", description="Normal then LLM injectable")
async def t11_normal_then_llm(prompt: str, llm: mesh.MeshLlmAgent = None) -> str:
    return f"Result for {prompt}"


# === Case 12: Normal + McpMeshTool + MeshLlmAgent (with @mesh.llm + dep) ===
@app.tool()
@mesh.llm(provider={"capability": "llm"}, max_iterations=1)
@mesh.tool(
    capability="schema.t12",
    description="All injectable types",
    dependencies=[{"capability": "dep_a"}],
)
async def t12_normal_meshtool_llm(
    q: str, svc: mesh.McpMeshTool = None, llm: mesh.MeshLlmAgent = None
) -> str:
    return f"Result for {q}"


# === Case 13: Pydantic model + MeshLlmAgent (with @mesh.llm) ===
class AnalysisContext(BaseModel):
    query: str = Field(..., description="The query to analyze")
    depth: int = Field(default=1, description="Analysis depth")


@app.tool()
@mesh.llm(provider={"capability": "llm"}, max_iterations=1)
@mesh.tool(capability="schema.t13", description="Pydantic model with LLM")
async def t13_pydantic_model_llm(
    ctx: AnalysisContext, llm: mesh.MeshLlmAgent = None
) -> str:
    return f"Result for {ctx.query}"


@mesh.agent(name="py-schema-agent", auto_run=True)
class SchemaAgent:
    pass
