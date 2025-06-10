"""
Integration tests for HTTP wrapper functionality.

Tests the HTTP metadata configuration for mesh agents.
Note: Actual HTTP wrapper implementation is pending.
"""

import os

import pytest
from mcp.server.fastmcp import FastMCP
from mcp_mesh import mesh_agent


@pytest.mark.asyncio
async def test_http_metadata_configuration():
    """Test that HTTP metadata is properly configured."""

    # Create a simple MCP server
    server = FastMCP(name="test-http-agent")

    @server.tool()
    @mesh_agent(
        capability="test",
        enable_http=True,
        http_port=0,  # Auto-assign
    )
    def test_function() -> str:
        """Test function for HTTP wrapper."""
        return "Hello from HTTP-configured MCP!"

    # Check metadata
    metadata = test_function._mesh_metadata
    assert metadata["enable_http"] is True
    assert metadata["http_port"] == 0
    assert metadata["http_host"] == "0.0.0.0"


@pytest.mark.asyncio
async def test_http_metadata_with_custom_config():
    """Test HTTP metadata with custom configuration."""

    server = FastMCP(name="test-custom-http")

    @server.tool()
    @mesh_agent(
        capability="health-test",
        enable_http=True,
        http_port=8080,
        http_host="localhost",
        agent_name="health-test-agent",
    )
    def health_check() -> dict:
        """Health check endpoint."""
        return {"status": "healthy", "service": "test"}

    # Check metadata
    metadata = health_check._mesh_metadata
    assert metadata["enable_http"] is True
    assert metadata["http_port"] == 8080
    assert metadata["http_host"] == "localhost"
    assert metadata["agent_name"] == "health-test-agent"


@pytest.mark.asyncio
async def test_http_metadata_with_versioning():
    """Test that metadata endpoint provides correct version information."""

    server = FastMCP(name="test-metadata-agent")

    @server.tool()
    @mesh_agent(
        capability="metadata-test",
        enable_http=True,
        http_port=0,
        version="1.2.3",
        tags=["test", "http"],
    )
    def get_metadata() -> dict:
        """Get service metadata."""
        return {"name": "test-service", "version": "1.2.3"}

    # Check metadata
    metadata = get_metadata._mesh_metadata
    assert metadata["capability"] == "metadata-test"
    assert metadata["version"] == "1.2.3"
    assert metadata["tags"] == ["test", "http"]
    assert metadata["enable_http"] is True


def test_http_disabled_by_default():
    """Test that HTTP is disabled by default in non-container environments."""

    # Ensure we're not in container mode
    os.environ.pop("MCP_MESH_HTTP_ENABLED", None)
    os.environ.pop("KUBERNETES_SERVICE_HOST", None)
    os.environ.pop("CONTAINER_MODE", None)

    server = FastMCP(name="test-no-http-agent")

    @server.tool()
    @mesh_agent(
        capability="no-http-test",
        # Don't explicitly enable HTTP
    )
    def no_http_function() -> str:
        """Function without HTTP."""
        return "No HTTP here"

    # Check metadata - enable_http should be None (not set)
    metadata = no_http_function._mesh_metadata
    assert metadata["enable_http"] is None


def test_http_container_mode_configuration():
    """Test HTTP configuration in container mode."""

    # Simulate container environment
    os.environ["CONTAINER_MODE"] = "true"

    try:
        server = FastMCP(name="test-container-agent")

        @server.tool()
        @mesh_agent(
            capability="container-test",
            # Don't explicitly set enable_http
        )
        def container_function() -> str:
            """Container function."""
            return "Running in container"

        # Check metadata - in real implementation, this might auto-enable
        metadata = container_function._mesh_metadata
        assert metadata["enable_http"] is None  # Not auto-enabled in decorator

    finally:
        # Cleanup
        os.environ.pop("CONTAINER_MODE", None)


@pytest.mark.asyncio
async def test_multiple_http_configurations():
    """Test multiple agents with different HTTP configurations."""

    agents = []

    for i in range(3):
        server = FastMCP(name=f"test-concurrent-{i}")

        @mesh_agent(
            capability=f"concurrent-{i}",
            enable_http=True,
            http_port=0,
            agent_name=f"concurrent-agent-{i}",
        )
        @server.tool()
        def concurrent_test(agent_num: int = i) -> str:
            """Test concurrent agents."""
            return f"Agent {agent_num}"

        # Store metadata for verification
        agents.append(
            {"function": concurrent_test, "metadata": concurrent_test._mesh_metadata}
        )

    # Verify each agent has unique configuration
    for i, agent_info in enumerate(agents):
        metadata = agent_info["metadata"]
        assert metadata["capability"] == f"concurrent-{i}"
        assert metadata["agent_name"] == f"concurrent-agent-{i}"
        assert metadata["enable_http"] is True
        assert metadata["http_port"] == 0


@pytest.mark.asyncio
async def test_http_configuration_with_dependencies():
    """Test HTTP configuration for agents with dependencies."""

    server = FastMCP(name="test-deps-http")

    @server.tool()
    @mesh_agent(
        capability="deps-test",
        enable_http=True,
        http_port=9090,
        dependencies=["AuthService", "LogService"],
    )
    def protected_endpoint(data: str, AuthService=None, LogService=None) -> dict:
        """Protected endpoint with dependencies."""
        result = {"data": data}
        if AuthService:
            result["auth"] = "authenticated"
        if LogService:
            result["logged"] = True
        return result

    # Check metadata
    metadata = protected_endpoint._mesh_metadata
    assert metadata["enable_http"] is True
    assert metadata["http_port"] == 9090
    assert metadata["dependencies"] == ["AuthService", "LogService"]


def test_http_configuration_validation():
    """Test that HTTP configuration values are properly validated."""

    server = FastMCP(name="test-validation")

    # Test with various port configurations
    @mesh_agent(
        capability="port-test",
        enable_http=True,
        http_port=65535,  # Max valid port
    )
    @server.tool()
    def max_port_test() -> str:
        return "Max port"

    assert max_port_test._mesh_metadata["http_port"] == 65535

    # Test with string host
    @mesh_agent(
        capability="host-test",
        enable_http=True,
        http_host="0.0.0.0",
    )
    @server.tool()
    def host_test() -> str:
        return "Host test"

    assert host_test._mesh_metadata["http_host"] == "0.0.0.0"
