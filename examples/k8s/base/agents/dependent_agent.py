#!/usr/bin/env python3
"""
Dependent Agent Example

This demonstrates an agent that depends on capabilities from other agents:
- Uses @mesh.tool with dependencies to require time_service capability
- Shows how dependency injection automatically resolves and injects services
- Minimal FastMCP setup with just two functions that depend on external services
"""

from datetime import datetime

import mesh
from fastmcp import FastMCP

# Single FastMCP server instance
app = FastMCP("Dependent Service")


# TESTING: Define multiple functions with McpMeshAgent to verify order handling
@app.tool()
@mesh.tool(capability="race_test_mcpmesh", dependencies=["time_service"])
def test_mcpmesh_first(
    test_data: str = "test", time_service: mesh.McpMeshAgent = None
) -> dict:
    """Test function with McpMeshAgent that's defined first."""
    timestamp = time_service() if time_service else "unknown"
    return {
        "test_data": test_data,
        "timestamp": timestamp,
        "proxy_type": "should_be_MCPClientProxy_if_order_matters",
        "function_order": "first",
    }


@app.tool()
@mesh.tool(capability="race_test_mcpmesh_second", dependencies=["time_service"])
def test_mcpmesh_second(
    test_data: str = "test", time_service: mesh.McpMeshAgent = None
) -> dict:
    """Test function with McpMeshAgent that's defined second."""
    timestamp = time_service() if time_service else "unknown"
    return {
        "test_data": test_data,
        "timestamp": timestamp,
        "proxy_type": "unified_mcp_proxy",
        "function_order": "second",
    }


@app.tool()
@mesh.tool(capability="report_service", dependencies=["time_service"])
def generate_report(
    title: str, content: str = "Sample content", time_service: mesh.McpMeshAgent = None
) -> dict:
    """Generate a timestamped report using the time service."""
    # Get timestamp from the injected time service
    timestamp = time_service() if time_service else "unknown"

    report = {
        "title": title,
        "content": content,
        "generated_at": timestamp,
        "agent": "dependent-service",
        "status": "completed",
    }

    return report


@app.tool()
@mesh.tool(capability="analysis_service", dependencies=["time_service"])
def analyze_data(
    data: list, analysis_type: str = "basic", time_service: mesh.McpMeshAgent = None
) -> dict:
    """Analyze data with timestamp from time service."""
    # Get timestamp from the injected time service
    timestamp = time_service() if time_service else "unknown"

    # Simple analysis
    if not data:
        result = {"error": "No data provided", "count": 0, "average": None}
    else:
        # Try to analyze as numbers, fallback to general analysis
        try:
            numbers = [float(x) for x in data]
            result = {
                "count": len(numbers),
                "sum": sum(numbers),
                "average": sum(numbers) / len(numbers),
                "min": min(numbers),
                "max": max(numbers),
            }
        except (ValueError, TypeError):
            # Fallback for non-numeric data
            result = {
                "count": len(data),
                "data_types": list(set(type(x).__name__ for x in data)),
                "sample": data[:3] if len(data) > 3 else data,
            }

    analysis = {
        "analysis_type": analysis_type,
        "result": result,
        "analyzed_at": timestamp,
        "agent": "dependent-service",
    }

    return analysis


@app.tool()
@mesh.tool(capability="full_mcp_inspector", dependencies=["time_service"])
async def inspect_remote_agent(
    agent_name: str = "fastmcp-service", time_service: mesh.McpMeshAgent = None
) -> dict:
    """Test Full MCP Proxy functionality using McpMeshAgent."""
    if not time_service:
        return {"error": "No time service available", "agent": "dependent-service"}

    # Get timestamp using basic call (McpMeshAgent compatibility)
    timestamp = time_service()

    inspection_result = {
        "agent_name": agent_name,
        "inspected_at": timestamp,
        "inspector": "dependent-service",
        "inspection_type": "full_mcp_test",
    }

    # Test Vanilla MCP Protocol methods (available with McpMeshAgent) - NOW WITH AWAIT!
    try:
        # Test list_tools (vanilla MCP method)
        tools = await time_service.list_tools()
        inspection_result["remote_tools"] = tools
        inspection_result["tools_count"] = len(tools) if tools else 0
    except Exception as e:
        inspection_result["tools_error"] = str(e)

    try:
        # Test list_resources (vanilla MCP method)
        resources = await time_service.list_resources()
        inspection_result["remote_resources"] = resources
        inspection_result["resources_count"] = len(resources) if resources else 0
    except Exception as e:
        inspection_result["resources_error"] = str(e)

    try:
        # Test list_prompts (vanilla MCP method)
        prompts = await time_service.list_prompts()
        inspection_result["remote_prompts"] = prompts
        inspection_result["prompts_count"] = len(prompts) if prompts else 0
    except Exception as e:
        inspection_result["prompts_error"] = str(e)

    inspection_result["note"] = (
        "Vanilla MCP async methods working perfectly with await!"
    )

    inspection_result["status"] = "completed"
    return inspection_result


@app.tool()
@mesh.tool(capability="session_test", dependencies=["session_counter"])
async def test_session_affinity(
    test_rounds: int = 3,
    session_counter: mesh.McpMeshAgent = None,  # ✅ Using McpMeshAgent for session support
) -> dict:
    """Test session affinity using explicit session management (Phase 6)."""
    if not session_counter:
        return {
            "error": "No session_counter service available",
            "agent": "dependent-service",
        }

    try:
        # Phase 6: Create session explicitly
        session_id = await session_counter.create_session()

        results = []
        handled_by_agents = set()

        for round_num in range(1, test_rounds + 1):
            try:
                # Call with explicit session ID for session affinity
                result = await session_counter.call_with_session(
                    session_id=session_id, increment=round_num
                )

                # Extract agent info from the response
                agent_id = "unknown"
                if isinstance(result, dict) and "structuredContent" in result:
                    agent_id = result["structuredContent"].get(
                        "handled_by_agent", "unknown"
                    )
                elif isinstance(result, dict):
                    agent_id = result.get("handled_by_agent", "unknown")

                results.append(
                    {"round": round_num, "response": result, "handled_by": agent_id}
                )

                handled_by_agents.add(agent_id)

            except Exception as e:
                results.append({"round": round_num, "error": str(e)})

        # Clean up session
        await session_counter.close_session(session_id)

        # Analyze session affinity
        unique_agents = len(handled_by_agents)
        session_affinity_working = unique_agents == 1

        return {
            "session_id": session_id,
            "test_rounds": test_rounds,
            "results": results,
            "handled_by_agents": list(handled_by_agents),
            "unique_agent_count": unique_agents,
            "session_affinity_working": session_affinity_working,
            "affinity_status": "SUCCESS" if session_affinity_working else "FAILED",
            "note": f"All {test_rounds} calls should go to the same agent instance for session affinity to work",
            "phase": "Phase 6 - Explicit session management",
            "tested_at": datetime.now().isoformat(),
        }

    except Exception as e:
        return {
            "error": f"Session affinity test failed: {str(e)}",
            "agent": "dependent-service",
            "phase": "Phase 6 - Explicit session management",
            "tested_at": datetime.now().isoformat(),
        }


# NEW ENHANCED FUNCTIONS - Less verbose thanks to enhanced proxy auto-configuration


@app.tool()
@mesh.tool(capability="enhanced_math_report", dependencies=["enhanced_math_service"])
def create_math_report(
    operations: list, enhanced_math: mesh.McpMeshAgent = None
) -> dict:
    """Create math report - enhanced proxy handles timeouts/retries automatically."""
    if not enhanced_math:
        return {"error": "Enhanced math service not available"}

    results = []
    for op in operations:
        # No timeout/retry logic needed - enhanced proxy handles it!
        result = enhanced_math(
            a=op.get("a", 0), b=op.get("b", 0), operation=op.get("operation", "add")
        )
        results.append(result)

    return {
        "report_type": "math_operations",
        "total_operations": len(operations),
        "results": results,
        "generated_at": datetime.now().isoformat(),
        "enhanced": True,
    }


@app.tool()
@mesh.tool(capability="enhanced_time_report", dependencies=["enhanced_time_service"])
def create_time_report(enhanced_time: mesh.McpMeshAgent = None) -> dict:
    """Create time report - enhanced proxy auto-configured with custom headers."""
    if not enhanced_time:
        return {"error": "Enhanced time service not available"}

    # Simple call - enhanced proxy adds headers and handles retries
    time_data = enhanced_time()

    return {
        "report_type": "time_status",
        "time_data": time_data,
        "report_generated_at": datetime.now().isoformat(),
        "enhanced": True,
        "note": "Enhanced proxy automatically added X-Service-Type and X-Enhanced headers",
    }


@app.tool()
@mesh.tool(capability="secure_config_report", dependencies=["secure_config_service"])
def get_secure_config_report(
    config_type: str = "production", secure_config: mesh.McpMeshAgent = None
) -> dict:
    """Get secure config report - enhanced proxy handles auth automatically."""
    if not secure_config:
        return {"error": "Secure config service not available"}

    # Simple call - enhanced proxy handles auth_required automatically
    config_data = secure_config(config_type=config_type)

    return {
        "report_type": "secure_configuration",
        "config_type": config_type,
        "config_data": config_data,
        "retrieved_at": datetime.now().isoformat(),
        "enhanced": True,
        "note": "Enhanced proxy automatically handled authentication requirements",
    }


@app.tool()
@mesh.tool(
    capability="enhanced_session_test", dependencies=["enhanced_session_counter"]
)
async def test_enhanced_session_management(
    test_rounds: int = 3,
    enhanced_session: mesh.McpMeshAgent = None,  # McpMeshAgent for full session support
) -> dict:
    """Test enhanced session management - auto-session handling."""
    if not enhanced_session:
        return {"error": "Enhanced session service not available"}

    try:
        # Enhanced proxy handles session creation automatically!
        # No manual session management needed
        results = []

        for round_num in range(1, test_rounds + 1):
            # Enhanced proxy auto-manages sessions
            result = await enhanced_session.call_tool_auto(
                session_id=f"auto-session-{round_num}",
                increment=round_num,
                metadata={"test_round": round_num, "enhanced": True},
            )
            results.append({"round": round_num, "result": result})

        return {
            "test_type": "enhanced_session_management",
            "test_rounds": test_rounds,
            "results": results,
            "tested_at": datetime.now().isoformat(),
            "enhanced": True,
            "note": "Enhanced proxy automatically managed session lifecycle",
        }

    except Exception as e:
        return {"error": f"Enhanced session test failed: {str(e)}", "enhanced": True}


@app.tool()
@mesh.tool(
    capability="streaming_data_consumer", dependencies=["streaming_data_service"]
)
async def consume_streaming_data(
    data_size: int = 5,
    streaming_service: mesh.McpMeshAgent = None,  # McpMeshAgent for streaming support
) -> dict:
    """Consume streaming data - enhanced proxy auto-selects streaming."""
    if not streaming_service:
        return {"error": "Streaming service not available"}

    try:
        # Enhanced proxy automatically detects streaming=True and uses async generator
        chunks = []
        async for chunk in streaming_service.call_tool_streaming(data_size=data_size):
            chunks.append(chunk)

        return {
            "consumption_type": "streaming_data",
            "total_chunks": len(chunks),
            "chunks": chunks,
            "consumed_at": datetime.now().isoformat(),
            "enhanced": True,
            "note": "Enhanced proxy automatically selected streaming mode",
        }

    except Exception as e:
        return {"error": f"Streaming consumption failed: {str(e)}", "enhanced": True}


# AGENT configuration - depends on time_service from the FastMCP agent
@mesh.agent(
    name="dependent-service",
    version="1.0.0",
    description="Dependent service that uses time_service capability",
    http_host="dependent-agent",
    http_port=9093,
    enable_http=True,
    auto_run=True,
)
class DependentService:
    """
    Agent that demonstrates dependency injection.

    This agent:
    1. Provides report_service and analysis_service capabilities
    2. Depends on time_service capability (from fastmcp-agent)
    3. Uses dependency injection to get timestamps from the time service
    4. Shows how mesh automatically resolves and injects dependencies
    """

    pass


# No main method needed!
# Mesh processor automatically handles:
# - Dependency resolution and injection
# - Service discovery and connection
# - HTTP server configuration
# - Service registration with mesh registry
