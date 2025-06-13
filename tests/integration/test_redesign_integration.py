"""
Integration tests for the redesigned registration and dependency injection system.

These tests verify the full flow with real components running.
"""

import asyncio
import os
import subprocess
import time
from typing import Any

import aiohttp
import pytest
from mcp.server.fastmcp import FastMCP
from mcp_mesh import mesh_agent


class TestFullStackIntegration:
    """Test the full stack with real registry and agents."""

    @pytest.fixture
    async def start_registry(self):
        """Start a real registry for testing."""
        # Start registry in background
        env = os.environ.copy()
        env["DATABASE_URL"] = "./test_registry.db"
        env["PORT"] = "18080"  # Use different port for tests

        proc = subprocess.Popen(
            ["mcp-mesh-registry"],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        # Wait for registry to start
        await asyncio.sleep(2)

        # Verify it's running
        async with aiohttp.ClientSession() as session:
            async with session.get("http://localhost:18080/health") as resp:
                assert resp.status == 200

        yield "http://localhost:18080"

        # Cleanup
        proc.terminate()
        proc.wait()
        if os.path.exists("./test_registry.db"):
            os.remove("./test_registry.db")

    @pytest.mark.asyncio
    async def test_multi_function_registration_no_collision(self, start_registry):
        """Test that multiple functions in same process don't collide."""
        registry_url = start_registry

        # Create first "service" with greet function
        server1 = FastMCP("service1")

        @server1.tool()
        @mesh_agent(capability="greeting", version="1.0.0")
        def greet(name: str) -> str:
            return f"Hello {name} from service1"

        # Create second "service" with same function name
        server2 = FastMCP("service2")

        @server2.tool()
        @mesh_agent(capability="greeting", version="2.0.0")
        def greet(name: str) -> str:  # Same function name!
            return f"Greetings {name} from service2"

        # Set different agent names
        os.environ["MCP_MESH_AGENT_NAME"] = "service1"
        os.environ["MCP_MESH_REGISTRY_URL"] = registry_url

        # Process service1
        from mcp_mesh.runtime.processor import DecoratorProcessor

        processor1 = DecoratorProcessor(registry_url)
        await processor1.process_agents()

        # Change agent name for service2
        os.environ["MCP_MESH_AGENT_NAME"] = "service2"

        # Process service2
        processor2 = DecoratorProcessor(registry_url)
        await processor2.process_agents()

        # Verify both are registered
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{registry_url}/capabilities?name=greeting"
            ) as resp:
                data = await resp.json()

                # Should have 2 different agents providing greeting
                assert data["count"] == 2

                # Check agent IDs are different
                agent_ids = [cap["agent_id"] for cap in data["capabilities"]]
                assert len(set(agent_ids)) == 2  # Two unique agent IDs

                # Both should have UUID suffixes
                for agent_id in agent_ids:
                    assert len(agent_id.split("-")[-1]) == 8

    @pytest.mark.asyncio
    async def test_dependency_updates_via_heartbeat(self, start_registry):
        """Test that dependencies are updated via heartbeat."""
        registry_url = start_registry

        # Create a service that depends on date_service
        server = FastMCP("dependent-service")

        date_service_proxy: Any | None = None

        @server.tool()
        @mesh_agent(
            capability="time_greeting", dependencies=[{"capability": "date_service"}]
        )
        def timed_greet(name: str, date_service=None) -> str:
            nonlocal date_service_proxy
            date_service_proxy = date_service  # Capture for testing

            if date_service:
                return f"Hello {name}, date is {date_service()}"
            return f"Hello {name}, date service unavailable"

        os.environ["MCP_MESH_AGENT_NAME"] = "dependent"
        os.environ["MCP_MESH_REGISTRY_URL"] = registry_url

        # Process without date_service available
        from mcp_mesh.runtime.processor import DecoratorProcessor

        processor = DecoratorProcessor(registry_url)
        await processor.process_agents()

        # Verify dependency is None
        assert date_service_proxy is None

        # Now start date_service
        date_server = FastMCP("date-service")

        @date_server.tool()
        @mesh_agent(capability="date_service")
        def get_date() -> str:
            return "2024-01-01"

        os.environ["MCP_MESH_AGENT_NAME"] = "dateservice"

        # Process date service
        date_processor = DecoratorProcessor(registry_url)
        await date_processor.process_agents()

        # Wait for next heartbeat cycle
        await asyncio.sleep(2)

        # Verify dependency is now injected
        assert date_service_proxy is not None
        assert callable(date_service_proxy)

    @pytest.mark.asyncio
    async def test_version_constraint_filtering(self, start_registry):
        """Test that version constraints work correctly."""
        registry_url = start_registry

        # Register multiple versions of a service
        versions = ["0.9.0", "1.0.0", "1.5.0", "2.0.0", "3.0.0"]

        for v in versions:
            server = FastMCP(f"service-v{v}")

            # Create function dynamically
            def make_func(version):
                @server.tool()
                @mesh_agent(capability="versioned_service", version=version)
                def service_func() -> str:
                    return f"Version {version}"

                return service_func

            make_func(v)

            os.environ["MCP_MESH_AGENT_NAME"] = f"service-v{v}"
            processor = DecoratorProcessor(registry_url)
            await processor.process_agents()

        # Now create consumers with different version requirements
        test_cases = [
            (">=1.0.0", ["1.0.0", "1.5.0", "2.0.0", "3.0.0"]),
            (">=1.0.0,<2.0.0", ["1.0.0", "1.5.0"]),
            ("~1.5", ["1.5.0"]),  # ~1.5 means >=1.5.0, <1.6.0
        ]

        for constraint, expected_versions in test_cases:
            consumer = FastMCP(f"consumer-{constraint}")
            resolved_version = None

            @consumer.tool()
            @mesh_agent(
                capability="consumer",
                dependencies=[
                    {"capability": "versioned_service", "version": constraint}
                ],
            )
            def consume(versioned_service=None) -> str:
                nonlocal resolved_version
                if versioned_service:
                    resolved_version = versioned_service()
                return "ok"

            os.environ["MCP_MESH_AGENT_NAME"] = f"consumer-{constraint}"
            processor = DecoratorProcessor(registry_url)
            await processor.process_agents()

            # Check that resolved version is in expected range
            if resolved_version:
                version_num = resolved_version.split()[-1]
                assert version_num in expected_versions

    @pytest.mark.asyncio
    async def test_batched_operations_performance(self, start_registry):
        """Test that batched operations are more efficient."""
        registry_url = start_registry

        # Create many functions
        server = FastMCP("batch-test")
        num_functions = 50

        for i in range(num_functions):
            # Create function dynamically to avoid variable capture issues
            def make_func(n):
                @server.tool()
                @mesh_agent(capability=f"capability_{n}")
                def func() -> str:
                    return f"Function {n}"

                return func

            make_func(i)

        os.environ["MCP_MESH_AGENT_NAME"] = "batch-test"
        os.environ["MCP_MESH_REGISTRY_URL"] = registry_url

        # Measure registration time
        start_time = time.time()

        from mcp_mesh.runtime.processor import DecoratorProcessor

        processor = DecoratorProcessor(registry_url)

        # Count actual HTTP requests made
        original_post = processor.registry_client.post
        post_count = 0

        async def counting_post(*args, **kwargs):
            nonlocal post_count
            post_count += 1
            return await original_post(*args, **kwargs)

        processor.registry_client.post = counting_post

        await processor.process_agents()

        registration_time = time.time() - start_time

        # Should make only 1 POST request for all functions
        assert post_count == 1

        # Should complete quickly (under 1 second for 50 functions)
        assert registration_time < 1.0

        # Verify all are registered
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{registry_url}/agents") as resp:
                data = await resp.json()

                # Find our agent
                our_agent = None
                for agent in data["agents"]:
                    if agent["agent_id"].startswith("batch-test-"):
                        our_agent = agent
                        break

                assert our_agent is not None
                assert len(our_agent["metadata"]["tools"]) == num_functions


class TestDependencyInjectionMagic:
    """Test that the DI magic still works with new design."""

    @pytest.mark.asyncio
    async def test_decorator_order_preservation(self):
        """Test that server.tool caching works correctly."""
        server = FastMCP("order-test")

        # Track function calls
        call_log = []

        @server.tool()
        @mesh_agent(capability="test")
        def my_function(x: int) -> int:
            call_log.append(f"Called with {x}")
            return x * 2

        # Call the function
        result = my_function(5)
        assert result == 10
        assert call_log == ["Called with 5"]

        # Verify server.tool has cached it
        assert hasattr(server, "_tools")
        # The tool should be registered
        tools = server.list_tools()
        assert any(tool.name == "my_function" for tool in tools)

    @pytest.mark.asyncio
    async def test_proxy_injection_after_registration(self):
        """Test that proxies can be injected after server.tool caches function."""
        server = FastMCP("injection-test")

        @server.tool()
        @mesh_agent(capability="test", dependencies=[{"capability": "helper"}])
        def my_function(x: int, helper=None) -> str:
            if helper:
                return f"Result: {x} with helper: {helper()}"
            return f"Result: {x} without helper"

        # Initially no helper
        result1 = my_function(10)
        assert result1 == "Result: 10 without helper"

        # Simulate dependency becoming available
        def mock_helper():
            return "I'm helping!"

        # Inject the proxy (simulating what processor does)
        import functools

        original_func = (
            my_function.__wrapped__
            if hasattr(my_function, "__wrapped__")
            else my_function
        )

        @functools.wraps(original_func)
        def wrapper(*args, **kwargs):
            # Inject helper
            kwargs["helper"] = mock_helper
            return original_func(*args, **kwargs)

        # This simulates the runtime injection
        my_function.__wrapped__ = wrapper

        # Now helper should be available
        result2 = my_function(10)
        assert "with helper: I'm helping!" in result2
