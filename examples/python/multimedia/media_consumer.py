#!/usr/bin/env python3
"""
media-consumer - MCP Mesh Media Consumer Agent

Demonstrates consuming resource_links produced by another mesh agent.
Depends on the media-producer agent's capabilities (report_generator,
chart_generator) to show how media flows through the mesh.
"""

import mesh
from fastmcp import FastMCP

app = FastMCP("Media Consumer")


@app.tool()
@mesh.tool(
    capability="report_summarizer",
    description="Requests a report from the producer and describes the received resource_link",
    dependencies=["report_generator"],
)
async def summarize_report(
    topic: str = "AI",
    report_generator: mesh.McpMeshTool = None,
) -> str:
    """Request a report from the media-producer and describe what we received."""
    if not report_generator:
        return "Error: report_generator dependency not available"

    result = await report_generator(topic=topic)

    if isinstance(result, dict) and result.get("type") == "resource_link":
        resource = result.get("resource", {})
        uri = resource.get("uri", "unknown")
        name = resource.get("name", "unknown")
        mime = resource.get("mimeType", "unknown")
        desc = resource.get("description", "")
        size = resource.get("size")
        size_info = f", size={size} bytes" if size is not None else ""
        return (
            f"Received resource_link from media-producer:\n"
            f"  Name: {name}\n"
            f"  URI:  {uri}\n"
            f"  Type: {mime}\n"
            f"  Description: {desc}{size_info}"
        )

    return f"Received non-resource_link result: {result}"


@app.tool()
@mesh.tool(
    capability="media_describer",
    description="Requests a chart from the producer and describes the received media",
    dependencies=["chart_generator"],
)
async def describe_media(
    data: str = "Q1:30,Q2:45,Q3:60,Q4:50",
    chart_generator: mesh.McpMeshTool = None,
) -> str:
    """Request a chart from the media-producer and describe the media we received."""
    if not chart_generator:
        return "Error: chart_generator dependency not available"

    result = await chart_generator(data=data)

    if isinstance(result, dict) and result.get("type") == "resource_link":
        resource = result.get("resource", {})
        uri = resource.get("uri", "unknown")
        name = resource.get("name", "unknown")
        mime = resource.get("mimeType", "unknown")
        desc = resource.get("description", "")
        size = resource.get("size")
        size_info = f", size={size} bytes" if size is not None else ""
        return (
            f"Received chart media from media-producer:\n"
            f"  Name: {name}\n"
            f"  URI:  {uri}\n"
            f"  Type: {mime}\n"
            f"  Description: {desc}{size_info}"
        )

    return f"Received non-resource_link result: {result}"


@mesh.agent(
    name="media-consumer",
    version="1.0.0",
    description="Agent that consumes resource_links from the media-producer",
    http_port=9201,
    enable_http=True,
    auto_run=True,
)
class MediaConsumerAgent:
    pass
