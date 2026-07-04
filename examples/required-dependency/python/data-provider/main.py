#!/usr/bin/env python3
"""
data-provider - MCP Mesh Agent

A MCP Mesh agent generated using meshctl scaffold.
"""

from typing import Any

import mesh
from fastmcp import FastMCP

# FastMCP server instance
app = FastMCP("DataProvider Service")


# ===== TOOLS =====

@app.tool()
@mesh.tool(
    capability="data_service",
    description="Returns a row of source data for reports",
    tags=["data"],
)
async def data_service() -> dict:
    """
    Provide source data that the report consumer depends on.

    Returns:
        A dict of sample data.
    """
    return {"revenue": 1250, "currency": "USD", "region": "emea"}


# ===== TOOL PARAMETER EXAMPLES (uncomment and adapt) =====
#
# Tool functions can accept typed parameters. The mesh SDK generates
# JSON Schema from the type hints automatically.
#
# @app.tool()
# @mesh.tool(capability="process", description="Process data", tags=["tools"])
# async def process(
#     text: str,                          # required string
#     count: int = 1,                     # optional int with default
#     threshold: float = 0.5,             # optional float with default
#     verbose: bool = False,              # optional boolean with default
# ) -> str:
#     return f"Processed {text} x{count}"


# ===== DEPENDENCY INJECTION EXAMPLE (uncomment and adapt) =====
#
# Declare dependencies to call tools on other agents in the mesh.
# The mesh runtime injects McpMeshTool instances by keyword name.
#
# @app.tool()
# @mesh.tool(
#     capability="orchestrate",
#     description="Calls another agent's tool",
#     tags=["tools"],
#     dependencies=["calculator"],          # declare dependency on "calculator" capability
# )
# async def orchestrate(
#     input_text: str,
#     calculator: mesh.McpMeshTool = None,  # injected by mesh (matches dependency name)
# ) -> str:
#     if calculator is None:
#         return "calculator dependency not available"
#     result = await calculator({"expression": "2 + 2"})
#     return f"Calculator says: {result}"


# ===== MULTIMODAL EXAMPLE (uncomment and adapt) =====
#
# Return media (images, PDFs, files) from tools using MediaResult.
# The LLM automatically resolves resource_link objects to native image blocks.
#
# @app.tool()
# @mesh.tool(capability="chart_gen", description="Generate a chart", tags=["tools"])
# async def generate_chart(query: str) -> ResourceLink:
#     png_bytes = render_chart(query)
#     return await mesh.MediaResult(
#         data=png_bytes, filename="chart.png", mime_type="image/png",
#         name="Chart", description=query,
#     )
#
# Accept media URIs with MediaParam type hints:
#
# @app.tool()
# @mesh.tool(capability="image_analyzer", description="Analyze an image", tags=["tools"])
# async def analyze_image(
#     question: str,
#     image: mesh.MediaParam("image/*") = None,
#     llm: mesh.MeshLlmAgent = None,
# ) -> str:
#     media = [image] if image else []
#     return await llm(question, media=media)


@mesh.agent(
    name="data-provider",
    version="1.0.0",
    description="MCP Mesh agent for data-provider",
    http_port=8080,
    enable_http=True,
    auto_run=True,
)
class DataProviderAgent:
    """
    Agent class that configures how mesh should run the FastMCP server.

    The mesh processor will:
    1. Discover the 'app' FastMCP instance
    2. Apply dependency injection to decorated functions
    3. Start the FastMCP HTTP server on the configured port
    4. Register all capabilities with the mesh registry
    """

    pass


# No main method needed!
# Mesh processor automatically handles:
# - FastMCP server discovery and startup
# - Dependency injection between functions
# - HTTP server configuration
# - Service registration with mesh registry
