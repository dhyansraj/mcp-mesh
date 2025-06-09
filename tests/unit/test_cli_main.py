"""Unit tests for CLI main entry point."""

import argparse
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.main import (
    _convert_config_value,
    cmd_config,
    cmd_list,
    cmd_logs,
    cmd_start,
    cmd_status,
    cmd_stop,
    create_parser,
    main,
)


class TestConfigValueConversion:
    """Test configuration value conversion utilities."""

    def test_convert_int_values(self):
        """Test conversion of integer configuration values."""
        assert _convert_config_value("registry_port", "8080") == 8080
        assert _convert_config_value("health_check_interval", "30") == 30
        assert _convert_config_value("startup_timeout", "60") == 60
        assert _convert_config_value("shutdown_timeout", "45") == 45

    def test_convert_bool_values(self):
        """Test conversion of boolean configuration values."""
        # Test true values
        assert _convert_config_value("auto_restart", "true") is True
        assert _convert_config_value("watch_files", "1") is True
        assert _convert_config_value("debug_mode", "yes") is True
        assert _convert_config_value("enable_background", "on") is True

        # Test false values
        assert _convert_config_value("auto_restart", "false") is False
        assert _convert_config_value("watch_files", "0") is False
        assert _convert_config_value("debug_mode", "no") is False
        assert _convert_config_value("enable_background", "off") is False

    def test_convert_string_values(self):
        """Test conversion of string configuration values."""
        assert _convert_config_value("registry_host", "localhost") == "localhost"
        assert _convert_config_value("db_path", "/tmp/test.db") == "/tmp/test.db"
        assert _convert_config_value("log_level", "DEBUG") == "DEBUG"
        assert _convert_config_value("pid_file", "/tmp/test.pid") == "/tmp/test.pid"

    def test_convert_invalid_values(self):
        """Test conversion of invalid configuration values."""
        assert _convert_config_value("registry_port", "invalid") is None
        assert _convert_config_value("unknown_key", "value") == "value"

    def test_convert_unknown_keys(self):
        """Test conversion of unknown configuration keys."""
        assert _convert_config_value("unknown_key", "test") == "test"


class TestArgumentParser:
    """Test argument parser creation and validation."""

    def test_create_parser_basic(self):
        """Test basic parser creation."""
        parser = create_parser()
        assert isinstance(parser, argparse.ArgumentParser)
        assert parser.prog == "mcp_mesh_dev"

    def test_parser_help_text(self):
        """Test parser includes proper help text."""
        parser = create_parser()
        help_text = parser.format_help()

        assert "MCP Mesh Developer CLI" in help_text
        assert "start" in help_text
        assert "stop" in help_text
        assert "status" in help_text
        assert "list" in help_text

    def test_start_command_parsing(self):
        """Test start command argument parsing."""
        parser = create_parser()

        # Test basic start
        args = parser.parse_args(["start"])
        assert args.command == "start"
        assert args.agents == []

        # Test start with agents
        args = parser.parse_args(["start", "agent1.py", "agent2.py"])
        assert args.command == "start"
        assert args.agents == ["agent1.py", "agent2.py"]

        # Test start with options
        args = parser.parse_args(
            [
                "start",
                "--registry-port",
                "8081",
                "--registry-host",
                "0.0.0.0",
                "--debug",
                "--background",
            ]
        )
        assert args.registry_port == 8081
        assert args.registry_host == "0.0.0.0"
        assert args.debug is True
        assert args.background is True

    def test_stop_command_parsing(self):
        """Test stop command argument parsing."""
        parser = create_parser()

        # Test basic stop
        args = parser.parse_args(["stop"])
        assert args.command == "stop"

        # Test stop with options
        args = parser.parse_args(["stop", "--force", "--timeout", "60"])
        assert args.force is True
        assert args.timeout == 60

        # Test stop specific agent
        args = parser.parse_args(["stop", "--agent", "my_agent"])
        assert args.agent == "my_agent"

    def test_status_command_parsing(self):
        """Test status command argument parsing."""
        parser = create_parser()

        # Test basic status
        args = parser.parse_args(["status"])
        assert args.command == "status"

        # Test status with options
        args = parser.parse_args(["status", "--verbose", "--json"])
        assert args.verbose is True
        assert args.json is True

    def test_config_command_parsing(self):
        """Test config command argument parsing."""
        parser = create_parser()

        # Test config show
        args = parser.parse_args(["config", "show"])
        assert args.command == "config"
        assert args.config_action == "show"

        # Test config set
        args = parser.parse_args(["config", "set", "registry_port", "8081"])
        assert args.config_action == "set"
        assert args.key == "registry_port"
        assert args.value == "8081"

        # Test config with format
        args = parser.parse_args(["config", "show", "--format", "json"])
        assert args.format == "json"


class TestMainFunction:
    """Test main CLI entry point."""

    def test_main_no_args_shows_help(self, capsys):
        """Test main with no arguments shows help."""
        result = main([])
        assert result == 1

        captured = capsys.readouterr()
        assert "usage:" in captured.out.lower() or "usage:" in captured.err.lower()

    def test_main_version_flag(self, capsys):
        """Test main with version flag."""
        with pytest.raises(SystemExit) as exc_info:
            main(["--version"])

        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        assert "mcp_mesh_dev" in captured.out

    def test_main_invalid_command(self, capsys):
        """Test main with invalid command."""
        with pytest.raises(SystemExit):
            main(["invalid_command"])

    @patch("packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.main.cmd_start")
    def test_main_start_command(self, mock_cmd_start):
        """Test main with start command."""
        mock_cmd_start.return_value = 0

        result = main(["start", "test_agent.py"])
        assert result == 0
        mock_cmd_start.assert_called_once()

    def test_main_keyboard_interrupt(self, capsys):
        """Test main handles keyboard interrupt gracefully."""
        with patch(
            "packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.main.cmd_start"
        ) as mock_cmd:
            mock_cmd.side_effect = KeyboardInterrupt()

            result = main(["start"])
            assert result == 130

            captured = capsys.readouterr()
            assert "cancelled by user" in captured.out.lower()


class TestCommandFunctions:
    """Test individual CLI command functions."""

    @pytest.fixture
    def mock_args(self):
        """Create mock arguments."""
        args = MagicMock()
        args.agents = []
        args.registry_only = False
        args.background = False
        args.registry_port = 8080
        args.registry_host = "localhost"
        args.debug = False
        return args

    @pytest.fixture
    def mock_config_manager(self):
        """Mock configuration manager."""
        with patch(
            "packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.main.cli_config_manager"
        ) as mock:
            config = MagicMock()
            config.registry_host = "localhost"
            config.registry_port = 8080
            config.db_path = "./test.db"
            config.log_level = "INFO"
            config.startup_timeout = 30
            mock.load_config.return_value = config
            mock.get_config.return_value = config
            yield mock

    @patch("packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.main.asyncio.run")
    @patch("packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.main.AgentManager")
    @patch("packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.main.RegistryManager")
    def test_cmd_start_success(
        self,
        mock_registry_manager,
        mock_agent_manager,
        mock_asyncio_run,
        mock_args,
        mock_config_manager,
    ):
        """Test successful start command."""
        # Setup mocks
        mock_asyncio_run.return_value = True

        result = cmd_start(mock_args)
        assert result == 0

        mock_registry_manager.assert_called_once()
        mock_agent_manager.assert_called_once()
        mock_asyncio_run.assert_called_once()

    @patch("packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.main.AgentManager")
    def test_cmd_stop_success(self, mock_agent_manager, mock_config_manager):
        """Test successful stop command."""
        args = MagicMock()
        args.force = False
        args.agent = None
        args.timeout = 30

        # Setup mocks
        mock_manager_instance = mock_agent_manager.return_value
        mock_manager_instance.stop_all_agents.return_value = {"test_agent": True}

        with patch(
            "packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.main.RegistryManager"
        ) as mock_registry:
            mock_registry_instance = mock_registry.return_value
            mock_registry_instance.stop_registry_service.return_value = True

            result = cmd_stop(args)
            assert result == 0

    def test_cmd_config_show(self, mock_config_manager):
        """Test config show command."""
        args = MagicMock()
        args.config_action = "show"
        args.format = "yaml"

        mock_config_manager.show_config.return_value = "test config"

        result = cmd_config(args)
        assert result == 0
        mock_config_manager.show_config.assert_called_once_with(format="yaml")

    def test_cmd_config_set(self, mock_config_manager):
        """Test config set command."""
        args = MagicMock()
        args.config_action = "set"
        args.key = "registry_port"
        args.value = "8081"

        result = cmd_config(args)
        assert result == 0
        mock_config_manager.update_config.assert_called_once_with(registry_port=8081)

    def test_cmd_config_reset(self, mock_config_manager):
        """Test config reset command."""
        args = MagicMock()
        args.config_action = "reset"

        result = cmd_config(args)
        assert result == 0
        mock_config_manager.reset_to_defaults.assert_called_once()

    @patch("packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.main.asyncio.run")
    @patch("packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.main.AgentManager")
    def test_cmd_status_success(
        self, mock_agent_manager, mock_asyncio_run, mock_config_manager
    ):
        """Test successful status command."""
        args = MagicMock()
        args.json = False
        args.verbose = False

        # Setup mock return values
        registry_status = {"status": "running", "host": "localhost", "port": 8080}
        agents_status = {"test_agent": {"status": "running", "health": "healthy"}}
        mock_asyncio_run.return_value = (registry_status, agents_status)

        result = cmd_status(args)
        assert result == 0

    @patch("packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.main.asyncio.run")
    @patch("packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.main.AgentManager")
    def test_cmd_list_success(
        self, mock_agent_manager, mock_asyncio_run, mock_config_manager
    ):
        """Test successful list command."""
        args = MagicMock()
        args.json = False
        args.filter = None
        args.agents = True
        args.services = False

        # Setup mock return values with all required fields
        agents_info = {
            "test_agent": {
                "name": "test_agent",
                "status": "running",
                "registered": True,
                "health": "healthy",
                "process_status": "running",  # Added missing field
                "pid": 12345,
                "uptime": "300.0s",
            }
        }
        mock_asyncio_run.return_value = agents_info

        result = cmd_list(args)
        assert result == 0

    @patch("packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.main.AgentManager")
    @patch("packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.main.RegistryManager")
    def test_cmd_logs_specific_agent(
        self, mock_registry_manager, mock_agent_manager, mock_config_manager
    ):
        """Test logs command for specific agent."""
        args = MagicMock()
        args.agent = "test_agent"
        args.lines = 50
        args.level = "INFO"
        args.follow = False

        # Setup mock process info
        mock_process_info = MagicMock()
        mock_process_info.pid = 12345
        mock_process_info.metadata = {"working_directory": "/tmp"}
        mock_process_info.command = ["python", "test_agent.py"]
        mock_process_info.start_time.strftime.return_value = "2024-01-01 12:00:00"
        mock_process_info.get_uptime.return_value.total_seconds.return_value = 3600.0

        mock_manager_instance = mock_agent_manager.return_value
        mock_manager_instance.process_tracker.get_process.return_value = (
            mock_process_info
        )

        with patch("pathlib.Path.exists", return_value=False):
            result = cmd_logs(args)
            assert result == 0


class TestErrorHandling:
    """Test error handling in CLI commands."""

    def test_cmd_start_exception_handling(self, capsys):
        """Test start command handles exceptions gracefully."""
        args = MagicMock()

        with patch(
            "packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.main.cli_config_manager"
        ) as mock_config:
            mock_config.load_config.side_effect = Exception("Config error")

            result = cmd_start(args)
            assert result == 1

            captured = capsys.readouterr()
            assert "Failed to start services" in captured.err

    def test_cmd_config_invalid_action(self):
        """Test config command with invalid action."""
        args = MagicMock()
        args.config_action = "invalid_action"

        with patch(
            "packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.main.cli_config_manager"
        ):
            result = cmd_config(args)
            assert result == 0  # No explicit handling, falls through

    def test_cmd_config_set_missing_params(self, capsys):
        """Test config set command with missing parameters."""
        args = MagicMock()
        args.config_action = "set"
        del args.key  # Simulate missing key attribute

        result = cmd_config(args)
        assert result == 1

        captured = capsys.readouterr()
        assert "key and value are required" in captured.err

    def test_cmd_config_set_invalid_value(self, capsys):
        """Test config set command with invalid value."""
        args = MagicMock()
        args.config_action = "set"
        args.key = "registry_port"
        args.value = "invalid_port"

        result = cmd_config(args)
        assert result == 1

        captured = capsys.readouterr()
        assert "Invalid value" in captured.err


class TestIntegrationScenarios:
    """Test integration scenarios between CLI components."""

    @patch("packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.main.asyncio.run")
    @patch("packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.main.cli_config_manager")
    def test_start_stop_workflow(self, mock_config_manager, mock_asyncio_run):
        """Test complete start-stop workflow."""
        # Setup config
        config = MagicMock()
        config.registry_host = "localhost"
        config.registry_port = 8080
        mock_config_manager.load_config.return_value = config
        mock_config_manager.get_config.return_value = config

        # Test start
        start_args = MagicMock()
        start_args.agents = ["test_agent.py"]
        start_args.registry_only = False
        start_args.background = False

        with (
            patch(
                "packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.main.RegistryManager"
            ),
            patch(
                "packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.main.AgentManager"
            ),
        ):
            mock_asyncio_run.return_value = True
            start_result = cmd_start(start_args)
            assert start_result == 0

        # Test stop
        stop_args = MagicMock()
        stop_args.force = False
        stop_args.agent = None
        stop_args.timeout = 30

        with (
            patch(
                "packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.main.RegistryManager"
            ) as mock_reg,
            patch(
                "packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.main.AgentManager"
            ) as mock_agent,
        ):
            mock_agent.return_value.stop_all_agents.return_value = {"test_agent": True}
            mock_reg.return_value.stop_registry_service.return_value = True

            stop_result = cmd_stop(stop_args)
            assert stop_result == 0

    def test_config_lifecycle(self):
        """Test configuration lifecycle operations."""
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "test_config.json"

            with patch(
                "packages.mcp_mesh_runtime.src.mcp_mesh_runtime.cli.main.cli_config_manager"
            ) as mock_manager:
                mock_manager.config_path = config_path

                # Test show default config
                show_args = MagicMock()
                show_args.config_action = "show"
                show_args.format = "json"
                mock_manager.show_config.return_value = '{"registry_port": 8080}'

                result = cmd_config(show_args)
                assert result == 0

                # Test set config
                set_args = MagicMock()
                set_args.config_action = "set"
                set_args.key = "registry_port"
                set_args.value = "8081"

                result = cmd_config(set_args)
                assert result == 0

                # Test reset config
                reset_args = MagicMock()
                reset_args.config_action = "reset"

                result = cmd_config(reset_args)
                assert result == 0


if __name__ == "__main__":
    pytest.main([__file__])
