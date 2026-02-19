"""Dual-dependency consumer for dep_index alignment test (issue #572).

Declares two dependencies in specific order:
  dep_index=0: student_lookup (from alpha provider)
  dep_index=1: schedule_lookup (from beta provider)

If dep_index alignment is broken (old bug), when only beta is running:
  - dep 0 would incorrectly appear available (beta wired to wrong index)
  - dep 1 would incorrectly appear unavailable
"""

import mesh
from fastmcp import FastMCP

app = FastMCP("py-dual-consumer")


@app.tool()
@mesh.tool(
    capability="enrollment_check",
    description="Check enrollment using student and schedule data",
    tags=["consumer", "dual-dep"],
    dependencies=[
        {"capability": "student_lookup"},  # dep_index=0 -> alpha provider
        {"capability": "schedule_lookup"},  # dep_index=1 -> beta provider
    ],
)
async def check_enrollment(
    id: str,
    student_service: mesh.McpMeshTool = None,
    schedule_service: mesh.McpMeshTool = None,
) -> dict:
    """Check enrollment by looking up student and schedule data."""
    result = {
        "student_available": student_service is not None,
        "schedule_available": schedule_service is not None,
        "student": None,
        "schedule": None,
    }

    if student_service is not None:
        try:
            result["student"] = await student_service(id=id)
        except Exception as e:
            result["student_error"] = str(e)

    if schedule_service is not None:
        try:
            result["schedule"] = await schedule_service(id=id)
        except Exception as e:
            result["schedule_error"] = str(e)

    return result


@mesh.agent(
    name="py-dual-consumer",
    version="1.0.0",
    description="Consumer with two dependencies for dep_index alignment test",
    http_port=9062,
    auto_run=True,
)
class PyDualConsumer:
    pass
