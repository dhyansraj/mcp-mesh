#!/usr/bin/env python3
"""Rogue schema-test producer (Python) — same capability, different shape.

Capability: employee_lookup, tags=["bad"]
Outputs Hardware {sku, model, price} — schema-aware consumer should evict this
(canonical hash sha256:5f1ac9c41f432516a62aebef8841df800fba29342d114eb3813788d16cfa690c).
"""

import mesh
from fastmcp import FastMCP
from pydantic import BaseModel


class Hardware(BaseModel):
    sku: str
    model: str
    price: float


app = FastMCP("Producer Bad (Python)")


@app.tool()
@mesh.tool(
    capability="employee_lookup",
    tags=["bad"],
    description="Returns Hardware (rogue, mis-registered as employee_lookup)",
)
def get_hardware(item_id: str) -> Hardware:
    return Hardware(sku="H123", model="X1 Carbon", price=1500.0)


@mesh.agent(
    name="producer-bad-py",
    version="1.0.0",
    description="Schema-test rogue producer (Python) with mismatched Hardware shape",
    http_port=9101,
    enable_http=True,
    auto_run=True,
)
class ProducerBadAgent:
    pass
