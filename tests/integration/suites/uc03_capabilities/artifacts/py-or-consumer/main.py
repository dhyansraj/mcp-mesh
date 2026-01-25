"""Consumer agent that uses OR alternatives (nested array) for dependencies.

This tests the Issue #471 OR alternatives feature where dependencies can be
specified as arrays of specs - try each in order until one resolves.
"""

import mesh
from fastmcp import FastMCP

app = FastMCP("py-or-consumer")


@app.tool()
@mesh.tool(
    capability="or_consumer",
    description="Process using OR alternatives: prefer claude, fallback to gpt",
    tags=["consumer", "or-alternatives"],
    dependencies=[
        # OR alternatives: nested array of specs
        # Try claude first, fallback to gpt if claude unavailable
        [
            {"capability": "llm_service", "tags": ["claude"]},
            {"capability": "llm_service", "tags": ["gpt"]},
        ],
    ],
)
async def process_with_fallback(
    prompt: str,
    llm_service: mesh.McpMeshTool = None,
) -> str:
    """
    Process prompt using OR alternatives.

    Resolution order:
    1. Try to resolve with claude tag
    2. If unavailable, fallback to gpt tag
    3. If both unavailable, llm_service will be None
    """
    if llm_service is None:
        return "NO_PROVIDER"
    result = await llm_service(prompt=prompt)
    return f"OR_RESULT: {result}"


@mesh.agent(
    name="py-or-consumer",
    version="1.0.0",
    description="Consumer agent with OR alternatives dependency",
    http_port=9045,
    auto_run=True,
)
class PyOrConsumer:
    pass
