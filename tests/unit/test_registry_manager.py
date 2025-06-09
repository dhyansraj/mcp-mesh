"""Tests for RegistryManager functionality."""

import asyncio
import socket
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import pytest
from mcp_mesh_runtime.cli.config import CLIConfig
from mcp_mesh_runtime.cli.registry_manager import RegistryManager
from mcp_mesh_runtime.shared.types import HealthStatusType


class TestRegistryManager(unittest.TestCase):
    """Test cases for RegistryManager."""

    def setUp(self):
        """Set up test environment."""
        self.temp_dir = Path(tempfile.mkdtemp())
        self.config = CLIConfig(
            registry_host="localhost",
            registry_port=8999,  # Use unusual port to avoid conflicts
            db_path=str(self.temp_dir / "test_registry.db"),
            startup_timeout=5,
        )
        self.registry_manager = RegistryManager(self.config)

    def tearDown(self):
        """Clean up test environment."""
        # Clean up any running processes
        try:
            asyncio.run(self.registry_manager.close())
        except Exception:
            pass

        # Clean up temp directory
        import shutil

        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_port_availability_check(self):
        """Test port availability checking."""
        # Test with a port that should be available
        available = self.registry_manager._is_port_available(65432)
        self.assertTrue(available)

        # Test with a socket that we bind to make unavailable
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("localhost", 0))
            port = sock.getsockname()[1]
            sock.listen(1)  # Make sure socket is listening

            # Port should not be available while socket is bound and listening
            available = self.registry_manager._is_port_available(port, "localhost")
            self.assertFalse(available)

    def test_find_available_port(self):
        """Test finding an available port."""
        # Find port starting from a high number to avoid conflicts
        port = self.registry_manager._find_available_port(60000)
        self.assertIsInstance(port, int)
        self.assertGreaterEqual(port, 60000)

        # Verify the found port is actually available
        available = self.registry_manager._is_port_available(port)
        self.assertTrue(available)

    def test_registry_status_not_running(self):
        """Test status when registry is not running."""
        status = self.registry_manager.get_registry_status()

        self.assertEqual(status["status"], "not_running")
        self.assertEqual(status["health"], HealthStatusType.UNKNOWN.value)
        self.assertIn("not tracked", status["message"])

    @pytest.mark.asyncio
    async def test_health_check_no_aiohttp(self):
        """Test health check when aiohttp is not available."""
        with patch("mcp_mesh_runtime.cli.registry_manager.aiohttp", None):
            # Should return True (fallback mode)
            result = await self.registry_manager.check_registry_health()
            self.assertTrue(result)

    def test_get_registry_client(self):
        """Test registry client creation."""
        client1 = self.registry_manager._get_registry_client()
        client2 = self.registry_manager._get_registry_client()

        # Should return the same instance (cached)
        self.assertIs(client1, client2)

        # Should have correct URL
        expected_url = f"http://{self.config.registry_host}:{self.config.registry_port}"
        self.assertEqual(client1.url, expected_url)


class TestRegistryManagerIntegration(unittest.TestCase):
    """Integration tests for RegistryManager (requires subprocess)."""

    def setUp(self):
        """Set up integration test environment."""
        self.temp_dir = Path(tempfile.mkdtemp())

        # Find an available port for testing
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("localhost", 0))
            port = sock.getsockname()[1]

        self.config = CLIConfig(
            registry_host="localhost",
            registry_port=port,
            db_path=str(self.temp_dir / "test_registry.db"),
            startup_timeout=5,
        )
        self.registry_manager = RegistryManager(self.config)
        self.started_processes = []

    def tearDown(self):
        """Clean up integration test environment."""
        # Stop any running registry processes
        try:
            self.registry_manager.stop_registry_service(timeout=5)
        except Exception:
            pass

        try:
            asyncio.run(self.registry_manager.close())
        except Exception:
            pass

        # Clean up temp directory
        import shutil

        shutil.rmtree(self.temp_dir, ignore_errors=True)

    @pytest.mark.slow
    def test_registry_lifecycle(self):
        """Test complete registry lifecycle: start -> status -> stop."""
        # Start registry
        process_info = self.registry_manager.start_registry_service()
        self.assertIsNotNone(process_info)
        self.assertIsNotNone(process_info.pid)
        self.assertEqual(process_info.name, "registry")
        self.assertEqual(process_info.service_type, "registry")

        # Wait a moment for startup
        time.sleep(2)

        # Check status
        status = self.registry_manager.get_registry_status()
        self.assertEqual(status["status"], "running")
        self.assertEqual(status["pid"], process_info.pid)
        self.assertGreater(status["uptime"], 0)

        # Stop registry
        success = self.registry_manager.stop_registry_service()
        self.assertTrue(success)

        # Verify stopped
        status = self.registry_manager.get_registry_status()
        self.assertEqual(status["status"], "not_running")

    @pytest.mark.slow
    def test_already_running_registry(self):
        """Test starting registry when it's already running."""
        # Start registry first time
        process_info1 = self.registry_manager.start_registry_service()
        self.assertIsNotNone(process_info1)

        time.sleep(1)

        # Try to start again - should return existing process
        process_info2 = self.registry_manager.start_registry_service()
        self.assertEqual(process_info1.pid, process_info2.pid)

        # Clean up
        self.registry_manager.stop_registry_service()

    @pytest.mark.slow
    def test_port_conflict_resolution(self):
        """Test automatic port conflict resolution."""
        original_port = self.config.registry_port

        # Bind to the configured port to create conflict
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as conflict_sock:
            conflict_sock.bind(("localhost", original_port))

            # Start registry - should find alternative port
            process_info = self.registry_manager.start_registry_service()
            self.assertIsNotNone(process_info)

            # Port should have changed
            self.assertNotEqual(self.config.registry_port, original_port)
            self.assertGreater(self.config.registry_port, original_port)

            time.sleep(1)

            # Verify it's running on the new port
            status = self.registry_manager.get_registry_status()
            self.assertEqual(status["status"], "running")
            self.assertEqual(status["port"], self.config.registry_port)

            # Clean up
            self.registry_manager.stop_registry_service()


if __name__ == "__main__":
    unittest.main()
