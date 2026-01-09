#!/usr/bin/env python3
"""
MCP Mesh FastAPI Example with @mesh.route Integration

This example demonstrates FastAPI integration with MCP Mesh dependency injection:
1. Regular FastAPI route handlers
2. @mesh.route decorators for automatic dependency injection
3. Graceful degradation when dependencies are unavailable

This is a development testing app for the @mesh.route decorator implementation.

Requirements:
    pip install fastapi uvicorn

Usage:
    python fastapi_app.py

    # Or manually with uvicorn:
    uvicorn fastapi_app:app --reload --host 0.0.0.0 --port 8080
"""

from typing import Optional

import mesh
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from mesh.types import McpMeshAgent

# Create FastAPI app
app = FastAPI(
    title="MCP Mesh FastAPI Example",
    description="Example FastAPI app with @mesh.route dependency injection",
    version="1.0.0",
)


# ===== REGULAR FASTAPI ROUTES (NO MESH INTEGRATION) =====


@app.get("/")
async def root():
    """Root endpoint - standard FastAPI route."""
    return {
        "message": "MCP Mesh FastAPI Example",
        "status": "running",
        "endpoints": {
            "health": "/health",
            "benchmark": "/api/v1/benchmark-services",
            "upload": "/api/v1/upload-resume",
            "process": "/api/v1/process-document",
            "user": "/api/v1/user/{user_id}",
        },
    }


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy", "service": "fastapi-example"}


# ===== MESH.ROUTE DECORATED ENDPOINTS =====
# These will use dependency injection once the API pipeline is implemented


@app.post("/api/v1/upload-resume")
@mesh.route(dependencies=["time_service"])
async def upload_resume(
    request: Request,
    file: UploadFile = File(...),
    time_agent: McpMeshAgent = None,  # Will be injected by MCP Mesh (time_service)
):
    """
    Upload and process a resume file using dependency injection.

    Dependencies:
    - time_service: For timestamp generation and time-based operations
    - data_service: For data processing and validation
    """
    try:
        # Get user data from request (simulated)
        user_data = {"email": "user@example.com", "name": "John Doe"}

        # Validate file
        if not file.filename or not file.filename.endswith(".pdf"):
            raise HTTPException(status_code=400, detail="Only PDF files are supported")

        # Read file content
        file_content = await file.read()
        file_size_mb = len(file_content) / (1024 * 1024)

        # Get current timestamp from time service
        current_time = None
        if time_agent:
            try:
                # Call the injected time service directly
                current_time = time_agent()
            except Exception as e:
                current_time = f"Time service error: {e}"
        else:
            current_time = "2024-01-15T10:30:00Z (time service unavailable)"

        # Simple file processing (no data service for now)
        processed_data = {
            "status": "processed_locally",
            "filename": file.filename,
            "size_mb": round(file_size_mb, 2),
        }

        # Build response based on service availability
        result = {
            "filename": file.filename,
            "size_mb": round(file_size_mb, 2),
            "uploaded_at": current_time,
            "data_processing": processed_data,
            "dependencies_status": {
                "time_service": "available" if time_agent else "unavailable"
            },
        }

        # TODO: Update user profile with extracted data
        # if user_service:
        #     await user_service.update_profile(user_data['email'], simulated_result)

        return {
            "status": "success",
            "message": "Resume processed successfully",
            "data": result,
            "user": user_data,
            "dependencies_available": {"time_service": time_agent is not None},
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Processing failed: {str(e)}")


@app.get("/api/v1/benchmark-services")
@mesh.route(dependencies=["time_service", "system_info_service"])
async def benchmark_services(
    time_agent: McpMeshAgent = None,  # Will be injected by MCP Mesh (time_service)
    system_info_agent: McpMeshAgent = None,  # Will be injected by MCP Mesh (system_info_service)
):
    """
    Benchmark and time both time_service and system_info_service calls.

    Dependencies:
    - time_service: For current time
    - system_info_service: For enriched system information
    """
    import time

    try:
        results = {"benchmark_started_at": time.time(), "services": {}}

        # Test time_service
        if time_agent:
            start_time = time.time()
            try:
                time_result = await time_agent()
                end_time = time.time()
                results["services"]["time_service"] = {
                    "status": "success",
                    "response_time_ms": round((end_time - start_time) * 1000, 2),
                    "result": time_result,
                }
            except Exception as e:
                end_time = time.time()
                results["services"]["time_service"] = {
                    "status": "error",
                    "response_time_ms": round((end_time - start_time) * 1000, 2),
                    "error": str(e),
                }
        else:
            results["services"]["time_service"] = {
                "status": "unavailable",
                "response_time_ms": 0,
                "error": "Service not injected",
            }

        # Test system_info_service
        if system_info_agent:
            start_time = time.time()
            try:
                system_result = await system_info_agent(include_timestamp=True)
                end_time = time.time()
                results["services"]["system_info_service"] = {
                    "status": "success",
                    "response_time_ms": round((end_time - start_time) * 1000, 2),
                    "result": system_result,
                }
            except Exception as e:
                end_time = time.time()
                results["services"]["system_info_service"] = {
                    "status": "error",
                    "response_time_ms": round((end_time - start_time) * 1000, 2),
                    "error": str(e),
                }
        else:
            results["services"]["system_info_service"] = {
                "status": "unavailable",
                "response_time_ms": 0,
                "error": "Service not injected",
            }

        # Calculate total benchmark time
        results["benchmark_completed_at"] = time.time()
        results["total_benchmark_time_ms"] = round(
            (results["benchmark_completed_at"] - results["benchmark_started_at"])
            * 1000,
            2,
        )

        # Summary
        successful_services = [
            name
            for name, data in results["services"].items()
            if data["status"] == "success"
        ]
        results["summary"] = {
            "total_services_tested": len(results["services"]),
            "successful_services": len(successful_services),
            "failed_services": len(results["services"]) - len(successful_services),
            "fastest_service": min(
                (
                    name
                    for name, data in results["services"].items()
                    if data["status"] == "success"
                ),
                key=lambda name: results["services"][name]["response_time_ms"],
                default=None,
            ),
            "dependencies_available": {
                "time_service": time_agent is not None,
                "system_info_service": system_info_agent is not None,
            },
        }

        return results

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Benchmark failed: {str(e)}")


@app.post("/api/v1/process-document")
@mesh.route(dependencies=["system_info_service"])
async def process_document(
    request: Request,
    document_type: str = "text",
    system_info_agent: McpMeshAgent = None,  # Will be injected by MCP Mesh (system_info_service)
):
    """
    Generic document processing endpoint.

    Dependencies:
    - system_info_service: For system information
    """
    try:
        # Get request body
        body = (
            await request.json()
            if request.headers.get("content-type") == "application/json"
            else {}
        )
        content = body.get("content", "Sample document content")

        # Get system info and configuration from injected services
        system_info = None
        if system_info_agent:
            try:
                # Call the injected system info service
                system_info = system_info_agent(include_timestamp=True)
            except Exception as e:
                system_info = {"error": f"System info service error: {e}"}
        else:
            system_info = {"message": "System info service unavailable"}

        # Static config since config_service is a resource, not a callable tool
        config_info = {
            "message": "Static config - using default document processing settings",
            "max_file_size": "10MB",
            "supported_formats": ["text", "json", "xml"],
        }

        # Process with dependency injection
        processing_result = {
            "status": "processed" if system_info_agent else "pending",
            "document_type": document_type,
            "content_preview": content[:100] + "..." if len(content) > 100 else content,
            "processed_at": (
                system_info.get("enriched_at", "2024-01-01T12:00:00Z")
                if isinstance(system_info, dict)
                else "2024-01-01T12:00:00Z"
            ),
            "system_info": system_info,
            "config_info": config_info,
            "dependencies_status": {
                "system_info_service": (
                    "available" if system_info_agent else "unavailable"
                )
            },
        }

        if system_info_agent is None:
            processing_result["message"] = (
                "Document queued - system info service not available"
            )
        else:
            processing_result["message"] = (
                "Document processed with system info and static config"
            )

        return processing_result

    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Document processing failed: {str(e)}"
        )


@app.get("/api/v1/user/{user_id}")
async def get_user_profile(user_id: str, request: Request):
    """
    Get user profile information.

    No dependencies - uses static/mock data for demo purposes.
    """
    try:
        # Static auth and user data for demo
        auth_status = "demo_authenticated"

        user_data = {
            "id": user_id,
            "name": f"Demo User {user_id}",
            "email": f"user{user_id}@example.com",
            "status": "active",
            "created_at": "2024-01-01T12:00:00Z",
        }

        return {
            "user": user_data,
            "auth_status": auth_status,
            "note": "Demo endpoint - no dependency injection required",
            "request_info": {
                "path": request.url.path,
                "method": request.method,
                "client_ip": request.client.host if request.client else "unknown",
            },
        }

    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"User profile fetch failed: {str(e)}"
        )


# ===== ERROR HANDLERS =====


@app.exception_handler(404)
async def not_found_handler(request: Request, exc):
    return JSONResponse(
        status_code=404,
        content={
            "error": "Not Found",
            "message": f"Path {request.url.path} not found",
            "available_endpoints": [
                "/",
                "/health",
                "/api/v1/upload-resume",
                "/api/v1/process-document",
                "/api/v1/user/{user_id}",
            ],
        },
    )


# ===== DEVELOPMENT SERVER =====

if __name__ == "__main__":
    print("🚀 Starting MCP Mesh FastAPI Example")
    print("📖 Visit http://localhost:8080/docs for interactive API documentation")
    print("🔍 Visit http://localhost:8080 for service information")
    print()
    print("🧪 Test endpoints:")
    print("  GET  /health")
    print("  GET  /api/v1/benchmark-services")
    print("  POST /api/v1/upload-resume")
    print("  POST /api/v1/process-document")
    print("  GET  /api/v1/user/123")
    print()
    print("✅ @mesh.route dependency injection is active")
    print("   Services will be injected automatically when available")
    print()

    try:
        import uvicorn

        uvicorn.run(
            app,  # Use the app object directly instead of module string
            host="0.0.0.0",
            port=8080,
            reload=False,  # Disabled for MCP Mesh focus - no file watching
            log_level="info",
        )
    except ImportError:
        print("❌ uvicorn not installed. Install with:")
        print("   pip install uvicorn")
        print()
        print("Or run manually:")
        print("   uvicorn fastapi_app:app --reload --host 0.0.0.0 --port 8080")
