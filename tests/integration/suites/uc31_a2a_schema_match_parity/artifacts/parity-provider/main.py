#!/usr/bin/env python3
"""
parity-provider - MCP Mesh Agent (uc31 fixture for issue #1089).

NEGATIVE counterpart to uc30's greeting-provider. Exposes ONE capability
`parity_cap` whose published OUTPUT SCHEMA is INTENTIONALLY INCOMPATIBLE (under
SUBSET matching) with what the two Java Spring consumers declare.

Both consumers declare the dependency with:
    expectedType = StrictResponse.class   // record StrictResponse(@NotNull String value)
    schemaMode   = SchemaMode.SUBSET
which stamps a SUBSET constraint requiring a `value: string` field on the
provider's output.

This provider instead returns a typed Pydantic model `MismatchResponse` that
has an `other: str` field and NO `value` field. Because the function is
annotated with that model as its return type, the Python SDK's
FastMCPSchemaExtractor publishes a CLOSED object output schema
({properties:{other:string}, required:["other"]}) that LACKS the consumer's
required `value`. Under SUBSET matching the registry computes `missing_field`
(the consumer requires `value`, the provider does not publish it) and EVICTS
the provider from the dependency — the dependency resolves 0/1.

This is the faithful negative contract: a capability consumed as StrictResponse
(requiring `value`) must publish a schema that contains `value`; this provider
deliberately does not, so a correct registry evicts it for BOTH @MeshRoute and
@MeshA2A consumers (after #1089 the A2A source matches identically to route).

The tool accepts a `name` arg so the consumers can call
`.call(Map.of("name", name))` exactly as in uc30.
"""

import mesh
from fastmcp import FastMCP
from pydantic import BaseModel

# FastMCP server instance
app = FastMCP("ParityProvider Service")


class MismatchResponse(BaseModel):
    """Typed output for parity_cap.

    Publishes a CLOSED schema {properties:{other:string}, required:["other"]}.
    It deliberately has NO `value` field, so a consumer declaring
    expectedType=StrictResponse (record with required `value: String`) under
    SUBSET matching gets a `missing_field` and the registry evicts this
    provider (DEPS 0/1).
    """

    other: str


@app.tool()
@mesh.tool(
    capability="parity_cap",
    description="Schema-incompatible capability for uc31 #1089 (returns `other`, not `value`)",
    tags=["parity"],
)
async def parity_cap(name: str = "world") -> MismatchResponse:
    """Provide the 'parity_cap' capability with an INCOMPATIBLE output schema."""
    return MismatchResponse(other=f"incompatible-{name}")


@mesh.agent(
    name="parity-provider",
    version="1.0.0",
    description="Provider with schema-INCOMPATIBLE parity_cap (uc31 #1089)",
    http_port=9100,
    enable_http=True,
    auto_run=True,
)
class ParityProviderAgent:
    """Configures how mesh runs the FastMCP server for this provider."""

    pass
