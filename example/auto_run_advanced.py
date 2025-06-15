#!/usr/bin/env python3
"""
Advanced Auto-Run Example

This shows auto-run with environment variable overrides and advanced configuration.

Environment Variables (optional):
- MCP_MESH_AUTO_RUN=true/false
- MCP_MESH_AUTO_RUN_INTERVAL=seconds
- MCP_MESH_ENABLE_HTTP=true/false
- MCP_MESH_NAMESPACE=namespace_name

Run: python example/auto_run_advanced.py
"""

import logging
import os

# Set up comprehensive logging
logging.basicConfig(
    level=logging.DEBUG, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

# Configure environment
os.environ["MCP_MESH_REGISTRY_URL"] = "http://localhost:8000"

# Optional: Override auto-run settings via environment
# os.environ['MCP_MESH_AUTO_RUN'] = 'true'
# os.environ['MCP_MESH_AUTO_RUN_INTERVAL'] = '15'
# os.environ['MCP_MESH_NAMESPACE'] = 'production'

import mesh


# Define advanced agent with auto-run
@mesh.agent(
    name="advanced-auto-service",
    version="3.0.0",
    description="Advanced auto-run service with full configuration",
    enable_http=True,
    namespace="demo",
    health_interval=30,
    auto_run=True,  # This enables auto-run
    auto_run_interval=15,  # Custom heartbeat interval
    custom_metadata="Advanced auto-run example",
)
class AdvancedAutoAgent:
    """Advanced agent with comprehensive configuration."""

    pass


# Define comprehensive tool set
@mesh.tool(
    capability="advanced_greeting",
    description="Advanced greeting with metadata",
    version="3.0.0",
    tags=["greeting", "advanced", "auto-run"],
)
def advanced_hello(name: str = "Developer", language: str = "en") -> dict:
    """Advanced greeting function with language support."""
    greetings = {
        "en": f"Hello, {name}! Welcome to advanced auto-run!",
        "es": f"¡Hola, {name}! ¡Bienvenido al auto-run avanzado!",
        "fr": f"Bonjour, {name}! Bienvenue dans l'auto-run avancé!",
        "de": f"Hallo, {name}! Willkommen beim erweiterten Auto-Run!",
    }

    return {
        "message": greetings.get(language, greetings["en"]),
        "language": language,
        "name": name,
        "service": "advanced-auto-service",
        "auto_run_enabled": True,
    }


@mesh.tool(
    capability="calculator_advanced",
    description="Advanced calculator with error handling",
    version="3.0.0",
    tags=["math", "calculator", "advanced"],
)
def calculate_advanced(operation: str, x: float, y: float) -> dict:
    """Advanced calculator with comprehensive operations."""
    try:
        operations = {
            "add": x + y,
            "subtract": x - y,
            "multiply": x * y,
            "divide": x / y if y != 0 else None,
            "power": x**y,
            "modulo": x % y if y != 0 else None,
            "sqrt": x**0.5 if x >= 0 else None,
        }

        if operation not in operations:
            return {
                "error": f"Unknown operation: {operation}",
                "available_operations": list(operations.keys()),
            }

        result = operations[operation]
        if result is None:
            return {
                "error": f"Invalid operation: {operation}({x}, {y})",
                "reason": "Division by zero or invalid input",
            }

        return {
            "operation": operation,
            "operands": [x, y],
            "result": result,
            "service": "advanced-auto-service",
            "auto_run": True,
        }

    except Exception as e:
        return {
            "error": f"Calculation error: {str(e)}",
            "operation": operation,
            "operands": [x, y],
        }


@mesh.tool(
    capability="service_diagnostics_advanced",
    description="Comprehensive service diagnostics",
    version="3.0.0",
    tags=["diagnostics", "monitoring", "advanced"],
)
def get_advanced_diagnostics() -> dict:
    """Get comprehensive service diagnostics."""
    import platform
    import sys
    import time

    return {
        "service_info": {
            "name": "advanced-auto-service",
            "version": "3.0.0",
            "description": "Advanced auto-run service with full configuration",
            "auto_run_enabled": True,
            "auto_run_interval": 15,
        },
        "system_info": {
            "python_version": sys.version,
            "platform": platform.platform(),
            "architecture": platform.architecture(),
            "processor": platform.processor(),
        },
        "runtime_info": {
            "timestamp": time.time(),
            "uptime_estimate": "Available via service monitoring",
            "mcp_mesh_version": "Latest",
        },
        "capabilities": {
            "advanced_greeting": "Multi-language greeting system",
            "calculator_advanced": "Advanced mathematical operations",
            "service_diagnostics_advanced": "Comprehensive diagnostics",
        },
        "features": [
            "Auto-created FastMCP server",
            "Auto-registered MCP tools",
            "Auto-run service lifecycle",
            "HTTP API endpoints",
            "Mesh registry integration",
            "Health monitoring",
            "Environment variable configuration",
            "Graceful shutdown handling",
        ],
    }


if __name__ == "__main__":
    print("🚀 ADVANCED AUTO-RUN SERVICE DEMO")
    print("=" * 60)
    print("🔧 Features:")
    print("   • Auto-created FastMCP server")
    print("   • Auto-registered MCP tools")
    print("   • Auto-run service lifecycle")
    print("   • Environment variable overrides")
    print("   • Comprehensive error handling")
    print("   • Graceful shutdown")
    print("=" * 60)
    print("🎯 Starting advanced auto-run service...")
    print("💡 This script will stay alive automatically - no manual loops!")

    # The magic happens here - no while loop needed!
    mesh.start_auto_run_service()
