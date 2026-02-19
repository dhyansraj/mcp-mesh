"""Beta provider - schedule lookup capability."""

import mesh
from fastmcp import FastMCP

app = FastMCP("py-beta-provider")


@app.tool()
@mesh.tool(
    capability="schedule_lookup",
    description="Look up class schedule",
    tags=["schedule"],
)
async def get_schedule(id: str) -> list:
    """Return schedule as a list."""
    return [{"day": "Monday", "class": "Math"}, {"day": "Wednesday", "class": "Art"}]


@mesh.agent(
    name="py-beta-provider",
    version="1.0.0",
    description="Schedule lookup provider",
    http_port=9061,
    auto_run=True,
)
class PyBetaProvider:
    pass
