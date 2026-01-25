"""Accurate data provider - tags: api, accurate"""

import mesh
from fastmcp import FastMCP

app = FastMCP("py-accurate-provider")


@app.tool()
@mesh.tool(
    capability="data_service",
    description="Get data accurately (accurate provider)",
    tags=["api", "accurate"],
)
async def get_data(query: str) -> str:
    """Return data with accurate provider identifier."""
    return f"ACCURATE: {query}"


@mesh.agent(
    name="py-accurate-provider",
    version="1.0.0",
    description="Accurate data provider with api,accurate tags",
    http_port=9031,
    auto_run=True,
)
class PyAccurateProvider:
    pass
