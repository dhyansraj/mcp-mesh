"""Agent with an unresolvable forward reference type hint.

The `value: "NonExistentType"` annotation cannot be resolved by
typing.get_type_hints(), exercising the exception path in
signature_analyzer.get_mesh_agent_parameter_names. The agent should
still come up (graceful degradation) and the runtime should log a
warning instead of silently swallowing the error.
"""

import mesh
from fastmcp import FastMCP

app = FastMCP("py-bad-hints-agent")


@app.tool()
@mesh.tool(
    capability="ping",
    description="Ping tool with an unresolvable forward reference",
    tags=["ping"],
)
def ping(value: "NonExistentType") -> str:  # noqa: F821
    """Return pong regardless of the (unresolvable) hint."""
    return "pong"


@mesh.agent(
    name="py-bad-hints-agent",
    version="1.0.0",
    description="Agent with an unresolvable forward reference type hint",
    http_port=9024,
    auto_run=True,
)
class PyBadHintsAgent:
    pass
