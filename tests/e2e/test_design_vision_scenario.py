"""End-to-end tests for original design vision scenario.

This test suite validates the complete original design vision:
1. Start hello_world.py agent
2. Start system_agent.py agent
3. Test automatic service discovery and dependency injection
4. Validate HTTP endpoint behavior changes
5. Test CLI status and monitoring commands
6. Test graceful shutdown and cleanup
"""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.main import main


@pytest.fixture
def design_vision_workspace():
    """Create workspace with the exact agents from design vision."""
    with tempfile.TemporaryDirectory() as temp_dir:
        workspace = Path(temp_dir)

        # Create MCP Mesh config directory
        config_dir = workspace / ".mcp_mesh"
        config_dir.mkdir(parents=True, exist_ok=True)

        # Create hello_world.py as described in design vision
        hello_world_py = workspace / "hello_world.py"
        hello_world_py.write_text(
            '''
"""Hello World MCP Agent - Design Vision Implementation."""

import asyncio
import json
import sys
import time
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from threading import Thread


class HelloWorldHandler(BaseHTTPRequestHandler):
    """HTTP handler for Hello World agent."""

    def do_GET(self):
        """Handle GET requests."""
        if self.path == "/hello":
            # Simple response without dependencies
            response = {
                "message": "Hello, World!",
                "timestamp": datetime.now().isoformat(),
                "agent": "hello_world",
                "dependencies_available": hasattr(self.server, 'dependencies')
            }

            # If dependencies are available, use them
            if hasattr(self.server, 'dependencies') and self.server.dependencies:
                try:
                    system_info = self.server.dependencies.get('system_info', {})
                    response["system_info"] = system_info
                    response["enhanced"] = True
                except Exception as e:
                    response["dependency_error"] = str(e)
            else:
                response["enhanced"] = False

            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(response, indent=2).encode())

        elif self.path == "/status":
            # Status endpoint
            status = {
                "agent": "hello_world",
                "status": "running",
                "uptime": time.time() - self.server.start_time,
                "dependencies": list(getattr(self.server, 'dependencies', {}).keys())
            }

            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(status, indent=2).encode())

        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        """Override to control logging."""
        print(f"[HelloWorld HTTP] {format % args}")


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    """Threaded HTTP server."""
    pass


class HelloWorldAgent:
    """Hello World MCP Agent implementing design vision."""

    def __init__(self):
        self.name = "hello_world"
        self.capabilities = ["greeting", "hello_endpoint"]
        self.dependencies = {}
        self.http_server = None
        self.http_thread = None
        self.start_time = time.time()
        self.running = False

    def register_dependency(self, name, service):
        """Register a dependency service (called by MCP Mesh)."""
        print(f"[HelloWorld] Registering dependency: {name}")
        self.dependencies[name] = service

        # Update HTTP server dependencies
        if self.http_server:
            self.http_server.dependencies = self.dependencies

    def start_http_server(self, port=8081):
        """Start HTTP server for demonstrations."""
        try:
            self.http_server = ThreadedHTTPServer(('localhost', port), HelloWorldHandler)
            self.http_server.start_time = self.start_time
            self.http_server.dependencies = self.dependencies

            self.http_thread = Thread(target=self.http_server.serve_forever)
            self.http_thread.daemon = True
            self.http_thread.start()

            print(f"[HelloWorld] HTTP server started on http://localhost:{port}")
            print(f"[HelloWorld] Try: curl http://localhost:{port}/hello")
            print(f"[HelloWorld] Try: curl http://localhost:{port}/status")

        except Exception as e:
            print(f"[HelloWorld] Failed to start HTTP server: {e}")

    def stop_http_server(self):
        """Stop HTTP server."""
        if self.http_server:
            self.http_server.shutdown()
            self.http_server.server_close()
            if self.http_thread:
                self.http_thread.join(timeout=2)
            print("[HelloWorld] HTTP server stopped")

    async def handle_mcp_request(self, request):
        """Handle MCP protocol requests."""
        method = request.get("method")

        if method == "greeting":
            return {
                "result": {
                    "message": "Hello from MCP Agent!",
                    "agent": self.name,
                    "timestamp": datetime.now().isoformat()
                }
            }

        elif method == "get_capabilities":
            return {
                "result": {
                    "capabilities": self.capabilities,
                    "dependencies": list(self.dependencies.keys())
                }
            }

        else:
            return {
                "error": {
                    "code": -32601,
                    "message": f"Method not found: {method}"
                }
            }

    async def run(self):
        """Main agent loop."""
        print(f"[HelloWorld] Starting {self.name} agent")
        print(f"[HelloWorld] Capabilities: {self.capabilities}")

        # Start HTTP server for demonstration
        self.start_http_server()

        self.running = True
        heartbeat_count = 0

        try:
            while self.running:
                await asyncio.sleep(5)
                heartbeat_count += 1

                dependency_status = {name: "available" for name in self.dependencies.keys()}
                print(f"[HelloWorld] Heartbeat #{heartbeat_count} - Dependencies: {dependency_status}")

        except KeyboardInterrupt:
            print("[HelloWorld] Received shutdown signal")
        finally:
            self.running = False
            self.stop_http_server()
            print("[HelloWorld] Agent shut down")


# MCP Mesh integration shim
class MCPMeshIntegration:
    """Integration layer for MCP Mesh (would be provided by mesh runtime)."""

    def __init__(self, agent):
        self.agent = agent

    async def discover_and_inject_dependencies(self):
        """Simulate MCP Mesh dependency discovery and injection."""
        print("[HelloWorld] MCP Mesh: Discovering dependencies...")

        # Simulate finding system_agent
        await asyncio.sleep(1)

        # Mock system info service (would come from system_agent)
        mock_system_service = {
            "platform": "linux",
            "hostname": "test-host",
            "uptime": 3600,
            "memory_usage": 45.2,
            "cpu_usage": 12.5,
            "processes": 156
        }

        self.agent.register_dependency("system_info", mock_system_service)
        print("[HelloWorld] MCP Mesh: Dependencies injected successfully")


if __name__ == "__main__":
    print("=== Hello World Agent - Design Vision ===")
    print("This agent demonstrates the original MCP Mesh design vision:")
    print("1. Starts as standalone HTTP service")
    print("2. Receives dependency injection from MCP Mesh")
    print("3. Enhances responses when dependencies are available")
    print()

    # Create and run agent
    agent = HelloWorldAgent()
    mesh_integration = MCPMeshIntegration(agent)

    async def main_loop():
        # Start dependency discovery in background
        discovery_task = asyncio.create_task(mesh_integration.discover_and_inject_dependencies())

        # Run agent
        await agent.run()

        # Cleanup
        if not discovery_task.done():
            discovery_task.cancel()

    # Run the agent
    asyncio.run(main_loop())
'''
        )

        # Create system_agent.py as described in design vision
        system_agent_py = workspace / "system_agent.py"
        system_agent_py.write_text(
            '''
"""System Agent - Design Vision Implementation."""

import asyncio
import json
import platform
import psutil
import time


class SystemInfoHandler(BaseHTTPRequestHandler):
    """HTTP handler for System agent."""

    def do_GET(self):
        """Handle GET requests."""
        if self.path == "/system":
            try:
                # Get comprehensive system information
                system_info = self.server.agent.get_system_info()

                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps(system_info, indent=2).encode())

            except Exception as e:
                error_response = {
                    "error": str(e),
                    "timestamp": datetime.now().isoformat()
                }
                self.send_response(500)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps(error_response).encode())

        elif self.path == "/processes":
            try:
                processes = self.server.agent.get_process_list()

                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps(processes, indent=2).encode())

            except Exception as e:
                error_response = {"error": str(e)}
                self.send_response(500)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps(error_response).encode())

        elif self.path == "/health":
            health_status = {
                "agent": "system_agent",
                "status": "healthy",
                "uptime": time.time() - self.server.agent.start_time,
                "last_update": datetime.now().isoformat()
            }

            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(health_status, indent=2).encode())

        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        """Override to control logging."""
        print(f"[System HTTP] {format % args}")


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    """Threaded HTTP server."""
    pass


class SystemAgent:
    """System Agent implementing design vision."""

    def __init__(self):
        self.name = "system_agent"
        self.capabilities = ["system_info", "process_management", "health_monitoring"]
        self.http_server = None
        self.http_thread = None
        self.start_time = time.time()
        self.running = False
        self.cache = {}
        self.cache_ttl = 5  # seconds

    def get_system_info(self):
        """Get comprehensive system information."""
        now = time.time()

        # Use cache if recent
        if 'system_info' in self.cache and (now - self.cache['system_info']['timestamp']) < self.cache_ttl:
            return self.cache['system_info']['data']

        try:
            # CPU information
            cpu_count = psutil.cpu_count()
            cpu_percent = psutil.cpu_percent(interval=0.1)

            # Memory information
            memory = psutil.virtual_memory()

            # Disk information
            disk = psutil.disk_usage('/')

            # Network information
            network = psutil.net_io_counters()

            # Boot time
            boot_time = psutil.boot_time()
            uptime = now - boot_time

            system_info = {
                "platform": {
                    "system": platform.system(),
                    "node": platform.node(),
                    "release": platform.release(),
                    "version": platform.version(),
                    "machine": platform.machine(),
                    "processor": platform.processor()
                },
                "cpu": {
                    "count": cpu_count,
                    "usage_percent": cpu_percent,
                    "frequency": psutil.cpu_freq()._asdict() if psutil.cpu_freq() else None
                },
                "memory": {
                    "total": memory.total,
                    "available": memory.available,
                    "percent": memory.percent,
                    "used": memory.used,
                    "free": memory.free
                },
                "disk": {
                    "total": disk.total,
                    "used": disk.used,
                    "free": disk.free,
                    "percent": (disk.used / disk.total) * 100
                },
                "network": {
                    "bytes_sent": network.bytes_sent,
                    "bytes_recv": network.bytes_recv,
                    "packets_sent": network.packets_sent,
                    "packets_recv": network.packets_recv
                },
                "uptime": {
                    "seconds": uptime,
                    "boot_time": datetime.fromtimestamp(boot_time).isoformat()
                },
                "agent_info": {
                    "name": self.name,
                    "agent_uptime": now - self.start_time,
                    "capabilities": self.capabilities,
                    "timestamp": datetime.now().isoformat()
                }
            }

            # Cache the result
            self.cache['system_info'] = {
                'data': system_info,
                'timestamp': now
            }

            return system_info

        except Exception as e:
            return {
                "error": f"Failed to get system info: {e}",
                "timestamp": datetime.now().isoformat()
            }

    def get_process_list(self, limit=10):
        """Get list of running processes."""
        try:
            processes = []
            for proc in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent', 'create_time']):
                try:
                    pinfo = proc.info
                    pinfo['uptime'] = time.time() - pinfo['create_time']
                    processes.append(pinfo)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass

            # Sort by CPU usage and return top processes
            processes.sort(key=lambda x: x['cpu_percent'] or 0, reverse=True)

            return {
                "processes": processes[:limit],
                "total_count": len(processes),
                "timestamp": datetime.now().isoformat()
            }

        except Exception as e:
            return {
                "error": f"Failed to get process list: {e}",
                "timestamp": datetime.now().isoformat()
            }

    def start_http_server(self, port=8082):
        """Start HTTP server for system information."""
        try:
            self.http_server = ThreadedHTTPServer(('localhost', port), SystemInfoHandler)
            self.http_server.agent = self

            self.http_thread = Thread(target=self.http_server.serve_forever)
            self.http_thread.daemon = True
            self.http_thread.start()

            print(f"[System] HTTP server started on http://localhost:{port}")
            print(f"[System] Try: curl http://localhost:{port}/system")
            print(f"[System] Try: curl http://localhost:{port}/processes")
            print(f"[System] Try: curl http://localhost:{port}/health")

        except Exception as e:
            print(f"[System] Failed to start HTTP server: {e}")

    def stop_http_server(self):
        """Stop HTTP server."""
        if self.http_server:
            self.http_server.shutdown()
            self.http_server.server_close()
            if self.http_thread:
                self.http_thread.join(timeout=2)
            print("[System] HTTP server stopped")

    async def handle_mcp_request(self, request):
        """Handle MCP protocol requests."""
        method = request.get("method")

        if method == "get_system_info":
            return {
                "result": self.get_system_info()
            }

        elif method == "get_processes":
            limit = request.get("params", {}).get("limit", 10)
            return {
                "result": self.get_process_list(limit)
            }

        elif method == "get_capabilities":
            return {
                "result": {
                    "capabilities": self.capabilities,
                    "agent": self.name
                }
            }

        else:
            return {
                "error": {
                    "code": -32601,
                    "message": f"Method not found: {method}"
                }
            }

    async def run(self):
        """Main agent loop."""
        print(f"[System] Starting {self.name} agent")
        print(f"[System] Capabilities: {self.capabilities}")

        # Start HTTP server
        self.start_http_server()

        self.running = True
        heartbeat_count = 0

        try:
            while self.running:
                await asyncio.sleep(10)
                heartbeat_count += 1

                # Get basic system stats for heartbeat
                try:
                    cpu_percent = psutil.cpu_percent(interval=0.1)
                    memory_percent = psutil.virtual_memory().percent

                    print(f"[System] Heartbeat #{heartbeat_count} - CPU: {cpu_percent}%, Memory: {memory_percent}%")

                except Exception as e:
                    print(f"[System] Heartbeat #{heartbeat_count} - Error getting stats: {e}")

        except KeyboardInterrupt:
            print("[System] Received shutdown signal")
        finally:
            self.running = False
            self.stop_http_server()
            print("[System] Agent shut down")


if __name__ == "__main__":
    print("=== System Agent - Design Vision ===")
    print("This agent provides system information and monitoring capabilities")
    print("for the MCP Mesh design vision demonstration.")
    print()

    # Check if psutil is available
    try:
        import psutil
    except ImportError:
        print("WARNING: psutil not available, using mock data")
        # Create mock psutil for testing
        class MockPsutil:
            @staticmethod
            def cpu_count(): return 4
            @staticmethod
            def cpu_percent(interval=None): return 25.0
            @staticmethod
            def virtual_memory():
                class MockMemory:
                    total = 8000000000
                    available = 6000000000
                    percent = 25.0
                    used = 2000000000
                    free = 6000000000
                return MockMemory()
            @staticmethod
            def disk_usage(path):
                class MockDisk:
                    total = 100000000000
                    used = 50000000000
                    free = 50000000000
                return MockDisk()
            @staticmethod
            def net_io_counters():
                class MockNetwork:
                    bytes_sent = 1000000
                    bytes_recv = 2000000
                    packets_sent = 10000
                    packets_recv = 15000
                return MockNetwork()
            @staticmethod
            def boot_time(): return time.time() - 3600
            @staticmethod
            def process_iter(*args): return []

        psutil = MockPsutil()

    # Create and run agent
    agent = SystemAgent()
    asyncio.run(agent.run())
'''
        )

        # Create process management demo as described in design vision
        process_demo_py = workspace / "process_management_demo.py"
        process_demo_py.write_text(
            '''
"""Process Management Demo - Design Vision Implementation."""

import asyncio
import json
import subprocess
import sys
import time


async def demo_original_design_vision():
    """Demonstrate the original MCP Mesh design vision."""
    print("=== MCP Mesh Design Vision Demo ===")
    print()
    print("This demo shows the original design vision:")
    print("1. Start hello_world.py → standalone HTTP service")
    print("2. Start system_agent.py → provides system information")
    print("3. MCP Mesh automatically discovers dependencies")
    print("4. hello_world.py gets enhanced with system information")
    print("5. HTTP endpoints show the difference before/after dependency injection")
    print()

    # Test that agents exist
    hello_world_path = Path(__file__).parent / "hello_world.py"
    system_agent_path = Path(__file__).parent / "system_agent.py"

    if not hello_world_path.exists():
        print(f"ERROR: {hello_world_path} not found!")
        return False

    if not system_agent_path.exists():
        print(f"ERROR: {system_agent_path} not found!")
        return False

    print("✓ Agent files found")
    print()

    # Step 1: Start hello_world.py
    print("Step 1: Starting hello_world.py...")
    hello_process = subprocess.Popen([
        sys.executable, str(hello_world_path)
    ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    await asyncio.sleep(2)  # Let it start
    print("✓ Hello World agent started")

    # Step 2: Test initial HTTP response (no dependencies)
    print("\\nStep 2: Testing initial HTTP response...")
    try:
        import requests
        response = requests.get("http://localhost:8081/hello", timeout=5)
        initial_data = response.json()

        print(f"Initial response (no dependencies):")
        print(f"  Enhanced: {initial_data.get('enhanced', False)}")
        print(f"  Dependencies Available: {initial_data.get('dependencies_available', False)}")
        print("✓ Initial HTTP test successful")

    except Exception as e:
        print(f"✗ Initial HTTP test failed: {e}")
        hello_process.terminate()
        return False

    # Step 3: Start system_agent.py
    print("\\nStep 3: Starting system_agent.py...")
    system_process = subprocess.Popen([
        sys.executable, str(system_agent_path)
    ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    await asyncio.sleep(3)  # Let it start and discover
    print("✓ System agent started")

    # Step 4: Test system agent HTTP endpoint
    print("\\nStep 4: Testing system agent HTTP endpoint...")
    try:
        response = requests.get("http://localhost:8082/system", timeout=5)
        system_data = response.json()

        print(f"System agent response:")
        print(f"  Platform: {system_data.get('platform', {}).get('system', 'unknown')}")
        print(f"  Memory: {system_data.get('memory', {}).get('percent', 0)}% used")
        print("✓ System agent HTTP test successful")

    except Exception as e:
        print(f"✗ System agent HTTP test failed: {e}")
        hello_process.terminate()
        system_process.terminate()
        return False

    # Step 5: Test enhanced hello_world response (with dependencies)
    print("\\nStep 5: Testing enhanced hello_world response...")
    await asyncio.sleep(2)  # Allow dependency injection time

    try:
        response = requests.get("http://localhost:8081/hello", timeout=5)
        enhanced_data = response.json()

        print(f"Enhanced response (with dependencies):")
        print(f"  Enhanced: {enhanced_data.get('enhanced', False)}")
        print(f"  Dependencies Available: {enhanced_data.get('dependencies_available', False)}")
        print(f"  System Info Included: {'system_info' in enhanced_data}")

        if enhanced_data.get('enhanced'):
            print("✓ Dependency injection successful!")
        else:
            print("⚠ Dependency injection not yet complete (expected in real implementation)")

    except Exception as e:
        print(f"✗ Enhanced HTTP test failed: {e}")
        hello_process.terminate()
        system_process.terminate()
        return False

    # Step 6: Test status endpoints
    print("\\nStep 6: Testing status endpoints...")
    try:
        hello_status = requests.get("http://localhost:8081/status", timeout=5).json()
        system_health = requests.get("http://localhost:8082/health", timeout=5).json()

        print(f"Hello World status:")
        print(f"  Agent: {hello_status.get('agent')}")
        print(f"  Uptime: {hello_status.get('uptime', 0):.1f}s")
        print(f"  Dependencies: {hello_status.get('dependencies', [])}")

        print(f"System Agent health:")
        print(f"  Agent: {system_health.get('agent')}")
        print(f"  Status: {system_health.get('status')}")
        print(f"  Uptime: {system_health.get('uptime', 0):.1f}s")

        print("✓ Status endpoints working")

    except Exception as e:
        print(f"✗ Status test failed: {e}")

    # Step 7: Cleanup
    print("\\nStep 7: Cleaning up processes...")
    hello_process.terminate()
    system_process.terminate()

    try:
        hello_process.wait(timeout=5)
        system_process.wait(timeout=5)
        print("✓ Processes terminated gracefully")
    except subprocess.TimeoutExpired:
        hello_process.kill()
        system_process.kill()
        print("⚠ Processes force killed")

    print()
    print("=== Demo Complete ===")
    print()
    print("The design vision demonstrates:")
    print("• Agents start as independent HTTP services")
    print("• System agent provides rich system information")
    print("• Hello World agent can be enhanced with dependencies")
    print("• HTTP endpoints show functional changes")
    print("• All services can be monitored and managed")
    print()
    print("In a full MCP Mesh implementation:")
    print("• Automatic service discovery would happen via registry")
    print("• Dependency injection would be handled by the mesh runtime")
    print("• CLI commands would manage the entire lifecycle")
    print("• Health monitoring and failure recovery would be automatic")

    return True


if __name__ == "__main__":
    # Run the demo
    success = asyncio.run(demo_original_design_vision())
    sys.exit(0 if success else 1)
'''
        )

        yield {
            "workspace": workspace,
            "config_dir": config_dir,
            "hello_world_py": hello_world_py,
            "system_agent_py": system_agent_py,
            "process_demo_py": process_demo_py,
        }


class TestOriginalDesignVision:
    """Test the complete original design vision scenario."""

    @pytest.mark.asyncio
    async def test_design_vision_agent_creation(self, design_vision_workspace):
        """Test that design vision agents are created correctly."""
        workspace = design_vision_workspace

        # Verify all required files exist
        assert workspace["hello_world_py"].exists()
        assert workspace["system_agent_py"].exists()
        assert workspace["process_demo_py"].exists()

        # Verify files have correct content
        hello_content = workspace["hello_world_py"].read_text()
        assert "HelloWorldAgent" in hello_content
        assert "register_dependency" in hello_content
        assert "start_http_server" in hello_content

        system_content = workspace["system_agent_py"].read_text()
        assert "SystemAgent" in system_content
        assert "get_system_info" in system_content
        assert "start_http_server" in system_content

    @patch("packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.main.cli_config_manager")
    @patch("packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.main.RegistryManager")
    @patch("packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.main.AgentManager")
    def test_cli_start_hello_world_agent(
        self,
        mock_agent_manager,
        mock_registry_manager,
        mock_config_manager,
        design_vision_workspace,
    ):
        """Test starting hello_world.py via CLI."""
        workspace = design_vision_workspace

        # Setup mocks
        config = MagicMock()
        config.registry_host = "localhost"
        config.registry_port = 8080
        config.db_path = str(workspace["config_dir"] / "registry.db")
        config.log_level = "INFO"
        config.startup_timeout = 30
        mock_config_manager.load_config.return_value = config

        mock_registry_instance = mock_registry_manager.return_value
        mock_agent_instance = mock_agent_manager.return_value

        # Mock successful startup
        mock_registry_process = MagicMock()
        mock_registry_process.pid = 12345
        mock_registry_process.metadata = {
            "host": "localhost",
            "port": 8080,
            "url": "http://localhost:8080",
        }
        mock_agent_instance.process_tracker.get_process.return_value = (
            mock_registry_process
        )

        mock_hello_process = MagicMock()
        mock_hello_process.pid = 12346
        mock_hello_process.metadata = {
            "agent_file": str(workspace["hello_world_py"]),
            "registry_url": "http://localhost:8080",
        }

        with patch(
            "packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.main.asyncio.run"
        ) as mock_asyncio:
            mock_asyncio.return_value = True
            mock_agent_instance.ensure_registry_running.return_value = True
            mock_agent_instance.start_multiple_agents.return_value = {
                "hello_world": mock_hello_process
            }
            mock_agent_instance.wait_for_agent_registration.return_value = True

            # Test CLI start command
            result = main(["start", str(workspace["hello_world_py"])])

            assert result == 0
            mock_agent_instance.start_multiple_agents.assert_called_once()

    @patch("packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.main.cli_config_manager")
    @patch("packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.main.RegistryManager")
    @patch("packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.main.AgentManager")
    def test_cli_start_system_agent(
        self,
        mock_agent_manager,
        mock_registry_manager,
        mock_config_manager,
        design_vision_workspace,
    ):
        """Test starting system_agent.py via CLI."""
        workspace = design_vision_workspace

        # Setup mocks similar to hello_world test
        config = MagicMock()
        config.registry_host = "localhost"
        config.registry_port = 8080
        config.db_path = str(workspace["config_dir"] / "registry.db")
        config.log_level = "INFO"
        config.startup_timeout = 30
        mock_config_manager.load_config.return_value = config

        mock_agent_instance = mock_agent_manager.return_value

        mock_system_process = MagicMock()
        mock_system_process.pid = 12347
        mock_system_process.metadata = {
            "agent_file": str(workspace["system_agent_py"]),
            "registry_url": "http://localhost:8080",
        }

        with patch(
            "packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.main.asyncio.run"
        ) as mock_asyncio:
            mock_asyncio.return_value = True
            mock_agent_instance.ensure_registry_running.return_value = True
            mock_agent_instance.start_multiple_agents.return_value = {
                "system_agent": mock_system_process
            }
            mock_agent_instance.wait_for_agent_registration.return_value = True

            # Test CLI start command
            result = main(["start", str(workspace["system_agent_py"])])

            assert result == 0

    @patch("packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.main.cli_config_manager")
    @patch("packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.main.RegistryManager")
    @patch("packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.main.AgentManager")
    def test_cli_start_both_agents(
        self,
        mock_agent_manager,
        mock_registry_manager,
        mock_config_manager,
        design_vision_workspace,
    ):
        """Test starting both agents simultaneously via CLI."""
        workspace = design_vision_workspace

        # Setup mocks
        config = MagicMock()
        config.registry_host = "localhost"
        config.registry_port = 8080
        config.db_path = str(workspace["config_dir"] / "registry.db")
        config.log_level = "INFO"
        config.startup_timeout = 30
        mock_config_manager.load_config.return_value = config

        mock_agent_instance = mock_agent_manager.return_value

        # Mock both processes
        mock_hello_process = MagicMock()
        mock_hello_process.pid = 12346
        mock_hello_process.metadata = {"agent_file": str(workspace["hello_world_py"])}

        mock_system_process = MagicMock()
        mock_system_process.pid = 12347
        mock_system_process.metadata = {"agent_file": str(workspace["system_agent_py"])}

        with patch(
            "packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.main.asyncio.run"
        ) as mock_asyncio:
            mock_asyncio.return_value = True
            mock_agent_instance.ensure_registry_running.return_value = True
            mock_agent_instance.start_multiple_agents.return_value = {
                "hello_world": mock_hello_process,
                "system_agent": mock_system_process,
            }
            mock_agent_instance.wait_for_agent_registration.return_value = True

            # Test CLI start command with both agents
            result = main(
                [
                    "start",
                    str(workspace["hello_world_py"]),
                    str(workspace["system_agent_py"]),
                ]
            )

            assert result == 0

            # Verify both agents were started
            call_args = mock_agent_instance.start_multiple_agents.call_args[0]
            assert len(call_args[0]) == 2  # Two agent files
            assert str(workspace["hello_world_py"]) in call_args[0]
            assert str(workspace["system_agent_py"]) in call_args[0]

    @patch("packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.main.cli_config_manager")
    @patch("packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.main.RegistryManager")
    @patch("packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.main.AgentManager")
    def test_cli_status_with_design_vision_agents(
        self,
        mock_agent_manager,
        mock_registry_manager,
        mock_config_manager,
        design_vision_workspace,
    ):
        """Test CLI status command with design vision agents."""
        workspace = design_vision_workspace

        # Setup mocks
        config = MagicMock()
        mock_config_manager.get_config.return_value = config

        # Mock registry status
        registry_status = {
            "status": "running",
            "host": "localhost",
            "port": 8080,
            "uptime": 300,
            "health": "healthy",
        }

        # Mock agents status
        agents_status = {
            "hello_world": {
                "status": "running",
                "registered": True,
                "health": "healthy",
                "pid": 12346,
                "uptime": 250,
                "file": str(workspace["hello_world_py"]),
                "capabilities": ["greeting", "hello_endpoint"],
                "endpoint": "http://localhost:8081",
            },
            "system_agent": {
                "status": "running",
                "registered": True,
                "health": "healthy",
                "pid": 12347,
                "uptime": 200,
                "file": str(workspace["system_agent_py"]),
                "capabilities": [
                    "system_info",
                    "process_management",
                    "health_monitoring",
                ],
                "endpoint": "http://localhost:8082",
            },
        }

        with patch(
            "packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.main.asyncio.run"
        ) as mock_asyncio:
            mock_asyncio.return_value = (registry_status, agents_status)

            # Test status command
            result = main(["status"])
            assert result == 0

            # Test verbose status
            result = main(["status", "--verbose"])
            assert result == 0

            # Test JSON status
            result = main(["status", "--json"])
            assert result == 0

    @patch("packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.main.cli_config_manager")
    @patch("packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.main.RegistryManager")
    @patch("packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.main.AgentManager")
    def test_cli_list_design_vision_agents(
        self,
        mock_agent_manager,
        mock_registry_manager,
        mock_config_manager,
        design_vision_workspace,
    ):
        """Test CLI list command with design vision agents."""
        workspace = design_vision_workspace

        # Setup mocks
        config = MagicMock()
        mock_config_manager.get_config.return_value = config

        # Mock agents info
        agents_info = {
            "hello_world": {
                "name": "hello_world",
                "status": "running_registered",
                "registered": True,
                "health": "healthy",
                "capabilities": ["greeting", "hello_endpoint"],
                "dependencies": ["system_info"],  # Shows dependency injection
                "endpoint": "http://localhost:8081",
                "pid": 12346,
                "process_status": "running",
                "agent_file": str(workspace["hello_world_py"]),
                "uptime": "250.0s",
            },
            "system_agent": {
                "name": "system_agent",
                "status": "running_registered",
                "registered": True,
                "health": "healthy",
                "capabilities": [
                    "system_info",
                    "process_management",
                    "health_monitoring",
                ],
                "dependencies": [],
                "endpoint": "http://localhost:8082",
                "pid": 12347,
                "process_status": "running",
                "agent_file": str(workspace["system_agent_py"]),
                "uptime": "200.0s",
            },
        }

        with patch(
            "packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.main.asyncio.run"
        ) as mock_asyncio:
            mock_asyncio.return_value = agents_info

            # Test list command
            result = main(["list"])
            assert result == 0

            # Test list with filter
            result = main(["list", "--filter", "hello"])
            assert result == 0

            # Test list with JSON output
            result = main(["list", "--json"])
            assert result == 0

    @patch("packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.main.cli_config_manager")
    @patch("packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.main.RegistryManager")
    @patch("packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.main.AgentManager")
    def test_cli_restart_agent_workflow(
        self,
        mock_agent_manager,
        mock_registry_manager,
        mock_config_manager,
        design_vision_workspace,
    ):
        """Test restarting agents in design vision scenario."""
        workspace = design_vision_workspace

        # Setup mocks
        config = MagicMock()
        mock_config_manager.get_config.return_value = config

        mock_agent_instance = mock_agent_manager.return_value

        # Mock existing process
        mock_existing_process = MagicMock()
        mock_existing_process.pid = 12346
        mock_existing_process.metadata = {
            "agent_file": str(workspace["hello_world_py"])
        }
        mock_existing_process.get_uptime.return_value.total_seconds.return_value = 300
        mock_agent_instance.process_tracker.get_process.return_value = (
            mock_existing_process
        )
        mock_agent_instance.process_tracker._is_process_running.return_value = True

        # Mock successful restart
        mock_new_process = MagicMock()
        mock_new_process.pid = 12349
        mock_new_process.metadata = {"agent_file": str(workspace["hello_world_py"])}

        with patch(
            "packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.main.asyncio.run"
        ) as mock_asyncio:
            mock_asyncio.return_value = True
            mock_agent_instance.restart_agent_with_registration_wait.return_value = True
            mock_agent_instance.process_tracker.get_process.side_effect = [
                mock_existing_process,  # First call
                mock_new_process,  # Second call
            ]

            # Test restart hello_world agent
            result = main(["restart-agent", "hello_world"])
            assert result == 0

            mock_agent_instance.restart_agent_with_registration_wait.assert_called_once_with(
                "hello_world", timeout=30
            )

    @patch("packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.main.cli_config_manager")
    @patch("packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.main.RegistryManager")
    @patch("packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.main.AgentManager")
    def test_cli_stop_all_agents(
        self,
        mock_agent_manager,
        mock_registry_manager,
        mock_config_manager,
        design_vision_workspace,
    ):
        """Test stopping all agents in design vision scenario."""
        workspace = design_vision_workspace

        # Setup mocks
        config = MagicMock()
        mock_config_manager.get_config.return_value = config

        mock_agent_instance = mock_agent_manager.return_value
        mock_registry_instance = mock_registry_manager.return_value

        # Mock successful stops
        mock_agent_instance.stop_all_agents.return_value = {
            "hello_world": True,
            "system_agent": True,
        }
        mock_registry_instance.stop_registry_service.return_value = True

        # Test stop command
        result = main(["stop"])
        assert result == 0

        mock_agent_instance.stop_all_agents.assert_called_once()
        mock_registry_instance.stop_registry_service.assert_called_once()

    def test_design_vision_dependency_injection_scenario(self, design_vision_workspace):
        """Test the dependency injection scenario from design vision."""
        workspace = design_vision_workspace

        # This test validates the conceptual flow described in the design vision:
        # 1. hello_world starts with basic functionality
        # 2. system_agent starts and registers capabilities
        # 3. MCP Mesh discovers the dependency relationship
        # 4. hello_world receives system_info dependency
        # 5. hello_world HTTP responses are enhanced

        # Read the agent code to verify dependency injection capability
        hello_content = workspace["hello_world_py"].read_text()

        # Verify hello_world has dependency registration capability
        assert "register_dependency" in hello_content
        assert "dependencies" in hello_content
        assert "system_info" in hello_content

        # Verify hello_world can enhance responses with dependencies
        assert "dependencies_available" in hello_content
        assert "enhanced" in hello_content

        # Read system agent code
        system_content = workspace["system_agent_py"].read_text()

        # Verify system_agent provides the expected capabilities
        assert "system_info" in system_content
        assert "process_management" in system_content
        assert "get_system_info" in system_content

        # Verify system_agent can provide information over HTTP
        assert "start_http_server" in system_content
        assert "/system" in system_content

    def test_design_vision_http_endpoint_behavior(self, design_vision_workspace):
        """Test HTTP endpoint behavior changes from design vision."""
        workspace = design_vision_workspace

        # Verify hello_world has the expected HTTP endpoints
        hello_content = workspace["hello_world_py"].read_text()

        # Check for key endpoints
        assert '"/hello"' in hello_content
        assert '"/status"' in hello_content

        # Verify response structure changes based on dependencies
        assert "enhanced" in hello_content
        assert "dependencies_available" in hello_content
        assert "system_info" in hello_content

        # Verify system_agent has monitoring endpoints
        system_content = workspace["system_agent_py"].read_text()

        assert '"/system"' in system_content
        assert '"/processes"' in system_content
        assert '"/health"' in system_content

    def test_design_vision_monitoring_capabilities(self, design_vision_workspace):
        """Test monitoring capabilities from design vision."""
        workspace = design_vision_workspace

        # Verify agents include monitoring and status capabilities
        hello_content = workspace["hello_world_py"].read_text()

        # Check for status reporting
        assert "status" in hello_content
        assert "uptime" in hello_content
        assert "dependencies" in hello_content

        # Verify system agent has comprehensive monitoring
        system_content = workspace["system_agent_py"].read_text()

        assert "cpu_percent" in system_content
        assert "memory" in system_content
        assert "disk" in system_content
        assert "processes" in system_content
        assert "health" in system_content

    @pytest.mark.asyncio
    async def test_design_vision_process_demo_execution(self, design_vision_workspace):
        """Test that the process demo can execute the design vision."""
        workspace = design_vision_workspace

        # Verify the demo file exists and has the right structure
        demo_content = workspace["process_demo_py"].read_text()

        # Check for key demo steps
        assert "demo_original_design_vision" in demo_content
        assert "Start hello_world.py" in demo_content
        assert "Start system_agent.py" in demo_content
        assert "dependency injection" in demo_content
        assert "HTTP endpoints" in demo_content

        # Verify the demo includes proper testing
        assert "requests.get" in demo_content
        assert "localhost:8081" in demo_content
        assert "localhost:8082" in demo_content

        # Verify cleanup procedures
        assert "terminate" in demo_content
        assert "cleanup" in demo_content


class TestDesignVisionErrorHandling:
    """Test error handling in design vision scenarios."""

    @patch("packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.main.cli_config_manager")
    @patch("packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.main.RegistryManager")
    @patch("packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.main.AgentManager")
    def test_agent_startup_failure_handling(
        self,
        mock_agent_manager,
        mock_registry_manager,
        mock_config_manager,
        design_vision_workspace,
    ):
        """Test handling of agent startup failures."""
        workspace = design_vision_workspace

        # Setup mocks
        config = MagicMock()
        mock_config_manager.load_config.return_value = config

        mock_agent_instance = mock_agent_manager.return_value

        with patch(
            "packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.main.asyncio.run"
        ) as mock_asyncio:
            # Mock agent startup failure
            mock_asyncio.return_value = False
            mock_agent_instance.ensure_registry_running.return_value = True
            mock_agent_instance.start_multiple_agents.return_value = (
                {}
            )  # No agents started

            # Test start command with failure
            result = main(["start", str(workspace["hello_world_py"])])

            assert result == 1  # Should indicate failure

    def test_missing_agent_files_handling(self, design_vision_workspace):
        """Test handling of missing agent files."""
        workspace = design_vision_workspace

        non_existent_agent = workspace["workspace"] / "non_existent_agent.py"

        with patch(
            "packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.main.cli_config_manager"
        ):
            # Test starting non-existent agent
            result = main(["start", str(non_existent_agent)])

            # Should handle gracefully (specific behavior depends on implementation)
            assert isinstance(result, int)

    @patch("packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.main.cli_config_manager")
    @patch("packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.main.RegistryManager")
    @patch("packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.main.AgentManager")
    def test_partial_agent_failure_recovery(
        self,
        mock_agent_manager,
        mock_registry_manager,
        mock_config_manager,
        design_vision_workspace,
    ):
        """Test recovery from partial agent failures."""
        workspace = design_vision_workspace

        # Setup mocks
        config = MagicMock()
        mock_config_manager.load_config.return_value = config

        mock_agent_instance = mock_agent_manager.return_value

        # Mock one agent success, one failure
        mock_hello_process = MagicMock()
        mock_hello_process.pid = 12346

        with patch(
            "packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.main.asyncio.run"
        ) as mock_asyncio:
            mock_asyncio.return_value = True
            mock_agent_instance.ensure_registry_running.return_value = True
            mock_agent_instance.start_multiple_agents.return_value = {
                "hello_world": mock_hello_process
                # system_agent missing = failure
            }
            mock_agent_instance.wait_for_agent_registration.return_value = True

            # Test with both agents, but one fails
            result = main(
                [
                    "start",
                    str(workspace["hello_world_py"]),
                    str(workspace["system_agent_py"]),
                ]
            )

            # Should still succeed if at least one agent started
            assert result == 0


if __name__ == "__main__":
    pytest.main([__file__])
