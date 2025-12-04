#!/usr/bin/env python3
"""
Simple FastAPI Example with APIRouter (Maya-style pattern)

This demonstrates the APIRouter pattern that Maya uses, where routes
are defined on a router and then included in the main app.
"""

import mesh
from fastapi import APIRouter, FastAPI
from mesh.types import McpMeshAgent

# Create the main FastAPI app
app = FastAPI(
    title="Simple FastAPI Router Example",
    description="Test APIRouter pattern with @mesh.route",
    version="1.0.0",
)

# Create an APIRouter (Maya's pattern)
router = APIRouter(prefix="/api/v1", tags=["api"])


@router.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy", "service": "simple-router-app"}


@router.get("/time")
@mesh.route(dependencies=["time_service"])
async def get_time(
    time_agent: McpMeshAgent = None,
):
    """
    Get current time from time_service.

    This route uses @mesh.route with APIRouter pattern.
    """
    if time_agent:
        try:
            result = await time_agent()
            return {
                "status": "success",
                "time": result,
                "dependency_injected": True,
            }
        except Exception as e:
            return {
                "status": "error",
                "error": str(e),
                "dependency_injected": True,
            }
    else:
        return {
            "status": "unavailable",
            "message": "time_service not injected",
            "dependency_injected": False,
        }


@router.get("/system-info")
@mesh.route(dependencies=["system_info_service"])
async def get_system_info(
    system_info_agent: McpMeshAgent = None,
):
    """
    Get enriched system info from system_info_service.

    This route uses @mesh.route with APIRouter pattern.
    """
    if system_info_agent:
        try:
            result = await system_info_agent()
            return {
                "status": "success",
                "data": result,
                "dependency_injected": True,
            }
        except Exception as e:
            return {
                "status": "error",
                "error": str(e),
                "dependency_injected": True,
            }
    else:
        return {
            "status": "unavailable",
            "message": "system_info_service not injected",
            "dependency_injected": False,
        }


@router.get("/both")
@mesh.route(dependencies=["time_service", "system_info_service"])
async def get_both(
    time_agent: McpMeshAgent = None,
    system_info_agent: McpMeshAgent = None,
):
    """
    Get both time and system info to test multiple dependencies.
    """
    results = {
        "time_service": None,
        "system_info_service": None,
        "dependencies_available": {
            "time_service": time_agent is not None,
            "system_info_service": system_info_agent is not None,
        },
    }

    if time_agent:
        try:
            results["time_service"] = await time_agent()
        except Exception as e:
            results["time_service"] = {"error": str(e)}

    if system_info_agent:
        try:
            results["system_info_service"] = await system_info_agent()
        except Exception as e:
            results["system_info_service"] = {"error": str(e)}

    return results


# Include the router in the main app
app.include_router(router)


# Root endpoint (on main app, not router)
@app.get("/")
async def root():
    """Root endpoint showing available routes."""
    return {
        "message": "Simple FastAPI Router Example (Maya-style)",
        "endpoints": [
            "/api/v1/health",
            "/api/v1/time",
            "/api/v1/system-info",
            "/api/v1/both",
        ],
    }


if __name__ == "__main__":
    print("Starting Simple FastAPI Router Example (Maya-style pattern)")
    print("Routes with @mesh.route on APIRouter:")
    print("  GET /api/v1/time          -> time_service")
    print("  GET /api/v1/system-info   -> system_info_service")
    print("  GET /api/v1/both          -> time_service, system_info_service")
    print()

    import uvicorn

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8080,
        log_level="info",
    )
