"""
Storage Agent - Leaf node for observability tracing test.

This agent:
- Receives calls from analyzer (chain flow)
- Receives direct calls from orchestrator (fan-out flow)
- Does NOT chain to any other agents (leaf node)
"""

import logging
import time
import uuid

import mesh
from fastmcp import FastMCP

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

app = FastMCP("Storage")

# In-memory storage for demo
_storage = {}


@app.tool()
@mesh.tool(
    capability="store_result",
    tags=["storage", "write"],
    version="1.0.0",
)
async def store_result(
    data: dict,
    storage_type: str = "generic",
) -> dict:
    """
    Store data - leaf node in the chain flow.

    In chain flow: orchestrator → processor → analyzer → storage (HERE)
    """
    logger.info(f"store_result called with storage_type={storage_type}")

    # Generate storage ID
    storage_id = str(uuid.uuid4())[:8]

    # Store the data
    record = {
        "id": storage_id,
        "data": data,
        "storage_type": storage_type,
        "stored_at": time.time(),
        "storage_node": "storage-001",
    }

    _storage[storage_id] = record

    logger.info(f"Stored data with id={storage_id}")

    return {
        "success": True,
        "storage_id": storage_id,
        "stored_at": record["stored_at"],
        "storage_type": storage_type,
    }


@app.tool()
@mesh.tool(
    capability="get_metrics",
    tags=["storage", "metrics"],
    version="1.0.0",
)
async def get_metrics(metric_type: str = "all") -> dict:
    """
    Get storage metrics - called in fan-out pattern from orchestrator.

    This is a leaf call (no further chaining).
    """
    logger.info(f"get_metrics called for metric_type={metric_type}")

    # Simulate metrics collection
    metrics = {
        "metric_type": metric_type,
        "total_records": len(_storage),
        "storage_used_bytes": 1024 * len(_storage),
        "read_ops": 100,
        "write_ops": 50,
        "latency_ms": 2.5,
        "timestamp": time.time(),
    }

    return metrics


@app.tool()
@mesh.tool(
    capability="retrieve_result",
    tags=["storage", "read"],
    version="1.0.0",
)
async def retrieve_result(storage_id: str) -> dict:
    """Retrieve stored data by ID."""
    logger.info(f"retrieve_result called for storage_id={storage_id}")

    if storage_id in _storage:
        return {"success": True, "record": _storage[storage_id]}
    else:
        return {"success": False, "error": "Record not found"}


@app.tool()
@mesh.tool(
    capability="storage_health",
    tags=["storage", "health"],
    version="1.0.0",
)
async def health_check() -> dict:
    """Health check endpoint."""
    return {"status": "healthy", "agent": "storage", "records": len(_storage)}


def storage_health():
    """Health check function for mesh registration."""
    return True


@mesh.agent(
    name="storage",
    version="1.0.0",
    description="Data storage for tracing test",
    http_port=8080,
    enable_http=True,
    auto_run=True,
    health_check=storage_health,
    health_check_ttl=30,
)
class StorageAgent:
    pass
