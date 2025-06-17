"""
Comprehensive Integration Test for MCP Mesh System

This test validates the entire MCP Mesh system using real components and our new
testing infrastructure. It serves as the definitive test of system functionality.

🤖 AI CRITICAL GUIDANCE:
This is the MASTER integration test. It uses:
- Real MCP Mesh registry (Go)
- Real Python runtime and decorators
- Real CLI commands
- State validation against expected system behavior
- Contract validation against OpenAPI spec

When this test fails, it means something fundamental is broken.
DO NOT modify this test to make it pass - fix the underlying issue!

The test follows this pattern:
1. Clean system state
2. Start registry
3. Register agents with dependencies
4. Validate all system interactions
5. Test CLI commands
6. Validate final state against tests/state/integration-full-system.yaml
"""

import asyncio
import logging
import os
import subprocess

# Import the actual MCP Mesh components
import sys
import tempfile
import time
from pathlib import Path

import pytest

# Import our testing infrastructure
from tests.contract.test_metadata import (
    core_contract_test,
    integration_test,
)
from tests.state_validator import StateValidator

sys.path.append(
    str(Path(__file__).parent.parent.parent / "src" / "runtime" / "python" / "src")
)


class SystemTestFixture:
    """
    Manages the complete system setup for integration testing.

    🤖 AI USAGE PATTERN:
    This fixture handles the complex orchestration of starting registry,
    agents, and coordinating their interactions. It's designed to be
    robust and provide clear failure information.
    """

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.temp_dir = None
        self.registry_process = None
        self.registry_port = 8000
        self.registry_url = f"http://localhost:{self.registry_port}"
        self.agent_processes = []
        self.cleanup_needed = False

    async def setup(self):
        """Set up the complete test system."""
        self.logger.info("🚀 Setting up comprehensive integration test system")

        # Create temporary directory for test files
        self.temp_dir = tempfile.mkdtemp(prefix="mcp_mesh_test_")
        self.logger.info(f"Using temp directory: {self.temp_dir}")

        # Clean any existing processes
        await self._cleanup_existing_processes()

        # Start registry
        await self._start_registry()

        # Wait for registry to be ready
        await self._wait_for_registry()

        self.cleanup_needed = True
        self.logger.info("✅ System setup complete")

    async def teardown(self):
        """Clean up the test system."""
        if not self.cleanup_needed:
            return

        self.logger.info("🧹 Cleaning up integration test system")

        # Stop all agent processes
        for process in self.agent_processes:
            try:
                process.terminate()
                process.wait(timeout=5)
            except:
                try:
                    process.kill()
                except:
                    pass

        # Stop registry
        if self.registry_process:
            try:
                self.registry_process.terminate()
                self.registry_process.wait(timeout=5)
            except:
                try:
                    self.registry_process.kill()
                except:
                    pass

        # Clean up temp directory
        if self.temp_dir:
            import shutil

            try:
                shutil.rmtree(self.temp_dir)
            except:
                pass

        self.logger.info("✅ Cleanup complete")

    async def _cleanup_existing_processes(self):
        """Clean up any existing MCP Mesh processes."""
        try:
            # Kill any existing registry processes
            subprocess.run(
                ["pkill", "-f", "mcp-mesh-registry"], capture_output=True, timeout=5
            )
            # Give processes time to clean up
            await asyncio.sleep(1)
        except:
            pass

    async def _start_registry(self):
        """Start the MCP Mesh registry."""
        self.logger.info(f"Starting registry on port {self.registry_port}")

        # Build registry if needed
        registry_binary = (
            "/media/psf/Home/workspace/github/mcp-mesh/bin/mcp-mesh-registry"
        )
        if not os.path.exists(registry_binary):
            self.logger.info("Building registry binary...")
            build_result = subprocess.run(
                ["make", "build"],
                cwd="/media/psf/Home/workspace/github/mcp-mesh",
                capture_output=True,
                text=True,
            )
            if build_result.returncode != 0:
                raise RuntimeError(f"Failed to build registry: {build_result.stderr}")

        # Create database path in temp directory
        db_path = os.path.join(self.temp_dir, "test_registry.db")

        # Start registry process with environment variables
        env = os.environ.copy()
        env["HOST"] = "localhost"
        env["PORT"] = str(self.registry_port)
        env["DATABASE_URL"] = db_path
        env["LOG_LEVEL"] = "info"

        self.registry_process = subprocess.Popen(
            [registry_binary],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )

        self.logger.info(f"Registry started with PID {self.registry_process.pid}")

    async def _wait_for_registry(self, timeout: int = 10):
        """Wait for registry to be ready."""
        self.logger.info("Waiting for registry to be ready...")

        import aiohttp

        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        f"{self.registry_url}/health",
                        timeout=aiohttp.ClientTimeout(total=2),
                    ) as resp:
                        if resp.status == 200:
                            self.logger.info("✅ Registry is ready")
                            return
            except:
                pass

            await asyncio.sleep(0.5)

        # Check if process is still running
        if self.registry_process.poll() is not None:
            stdout, stderr = self.registry_process.communicate()
            raise RuntimeError(f"Registry process died: {stderr}")

        raise TimeoutError(f"Registry not ready after {timeout}s")

    async def create_test_agent_file(
        self, agent_name: str, capabilities: list[str], dependencies: list[str] = None
    ) -> str:
        """Create a test agent file."""
        dependencies = dependencies or []

        agent_code = f'''
"""Test agent: {agent_name}"""

import asyncio
import logging
from mcp_mesh import mesh_agent

logger = logging.getLogger(__name__)

@mesh_agent(
    agent_name="{agent_name}",
    capabilities={capabilities},
    dependencies={dependencies},
    health_interval=5,
    version="1.0.0"
)
async def {agent_name.replace("-", "_")}_main():
    """Main function for {agent_name} agent."""
    logger.info("Agent {agent_name} started successfully")

    # Simulate some work
    await asyncio.sleep(0.1)

    return "Agent {agent_name} is running"

if __name__ == "__main__":
    # Configure logging
    logging.basicConfig(level=logging.INFO)

    # Run the agent
    import sys
    import os

    # Set registry URL
    os.environ["MCP_MESH_REGISTRY_URL"] = "{self.registry_url}"

    # Start the mesh processor to handle registration
    from mcp_mesh.runtime.processor import DecoratorProcessor

    async def main():
        processor = DecoratorProcessor(registry_url="{self.registry_url}")

        try:
            # Process decorators (this will register the agent)
            results = await processor.process_all_decorators()
            logger.info(f"Registration results: {{results}}")

            # Keep the agent running
            logger.info("Agent {agent_name} is running...")
            while True:
                await asyncio.sleep(1)

        except KeyboardInterrupt:
            logger.info("Agent {agent_name} shutting down...")
        finally:
            await processor.cleanup()

    asyncio.run(main())
'''

        agent_file = os.path.join(self.temp_dir, f"{agent_name}.py")
        with open(agent_file, "w") as f:
            f.write(agent_code)

        return agent_file

    async def start_agent(self, agent_file: str, agent_name: str) -> subprocess.Popen:
        """Start an agent process."""
        self.logger.info(f"Starting agent {agent_name} from {agent_file}")

        # Set up environment
        env = os.environ.copy()
        env["MCP_MESH_REGISTRY_URL"] = self.registry_url
        env["PYTHONPATH"] = str(
            Path(__file__).parent.parent.parent / "src" / "runtime" / "python" / "src"
        )

        # Start agent process
        process = subprocess.Popen(
            ["python", agent_file],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        self.agent_processes.append(process)
        self.logger.info(f"Agent {agent_name} started with PID {process.pid}")

        return process

    async def wait_for_agent_registration(
        self, agent_name: str, timeout: int = 10
    ) -> bool:
        """Wait for an agent to register successfully."""
        self.logger.info(f"Waiting for agent {agent_name} to register...")

        import aiohttp

        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        f"{self.registry_url}/agents",
                        timeout=aiohttp.ClientTimeout(total=2),
                    ) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            agents = data.get("agents", [])
                            for agent in agents:
                                if (
                                    agent.get("id") == agent_name
                                    or agent.get("name") == agent_name
                                ):
                                    self.logger.info(
                                        f"✅ Agent {agent_name} registered successfully"
                                    )
                                    return True
            except:
                pass

            await asyncio.sleep(0.5)

        self.logger.error(f"❌ Agent {agent_name} failed to register within {timeout}s")
        return False


# Test fixture for pytest
@pytest.fixture
async def system_fixture():
    """Pytest fixture that provides a complete test system."""
    fixture = SystemTestFixture()
    try:
        await fixture.setup()
        yield fixture
    finally:
        await fixture.teardown()


class TestComprehensiveIntegration:
    """
    Comprehensive integration tests for the complete MCP Mesh system.

    🤖 AI CRITICAL TESTS:
    These tests validate the entire system working together.
    They use real components, not mocks, so failures indicate real problems.
    """

    @core_contract_test(
        description="Validates that registry starts and responds to health checks according to OpenAPI spec",
        api_contract_reference="api/mcp-mesh-registry.openapi.yaml#/paths/~1health/get",
        expected_behavior="Registry starts successfully and health endpoint returns proper schema",
    )
    async def test_registry_startup_and_health(self, system_fixture):
        """
        Test that the registry starts properly and responds to health checks.

        🤖 AI CONTRACT COMPLIANCE:
        This test validates the core registry health endpoint against OpenAPI spec.
        NEVER modify this test - if it fails, the registry is broken!
        """

        # Registry should already be started by fixture
        import aiohttp

        async with aiohttp.ClientSession() as session:
            # Test health endpoint
            async with session.get(f"{system_fixture.registry_url}/health") as resp:
                assert resp.status == 200, f"Health endpoint returned {resp.status}"

                data = await resp.json()

                # Validate required fields per OpenAPI spec
                required_fields = [
                    "status",
                    "version",
                    "uptime_seconds",
                    "timestamp",
                    "service",
                ]
                for field in required_fields:
                    assert (
                        field in data
                    ), f"Health response missing required field: {field}"

                # Validate field types and values
                assert data["status"] in [
                    "healthy",
                    "degraded",
                    "unhealthy",
                ], f"Invalid status: {data['status']}"
                assert isinstance(data["version"], str), "Version must be string"
                assert isinstance(data["uptime_seconds"], int), "Uptime must be integer"
                assert (
                    data["service"] == "mcp-mesh-registry"
                ), f"Invalid service name: {data['service']}"

            # Test root endpoint
            async with session.get(f"{system_fixture.registry_url}/") as resp:
                assert resp.status == 200, f"Root endpoint returned {resp.status}"

                data = await resp.json()
                required_fields = ["service", "version", "status", "endpoints"]
                for field in required_fields:
                    assert (
                        field in data
                    ), f"Root response missing required field: {field}"

                # Validate endpoints list
                expected_endpoints = [
                    "/health",
                    "/heartbeat",
                    "/agents",
                    "/agents/register",
                ]
                for endpoint in expected_endpoints:
                    assert (
                        endpoint in data["endpoints"]
                    ), f"Missing endpoint: {endpoint}"

    @integration_test(
        description="Validates complete agent registration and heartbeat flow",
        expected_behavior="Agents register successfully, maintain heartbeats, and dependency resolution works",
        related_files=["src/runtime/python/src/mcp_mesh/runtime/processor.py"],
    )
    async def test_agent_registration_and_heartbeat_flow(self, system_fixture):
        """
        Test the complete agent registration and heartbeat flow.

        This tests:
        1. Agent registration via Python decorator
        2. Heartbeat mechanism
        3. Registry agent listing
        4. Basic dependency resolution
        """

        # Create test agents
        hello_agent_file = await system_fixture.create_test_agent_file(
            "hello-world", ["greeting"], []
        )

        system_agent_file = await system_fixture.create_test_agent_file(
            "system-monitor", ["cpu_usage", "memory_usage"], ["greeting"]
        )

        # Start hello-world agent first (no dependencies)
        hello_process = await system_fixture.start_agent(
            hello_agent_file, "hello-world"
        )

        # Wait for registration
        assert await system_fixture.wait_for_agent_registration(
            "hello-world", timeout=15
        ), "Hello-world agent failed to register"

        # Start system-monitor agent (has dependency on hello-world)
        system_process = await system_fixture.start_agent(
            system_agent_file, "system-monitor"
        )

        # Wait for registration
        assert await system_fixture.wait_for_agent_registration(
            "system-monitor", timeout=15
        ), "System-monitor agent failed to register"

        # Give some time for heartbeats
        await asyncio.sleep(3)

        # Validate agents are listed correctly
        import aiohttp

        async with aiohttp.ClientSession() as session:
            async with session.get(f"{system_fixture.registry_url}/agents") as resp:
                assert resp.status == 200, f"List agents returned {resp.status}"

                data = await resp.json()
                assert "agents" in data, "Response missing agents field"
                assert "count" in data, "Response missing count field"
                assert data["count"] == 2, f"Expected 2 agents, got {data['count']}"

                # Find our agents
                agents_by_name = {agent["name"]: agent for agent in data["agents"]}

                assert "hello-world" in agents_by_name, "Hello-world agent not found"
                assert (
                    "system-monitor" in agents_by_name
                ), "System-monitor agent not found"

                # Validate hello-world agent
                hello_agent = agents_by_name["hello-world"]
                assert (
                    "greeting" in hello_agent["capabilities"]
                ), "Hello-world missing greeting capability"
                assert (
                    hello_agent["status"] == "healthy"
                ), f"Hello-world status: {hello_agent['status']}"

                # Validate system-monitor agent
                system_agent = agents_by_name["system-monitor"]
                assert (
                    "cpu_usage" in system_agent["capabilities"]
                ), "System-monitor missing cpu_usage capability"
                assert (
                    "memory_usage" in system_agent["capabilities"]
                ), "System-monitor missing memory_usage capability"
                assert (
                    hello_agent["status"] == "healthy"
                ), f"System-monitor status: {system_agent['status']}"

    @integration_test(
        description="Validates CLI commands work correctly with the running system",
        expected_behavior="CLI commands return correct information and exit codes",
        related_files=["src/core/cli/list.go", "src/core/cli/status.go"],
    )
    async def test_cli_commands(self, system_fixture):
        """
        Test that CLI commands work correctly with the running system.

        Tests:
        1. mcp-mesh-dev list command
        2. mcp-mesh-dev status command
        3. Proper exit codes and output format
        """

        # First ensure we have some agents registered
        hello_agent_file = await system_fixture.create_test_agent_file(
            "hello-cli-test", ["greeting"], []
        )
        hello_process = await system_fixture.start_agent(
            hello_agent_file, "hello-cli-test"
        )
        assert await system_fixture.wait_for_agent_registration(
            "hello-cli-test", timeout=15
        )

        # Test list command
        list_result = subprocess.run(
            [
                "/media/psf/Home/workspace/github/mcp-mesh/bin/meshctl",
                "list",
                "--registry-url",
                system_fixture.registry_url,
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )

        assert list_result.returncode == 0, f"List command failed: {list_result.stderr}"
        assert "hello-cli-test" in list_result.stdout, "List output missing test agent"
        assert "greeting" in list_result.stdout, "List output missing capability"

        # Test status command
        status_result = subprocess.run(
            [
                "/media/psf/Home/workspace/github/mcp-mesh/bin/meshctl",
                "status",
                "--registry-url",
                system_fixture.registry_url,
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )

        assert (
            status_result.returncode == 0
        ), f"Status command failed: {status_result.stderr}"
        # Status should show registry information
        assert (
            "registry" in status_result.stdout.lower()
            or "healthy" in status_result.stdout.lower()
        )

    @integration_test(
        description="Validates system state matches expected state definition",
        expected_behavior="Actual system state matches tests/state/integration-full-system.yaml",
        related_files=[
            "tests/state/integration-full-system.yaml",
            "tests/state_validator.py",
        ],
    )
    async def test_system_state_validation(self, system_fixture):
        """
        Test that the actual system state matches our expected state definition.

        This is the ultimate integration test - it validates that the entire system
        behaves according to our state definition file.
        """

        # Set up the expected system (2 agents with dependency)
        hello_agent_file = await system_fixture.create_test_agent_file(
            "hello-world", ["greeting"], []
        )
        system_agent_file = await system_fixture.create_test_agent_file(
            "system-monitor", ["cpu_usage", "memory_usage"], ["hello-world"]
        )

        # Start agents
        hello_process = await system_fixture.start_agent(
            hello_agent_file, "hello-world"
        )
        assert await system_fixture.wait_for_agent_registration(
            "hello-world", timeout=15
        )

        system_process = await system_fixture.start_agent(
            system_agent_file, "system-monitor"
        )
        assert await system_fixture.wait_for_agent_registration(
            "system-monitor", timeout=15
        )

        # Give system time to stabilize
        await asyncio.sleep(2)

        # Run state validation
        validator = StateValidator("tests/state/integration-full-system.yaml")
        success = await validator.validate_full_system()

        if not success:
            # Print detailed report for debugging
            report = validator.get_detailed_report()
            print("\n" + "=" * 60)
            print("SYSTEM STATE VALIDATION FAILED")
            print("=" * 60)
            print(report)
            print("=" * 60)

            # Also print failure summary
            failure_summary = validator.get_failure_summary()
            print(failure_summary)

            assert False, "System state validation failed. See detailed report above."

        # If we get here, all validations passed
        assert success, "System state validation should have passed"


# Helper function for running the complete integration test standalone
async def run_comprehensive_integration_test():
    """
    Standalone function to run the comprehensive integration test.

    🤖 AI USAGE:
    You can call this function directly to test the entire system:

    python -c "
    import asyncio
    from tests.contract.test_comprehensive_integration import run_comprehensive_integration_test
    asyncio.run(run_comprehensive_integration_test())
    "
    """
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)

    logger.info("🚀 Starting comprehensive MCP Mesh integration test")

    system = SystemTestFixture()
    try:
        await system.setup()

        # Create test instance
        test_instance = TestComprehensiveIntegration()

        # Run all tests
        logger.info("Running registry health test...")
        await test_instance.test_registry_startup_and_health(system)

        logger.info("Running agent registration test...")
        await test_instance.test_agent_registration_and_heartbeat_flow(system)

        logger.info("Running CLI commands test...")
        await test_instance.test_cli_commands(system)

        logger.info("Running system state validation...")
        await test_instance.test_system_state_validation(system)

        logger.info("✅ All integration tests passed!")

    except Exception as e:
        logger.error(f"❌ Integration test failed: {e}")
        raise
    finally:
        await system.teardown()


if __name__ == "__main__":
    # Allow running this test directly
    asyncio.run(run_comprehensive_integration_test())
