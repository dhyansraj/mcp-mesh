"""Report agent that depends on calculator tools for computations."""

import mesh
from fastmcp import FastMCP

app = FastMCP("py-report-agent")


@app.tool()
@mesh.tool(
    capability="reporting",
    description="Generate a sum report by calling calculator",
    tags=["report", "summary"],
    dependencies=["calc_add"],  # Depend on the calc_add tool
)
async def sum_report(
    numbers: list[int],
    calc_add: mesh.McpMeshTool = None,  # Injected tool (will be McpMeshTool)
) -> str:
    """Generate a report summing all numbers using calculator."""
    if not numbers:
        return "No numbers provided"

    if calc_add is None:
        # Fallback to local calculation
        total = sum(numbers)
        return f"Sum of {numbers} = {total} (local)"

    # Use the injected calc_add tool
    total = numbers[0]
    for num in numbers[1:]:
        result = await calc_add(a=total, b=num)
        total = result

    return f"Sum of {numbers} = {total}"


@app.tool()
@mesh.tool(
    capability="reporting",
    description="Generate a product report by calling calculator",
    tags=["report", "summary"],
    dependencies=["calc_multiply"],  # Depend on the calc_multiply tool
)
async def product_report(
    numbers: list[int],
    calc_multiply: mesh.McpMeshTool = None,  # Injected tool
) -> str:
    """Generate a report multiplying all numbers using calculator."""
    if not numbers:
        return "No numbers provided"

    if calc_multiply is None:
        # Fallback to local calculation
        total = 1
        for num in numbers:
            total *= num
        return f"Product of {numbers} = {total} (local)"

    # Use the injected calc_multiply tool
    total = numbers[0]
    for num in numbers[1:]:
        result = await calc_multiply(a=total, b=num)
        total = result

    return f"Product of {numbers} = {total}"


@mesh.agent(
    name="py-report-agent",
    version="1.0.0",
    description="Report agent that uses calculator tools for computations",
    http_port=9021,
    auto_run=True,
)
class PyReportAgent:
    pass
