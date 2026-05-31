#!/usr/bin/env python3
"""
greeting-provider - MCP Mesh Agent (uc30 fixture for issue #1088).

Fast-cold-start Python provider exposing TWO independent capabilities so the
Java consumer under test can declare each via a DIFFERENT source:

  - greeting_service  -> declared by the consumer's @MeshRoute method
  - farewell_service  -> declared by the consumer's @MeshA2A method

Each returns a TYPED Pydantic model with a single `message: str` field. Because
the function is annotated with that model as its return type, the Python SDK's
FastMCPSchemaExtractor.extract_output_schema publishes a CLOSED object output
schema (properties.message + required: ["message"]) instead of the open object
schema that a bare ``dict[str, Any]`` produces. This satisfies the consumers'
declared expectedType contract — the route consumer's
@MeshDependency(expectedType=GreetingResponse.class) where
``record GreetingResponse(String message)`` stamps a subset constraint requiring
a ``message:string`` field; the registry's subset matcher only resolves the
provider when its published schema actually contains ``message``. Returning a
typed model (not a weakening) is the faithful contract: a capability consumed as
GreetingResponse / FarewellResponse must publish a schema that contains
``message``.

These typed returns also let the consumer's typed
McpMeshTool<GreetingResponse> / McpMeshTool<FarewellResponse> proxies prove the
expectedType flowed through the early-phase bean registration.
"""

import mesh
from fastmcp import FastMCP
from pydantic import BaseModel

# FastMCP server instance
app = FastMCP("GreetingProvider Service")


class GreetingResponse(BaseModel):
    """Typed output for greeting_service — publishes a closed schema with `message`."""

    message: str


class FarewellResponse(BaseModel):
    """Typed output for farewell_service — publishes a closed schema with `message`."""

    message: str


@app.tool()
@mesh.tool(
    capability="greeting_service",
    description="Return a structured greeting for a name",
    tags=["greeting"],
)
async def greeting_service(name: str = "world") -> GreetingResponse:
    """Greet `name`. Provides the 'greeting_service' capability."""
    return GreetingResponse(message=f"hello {name}")


@app.tool()
@mesh.tool(
    capability="farewell_service",
    description="Return a structured farewell for a name",
    tags=["farewell"],
)
async def farewell_service(name: str = "world") -> FarewellResponse:
    """Bid farewell to `name`. Provides the 'farewell_service' capability."""
    return FarewellResponse(message=f"bye {name}")


@mesh.agent(
    name="greeting-provider",
    version="1.0.0",
    description="Provider with greeting_service and farewell_service (uc30 #1088)",
    http_port=9100,
    enable_http=True,
    auto_run=True,
)
class GreetingProviderAgent:
    """Configures how mesh runs the FastMCP server for this provider."""

    pass
