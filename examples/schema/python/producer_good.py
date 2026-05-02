#!/usr/bin/env python3
"""Schema-test producer (Python) — Employee shape that matches the consumer.

Capability: employee_lookup, tags=["good"]
Outputs Employee {name, dept, salary} — the canonical cross-runtime shape
(sha256:48882e31915113ed70ee620b2245bfcf856e4e146e2eb6e37700809d7338e732).
"""

import mesh
from fastmcp import FastMCP
from pydantic import BaseModel


class Employee(BaseModel):
    name: str
    dept: str
    salary: float


app = FastMCP("Producer Good (Python)")


@app.tool()
@mesh.tool(
    capability="employee_lookup",
    tags=["good"],
    description="Return an Employee record (matching shape)",
)
def get_employee(employee_id: str) -> Employee:
    return Employee(name="Alice", dept="Engineering", salary=120000.0)


@mesh.agent(
    name="producer-good-py",
    version="1.0.0",
    description="Schema-test producer (Python) with matching Employee shape",
    http_port=9100,
    enable_http=True,
    auto_run=True,
)
class ProducerGoodAgent:
    pass
