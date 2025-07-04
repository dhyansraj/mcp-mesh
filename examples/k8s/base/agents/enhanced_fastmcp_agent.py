#!/usr/bin/env python3
"""
Enhanced FastMCP Agent with kwargs-configured capabilities

This demonstrates Phase 6 enhanced proxy auto-configuration:
- @mesh.tool with timeout, retry_count, custom_headers kwargs
- Streaming capabilities with streaming=True
- Session management with session_required=True
- Authentication requirements with auth_required=True
"""

from datetime import datetime
from typing import AsyncGenerator

import asyncio

import mesh
from fastmcp import FastMCP

# Single FastMCP server instance
app = FastMCP("Enhanced FastMCP Service")


# ENHANCED TOOLS with kwargs configuration
@app.tool()
@mesh.tool(
    capability="enhanced_time_service",
    tags=["system", "time", "enhanced"],
    timeout=10,
    retry_count=2,
    custom_headers={"X-Service-Type": "time", "X-Enhanced": "true"},
)
def get_enhanced_time() -> dict:
    """Get enhanced time with metadata - auto-configured with 10s timeout, 2 retries."""
    return {
        "timestamp": datetime.now().isoformat(),
        "timezone": "UTC",
        "service": "enhanced-time",
        "enhanced": True,
        "response_time_ms": 50,
    }


@app.tool()
@mesh.tool(
    capability="enhanced_math_service",
    dependencies=["enhanced_time_service"],
    timeout=15,
    retry_count=3,
    custom_headers={"X-Service-Type": "math", "X-Compute-Heavy": "true"},
)
def calculate_enhanced(
    a: float, b: float, operation: str = "add", time_service: mesh.McpMeshAgent = None
) -> dict:
    """Enhanced math with timestamp - auto-configured with 15s timeout, 3 retries."""
    if operation == "add":
        result = a + b
    elif operation == "multiply":
        result = a * b
    elif operation == "subtract":
        result = a - b
    elif operation == "divide":
        result = a / b if b != 0 else None
    else:
        result = 0

    # Get enhanced timestamp
    time_data = time_service() if time_service else {"timestamp": "unknown"}

    return {
        "operation": operation,
        "operands": [a, b],
        "result": result,
        "computed_at": time_data.get("timestamp"),
        "service": "enhanced-math",
        "enhanced": True,
    }


@app.tool()
@mesh.tool(
    capability="streaming_data_service",
    tags=["data", "streaming", "async"],
    streaming=True,
    timeout=300,  # Longer timeout for streaming
    custom_headers={"X-Stream-Type": "data", "X-Content-Type": "application/json"},
)
async def stream_data_processing(data_size: int = 10) -> AsyncGenerator[dict, None]:
    """Stream data processing results - auto-configured for streaming with 300s timeout."""
    yield {
        "event": "start",
        "data_size": data_size,
        "service": "streaming-data",
        "enhanced": True,
        "timestamp": datetime.now().isoformat(),
    }

    for i in range(data_size):
        await asyncio.sleep(0.1)  # Simulate processing
        yield {
            "event": "data",
            "index": i,
            "processed_data": f"item_{i}",
            "progress": (i + 1) / data_size,
            "timestamp": datetime.now().isoformat(),
        }

    yield {
        "event": "complete",
        "total_processed": data_size,
        "service": "streaming-data",
        "enhanced": True,
        "timestamp": datetime.now().isoformat(),
    }


@app.tool()
@mesh.tool(
    capability="secure_config_service",
    tags=["config", "secure", "authenticated"],
    auth_required=True,
    timeout=20,
    custom_headers={"X-Security-Level": "high", "X-Auth-Required": "true"},
)
def get_secure_config(config_type: str = "default") -> dict:
    """Get secure configuration - requires authentication, 20s timeout."""
    configs = {
        "default": {"level": "basic", "features": ["logging", "metrics"]},
        "advanced": {
            "level": "advanced",
            "features": ["logging", "metrics", "tracing", "security"],
        },
        "production": {
            "level": "production",
            "features": ["all"],
            "security": "enhanced",
        },
    }

    return {
        "config_type": config_type,
        "config": configs.get(config_type, configs["default"]),
        "retrieved_at": datetime.now().isoformat(),
        "service": "secure-config",
        "enhanced": True,
        "auth_verified": True,
    }


@app.tool()
@mesh.tool(
    capability="enhanced_session_counter",
    tags=["session", "stateful", "enhanced"],
    session_required=True,
    stateful=True,
    auto_session_management=True,
    timeout=30,
    custom_headers={"X-Session-Enabled": "true", "X-Stateful": "true"},
)
def enhanced_session_increment(
    session_id: str, increment: int = 1, metadata: dict = None
) -> dict:
    """Enhanced session counter with metadata - auto session management, 30s timeout."""
    import os

    # Enhanced agent identification
    agent_id = os.getenv("AGENT_ID", "enhanced-fastmcp-service")
    pod_ip = os.getenv("POD_IP", "localhost")
    container_name = os.getenv("HOSTNAME", "unknown")

    # Enhanced in-memory storage
    if not hasattr(enhanced_session_increment, "_enhanced_counters"):
        enhanced_session_increment._enhanced_counters = {}
        enhanced_session_increment._session_metadata = {}

    # Get or initialize counter and metadata
    current_count = enhanced_session_increment._enhanced_counters.get(session_id, 0)
    new_count = current_count + increment
    enhanced_session_increment._enhanced_counters[session_id] = new_count

    # Store session metadata
    if metadata:
        enhanced_session_increment._session_metadata[session_id] = metadata

    return {
        "session_id": session_id,
        "previous_count": current_count,
        "increment": increment,
        "new_count": new_count,
        "handled_by_agent": agent_id,
        "handled_by_pod": pod_ip,
        "handled_by_container": container_name,
        "timestamp": datetime.now().isoformat(),
        "total_sessions": len(enhanced_session_increment._enhanced_counters),
        "session_metadata": enhanced_session_increment._session_metadata.get(
            session_id
        ),
        "service": "enhanced-session",
        "enhanced": True,
        "auto_session_managed": True,
    }


# AGENT configuration - enhanced FastMCP service
@mesh.agent(
    name="enhanced-fastmcp-service",
    version="2.0.0",
    description="Enhanced FastMCP service with kwargs-configured capabilities",
    http_port=9094,
    enable_http=True,
    auto_run=True,
)
class EnhancedFastMCPService:
    """
    Enhanced agent with kwargs-configured capabilities.

    Demonstrates:
    - Enhanced proxy auto-configuration via kwargs
    - Timeout management (10s, 15s, 20s, 30s, 300s)
    - Retry policies (2, 3 retries)
    - Custom headers for service identification
    - Streaming capabilities with proper timeouts
    - Authentication requirements
    - Session management with auto-session handling
    """

    pass


# No main method needed!
# Enhanced mesh processor automatically handles:
# - Enhanced proxy creation with kwargs configuration
# - Timeout management per capability
# - Retry policies per capability
# - Custom header injection
# - Streaming auto-selection
# - Session management automation
# - Authentication flow handling
