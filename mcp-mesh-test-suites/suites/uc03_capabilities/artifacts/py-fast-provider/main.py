"""Fast data provider - tags: api, fast"""

import mesh
from fastmcp import FastMCP

app = FastMCP("py-fast-provider")


@app.tool()
@mesh.tool(
    capability="data_service",
    description="Get data quickly (fast provider)",
    tags=["api", "fast"],
)
async def get_data(query: str) -> str:
    """Return data with fast provider identifier."""
    return f"FAST: {query}"


@mesh.agent(
    name="py-fast-provider",
    version="1.0.0",
    description="Fast data provider with api,fast tags",
    http_port=9030,
    auto_run=True,
)
class PyFastProvider:
    pass
