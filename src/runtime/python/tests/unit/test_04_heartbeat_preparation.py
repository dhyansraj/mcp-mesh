"""
Unit tests for HeartbeatPreparationStep pipeline step.

Tests the preparation of heartbeat data including agent registration payload
and health status for registry communication. Focus on the simplified logic
after refactoring to remove duplicated configuration handling.
"""

from datetime import UTC, datetime
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

from _mcp_mesh.engine.decorator_registry import DecoratedFunction
from _mcp_mesh.pipeline.shared import PipelineResult, PipelineStatus

# Import the classes under test
from _mcp_mesh.pipeline.startup.heartbeat_preparation import HeartbeatPreparationStep
from _mcp_mesh.shared.support_types import HealthStatus, HealthStatusType


class TestHeartbeatPreparationStep:
    """Test the HeartbeatPreparationStep class initialization and basic properties."""

    def test_initialization(self):
        """Test HeartbeatPreparationStep initialization."""
        step = HeartbeatPreparationStep()

        assert step.name == "heartbeat-preparation"
        assert step.required is True
        assert step.description == "Prepare heartbeat payload with tools and metadata"

    def test_inheritance(self):
        """Test HeartbeatPreparationStep inherits from PipelineStep."""
        from _mcp_mesh.pipeline.shared import PipelineStep

        step = HeartbeatPreparationStep()
        assert isinstance(step, PipelineStep)

    def test_execute_method_exists(self):
        """Test execute method exists and is callable."""
        step = HeartbeatPreparationStep()
        assert hasattr(step, "execute")
        assert callable(step.execute)


class TestHeartbeatPreparationSuccess:
    """Test successful heartbeat preparation scenarios."""

    @pytest.fixture
    def step(self):
        """Create a HeartbeatPreparationStep instance."""
        return HeartbeatPreparationStep()

    @pytest.fixture
    def mock_agent_config(self):
        """Mock resolved agent configuration."""
        return {
            "agent_id": "test-agent-123",
            "name": "test-agent",
            "version": "1.0.0",
            "description": "Test agent",
            "http_host": "localhost",
            "http_port": 8080,
            "enable_http": True,
            "namespace": "default",
            "health_interval": 30,
        }

    @pytest.fixture
    def mock_tool_function(self):
        """Create a mock tool function."""
        mock_func = MagicMock()
        mock_func.__name__ = "test_tool"
        return mock_func

    @pytest.fixture
    def mock_mesh_tools(self, mock_tool_function):
        """Mock mesh tools dictionary."""
        decorated_func = DecoratedFunction(
            decorator_type="mesh_tool",
            function=mock_tool_function,
            metadata={
                "capability": "test_capability",
                "tags": ["test"],
                "version": "1.0.0",
                "description": "Test tool",
                "dependencies": [],
            },
            registered_at=MagicMock(),
        )
        return {"test_tool": decorated_func}

    @pytest.mark.asyncio
    async def test_heartbeat_preparation_basic(
        self, step, mock_agent_config, mock_mesh_tools
    ):
        """Test basic heartbeat preparation with simple tools."""
        with patch(
            "_mcp_mesh.pipeline.startup.heartbeat_preparation.DecoratorRegistry"
        ) as mock_registry:
            mock_registry.get_mesh_tools.return_value = mock_mesh_tools
            mock_registry.get_resolved_agent_config.return_value = mock_agent_config

            result = await step.execute({})

            assert result.status == PipelineStatus.SUCCESS
            assert (
                result.message
                == "Heartbeat prepared for agent 'test-agent-123' with 1 tools"
            )

            # Check context keys
            assert "registration_data" in result.context
            assert "health_status" in result.context
            assert "tools_list" in result.context
            assert "tool_count" in result.context
            assert result.context["tool_count"] == 1

    @pytest.mark.asyncio
    async def test_heartbeat_preparation_no_tools(self, step, mock_agent_config):
        """Test heartbeat preparation with no tools."""
        with patch(
            "_mcp_mesh.pipeline.startup.heartbeat_preparation.DecoratorRegistry"
        ) as mock_registry:
            mock_registry.get_mesh_tools.return_value = {}
            mock_registry.get_resolved_agent_config.return_value = mock_agent_config

            result = await step.execute({})

            assert result.status == PipelineStatus.SUCCESS
            assert (
                result.message
                == "Heartbeat prepared for agent 'test-agent-123' with 0 tools"
            )
            assert result.context["tool_count"] == 0
            assert result.context["tools_list"] == []

    @pytest.mark.asyncio
    async def test_heartbeat_preparation_multiple_tools(self, step, mock_agent_config):
        """Test heartbeat preparation with multiple tools."""
        mock_tools = {}
        for i in range(3):
            mock_func = MagicMock()
            mock_func.__name__ = f"tool_{i}"
            decorated_func = DecoratedFunction(
                decorator_type="mesh_tool",
                function=mock_func,
                metadata={
                    "capability": f"capability_{i}",
                    "tags": [f"tag_{i}"],
                    "version": "1.0.0",
                    "dependencies": [],
                },
                registered_at=MagicMock(),
            )
            mock_tools[f"tool_{i}"] = decorated_func

        with patch(
            "_mcp_mesh.pipeline.startup.heartbeat_preparation.DecoratorRegistry"
        ) as mock_registry:
            mock_registry.get_mesh_tools.return_value = mock_tools
            mock_registry.get_resolved_agent_config.return_value = mock_agent_config

            result = await step.execute({})

            assert result.status == PipelineStatus.SUCCESS
            assert (
                result.message
                == "Heartbeat prepared for agent 'test-agent-123' with 3 tools"
            )
            assert result.context["tool_count"] == 3


class TestHeartbeatPreparationContext:
    """Test context population and data structure."""

    @pytest.fixture
    def step(self):
        """Create a HeartbeatPreparationStep instance."""
        return HeartbeatPreparationStep()

    @pytest.fixture
    def mock_agent_config(self):
        """Mock agent configuration."""
        return {
            "agent_id": "context-test-456",
            "name": "context-agent",
            "version": "2.0.0",
            "http_host": "test.host.com",
            "http_port": 9090,
            "namespace": "test",
        }

    @pytest.mark.asyncio
    async def test_context_keys_present(self, step, mock_agent_config):
        """Test that all expected context keys are populated."""
        with patch(
            "_mcp_mesh.pipeline.startup.heartbeat_preparation.DecoratorRegistry"
        ) as mock_registry:
            mock_registry.get_mesh_tools.return_value = {}
            mock_registry.get_resolved_agent_config.return_value = mock_agent_config

            result = await step.execute({})

            required_keys = [
                "registration_data",
                "health_status",
                "tools_list",
                "tool_count",
            ]
            for key in required_keys:
                assert key in result.context, f"Missing context key: {key}"

    @pytest.mark.asyncio
    async def test_registration_data_structure(self, step, mock_agent_config):
        """Test registration data structure."""
        with (
            patch(
                "_mcp_mesh.pipeline.startup.heartbeat_preparation.DecoratorRegistry"
            ) as mock_registry,
            patch(
                "_mcp_mesh.shared.host_resolver.HostResolver.get_external_host",
                return_value="test.host.com",
            ),
        ):
            mock_registry.get_mesh_tools.return_value = {}
            mock_registry.get_resolved_agent_config.return_value = mock_agent_config

            result = await step.execute({})

            reg_data = result.context["registration_data"]
            assert isinstance(reg_data, dict)
            assert reg_data["agent_id"] == "context-test-456"
            assert reg_data["agent_type"] == "mcp_agent"
            assert reg_data["name"] == "context-test-456"
            assert reg_data["version"] == "2.0.0"
            assert (
                reg_data["http_host"] == "test.host.com"
            )  # Now comes from HostResolver
            assert reg_data["http_port"] == 9090
            assert reg_data["namespace"] == "test"
            assert isinstance(reg_data["timestamp"], datetime)
            assert isinstance(reg_data["tools"], list)

    @pytest.mark.asyncio
    async def test_health_status_structure(self, step, mock_agent_config):
        """Test health status structure."""
        with patch(
            "_mcp_mesh.pipeline.startup.heartbeat_preparation.DecoratorRegistry"
        ) as mock_registry:
            mock_registry.get_mesh_tools.return_value = {}
            mock_registry.get_resolved_agent_config.return_value = mock_agent_config

            result = await step.execute({})

            health_status = result.context["health_status"]
            assert isinstance(health_status, HealthStatus)
            assert health_status.agent_name == "context-test-456"
            assert health_status.status == HealthStatusType.HEALTHY
            assert health_status.version == "2.0.0"
            assert isinstance(health_status.capabilities, list)
            assert isinstance(health_status.timestamp, datetime)
            assert isinstance(health_status.metadata, dict)

    @pytest.mark.asyncio
    async def test_tools_list_structure(self, step, mock_agent_config):
        """Test tools list structure."""
        mock_func = MagicMock()
        mock_func.__name__ = "structured_tool"
        mock_tools = {
            "structured_tool": DecoratedFunction(
                decorator_type="mesh_tool",
                function=mock_func,
                metadata={
                    "capability": "structured_capability",
                    "tags": ["structured", "test"],
                    "version": "1.5.0",
                    "description": "Structured test tool",
                    "dependencies": [],  # No dependencies to avoid validation issues
                },
                registered_at=MagicMock(),
            )
        }

        with patch(
            "_mcp_mesh.pipeline.startup.heartbeat_preparation.DecoratorRegistry"
        ) as mock_registry:
            mock_registry.get_mesh_tools.return_value = mock_tools
            mock_registry.get_resolved_agent_config.return_value = mock_agent_config

            result = await step.execute({})

            tools_list = result.context["tools_list"]
            assert isinstance(tools_list, list)
            assert len(tools_list) == 1

            tool_data = tools_list[0]
            assert tool_data["function_name"] == "structured_tool"
            assert tool_data["capability"] == "structured_capability"
            assert tool_data["tags"] == ["structured", "test"]
            assert tool_data["version"] == "1.5.0"
            assert tool_data["description"] == "Structured test tool"
            assert isinstance(tool_data["dependencies"], list)
            assert len(tool_data["dependencies"]) == 0


class TestHeartbeatPreparationConfigUsage:
    """Test that agent config values are used directly."""

    @pytest.fixture
    def step(self):
        """Create a HeartbeatPreparationStep instance."""
        return HeartbeatPreparationStep()

    @pytest.mark.asyncio
    async def test_agent_config_values_used_directly(self, step):
        """Test that registration uses agent config values directly."""
        mock_agent_config = {
            "agent_id": "config-test-789",
            "http_host": "resolved.example.com",  # This will be ignored, HostResolver used instead
            "http_port": 9090,
            "version": "2.0.0",
            "namespace": "production",
        }

        with (
            patch(
                "_mcp_mesh.pipeline.startup.heartbeat_preparation.DecoratorRegistry"
            ) as mock_registry,
            patch(
                "_mcp_mesh.shared.host_resolver.HostResolver.get_external_host",
                return_value="resolved.example.com",
            ),
        ):
            mock_registry.get_mesh_tools.return_value = {}
            mock_registry.get_resolved_agent_config.return_value = mock_agent_config

            result = await step.execute({})

            reg_data = result.context["registration_data"]
            assert (
                reg_data["http_host"] == "resolved.example.com"
            )  # Now comes from HostResolver
            assert reg_data["http_port"] == 9090
            assert reg_data["version"] == "2.0.0"
            assert reg_data["namespace"] == "production"

    @pytest.mark.asyncio
    async def test_default_values_when_missing_from_config(self, step):
        """Test default values are used when missing from agent config."""
        mock_agent_config = {
            "agent_id": "minimal-config-001",
            # Missing http_host, http_port, version, namespace
        }

        with (
            patch(
                "_mcp_mesh.pipeline.startup.heartbeat_preparation.DecoratorRegistry"
            ) as mock_registry,
            patch(
                "_mcp_mesh.shared.host_resolver.HostResolver.get_external_host",
                return_value="localhost",
            ),
        ):
            mock_registry.get_mesh_tools.return_value = {}
            mock_registry.get_resolved_agent_config.return_value = mock_agent_config

            result = await step.execute({})

            reg_data = result.context["registration_data"]
            assert reg_data["http_host"] == "localhost"  # From HostResolver default
            assert reg_data["http_port"] == 0  # Default (auto-assign)
            assert reg_data["version"] == "1.0.0"  # Default
            assert reg_data["namespace"] == "default"  # Default

    @pytest.mark.asyncio
    async def test_health_status_uses_agent_config(self, step):
        """Test that health status metadata includes agent config."""
        mock_agent_config = {
            "agent_id": "health-test-456",
            "http_host": "health.example.com",
            "http_port": 7070,
            "version": "3.0.0",
            "custom_field": "custom_value",
        }

        with patch(
            "_mcp_mesh.pipeline.startup.heartbeat_preparation.DecoratorRegistry"
        ) as mock_registry:
            mock_registry.get_mesh_tools.return_value = {}
            mock_registry.get_resolved_agent_config.return_value = mock_agent_config

            result = await step.execute({})

            health_status = result.context["health_status"]
            metadata = health_status.metadata

            # Should include all agent config in metadata
            assert metadata["http_host"] == "health.example.com"
            assert metadata["http_port"] == 7070
            assert metadata["version"] == "3.0.0"
            assert metadata["custom_field"] == "custom_value"


class TestHeartbeatPreparationDebugMode:
    """Test debug mode functionality using config resolver."""

    @pytest.fixture
    def step(self):
        """Create a HeartbeatPreparationStep instance."""
        return HeartbeatPreparationStep()

    @pytest.fixture
    def mock_agent_config(self):
        """Mock agent configuration."""
        return {"agent_id": "debug-test-123"}

    @pytest.fixture
    def mock_tool_with_dependencies(self):
        """Mock tool with dependencies."""
        mock_func = MagicMock()
        mock_func.__name__ = "debug_tool"
        return {
            "debug_tool": DecoratedFunction(
                decorator_type="mesh_tool",
                function=mock_func,
                metadata={
                    "capability": "debug_capability",
                    "dependencies": [],  # No dependencies to avoid validation issues
                },
                registered_at=MagicMock(),
            )
        }

    @pytest.mark.asyncio
    async def test_debug_mode_enabled(
        self, step, mock_agent_config, mock_tool_with_dependencies
    ):
        """Test debug pointer information is included when debug mode is enabled."""
        with patch(
            "_mcp_mesh.pipeline.startup.heartbeat_preparation.get_config_value"
        ) as mock_get_config:
            # Mock debug mode enabled
            mock_get_config.return_value = True

            with patch(
                "_mcp_mesh.pipeline.startup.heartbeat_preparation.DecoratorRegistry"
            ) as mock_registry:
                mock_registry.get_mesh_tools.return_value = mock_tool_with_dependencies
                mock_registry.get_resolved_agent_config.return_value = mock_agent_config

                result = await step.execute({})

                tools_list = result.context["tools_list"]
                assert len(tools_list) == 1
                assert "debug_pointers" in tools_list[0]

                # Verify get_config_value was called correctly
                from _mcp_mesh.shared.config_resolver import ValidationRule

                mock_get_config.assert_called_with(
                    "MCP_MESH_DEBUG", default=False, rule=ValidationRule.TRUTHY_RULE
                )

    @pytest.mark.asyncio
    async def test_debug_mode_disabled(
        self, step, mock_agent_config, mock_tool_with_dependencies
    ):
        """Test debug pointer information is excluded when debug mode is disabled."""
        with patch(
            "_mcp_mesh.pipeline.startup.heartbeat_preparation.get_config_value"
        ) as mock_get_config:
            # Mock debug mode disabled
            mock_get_config.return_value = False

            with patch(
                "_mcp_mesh.pipeline.startup.heartbeat_preparation.DecoratorRegistry"
            ) as mock_registry:
                mock_registry.get_mesh_tools.return_value = mock_tool_with_dependencies
                mock_registry.get_resolved_agent_config.return_value = mock_agent_config

                result = await step.execute({})

                tools_list = result.context["tools_list"]
                assert len(tools_list) == 1
                assert "debug_pointers" not in tools_list[0]


class TestHeartbeatPreparationErrors:
    """Test error handling scenarios."""

    @pytest.fixture
    def step(self):
        """Create a HeartbeatPreparationStep instance."""
        return HeartbeatPreparationStep()

    @pytest.mark.asyncio
    async def test_get_mesh_tools_exception(self, step):
        """Test exception during get_mesh_tools call."""
        error_message = "Tools registry access failed"

        with patch(
            "_mcp_mesh.pipeline.startup.heartbeat_preparation.DecoratorRegistry"
        ) as mock_registry:
            mock_registry.get_mesh_tools.side_effect = Exception(error_message)

            result = await step.execute({})

            assert result.status == PipelineStatus.FAILED
            assert result.message == f"Heartbeat preparation failed: {error_message}"
            assert error_message in result.errors

    @pytest.mark.asyncio
    async def test_get_resolved_agent_config_exception(self, step):
        """Test exception during get_resolved_agent_config call."""
        error_message = "Agent config resolution failed"

        with patch(
            "_mcp_mesh.pipeline.startup.heartbeat_preparation.DecoratorRegistry"
        ) as mock_registry:
            mock_registry.get_mesh_tools.return_value = {}
            mock_registry.get_resolved_agent_config.side_effect = Exception(
                error_message
            )

            result = await step.execute({})

            assert result.status == PipelineStatus.FAILED
            assert result.message == f"Heartbeat preparation failed: {error_message}"
            assert error_message in result.errors

    @pytest.mark.asyncio
    async def test_tool_validation_exception(self, step):
        """Test exception during tool validation."""
        mock_agent_config = {"agent_id": "error-test-456"}

        # Create a tool that will cause validation to fail
        mock_func = MagicMock()
        mock_func.__name__ = "invalid_tool"
        mock_tools = {
            "invalid_tool": DecoratedFunction(
                decorator_type="mesh_tool",
                function=mock_func,
                metadata={
                    "capability": "invalid_capability",
                    "dependencies": ["dep1"],  # Has dependencies
                },
                registered_at=MagicMock(),
            )
        }

        with patch(
            "_mcp_mesh.pipeline.startup.heartbeat_preparation.DecoratorRegistry"
        ) as mock_registry:
            mock_registry.get_mesh_tools.return_value = mock_tools
            mock_registry.get_resolved_agent_config.return_value = mock_agent_config

            # Mock validation to fail
            with patch(
                "_mcp_mesh.pipeline.startup.heartbeat_preparation.validate_mesh_dependencies"
            ) as mock_validate:
                mock_validate.side_effect = Exception("Validation error")

                result = await step.execute({})

                assert result.status == PipelineStatus.FAILED
                assert "Heartbeat preparation failed:" in result.message

    @pytest.mark.asyncio
    async def test_error_context_preservation(self, step):
        """Test that context is not populated when error occurs."""
        error_message = "Heartbeat preparation error"

        with patch(
            "_mcp_mesh.pipeline.startup.heartbeat_preparation.DecoratorRegistry"
        ) as mock_registry:
            mock_registry.get_mesh_tools.side_effect = Exception(error_message)

            result = await step.execute({})

            # Context should be empty on error
            assert len(result.context) == 0


class TestHeartbeatPreparationToolValidation:
    """Test tool validation and dependency processing."""

    @pytest.fixture
    def step(self):
        """Create a HeartbeatPreparationStep instance."""
        return HeartbeatPreparationStep()

    @pytest.fixture
    def mock_agent_config(self):
        """Mock agent configuration."""
        return {"agent_id": "validation-test-789"}

    @pytest.mark.asyncio
    async def test_tool_with_valid_dependencies(self, step, mock_agent_config):
        """Test tool with valid dependencies passes validation."""
        mock_func = MagicMock()
        mock_func.__name__ = "valid_tool"
        mock_tools = {
            "valid_tool": DecoratedFunction(
                decorator_type="mesh_tool",
                function=mock_func,
                metadata={
                    "capability": "valid_capability",
                    "dependencies": [
                        "simple_dep",
                        {
                            "capability": "complex_dep",
                            "tags": ["tag1"],
                            "version": "1.0.0",
                        },
                    ],
                },
                registered_at=MagicMock(),
            )
        }

        with patch(
            "_mcp_mesh.pipeline.startup.heartbeat_preparation.DecoratorRegistry"
        ) as mock_registry:
            mock_registry.get_mesh_tools.return_value = mock_tools
            mock_registry.get_resolved_agent_config.return_value = mock_agent_config

            with patch(
                "_mcp_mesh.pipeline.startup.heartbeat_preparation.validate_mesh_dependencies"
            ) as mock_validate:
                mock_validate.return_value = (True, "")  # Valid

                result = await step.execute({})

                assert result.status == PipelineStatus.SUCCESS
                tools_list = result.context["tools_list"]
                assert len(tools_list) == 1

                tool_data = tools_list[0]
                assert len(tool_data["dependencies"]) == 2

                # Check simple dependency processing
                simple_dep = tool_data["dependencies"][0]
                assert simple_dep["capability"] == "simple_dep"
                assert simple_dep["tags"] == []
                assert simple_dep["version"] == ""
                assert simple_dep["namespace"] == "default"

                # Check complex dependency processing
                complex_dep = tool_data["dependencies"][1]
                assert complex_dep["capability"] == "complex_dep"
                assert complex_dep["tags"] == ["tag1"]
                assert complex_dep["version"] == "1.0.0"
                assert complex_dep["namespace"] == "default"

    @pytest.mark.asyncio
    async def test_tool_with_invalid_dependencies_skipped(
        self, step, mock_agent_config
    ):
        """Test tool with invalid dependencies is skipped."""
        mock_func = MagicMock()
        mock_func.__name__ = "invalid_tool"
        mock_tools = {
            "invalid_tool": DecoratedFunction(
                decorator_type="mesh_tool",
                function=mock_func,
                metadata={"capability": "invalid_capability", "dependencies": ["dep1"]},
                registered_at=MagicMock(),
            )
        }

        with patch(
            "_mcp_mesh.pipeline.startup.heartbeat_preparation.DecoratorRegistry"
        ) as mock_registry:
            mock_registry.get_mesh_tools.return_value = mock_tools
            mock_registry.get_resolved_agent_config.return_value = mock_agent_config

            with patch(
                "_mcp_mesh.pipeline.startup.heartbeat_preparation.validate_mesh_dependencies"
            ) as mock_validate:
                mock_validate.return_value = (False, "Invalid signature")  # Invalid

                result = await step.execute({})

                assert result.status == PipelineStatus.SUCCESS  # Still succeeds
                assert result.context["tool_count"] == 0  # Tool was skipped
                assert result.context["tools_list"] == []

    @pytest.mark.asyncio
    async def test_capabilities_extraction(self, step, mock_agent_config):
        """Test capabilities extraction from tools list."""
        mock_tools = {}
        for i in range(3):
            mock_func = MagicMock()
            mock_func.__name__ = f"tool_{i}"
            mock_tools[f"tool_{i}"] = DecoratedFunction(
                decorator_type="mesh_tool",
                function=mock_func,
                metadata={"capability": f"capability_{i}", "dependencies": []},
                registered_at=MagicMock(),
            )

        with patch(
            "_mcp_mesh.pipeline.startup.heartbeat_preparation.DecoratorRegistry"
        ) as mock_registry:
            mock_registry.get_mesh_tools.return_value = mock_tools
            mock_registry.get_resolved_agent_config.return_value = mock_agent_config

            result = await step.execute({})

            health_status = result.context["health_status"]
            capabilities = health_status.capabilities

            # Should extract all capabilities
            assert len(capabilities) == 3
            assert "capability_0" in capabilities
            assert "capability_1" in capabilities
            assert "capability_2" in capabilities

    @pytest.mark.asyncio
    async def test_default_capability_when_none_provided(self, step, mock_agent_config):
        """Test default capability is added when no tools provide capabilities."""
        with patch(
            "_mcp_mesh.pipeline.startup.heartbeat_preparation.DecoratorRegistry"
        ) as mock_registry:
            mock_registry.get_mesh_tools.return_value = {}  # No tools
            mock_registry.get_resolved_agent_config.return_value = mock_agent_config

            result = await step.execute({})

            health_status = result.context["health_status"]
            capabilities = health_status.capabilities

            # Should have default capability
            assert capabilities == ["default"]
