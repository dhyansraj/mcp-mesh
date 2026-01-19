"""
Analyzer Agent - Middle tier for observability tracing test.

This agent:
- Receives calls from processor
- Chains to storage for the chain call flow
"""

import logging
import time

import mesh
from fastmcp import FastMCP

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

app = FastMCP("Analyzer")


@app.tool()
@mesh.tool(
    capability="analyze_data",
    tags=["analyzer", "data"],
    version="1.0.0",
    dependencies=["store_result"],
)
async def analyze_data(
    data: dict,
    analysis_type: str = "basic",
    storage: mesh.McpMeshTool = None,
) -> dict:
    """
    Analyze incoming data and chain to storage.

    In chain flow: orchestrator → processor → analyzer → storage
    """
    logger.info(f"analyze_data called with analysis_type={analysis_type}, data={data}")

    # Simulate analysis work
    analysis = {
        "input_data": data,
        "analyzed_at": time.time(),
        "analyzer_id": "analyzer-001",
        "analysis_type": analysis_type,
        "findings": {
            "data_quality": "good",
            "anomalies_detected": 0,
            "confidence_score": 0.95,
        },
    }

    # Chain to storage
    logger.info("Chaining to storage...")
    try:
        storage_result = await storage(data=analysis, storage_type="analysis_result")
        analysis["storage_result"] = storage_result
        logger.info(f"Storage returned: {storage_result}")
    except Exception as e:
        logger.error(f"Storage call failed: {e}")
        analysis["storage_error"] = str(e)

    return analysis


@app.tool()
@mesh.tool(
    capability="quick_analyze",
    tags=["analyzer", "quick"],
    version="1.0.0",
)
async def quick_analyze(data: dict) -> dict:
    """
    Quick analysis without storage - leaf call.
    """
    logger.info(f"quick_analyze called with data={data}")

    return {
        "input": data,
        "quick_result": "analyzed",
        "score": 0.85,
        "timestamp": time.time(),
    }


@app.tool()
@mesh.tool(
    capability="analyzer_health",
    tags=["analyzer", "health"],
    version="1.0.0",
)
async def health_check() -> dict:
    """Health check endpoint."""
    return {"status": "healthy", "agent": "analyzer"}


def analyzer_health():
    """Health check function for mesh registration."""
    return True


@mesh.agent(
    name="analyzer",
    version="1.0.0",
    description="Data analyzer for tracing test",
    http_port=8080,
    enable_http=True,
    auto_run=True,
    health_check=analyzer_health,
    health_check_ttl=30,
)
class AnalyzerAgent:
    pass
