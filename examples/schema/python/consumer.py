#!/usr/bin/env python3
"""Schema-aware consumer (Python).

Depends on capability `employee_lookup` with subset-mode schema check
(expected_type=Employee). Producer-good wires; producer-bad (Hardware) is
evicted by the schema stage. Cross-runtime: also wires to TS/Java producer-good
because they declare the same canonical Employee hash.
"""

import mesh
from fastmcp import FastMCP
from pydantic import BaseModel


class Employee(BaseModel):
    name: str
    dept: str
    salary: float


app = FastMCP("Consumer (Python)")


@app.tool()
@mesh.tool(
    capability="schema_aware_lookup_py",
    description="Schema-aware consumer (subset mode) — Python",
    dependencies=[
        {
            "capability": "employee_lookup",
            "expected_type": Employee,
            "match_mode": "subset",
        }
    ],
)
async def lookup_with_schema(
    emp_id: str, lookup: mesh.McpMeshTool | None = None
) -> str:
    if lookup is None:
        return f"no compatible producer for {emp_id}"
    result = await lookup(employee_id=emp_id)
    return f"got: {result}"


@mesh.agent(
    name="consumer-py",
    version="1.0.0",
    description="Schema-aware consumer (Python) for issue #547 cross-runtime tests",
    http_port=9102,
    enable_http=True,
    auto_run=True,
)
class ConsumerAgent:
    pass
