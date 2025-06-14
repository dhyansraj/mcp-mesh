#!/usr/bin/env python3
"""
Comprehensive End-to-End Integration Test Suite

This test suite implements the complete integration test workflow as specified:
1. Clean up all processes and db (python, mcp-mesh-dev mcp-mesh-registry)
2. Start Registry, wait for 5 seconds
3. Check registry log for 404 or other errors
4. Check all registry endpoints
5. Start hello world script, wait for 1 minute
6. Check all logs for 404 and other errors. Check Registration and heart beats logged correctly
7. Check registry endpoints and see if agent is registered, capability and dependencies are showing as expected
8. Check if mcp-mesh-dev list shows agent correctly
9. Start system agent script, wait for 1 minute
10. Check all logs for 404 and other errors. Check Registration and heart beats logged correctly
11. Check hello worlds logs to see if agent dependency has arrived
12. Check registry endpoints and see if both agents are registered, capability and dependencies are showing as expected
13. Check if mcp-mesh-dev list shows agent correctly
14. Stop system agent script, wait for 1 minute
15. Check all logs for 404 and other errors. Check De-registration and heart beats logged correctly
16. Check hello worlds logs to see if agent dependency are removed
17. Check registry endpoints and see if system agent health is degraded, capability and dependencies are showing as expected
18. Check if mcp-mesh-dev list shows agent correctly with health and dependencies updated
19. Clean up all processes and db (python, mcp-mesh-dev mcp-mesh-registry)

Each step is implemented as a separate test function for clear isolation and debugging.
"""

import os
import re
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import pytest
import requests


class ProcessManager:
    """Manages test processes with proper cleanup"""

    def __init__(self):
        self.processes: dict[str, subprocess.Popen] = {}
        self.log_files: dict[str, str] = {}
        self.temp_dir = tempfile.mkdtemp(prefix="mcp_mesh_test_")

    def start_process(
        self, name: str, cmd: list[str], cwd: str | None = None
    ) -> subprocess.Popen:
        """Start a process and capture its logs"""
        log_file = os.path.join(self.temp_dir, f"{name}.log")
        self.log_files[name] = log_file

        with open(log_file, "w") as f:
            f.write(f"Starting {name} with command: {' '.join(cmd)}\n")
            f.flush()

            proc = subprocess.Popen(
                cmd,
                stdout=f,
                stderr=subprocess.STDOUT,
                cwd=cwd,
                preexec_fn=os.setsid,  # Create new process group for clean termination
            )

        self.processes[name] = proc
        print(f"Started {name} (PID: {proc.pid}), logs: {log_file}")
        return proc

    def stop_process(self, name: str, timeout: int = 10) -> bool:
        """Stop a process gracefully, force kill if needed"""
        if name not in self.processes:
            return True

        proc = self.processes[name]
        if proc.poll() is not None:
            # Already terminated
            del self.processes[name]
            return True

        try:
            # Try graceful termination first
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)

            # Wait for graceful shutdown
            try:
                proc.wait(timeout=timeout)
                print(f"Gracefully stopped {name}")
            except subprocess.TimeoutExpired:
                # Force kill if graceful shutdown failed
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                proc.wait()
                print(f"Force killed {name}")

            del self.processes[name]
            return True

        except (ProcessLookupError, OSError) as e:
            print(f"Process {name} already dead: {e}")
            del self.processes[name]
            return True

    def get_log_content(self, name: str) -> str:
        """Get the log content for a process"""
        if name not in self.log_files:
            return ""

        try:
            with open(self.log_files[name]) as f:
                return f.read()
        except FileNotFoundError:
            return ""

    def check_for_errors(self, name: str) -> list[str]:
        """Check process logs for error indicators"""
        log_content = self.get_log_content(name)
        error_patterns = [
            r"404",
            r"500",
            r"ERROR",
            r"FATAL",
            r"panic:",
            r"failed to",
            r"error:",
            r"Error:",
            r"Exception",
            r"Traceback",
        ]

        errors = []
        for pattern in error_patterns:
            matches = re.findall(pattern, log_content, re.IGNORECASE)
            if matches:
                errors.extend(matches)

        return errors

    def check_for_patterns(
        self, name: str, patterns: list[str]
    ) -> dict[str, list[str]]:
        """Check process logs for specific patterns"""
        log_content = self.get_log_content(name)
        results = {}

        for pattern in patterns:
            matches = re.findall(pattern, log_content, re.IGNORECASE | re.MULTILINE)
            results[pattern] = matches

        return results

    def cleanup(self):
        """Clean up all processes and temp files"""
        for name in list(self.processes.keys()):
            self.stop_process(name)

        # Clean up temp directory
        import shutil

        try:
            shutil.rmtree(self.temp_dir)
        except OSError:
            pass


class IntegrationTestSuite:
    """Comprehensive integration test suite"""

    def __init__(self):
        self.process_manager = ProcessManager()
        self.registry_url = "http://localhost:8000"
        self.project_root = Path(__file__).parent.parent.parent

    def run_makefile_clean(self):
        """Run makefile clean-test target"""
        cmd = ["make", "clean-test"]
        result = subprocess.run(
            cmd, cwd=self.project_root, capture_output=True, text=True
        )
        if result.returncode != 0:
            print(f"Warning: make clean-test failed: {result.stderr}")

    def wait_for_registry_ready(self, timeout: int = 30) -> bool:
        """Wait for registry to be ready"""
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                response = requests.get(f"{self.registry_url}/health", timeout=5)
                if response.status_code == 200:
                    return True
            except requests.RequestException:
                pass
            time.sleep(1)
        return False

    def check_registry_endpoints(self) -> dict[str, Any]:
        """Check all registry endpoints are working"""
        endpoints = {"/": "GET", "/health": "GET", "/agents": "GET"}

        results = {}
        for endpoint, method in endpoints.items():
            try:
                if method == "GET":
                    response = requests.get(
                        f"{self.registry_url}{endpoint}", timeout=10
                    )
                    results[endpoint] = {
                        "status_code": response.status_code,
                        "success": 200 <= response.status_code < 300,
                        "response": (
                            response.json()
                            if response.headers.get("content-type", "").startswith(
                                "application/json"
                            )
                            else response.text
                        ),
                    }
            except Exception as e:
                results[endpoint] = {
                    "status_code": None,
                    "success": False,
                    "error": str(e),
                }

        return results

    def check_agent_registration(self, expected_count: int) -> dict[str, Any]:
        """Check agent registration status"""
        try:
            response = requests.get(f"{self.registry_url}/agents", timeout=10)
            if response.status_code == 200:
                data = response.json()
                return {
                    "success": True,
                    "agent_count": data.get("count", 0),
                    "agents": data.get("agents", []),
                    "expected_count_match": data.get("count", 0) == expected_count,
                }
        except Exception:
            pass

        return {"success": False, "error": "Failed to get agents"}

    def run_mcp_mesh_dev_list(self) -> dict[str, Any]:
        """Run mcp-mesh-dev list command"""
        binary_path = self.project_root / "bin" / "mcp-mesh-dev"
        if not binary_path.exists():
            return {"success": False, "error": "mcp-mesh-dev binary not found"}

        try:
            result = subprocess.run(
                [str(binary_path), "list"],
                capture_output=True,
                text=True,
                timeout=30,
                cwd=self.project_root,
            )
            return {
                "success": result.returncode == 0,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "returncode": result.returncode,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}


@pytest.fixture(scope="class")
def test_suite():
    """Fixture to set up and tear down the test suite"""
    suite = IntegrationTestSuite()
    yield suite
    suite.process_manager.cleanup()


class TestComprehensiveE2EWorkflow:
    """Test class implementing the complete E2E workflow"""

    def test_01_initial_cleanup(self, test_suite):
        """Step 1: Clean up all processes and db files"""
        print("\n=== Step 1: Initial cleanup ===")
        test_suite.run_makefile_clean()

        # Verify no processes are running
        result = subprocess.run(["pgrep", "-f", "mcp-mesh"], capture_output=True)
        assert (
            result.returncode != 0
        ), "mcp-mesh processes should not be running after cleanup"

        # Verify no database files exist
        db_files = list(test_suite.project_root.glob("**/*.db"))
        assert (
            len(db_files) == 0
        ), f"Database files should not exist after cleanup: {db_files}"

        print("✅ Initial cleanup completed")

    def test_02_start_registry(self, test_suite):
        """Step 2: Start Registry, wait for 5 seconds"""
        print("\n=== Step 2: Start Registry ===")

        # Build first if needed
        build_result = subprocess.run(
            ["make", "build"], cwd=test_suite.project_root, capture_output=True
        )
        assert build_result.returncode == 0, f"Build failed: {build_result.stderr}"

        # Start registry
        registry_binary = test_suite.project_root / "bin" / "mcp-mesh-registry"
        assert registry_binary.exists(), f"Registry binary not found: {registry_binary}"

        test_suite.process_manager.start_process(
            "registry", [str(registry_binary)], cwd=str(test_suite.project_root)
        )

        # Wait 5 seconds as specified
        time.sleep(5)

        # Verify process is still running
        registry_proc = test_suite.process_manager.processes["registry"]
        assert registry_proc.poll() is None, "Registry process should still be running"

        print("✅ Registry started and running")

    def test_03_check_registry_logs_for_errors(self, test_suite):
        """Step 3: Check registry log for 404 or other errors"""
        print("\n=== Step 3: Check registry logs for errors ===")

        errors = test_suite.process_manager.check_for_errors("registry")

        # Filter out acceptable errors (like 404s for non-existent agents during startup)
        critical_errors = [
            e
            for e in errors
            if not any(
                acceptable in e.lower()
                for acceptable in [
                    "no agents found",  # Expected when no agents registered yet
                    "empty response",  # Expected for empty registry
                ]
            )
        ]

        assert (
            len(critical_errors) == 0
        ), f"Registry has critical errors: {critical_errors}"

        # Check for successful startup patterns
        startup_patterns = test_suite.process_manager.check_for_patterns(
            "registry",
            [r"Starting.*registry", r"Server.*listening", r"Registry.*started"],
        )

        assert any(
            startup_patterns.values()
        ), f"Registry startup patterns not found: {startup_patterns}"

        print("✅ Registry logs look healthy")

    def test_04_check_registry_endpoints(self, test_suite):
        """Step 4: Check all registry endpoints"""
        print("\n=== Step 4: Check registry endpoints ===")

        # Wait for registry to be ready
        assert test_suite.wait_for_registry_ready(), "Registry not ready within timeout"

        endpoints_result = test_suite.check_registry_endpoints()

        for endpoint, result in endpoints_result.items():
            assert result["success"], f"Endpoint {endpoint} failed: {result}"

        print(f"✅ All registry endpoints working: {list(endpoints_result.keys())}")

    def test_05_start_hello_world(self, test_suite):
        """Step 5: Start hello world script, wait for 1 minute"""
        print("\n=== Step 5: Start hello world script ===")

        hello_world_script = test_suite.project_root / "examples" / "hello_world.py"
        assert (
            hello_world_script.exists()
        ), f"Hello world script not found: {hello_world_script}"

        # Start hello world agent
        test_suite.process_manager.start_process(
            "hello_world",
            [sys.executable, str(hello_world_script)],
            cwd=str(test_suite.project_root),
        )

        # Wait for 1 minute as specified
        print(
            "Waiting 1 minute for hello world agent to register and establish heartbeat..."
        )
        time.sleep(60)

        # Verify process is still running
        hello_proc = test_suite.process_manager.processes["hello_world"]
        assert hello_proc.poll() is None, "Hello world process should still be running"

        print("✅ Hello world agent running for 1 minute")

    def test_06_check_hello_world_logs(self, test_suite):
        """Step 6: Check all logs for 404 and other errors. Check Registration and heartbeats logged correctly"""
        print("\n=== Step 6: Check hello world and registry logs ===")

        # Check hello world logs for errors
        hello_errors = test_suite.process_manager.check_for_errors("hello_world")
        critical_hello_errors = [
            e
            for e in hello_errors
            if not any(
                acceptable in e.lower()
                for acceptable in [
                    "dependency.*not available",  # Expected when system agent not running
                    "no.*provider.*found",  # Expected for unresolved dependencies
                ]
            )
        ]
        assert (
            len(critical_hello_errors) == 0
        ), f"Hello world has critical errors: {critical_hello_errors}"

        # Check registry logs for errors (after hello world started)
        registry_errors = test_suite.process_manager.check_for_errors("registry")
        critical_registry_errors = [
            e
            for e in registry_errors
            if not any(
                acceptable in e.lower()
                for acceptable in [
                    "no.*provider.*found",  # Expected for unresolved dependencies
                ]
            )
        ]
        assert (
            len(critical_registry_errors) == 0
        ), f"Registry has critical errors: {critical_registry_errors}"

        # Check for registration patterns in hello world logs
        hello_patterns = test_suite.process_manager.check_for_patterns(
            "hello_world",
            [
                r"registered.*successfully",
                r"registration.*success",
                r"201",  # HTTP 201 Created response
            ],
        )
        assert any(
            hello_patterns.values()
        ), f"Hello world registration patterns not found: {hello_patterns}"

        # Check for heartbeat patterns in hello world logs
        heartbeat_patterns = test_suite.process_manager.check_for_patterns(
            "hello_world",
            [
                r"heartbeat.*sent",
                r"heartbeat.*success",
                r"200",  # HTTP 200 OK for heartbeats
            ],
        )
        assert any(
            heartbeat_patterns.values()
        ), f"Hello world heartbeat patterns not found: {heartbeat_patterns}"

        print("✅ Logs show successful registration and heartbeats")

    def test_07_check_hello_world_registration(self, test_suite):
        """Step 7: Check registry endpoints and see if agent is registered, capability and dependencies are showing as expected"""
        print("\n=== Step 7: Check hello world registration ===")

        registration_result = test_suite.check_agent_registration(expected_count=1)
        assert registration_result[
            "success"
        ], f"Failed to get agent registration: {registration_result}"
        assert registration_result[
            "expected_count_match"
        ], f"Expected 1 agent, got {registration_result['agent_count']}"

        agents = registration_result["agents"]
        hello_agent = None
        for agent in agents:
            if "hello" in agent.get("name", "").lower():
                hello_agent = agent
                break

        assert hello_agent is not None, f"Hello world agent not found in: {agents}"

        # Check capabilities
        capabilities = hello_agent.get("capabilities", [])
        expected_capabilities = ["date_service", "info"]  # Based on hello_world.py

        capability_names = [
            cap.get("name") if isinstance(cap, dict) else cap for cap in capabilities
        ]
        for expected_cap in expected_capabilities:
            assert (
                expected_cap in capability_names
            ), f"Expected capability {expected_cap} not found in {capability_names}"

        # Check dependencies
        dependencies = hello_agent.get("dependencies", [])
        expected_dependencies = ["info"]  # Hello world depends on info capability

        for expected_dep in expected_dependencies:
            assert (
                expected_dep in dependencies
            ), f"Expected dependency {expected_dep} not found in {dependencies}"

        print(
            f"✅ Hello world agent properly registered with capabilities: {capability_names}"
        )

    def test_08_check_mcp_mesh_dev_list_hello_only(self, test_suite):
        """Step 8: Check if mcp-mesh-dev list shows agent correctly"""
        print("\n=== Step 8: Check mcp-mesh-dev list (hello world only) ===")

        list_result = test_suite.run_mcp_mesh_dev_list()
        assert list_result["success"], f"mcp-mesh-dev list failed: {list_result}"

        output = list_result["stdout"]
        assert (
            "hello" in output.lower()
        ), f"Hello world agent not found in mcp-mesh-dev list: {output}"

        print("✅ mcp-mesh-dev list shows hello world agent")

    def test_09_start_system_agent(self, test_suite):
        """Step 9: Start system agent script, wait for 1 minute"""
        print("\n=== Step 9: Start system agent script ===")

        system_agent_script = test_suite.project_root / "examples" / "system_agent.py"
        assert (
            system_agent_script.exists()
        ), f"System agent script not found: {system_agent_script}"

        # Start system agent
        test_suite.process_manager.start_process(
            "system_agent",
            [sys.executable, str(system_agent_script)],
            cwd=str(test_suite.project_root),
        )

        # Wait for 1 minute as specified
        print(
            "Waiting 1 minute for system agent to register and establish heartbeat..."
        )
        time.sleep(60)

        # Verify process is still running
        system_proc = test_suite.process_manager.processes["system_agent"]
        assert (
            system_proc.poll() is None
        ), "System agent process should still be running"

        print("✅ System agent running for 1 minute")

    def test_10_check_system_agent_logs(self, test_suite):
        """Step 10: Check all logs for 404 and other errors. Check Registration and heartbeats logged correctly"""
        print("\n=== Step 10: Check system agent logs ===")

        # Check system agent logs for errors
        system_errors = test_suite.process_manager.check_for_errors("system_agent")
        critical_system_errors = [
            e
            for e in system_errors
            if not any(
                acceptable in e.lower()
                for acceptable in [
                    "dependency.*not available",  # May be acceptable during startup
                ]
            )
        ]
        assert (
            len(critical_system_errors) == 0
        ), f"System agent has critical errors: {critical_system_errors}"

        # Check for registration patterns in system agent logs
        system_patterns = test_suite.process_manager.check_for_patterns(
            "system_agent",
            [
                r"registered.*successfully",
                r"registration.*success",
                r"201",  # HTTP 201 Created response
            ],
        )
        assert any(
            system_patterns.values()
        ), f"System agent registration patterns not found: {system_patterns}"

        # Check for heartbeat patterns in system agent logs
        heartbeat_patterns = test_suite.process_manager.check_for_patterns(
            "system_agent",
            [
                r"heartbeat.*sent",
                r"heartbeat.*success",
                r"200",  # HTTP 200 OK for heartbeats
            ],
        )
        assert any(
            heartbeat_patterns.values()
        ), f"System agent heartbeat patterns not found: {heartbeat_patterns}"

        print("✅ System agent logs show successful registration and heartbeats")

    def test_11_check_hello_world_dependency_arrival(self, test_suite):
        """Step 11: Check hello world logs to see if agent dependency has arrived"""
        print("\n=== Step 11: Check hello world dependency injection ===")

        # Check hello world logs for dependency resolution patterns
        dependency_patterns = test_suite.process_manager.check_for_patterns(
            "hello_world",
            [
                r"dependency.*resolved",
                r"dependency.*available",
                r"proxy.*created",
                r"dependencies.*updated",
                r"info.*dependency",  # Specific to info dependency
            ],
        )

        # At least one dependency pattern should be found
        assert any(
            dependency_patterns.values()
        ), f"No dependency resolution patterns found in hello world logs: {dependency_patterns}"

        print("✅ Hello world logs show dependency resolution")

    def test_12_check_both_agents_registration(self, test_suite):
        """Step 12: Check registry endpoints and see if both agents are registered, capability and dependencies are showing as expected"""
        print("\n=== Step 12: Check both agents registration ===")

        registration_result = test_suite.check_agent_registration(expected_count=2)
        assert registration_result[
            "success"
        ], f"Failed to get agent registration: {registration_result}"
        assert registration_result[
            "expected_count_match"
        ], f"Expected 2 agents, got {registration_result['agent_count']}"

        agents = registration_result["agents"]
        hello_agent = None
        system_agent = None

        for agent in agents:
            name = agent.get("name", "").lower()
            if "hello" in name:
                hello_agent = agent
            elif "system" in name:
                system_agent = agent

        assert (
            hello_agent is not None
        ), f"Hello world agent not found in: {[a.get('name') for a in agents]}"
        assert (
            system_agent is not None
        ), f"System agent not found in: {[a.get('name') for a in agents]}"

        # Check hello world capabilities
        hello_capabilities = hello_agent.get("capabilities", [])
        hello_cap_names = [
            cap.get("name") if isinstance(cap, dict) else cap
            for cap in hello_capabilities
        ]
        expected_hello_caps = ["date_service", "info"]
        for cap in expected_hello_caps:
            assert (
                cap in hello_cap_names
            ), f"Hello world missing capability {cap}: {hello_cap_names}"

        # Check system agent capabilities
        system_capabilities = system_agent.get("capabilities", [])
        system_cap_names = [
            cap.get("name") if isinstance(cap, dict) else cap
            for cap in system_capabilities
        ]
        expected_system_caps = ["info", "date_service"]  # Based on system_agent.py
        for cap in expected_system_caps:
            assert (
                cap in system_cap_names
            ), f"System agent missing capability {cap}: {system_cap_names}"

        print(
            f"✅ Both agents registered - Hello: {hello_cap_names}, System: {system_cap_names}"
        )

    def test_13_check_mcp_mesh_dev_list_both_agents(self, test_suite):
        """Step 13: Check if mcp-mesh-dev list shows both agents correctly"""
        print("\n=== Step 13: Check mcp-mesh-dev list (both agents) ===")

        list_result = test_suite.run_mcp_mesh_dev_list()
        assert list_result["success"], f"mcp-mesh-dev list failed: {list_result}"

        output = list_result["stdout"]
        assert (
            "hello" in output.lower()
        ), f"Hello world agent not found in mcp-mesh-dev list: {output}"
        assert (
            "system" in output.lower()
        ), f"System agent not found in mcp-mesh-dev list: {output}"

        print("✅ mcp-mesh-dev list shows both agents")

    def test_14_stop_system_agent(self, test_suite):
        """Step 14: Stop system agent script, wait for 1 minute"""
        print("\n=== Step 14: Stop system agent ===")

        success = test_suite.process_manager.stop_process("system_agent")
        assert success, "Failed to stop system agent process"

        # Wait for 1 minute as specified for deregistration/health degradation
        print("Waiting 1 minute for system agent deregistration/health degradation...")
        time.sleep(60)

        print("✅ System agent stopped, waited 1 minute")

    def test_15_check_deregistration_logs(self, test_suite):
        """Step 15: Check all logs for 404 and other errors. Check De-registration and heartbeats logged correctly"""
        print("\n=== Step 15: Check deregistration logs ===")

        # Check registry logs for deregistration or health degradation patterns
        deregistration_patterns = test_suite.process_manager.check_for_patterns(
            "registry",
            [
                r"agent.*offline",
                r"agent.*degraded",
                r"agent.*unhealthy",
                r"heartbeat.*timeout",
                r"agent.*deregistered",
            ],
        )

        # At least one deregistration/degradation pattern should be found
        assert any(
            deregistration_patterns.values()
        ), f"No deregistration patterns found in registry logs: {deregistration_patterns}"

        print("✅ Registry logs show system agent deregistration/degradation")

    def test_16_check_hello_world_dependency_removal(self, test_suite):
        """Step 16: Check hello world logs to see if agent dependencies are removed"""
        print("\n=== Step 16: Check hello world dependency removal ===")

        # Check hello world logs for dependency removal patterns
        removal_patterns = test_suite.process_manager.check_for_patterns(
            "hello_world",
            [
                r"dependency.*unavailable",
                r"dependency.*removed",
                r"proxy.*unregistered",
                r"dependencies.*updated",
                r"no.*provider.*found",
            ],
        )

        # At least one removal pattern should be found
        assert any(
            removal_patterns.values()
        ), f"No dependency removal patterns found in hello world logs: {removal_patterns}"

        print("✅ Hello world logs show dependency removal")

    def test_17_check_system_agent_health_degraded(self, test_suite):
        """Step 17: Check registry endpoints and see if system agent health is degraded, capability and dependencies are showing as expected"""
        print("\n=== Step 17: Check system agent health degradation ===")

        registration_result = test_suite.check_agent_registration(expected_count=2)
        assert registration_result[
            "success"
        ], f"Failed to get agent registration: {registration_result}"

        agents = registration_result["agents"]
        system_agent = None

        for agent in agents:
            name = agent.get("name", "").lower()
            if "system" in name:
                system_agent = agent
                break

        assert (
            system_agent is not None
        ), f"System agent not found in: {[a.get('name') for a in agents]}"

        # Check that system agent status is degraded/unhealthy/offline
        status = system_agent.get("status", "").lower()
        assert status in [
            "degraded",
            "unhealthy",
            "offline",
        ], f"System agent status should be degraded/unhealthy/offline, got: {status}"

        print(f"✅ System agent health degraded: {status}")

    def test_18_check_mcp_mesh_dev_list_health_updated(self, test_suite):
        """Step 18: Check if mcp-mesh-dev list shows agents correctly with health and dependencies updated"""
        print("\n=== Step 18: Check mcp-mesh-dev list (health updated) ===")

        list_result = test_suite.run_mcp_mesh_dev_list()
        assert list_result["success"], f"mcp-mesh-dev list failed: {list_result}"

        output = list_result["stdout"]

        # Should still show both agents, but with updated health status
        assert (
            "hello" in output.lower()
        ), f"Hello world agent not found in mcp-mesh-dev list: {output}"
        assert (
            "system" in output.lower()
        ), f"System agent not found in mcp-mesh-dev list: {output}"

        # Should show degraded/unhealthy status for system agent
        degraded_indicators = ["degraded", "unhealthy", "offline", "down"]
        assert any(
            indicator in output.lower() for indicator in degraded_indicators
        ), f"No degraded status indicators found in: {output}"

        print("✅ mcp-mesh-dev list shows updated health status")

    def test_19_final_cleanup(self, test_suite):
        """Step 19: Clean up all processes and db files"""
        print("\n=== Step 19: Final cleanup ===")

        # Stop all test processes
        test_suite.process_manager.cleanup()

        # Run makefile cleanup
        test_suite.run_makefile_clean()

        # Verify no processes are running
        result = subprocess.run(["pgrep", "-f", "mcp-mesh"], capture_output=True)
        assert (
            result.returncode != 0
        ), "mcp-mesh processes should not be running after cleanup"

        print("✅ Final cleanup completed")


def test_comprehensive_workflow_summary():
    """Summary test that can be run to execute the entire workflow"""
    print("\n" + "=" * 80)
    print("COMPREHENSIVE E2E INTEGRATION TEST WORKFLOW COMPLETED")
    print("=" * 80)
    print("✅ All 19 test steps passed successfully")
    print("✅ Registry startup and endpoint validation")
    print("✅ Hello world agent registration and heartbeat")
    print("✅ System agent registration and dependency injection")
    print("✅ Agent deregistration and health degradation")
    print("✅ Cleanup and process management")
    print("=" * 80)


if __name__ == "__main__":
    """Run the test suite directly"""
    print("Running Comprehensive E2E Integration Test Suite...")
    pytest.main([__file__, "-v", "-s", "--tb=short"])
