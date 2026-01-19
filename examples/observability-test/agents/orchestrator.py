"""
Orchestrator Agent - Entry point for observability tracing test.

This agent demonstrates distributed tracing with:
- Call A (chain): orchestrator → processor → analyzer → storage
- Call B (fan-out): orchestrator → processor AND orchestrator → storage
"""

import asyncio
import logging

import mesh
from fastmcp import FastMCP

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

app = FastMCP("Orchestrator")


@app.tool()
@mesh.tool(
    capability="orchestrate_workflow",
    tags=["orchestrator", "entry"],
    version="1.0.0",
    dependencies=["process_data", "get_status", "get_metrics"],
)
async def orchestrate_workflow(
    workflow_id: str,
    processor: mesh.McpMeshTool = None,
    status_checker: mesh.McpMeshTool = None,
    metrics_checker: mesh.McpMeshTool = None,
) -> dict:
    """
    Main orchestration tool that demonstrates tracing hierarchy.

    Call Flow:
    - Call A: Chain through all 4 agents (processor → analyzer → storage)
    - Call B: Fan-out to processor and storage in parallel
    """
    logger.info(f"Starting orchestrate_workflow for {workflow_id}")
    results = {"workflow_id": workflow_id, "calls": {}}

    # ========== CALL A: Chain through all agents ==========
    # This creates a deep trace: orchestrator → processor → analyzer → storage
    logger.info("CALL A: Starting chain call through all agents")
    try:
        chain_result = await processor(
            data={"workflow_id": workflow_id, "step": "initial"}, operation="chain"
        )
        results["calls"]["chain"] = {"success": True, "result": chain_result}
        logger.info(f"CALL A completed: {chain_result}")
    except Exception as e:
        logger.error(f"CALL A failed: {e}")
        results["calls"]["chain"] = {"success": False, "error": str(e)}

    # ========== CALL B: Fan-out to processor and storage ==========
    # This creates parallel traces from orchestrator
    logger.info("CALL B: Starting fan-out calls to processor and storage")
    try:
        # Run both calls in parallel
        status_task = status_checker(service="processor")
        metrics_task = metrics_checker(metric_type="all")

        status_result, metrics_result = await asyncio.gather(
            status_task, metrics_task, return_exceptions=True
        )

        results["calls"]["fanout"] = {
            "status": (
                status_result
                if not isinstance(status_result, Exception)
                else str(status_result)
            ),
            "metrics": (
                metrics_result
                if not isinstance(metrics_result, Exception)
                else str(metrics_result)
            ),
        }
        logger.info(
            f"CALL B completed: status={status_result}, metrics={metrics_result}"
        )
    except Exception as e:
        logger.error(f"CALL B failed: {e}")
        results["calls"]["fanout"] = {"success": False, "error": str(e)}

    logger.info(f"orchestrate_workflow completed for {workflow_id}")
    return results


@app.tool()
@mesh.tool(
    capability="simple_chain",
    tags=["orchestrator", "simple"],
    version="1.0.0",
    dependencies=["process_data"],
)
async def simple_chain(
    data: str,
    processor: mesh.McpMeshTool = None,
) -> dict:
    """Simple single chain call for basic testing."""
    logger.info(f"Starting simple_chain with data: {data}")
    result = await processor(data={"input": data}, operation="simple")
    return {"input": data, "result": result}


@app.tool()
@mesh.tool(
    capability="health_check",
    tags=["orchestrator", "health"],
    version="1.0.0",
)
async def health_check() -> dict:
    """Health check endpoint."""
    return {"status": "healthy", "agent": "orchestrator"}


def orchestrator_health():
    """Health check function for mesh registration."""
    return True


@mesh.agent(
    name="orchestrator",
    version="1.0.0",
    description="Entry point orchestrator for tracing test",
    http_port=8080,
    enable_http=True,
    auto_run=True,
    health_check=orchestrator_health,
    health_check_ttl=30,
)
class OrchestratorAgent:
    pass
