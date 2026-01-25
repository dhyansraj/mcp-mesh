"""Deprecated data provider - tags: api, deprecated"""

import mesh
from fastmcp import FastMCP

app = FastMCP("py-deprecated-provider")


@app.tool()
@mesh.tool(
    capability="data_service",
    description="Get data (deprecated provider)",
    tags=["api", "deprecated"],
)
async def get_data(query: str) -> str:
    """Return data with deprecated provider identifier."""
    return f"DEPRECATED: {query}"


@mesh.agent(
    name="py-deprecated-provider",
    version="1.0.0",
    description="Deprecated data provider with api,deprecated tags",
    http_port=9032,
    auto_run=True,
)
class PyDeprecatedProvider:
    pass
