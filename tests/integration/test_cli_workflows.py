"""Integration tests for CLI workflows and error handling."""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.config import CLIConfigManager

# Import CLI components for integration testing
from packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.main import (
    cmd_config,
    cmd_list,
    cmd_logs,
    cmd_restart,
    cmd_restart_agent,
    cmd_start,
    cmd_status,
    cmd_stop,
    main,
)
from packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.process_tracker import (
    ProcessTracker,
)


@pytest.fixture
def temp_workspace():
    """Create a temporary workspace for testing."""
    with tempfile.TemporaryDirectory() as temp_dir:
        workspace = Path(temp_dir)

        # Create test configuration
        config_dir = workspace / ".mcp_mesh"
        config_dir.mkdir(parents=True, exist_ok=True)

        # Create test agent files
        agent_dir = workspace / "agents"
        agent_dir.mkdir(parents=True, exist_ok=True)

        # Create a simple test agent
        test_agent = agent_dir / "test_agent.py"
        test_agent.write_text(
            """
import asyncio
import json
import sys
from datetime import datetime

class TestAgent:
    def __init__(self):
        self.name = "test_agent"
        self.capabilities = ["test_capability"]

    async def handle_request(self, request):
        return {"status": "success", "timestamp": datetime.now().isoformat()}

    async def run(self):
        print(f"Test agent {self.name} starting at {datetime.now()}")
        try:
            while True:
                await asyncio.sleep(1)
                print(f"Test agent {self.name} heartbeat")
        except KeyboardInterrupt:
            print(f"Test agent {self.name} shutting down")

if __name__ == "__main__":
    agent = TestAgent()
    asyncio.run(agent.run())
"""
        )

        # Create a system agent
        system_agent = agent_dir / "system_agent.py"
        system_agent.write_text(
            """
import asyncio
import json
import sys
from datetime import datetime

class SystemAgent:
    def __init__(self):
        self.name = "system_agent"
        self.capabilities = ["system_info", "process_management"]

    async def get_system_info(self):
        return {
            "platform": "test",
            "uptime": 1000,
            "memory_usage": 50.0
        }

    async def run(self):
        print(f"System agent {self.name} starting at {datetime.now()}")
        try:
            while True:
                await asyncio.sleep(2)
                info = await self.get_system_info()
                print(f"System agent {self.name} info: {info}")
        except KeyboardInterrupt:
            print(f"System agent {self.name} shutting down")

if __name__ == "__main__":
    agent = SystemAgent()
    asyncio.run(agent.run())
"""
        )

        yield {
            "workspace": workspace,
            "config_dir": config_dir,
            "agent_dir": agent_dir,
            "test_agent": test_agent,
            "system_agent": system_agent,
        }


@pytest.fixture
def cli_config_manager_with_temp_path(temp_workspace):
    """Create CLI config manager with temporary path."""
    config_path = temp_workspace["config_dir"] / "cli_config.json"
    return CLIConfigManager(config_path=config_path)


@pytest.fixture
def process_tracker_with_temp_path(temp_workspace):
    """Create process tracker with temporary path."""
    state_file = temp_workspace["config_dir"] / "processes.json"
    return ProcessTracker(state_file=state_file)


class TestCompleteStartStopWorkflow:
    """Test complete start-stop workflow."""

    @patch("packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.main.cli_config_manager")
    @patch("packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.main.RegistryManager")
    @patch("packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.main.AgentManager")
    def test_registry_only_start_stop(
        self,
        mock_agent_manager,
        mock_registry_manager,
        mock_config_manager,
        temp_workspace,
    ):
        """Test starting and stopping registry-only mode."""
        # Setup mocks
        config = MagicMock()
        config.registry_host = "localhost"
        config.registry_port = 8080
        config.db_path = str(temp_workspace["config_dir"] / "test_registry.db")
        config.log_level = "INFO"
        config.startup_timeout = 30
        mock_config_manager.load_config.return_value = config
        mock_config_manager.get_config.return_value = config

        # Mock successful registry startup
        mock_registry_instance = mock_registry_manager.return_value
        mock_agent_instance = mock_agent_manager.return_value

        with patch(
            "packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.main.asyncio.run"
        ) as mock_asyncio:
            # Test start command
            mock_asyncio.return_value = True  # Successful start

            start_args = MagicMock()
            start_args.agents = []
            start_args.registry_only = True
            start_args.background = False

            start_result = cmd_start(start_args)
            assert start_result == 0

            # Verify managers were created
            mock_registry_manager.assert_called_once_with(config)
            mock_agent_manager.assert_called_once_with(config, mock_registry_instance)

            # Test stop command
            stop_args = MagicMock()
            stop_args.force = False
            stop_args.agent = None
            stop_args.timeout = 30

            mock_agent_instance.stop_all_agents.return_value = {}
            mock_registry_instance.stop_registry_service.return_value = True

            stop_result = cmd_stop(stop_args)
            assert stop_result == 0

    @patch("packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.main.cli_config_manager")
    @patch("packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.main.RegistryManager")
    @patch("packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.main.AgentManager")
    def test_start_with_agents_workflow(
        self,
        mock_agent_manager,
        mock_registry_manager,
        mock_config_manager,
        temp_workspace,
    ):
        """Test starting registry with agents and stopping."""
        # Setup mocks
        config = MagicMock()
        config.registry_host = "localhost"
        config.registry_port = 8080
        config.db_path = str(temp_workspace["config_dir"] / "test_registry.db")
        config.log_level = "INFO"
        config.startup_timeout = 30
        mock_config_manager.load_config.return_value = config
        mock_config_manager.get_config.return_value = config

        mock_registry_instance = mock_registry_manager.return_value
        mock_agent_instance = mock_agent_manager.return_value

        # Mock process tracking
        mock_process = MagicMock()
        mock_process.pid = 12345
        mock_process.metadata = {
            "host": "localhost",
            "port": 8080,
            "url": "http://localhost:8080",
        }
        mock_agent_instance.process_tracker.get_process.return_value = mock_process

        with patch(
            "packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.main.asyncio.run"
        ) as mock_asyncio:
            # Test start with agents
            mock_asyncio.return_value = True
            mock_agent_instance.ensure_registry_running.return_value = True
            mock_agent_instance.start_multiple_agents.return_value = {
                "test_agent": MagicMock(
                    pid=12346, metadata={"agent_file": "test_agent.py"}
                )
            }
            mock_agent_instance.wait_for_agent_registration.return_value = True

            start_args = MagicMock()
            start_args.agents = [str(temp_workspace["test_agent"])]
            start_args.registry_only = False
            start_args.background = False

            start_result = cmd_start(start_args)
            assert start_result == 0

            # Verify agent startup was called
            mock_agent_instance.start_multiple_agents.assert_called_once()
            mock_agent_instance.wait_for_agent_registration.assert_called()

            # Test stop all services
            stop_args = MagicMock()
            stop_args.force = False
            stop_args.agent = None
            stop_args.timeout = 30

            mock_agent_instance.stop_all_agents.return_value = {"test_agent": True}
            mock_registry_instance.stop_registry_service.return_value = True

            stop_result = cmd_stop(stop_args)
            assert stop_result == 0


class TestStatusAndListWorkflows:
    """Test status and list command workflows."""

    @patch("packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.main.cli_config_manager")
    @patch("packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.main.RegistryManager")
    @patch("packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.main.AgentManager")
    def test_status_command_detailed_output(
        self,
        mock_agent_manager,
        mock_registry_manager,
        mock_config_manager,
        temp_workspace,
    ):
        """Test status command with detailed output."""
        # Setup mocks
        config = MagicMock()
        mock_config_manager.get_config.return_value = config

        mock_registry_instance = mock_registry_manager.return_value
        mock_agent_instance = mock_agent_manager.return_value

        # Mock status data
        registry_status = {
            "status": "running",
            "host": "localhost",
            "port": 8080,
            "uptime": 300,
            "health": "healthy",
        }

        agents_status = {
            "test_agent": {
                "status": "running",
                "registered": True,
                "health": "healthy",
                "pid": 12346,
                "uptime": 250,
                "file": str(temp_workspace["test_agent"]),
            },
            "system_agent": {
                "status": "running",
                "registered": True,
                "health": "healthy",
                "pid": 12347,
                "uptime": 200,
                "file": str(temp_workspace["system_agent"]),
            },
        }

        with patch(
            "packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.main.asyncio.run"
        ) as mock_asyncio:
            mock_asyncio.return_value = (registry_status, agents_status)

            # Test basic status
            status_args = MagicMock()
            status_args.json = False
            status_args.verbose = False

            result = cmd_status(status_args)
            assert result == 0

            # Test verbose status
            status_args.verbose = True
            result = cmd_status(status_args)
            assert result == 0

            # Test JSON status
            status_args.json = True
            status_args.verbose = False
            result = cmd_status(status_args)
            assert result == 0

    @patch("packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.main.cli_config_manager")
    @patch("packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.main.RegistryManager")
    @patch("packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.main.AgentManager")
    def test_list_command_filtering(
        self,
        mock_agent_manager,
        mock_registry_manager,
        mock_config_manager,
        temp_workspace,
    ):
        """Test list command with filtering options."""
        # Setup mocks
        config = MagicMock()
        mock_config_manager.get_config.return_value = config

        mock_registry_instance = mock_registry_manager.return_value
        mock_agent_instance = mock_agent_manager.return_value

        # Mock agents info
        agents_info = {
            "test_agent": {
                "name": "test_agent",
                "status": "running",
                "registered": True,
                "health": "healthy",
                "capabilities": ["test_capability"],
                "dependencies": [],
                "pid": 12346,
                "process_status": "running",
                "agent_file": str(temp_workspace["test_agent"]),
            },
            "system_agent": {
                "name": "system_agent",
                "status": "running",
                "registered": True,
                "health": "healthy",
                "capabilities": ["system_info", "process_management"],
                "dependencies": [],
                "pid": 12347,
                "process_status": "running",
                "agent_file": str(temp_workspace["system_agent"]),
            },
        }

        with patch(
            "packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.main.asyncio.run"
        ) as mock_asyncio:
            mock_asyncio.return_value = agents_info

            # Test basic list
            list_args = MagicMock()
            list_args.json = False
            list_args.filter = None
            list_args.agents = True
            list_args.services = False

            result = cmd_list(list_args)
            assert result == 0

            # Test with filter
            list_args.filter = "test"
            result = cmd_list(list_args)
            assert result == 0

            # Test JSON output
            list_args.json = True
            list_args.filter = None
            result = cmd_list(list_args)
            assert result == 0


class TestRestartWorkflows:
    """Test restart command workflows."""

    @patch("packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.main.cli_config_manager")
    @patch("packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.main.RegistryManager")
    def test_restart_registry_workflow(
        self, mock_registry_manager, mock_config_manager
    ):
        """Test restarting registry service."""
        # Setup mocks
        config = MagicMock()
        config.startup_timeout = 30
        mock_config_manager.get_config.return_value = config

        mock_registry_instance = mock_registry_manager.return_value

        # Mock successful restart
        mock_process_info = MagicMock()
        mock_process_info.pid = 12348
        mock_process_info.metadata = {
            "host": "localhost",
            "port": 8080,
            "url": "http://localhost:8080",
        }
        mock_registry_instance.restart_registry_service.return_value = mock_process_info

        with patch(
            "packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.main.asyncio.run"
        ) as mock_asyncio:
            mock_asyncio.return_value = True  # Registry ready

            restart_args = MagicMock()
            restart_args.timeout = 30
            restart_args.reset_config = False

            result = cmd_restart(restart_args)
            assert result == 0

            mock_registry_instance.restart_registry_service.assert_called_once_with(
                timeout=30, preserve_config=True
            )

    @patch("packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.main.cli_config_manager")
    @patch("packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.main.RegistryManager")
    @patch("packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.main.AgentManager")
    def test_restart_agent_workflow(
        self, mock_agent_manager, mock_registry_manager, mock_config_manager
    ):
        """Test restarting specific agent."""
        # Setup mocks
        config = MagicMock()
        mock_config_manager.get_config.return_value = config

        mock_registry_instance = mock_registry_manager.return_value
        mock_agent_instance = mock_agent_manager.return_value

        # Mock existing process
        mock_existing_process = MagicMock()
        mock_existing_process.pid = 12346
        mock_existing_process.metadata = {"agent_file": "test_agent.py"}
        mock_existing_process.get_uptime.return_value.total_seconds.return_value = 300
        mock_agent_instance.process_tracker.get_process.return_value = (
            mock_existing_process
        )
        mock_agent_instance.process_tracker._is_process_running.return_value = True

        # Mock successful restart
        mock_new_process = MagicMock()
        mock_new_process.pid = 12349
        mock_new_process.metadata = {"agent_file": "test_agent.py"}

        with patch(
            "packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.main.asyncio.run"
        ) as mock_asyncio:
            mock_asyncio.return_value = True  # Restart successful
            mock_agent_instance.restart_agent_with_registration_wait.return_value = True
            mock_agent_instance.process_tracker.get_process.side_effect = [
                mock_existing_process,  # First call for current status
                mock_new_process,  # Second call for new process
            ]

            restart_args = MagicMock()
            restart_args.agent_name = "test_agent"
            restart_args.timeout = 30

            result = cmd_restart_agent(restart_args)
            assert result == 0

            mock_agent_instance.restart_agent_with_registration_wait.assert_called_once_with(
                "test_agent", timeout=30
            )


class TestConfigurationWorkflows:
    """Test configuration management workflows."""

    def test_config_show_set_workflow(self, cli_config_manager_with_temp_path):
        """Test showing and setting configuration."""
        with patch(
            "packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.main.cli_config_manager",
            cli_config_manager_with_temp_path,
        ):

            # Test show config
            show_args = MagicMock()
            show_args.config_action = "show"
            show_args.format = "yaml"

            result = cmd_config(show_args)
            assert result == 0

            # Test set config
            set_args = MagicMock()
            set_args.config_action = "set"
            set_args.key = "registry_port"
            set_args.value = "8081"

            result = cmd_config(set_args)
            assert result == 0

            # Verify the change
            config = cli_config_manager_with_temp_path.get_config()
            assert config.registry_port == 8081

    def test_config_reset_workflow(self, cli_config_manager_with_temp_path):
        """Test resetting configuration."""
        with patch(
            "packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.main.cli_config_manager",
            cli_config_manager_with_temp_path,
        ):

            # Modify config first
            cli_config_manager_with_temp_path.update_config(
                registry_port=8081, debug_mode=True
            )

            # Test reset
            reset_args = MagicMock()
            reset_args.config_action = "reset"

            result = cmd_config(reset_args)
            assert result == 0

            # Verify reset to defaults
            config = cli_config_manager_with_temp_path.get_config()
            assert config.registry_port == 8080
            assert config.debug_mode is False

    def test_config_path_and_save_workflow(self, cli_config_manager_with_temp_path):
        """Test showing config path and saving."""
        with patch(
            "packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.main.cli_config_manager",
            cli_config_manager_with_temp_path,
        ):

            # Test show path
            path_args = MagicMock()
            path_args.config_action = "path"

            result = cmd_config(path_args)
            assert result == 0

            # Test save config
            save_args = MagicMock()
            save_args.config_action = "save"

            result = cmd_config(save_args)
            assert result == 0


class TestLogsWorkflows:
    """Test logs command workflows."""

    @patch("packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.main.cli_config_manager")
    @patch("packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.main.RegistryManager")
    @patch("packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.main.AgentManager")
    def test_logs_specific_agent(
        self,
        mock_agent_manager,
        mock_registry_manager,
        mock_config_manager,
        temp_workspace,
    ):
        """Test viewing logs for specific agent."""
        # Setup mocks
        config = MagicMock()
        mock_config_manager.get_config.return_value = config

        mock_agent_instance = mock_agent_manager.return_value

        # Mock process info
        mock_process = MagicMock()
        mock_process.pid = 12346
        mock_process.metadata = {
            "working_directory": str(temp_workspace["agent_dir"]),
            "agent_file": str(temp_workspace["test_agent"]),
        }
        mock_process.command = ["python", str(temp_workspace["test_agent"])]
        mock_process.start_time.strftime.return_value = "2024-01-01 12:00:00"
        mock_process.get_uptime.return_value.total_seconds.return_value = 300
        mock_agent_instance.process_tracker.get_process.return_value = mock_process

        # Create a mock log file
        log_file = temp_workspace["agent_dir"] / "test_agent.log"
        log_file.write_text(
            """
2024-01-01 12:00:00 INFO Test agent starting
2024-01-01 12:00:01 DEBUG Initializing capabilities
2024-01-01 12:00:02 INFO Test agent ready
2024-01-01 12:00:03 WARNING Test warning message
2024-01-01 12:00:04 ERROR Test error message
""".strip()
        )

        with (
            patch("pathlib.Path.exists", return_value=True),
            patch(
                "builtins.open",
                lambda *args, **kwargs: open(log_file, *args[1:], **kwargs),
            ),
        ):

            logs_args = MagicMock()
            logs_args.agent = "test_agent"
            logs_args.lines = 50
            logs_args.level = "INFO"
            logs_args.follow = False

            result = cmd_logs(logs_args)
            assert result == 0

    @patch("packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.main.cli_config_manager")
    @patch("packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.main.RegistryManager")
    @patch("packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.main.AgentManager")
    def test_logs_all_services(
        self,
        mock_agent_manager,
        mock_registry_manager,
        mock_config_manager,
        temp_workspace,
    ):
        """Test viewing logs for all services."""
        # Setup mocks
        config = MagicMock()
        mock_config_manager.get_config.return_value = config

        mock_agent_instance = mock_agent_manager.return_value

        # Mock registry process
        mock_registry_process = MagicMock()
        mock_registry_process.pid = 12345
        mock_registry_process.get_uptime.return_value.total_seconds.return_value = 600

        # Mock agent processes
        mock_agent_processes = {
            "test_agent": MagicMock(
                pid=12346,
                get_uptime=lambda: MagicMock(total_seconds=lambda: 300),
                metadata={"agent_file": str(temp_workspace["test_agent"])},
            )
        }

        mock_agent_instance.process_tracker.get_process.side_effect = lambda name: {
            "registry": mock_registry_process
        }.get(name)

        mock_agent_instance.process_tracker.get_all_processes.return_value = {
            "registry": mock_registry_process,
            **mock_agent_processes,
        }

        mock_agent_instance.process_tracker._is_process_running.return_value = True

        logs_args = MagicMock()
        logs_args.agent = None
        logs_args.lines = 50
        logs_args.level = "INFO"
        logs_args.follow = False

        result = cmd_logs(logs_args)
        assert result == 0


class TestErrorHandlingWorkflows:
    """Test error handling in various workflows."""

    @patch("packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.main.cli_config_manager")
    def test_start_command_config_error(self, mock_config_manager, capsys):
        """Test start command with configuration error."""
        mock_config_manager.load_config.side_effect = Exception("Configuration failed")

        start_args = MagicMock()
        start_args.agents = []

        result = cmd_start(start_args)
        assert result == 1

        captured = capsys.readouterr()
        assert "Failed to start services" in captured.err

    @patch("packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.main.cli_config_manager")
    @patch("packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.main.RegistryManager")
    @patch("packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.main.AgentManager")
    def test_start_command_registry_failure(
        self, mock_agent_manager, mock_registry_manager, mock_config_manager
    ):
        """Test start command with registry startup failure."""
        # Setup mocks
        config = MagicMock()
        mock_config_manager.load_config.return_value = config

        mock_agent_instance = mock_agent_manager.return_value

        with patch(
            "packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.main.asyncio.run"
        ) as mock_asyncio:
            # Mock registry failure
            mock_asyncio.return_value = False
            mock_agent_instance.ensure_registry_running.return_value = False

            start_args = MagicMock()
            start_args.agents = []
            start_args.registry_only = True
            start_args.background = False

            result = cmd_start(start_args)
            assert result == 1

    @patch("packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.main.cli_config_manager")
    @patch("packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.main.RegistryManager")
    @patch("packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.main.AgentManager")
    def test_stop_command_partial_failure(
        self, mock_agent_manager, mock_registry_manager, mock_config_manager
    ):
        """Test stop command with partial failures."""
        # Setup mocks
        config = MagicMock()
        mock_config_manager.get_config.return_value = config

        mock_agent_instance = mock_agent_manager.return_value
        mock_registry_instance = mock_registry_manager.return_value

        # Mock partial agent stop failure
        mock_agent_instance.stop_all_agents.return_value = {
            "agent1": True,
            "agent2": False,  # Failed to stop
        }
        mock_registry_instance.stop_registry_service.return_value = True

        stop_args = MagicMock()
        stop_args.force = False
        stop_args.agent = None
        stop_args.timeout = 30

        result = cmd_stop(stop_args)
        assert result == 1  # Partial failure

    def test_config_set_invalid_value(self, capsys):
        """Test config set with invalid value."""
        set_args = MagicMock()
        set_args.config_action = "set"
        set_args.key = "registry_port"
        set_args.value = "invalid_port"

        result = cmd_config(set_args)
        assert result == 1

        captured = capsys.readouterr()
        assert "Invalid value" in captured.err

    @patch("packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.main.cli_config_manager")
    @patch("packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.main.RegistryManager")
    @patch("packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.main.AgentManager")
    def test_status_command_connection_error(
        self, mock_agent_manager, mock_registry_manager, mock_config_manager, capsys
    ):
        """Test status command with connection error."""
        # Setup mocks
        config = MagicMock()
        mock_config_manager.get_config.return_value = config

        with patch(
            "packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.main.asyncio.run"
        ) as mock_asyncio:
            mock_asyncio.side_effect = Exception("Connection failed")

            status_args = MagicMock()
            status_args.json = False
            status_args.verbose = False

            result = cmd_status(status_args)
            assert result == 1

            captured = capsys.readouterr()
            assert "Failed to get status" in captured.err


class TestConcurrentOperations:
    """Test concurrent operations and race conditions."""

    @patch("packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.main.cli_config_manager")
    @patch("packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.main.RegistryManager")
    @patch("packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.main.AgentManager")
    def test_concurrent_start_stop_operations(
        self, mock_agent_manager, mock_registry_manager, mock_config_manager
    ):
        """Test handling concurrent start/stop operations."""
        # Setup mocks
        config = MagicMock()
        mock_config_manager.load_config.return_value = config
        mock_config_manager.get_config.return_value = config

        mock_registry_instance = mock_registry_manager.return_value
        mock_agent_instance = mock_agent_manager.return_value

        # Mock successful operations
        with patch(
            "packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.main.asyncio.run"
        ) as mock_asyncio:
            mock_asyncio.return_value = True
            mock_agent_instance.stop_all_agents.return_value = {"test_agent": True}
            mock_registry_instance.stop_registry_service.return_value = True

            start_args = MagicMock()
            start_args.agents = []
            start_args.registry_only = True
            start_args.background = False

            stop_args = MagicMock()
            stop_args.force = False
            stop_args.agent = None
            stop_args.timeout = 30

            # Simulate rapid start/stop operations
            start_result = cmd_start(start_args)
            stop_result = cmd_stop(stop_args)

            assert start_result == 0
            assert stop_result == 0

    def test_config_concurrent_modifications(self, cli_config_manager_with_temp_path):
        """Test concurrent configuration modifications."""
        with patch(
            "packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.main.cli_config_manager",
            cli_config_manager_with_temp_path,
        ):

            # Simulate concurrent config operations
            set_args1 = MagicMock()
            set_args1.config_action = "set"
            set_args1.key = "registry_port"
            set_args1.value = "8081"

            set_args2 = MagicMock()
            set_args2.config_action = "set"
            set_args2.key = "debug_mode"
            set_args2.value = "true"

            show_args = MagicMock()
            show_args.config_action = "show"
            show_args.format = "json"

            # Execute operations
            result1 = cmd_config(set_args1)
            result2 = cmd_config(set_args2)
            result3 = cmd_config(show_args)

            assert result1 == 0
            assert result2 == 0
            assert result3 == 0

            # Verify final state
            config = cli_config_manager_with_temp_path.get_config()
            assert config.registry_port == 8081
            assert config.debug_mode is True


class TestMainEntryPointIntegration:
    """Test main entry point integration scenarios."""

    def test_main_with_valid_commands(self):
        """Test main entry point with valid commands."""
        with patch(
            "packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.main.cmd_config"
        ) as mock_cmd:
            mock_cmd.return_value = 0

            result = main(["config", "show"])
            assert result == 0
            mock_cmd.assert_called_once()

    def test_main_with_keyboard_interrupt(self, capsys):
        """Test main entry point handles keyboard interrupt."""
        with patch(
            "packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.main.cmd_start"
        ) as mock_cmd:
            mock_cmd.side_effect = KeyboardInterrupt()

            result = main(["start"])
            assert result == 130

            captured = capsys.readouterr()
            assert "cancelled by user" in captured.out.lower()

    def test_main_with_unexpected_error(self, capsys):
        """Test main entry point handles unexpected errors."""
        with patch(
            "packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.main.cmd_start"
        ) as mock_cmd:
            mock_cmd.side_effect = RuntimeError("Unexpected error")

            result = main(["start"])
            assert result == 1

            captured = capsys.readouterr()
            assert "Error:" in captured.err

    def test_main_signal_handler_integration(self):
        """Test main entry point signal handler integration."""
        with (
            patch(
                "packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.main.install_signal_handlers"
            ) as mock_install,
            patch(
                "packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.main.register_cleanup_handler"
            ) as mock_register,
            patch(
                "packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.main.cmd_config"
            ) as mock_cmd,
        ):

            mock_cmd.return_value = 0

            result = main(["config", "show"])
            assert result == 0

            # Verify signal handlers were installed
            mock_install.assert_called_once()
            mock_register.assert_called_once()


if __name__ == "__main__":
    pytest.main([__file__])
