"""
Processor Agent - Middle tier for observability tracing test.

This agent:
- Receives calls from orchestrator
- Chains to analyzer for the chain call flow
- Provides status endpoint for fan-out calls
"""

import logging
import time

import mesh
from fastmcp import FastMCP

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

app = FastMCP("Processor")


@app.tool()
@mesh.tool(
    capability="process_data",
    tags=["processor", "data"],
    version="1.0.0",
    dependencies=["analyze_data"],
)
async def process_data(
    data: dict,
    operation: str = "default",
    analyzer: mesh.McpMeshAgent = None,
) -> dict:
    """
    Process incoming data and chain to analyzer.

    In chain flow: orchestrator → processor → analyzer → storage
    """
    logger.info(f"process_data called with operation={operation}, data={data}")

    # Simulate processing work
    processed = {
        "original": data,
        "processed_at": time.time(),
        "processor_id": "processor-001",
        "operation": operation,
    }

    # Chain to analyzer
    logger.info("Chaining to analyzer...")
    try:
        analyzer_result = await analyzer(data=processed, analysis_type="full")
        processed["analyzer_result"] = analyzer_result
        logger.info(f"Analyzer returned: {analyzer_result}")
    except Exception as e:
        logger.error(f"Analyzer call failed: {e}")
        processed["analyzer_error"] = str(e)

    return processed


@app.tool()
@mesh.tool(
    capability="get_status",
    tags=["processor", "status"],
    version="1.0.0",
)
async def get_status(service: str = "all") -> dict:
    """
    Get processor status - called in fan-out pattern from orchestrator.

    This is a leaf call (no further chaining).
    """
    logger.info(f"get_status called for service={service}")

    # Simulate status check
    status = {
        "service": service,
        "status": "healthy",
        "uptime_seconds": 12345,
        "processed_count": 42,
        "timestamp": time.time(),
    }

    return status


@app.tool()
@mesh.tool(
    capability="processor_health",
    tags=["processor", "health"],
    version="1.0.0",
)
async def health_check() -> dict:
    """Health check endpoint."""
    return {"status": "healthy", "agent": "processor"}


def processor_health():
    """Health check function for mesh registration."""
    return True


@mesh.agent(
    name="processor",
    version="1.0.0",
    description="Data processor for tracing test",
    http_port=8080,
    enable_http=True,
    auto_run=True,
    health_check=processor_health,
    health_check_ttl=30,
)
class ProcessorAgent:
    pass
