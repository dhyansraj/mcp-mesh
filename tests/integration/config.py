"""
Integration test configuration

This module contains configuration settings for integration tests.
"""

import os
from pathlib import Path

# Test timing configuration (in seconds)
REGISTRY_STARTUP_WAIT = 5          # Step 2: Wait after starting registry
AGENT_STABILIZATION_WAIT = 60      # Steps 5&9: Wait for agents to register and stabilize  
DEGRADATION_WAIT = 60               # Step 14: Wait for health degradation after stopping agent
PROCESS_TERMINATION_TIMEOUT = 10   # Timeout for graceful process termination

# Registry configuration
REGISTRY_HOST = os.getenv("MCP_MESH_REGISTRY_HOST", "localhost")
REGISTRY_PORT = int(os.getenv("MCP_MESH_REGISTRY_PORT", "8000"))
REGISTRY_URL = f"http://{REGISTRY_HOST}:{REGISTRY_PORT}"

# Test paths
PROJECT_ROOT = Path(__file__).parent.parent.parent
EXAMPLES_DIR = PROJECT_ROOT / "examples"
BIN_DIR = PROJECT_ROOT / "bin"

# Binary paths
REGISTRY_BINARY = BIN_DIR / "mcp-mesh-registry"
DEV_BINARY = BIN_DIR / "mcp-mesh-dev"

# Example script paths
HELLO_WORLD_SCRIPT = EXAMPLES_DIR / "hello_world.py"
SYSTEM_AGENT_SCRIPT = EXAMPLES_DIR / "system_agent.py"

# Expected capabilities (based on current example scripts)
HELLO_WORLD_CAPABILITIES = ["date_service", "info"]
HELLO_WORLD_DEPENDENCIES = ["info"]

SYSTEM_AGENT_CAPABILITIES = ["info", "date_service"]  
SYSTEM_AGENT_DEPENDENCIES = []  # System agent doesn't depend on others

# Log patterns for validation
REGISTRY_STARTUP_PATTERNS = [
    r"Starting.*registry",
    r"Server.*listening", 
    r"Registry.*started",
    r"Listening on"
]

AGENT_REGISTRATION_PATTERNS = [
    r"registered.*successfully",
    r"registration.*success",
    r"201"  # HTTP 201 Created
]

HEARTBEAT_PATTERNS = [
    r"heartbeat.*sent",
    r"heartbeat.*success", 
    r"200"  # HTTP 200 OK
]

DEPENDENCY_RESOLUTION_PATTERNS = [
    r"dependency.*resolved",
    r"dependency.*available",
    r"proxy.*created", 
    r"dependencies.*updated"
]

DEPENDENCY_REMOVAL_PATTERNS = [
    r"dependency.*unavailable",
    r"dependency.*removed",
    r"proxy.*unregistered",
    r"no.*provider.*found"
]

DEREGISTRATION_PATTERNS = [
    r"agent.*offline",
    r"agent.*degraded",
    r"agent.*unhealthy", 
    r"heartbeat.*timeout",
    r"agent.*deregistered"
]

# Error patterns to check for (these indicate problems)
ERROR_PATTERNS = [
    r"404",
    r"500", 
    r"ERROR",
    r"FATAL",
    r"panic:",
    r"failed to",
    r"error:",
    r"Error:",
    r"Exception",
    r"Traceback"
]

# Acceptable error patterns (these can be ignored in specific contexts)
ACCEPTABLE_STARTUP_ERRORS = [
    r"no agents found",      # Expected when registry starts empty
    r"empty response"        # Expected for empty registry
]

ACCEPTABLE_AGENT_ERRORS = [
    r"dependency.*not available",  # Expected when dependencies not yet available
    r"no.*provider.*found"         # Expected for unresolved dependencies
]

ACCEPTABLE_REGISTRY_ERRORS = [
    r"no.*provider.*found",  # Expected for unresolved dependencies
]

# Health status values
HEALTHY_STATUSES = ["healthy"]
DEGRADED_STATUSES = ["degraded", "unhealthy", "offline"]

# Test environment
TEST_TEMP_DIR_PREFIX = "mcp_mesh_test_"