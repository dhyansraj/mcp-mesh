"""Alpha provider - student lookup capability."""

import mesh
from fastmcp import FastMCP

app = FastMCP("py-alpha-provider")


@app.tool()
@mesh.tool(
    capability="student_lookup",
    description="Look up student information",
    tags=["student"],
)
async def get_student(id: str) -> dict:
    """Return student information."""
    return {"name": "Alice", "grade": "A", "source": "alpha-provider"}


@mesh.agent(
    name="py-alpha-provider",
    version="1.0.0",
    description="Student lookup provider",
    http_port=9060,
    auto_run=True,
)
class PyAlphaProvider:
    pass
