"""Agent with optional dependency that handles unavailable tools gracefully."""

import mesh
from fastmcp import FastMCP

app = FastMCP("py-optional-dep-agent")


@app.tool()
@mesh.tool(
    capability="smart_math",
    description="Add numbers, using calc_add tool if available",
    tags=["math", "smart"],
    dependencies=["calc_add"],  # Depend on the calc_add tool
)
async def smart_add(
    a: int,
    b: int,
    calc_add: mesh.McpMeshAgent = None,  # Optional - will be None if not available
) -> str:
    """Add numbers using calc_add tool if available, otherwise do it locally."""
    if calc_add is not None:
        try:
            result = await calc_add(a=a, b=b)
            return f"Calculator result: {result}"
        except Exception as e:
            return f"Calculator failed ({e}), local result: {a + b}"
    else:
        return f"Local result (no calculator): {a + b}"


@app.tool()
@mesh.tool(
    capability="smart_math",
    description="Check if calc_add tool is available",
    tags=["math", "status"],
    dependencies=["calc_add"],
)
async def check_calculator(
    calc_add: mesh.McpMeshAgent = None,
) -> str:
    """Check if calc_add tool is wired."""
    if calc_add is not None:
        return "Calculator is available"
    else:
        return "Calculator is not available"


@mesh.agent(
    name="py-optional-dep-agent",
    version="1.0.0",
    description="Agent with optional calc_add dependency",
    http_port=9022,
    auto_run=True,
)
class PyOptionalDepAgent:
    pass
