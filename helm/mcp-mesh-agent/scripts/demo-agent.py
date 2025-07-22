#!/usr/bin/env python3
"""
Demo Agent - Auto-Generated ConfigMap Example

This script demonstrates how to use the enhanced agentCode.scriptPath feature
to automatically create ConfigMaps from Python files.
"""

import mesh
from fastmcp import FastMCP

# Create FastMCP server instance
app = FastMCP("Demo Agent")


@app.tool()
@mesh.tool(capability="demo_service")
def demo_function(message: str = "Hello from auto-generated ConfigMap!") -> dict:
    """Demo function that shows the auto-generated ConfigMap in action."""
    return {
        "message": message,
        "source": "auto-generated-configmap",
        "agent": "demo-agent",
        "method": "helm-file-templating"
    }


@app.tool()
@mesh.tool(capability="config_info")
def get_config_info() -> dict:
    """Returns information about how this agent was configured."""
    return {
        "deployment_method": "helm-auto-configmap",
        "script_source": "helm/mcp-mesh-agent/scripts/demo-agent.py",
        "configmap_generation": "automatic",
        "benefits": [
            "No manual ConfigMap creation needed",
            "Version controlled with chart",
            "Simplified deployment workflow",
            "Automatic ConfigMap naming"
        ]
    }


# Configure the mesh agent
@mesh.agent(
    name="demo-agent",
    version="1.0.0",
    description="Demo agent showing auto-generated ConfigMap from scriptPath",
    http_host="demo-agent",
    http_port=9094,
    enable_http=True,
    auto_run=True,
)
class DemoAgent:
    """
    Demo agent that shows the enhanced Helm chart functionality.
    
    This agent demonstrates:
    1. Auto-generated ConfigMap from scriptPath
    2. Simplified deployment workflow
    3. Version-controlled agent scripts
    4. No manual ConfigMap management required
    """
    pass