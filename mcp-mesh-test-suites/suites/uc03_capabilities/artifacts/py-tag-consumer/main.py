"""Consumer agent that uses tag selectors for dependencies."""

import mesh
from fastmcp import FastMCP

app = FastMCP("py-tag-consumer")


@app.tool()
@mesh.tool(
    capability="consumer",
    description="Fetch data requiring api tag",
    tags=["consumer"],
    dependencies=[
        {"capability": "data_service", "tags": ["api"]},  # Require api tag
    ],
)
async def fetch_required(
    query: str,
    data_service: mesh.McpMeshAgent = None,
) -> str:
    """Fetch data from provider that has 'api' tag."""
    if data_service is None:
        return "NO_PROVIDER"
    result = await data_service(query=query)
    return f"Required: {result}"


@app.tool()
@mesh.tool(
    capability="consumer",
    description="Fetch data preferring fast provider",
    tags=["consumer"],
    dependencies=[
        {"capability": "data_service", "tags": ["+fast"]},  # Prefer fast tag
    ],
)
async def fetch_prefer_fast(
    query: str,
    data_service: mesh.McpMeshAgent = None,
) -> str:
    """Fetch data preferring provider with 'fast' tag."""
    if data_service is None:
        return "NO_PROVIDER"
    result = await data_service(query=query)
    return f"PreferFast: {result}"


@app.tool()
@mesh.tool(
    capability="consumer",
    description="Fetch data excluding deprecated provider",
    tags=["consumer"],
    dependencies=[
        {"capability": "data_service", "tags": ["-deprecated"]},  # Exclude deprecated
    ],
)
async def fetch_exclude_deprecated(
    query: str,
    data_service: mesh.McpMeshAgent = None,
) -> str:
    """Fetch data excluding provider with 'deprecated' tag."""
    if data_service is None:
        return "NO_PROVIDER"
    result = await data_service(query=query)
    return f"ExcludeDeprecated: {result}"


@app.tool()
@mesh.tool(
    capability="consumer",
    description="Fetch data with combined filters",
    tags=["consumer"],
    dependencies=[
        {"capability": "data_service", "tags": ["api", "+accurate", "-deprecated"]},
    ],
)
async def fetch_combined(
    query: str,
    data_service: mesh.McpMeshAgent = None,
) -> str:
    """Fetch data requiring api, preferring accurate, excluding deprecated."""
    if data_service is None:
        return "NO_PROVIDER"
    result = await data_service(query=query)
    return f"Combined: {result}"


@mesh.agent(
    name="py-tag-consumer",
    version="1.0.0",
    description="Consumer agent with various tag selectors",
    http_port=9035,
    auto_run=True,
)
class PyTagConsumer:
    pass
