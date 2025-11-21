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

# Import the classes under test
from _mcp_mesh.pipeline.mcp_startup.heartbeat_preparation import (
    HeartbeatPreparationStep,
)
from _mcp_mesh.pipeline.shared import PipelineResult, PipelineStatus
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
            "_mcp_mesh.pipeline.mcp_startup.heartbeat_preparation.DecoratorRegistry"
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
            "_mcp_mesh.pipeline.mcp_startup.heartbeat_preparation.DecoratorRegistry"
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
            "_mcp_mesh.pipeline.mcp_startup.heartbeat_preparation.DecoratorRegistry"
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
            "_mcp_mesh.pipeline.mcp_startup.heartbeat_preparation.DecoratorRegistry"
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
                "_mcp_mesh.pipeline.mcp_startup.heartbeat_preparation.DecoratorRegistry"
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
            "_mcp_mesh.pipeline.mcp_startup.heartbeat_preparation.DecoratorRegistry"
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
            "_mcp_mesh.pipeline.mcp_startup.heartbeat_preparation.DecoratorRegistry"
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
                "_mcp_mesh.pipeline.mcp_startup.heartbeat_preparation.DecoratorRegistry"
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
                "_mcp_mesh.pipeline.mcp_startup.heartbeat_preparation.DecoratorRegistry"
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
            "_mcp_mesh.pipeline.mcp_startup.heartbeat_preparation.DecoratorRegistry"
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
            "_mcp_mesh.pipeline.mcp_startup.heartbeat_preparation.get_config_value"
        ) as mock_get_config:
            # Mock debug mode enabled
            mock_get_config.return_value = True

            with patch(
                "_mcp_mesh.pipeline.mcp_startup.heartbeat_preparation.DecoratorRegistry"
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
            "_mcp_mesh.pipeline.mcp_startup.heartbeat_preparation.get_config_value"
        ) as mock_get_config:
            # Mock debug mode disabled
            mock_get_config.return_value = False

            with patch(
                "_mcp_mesh.pipeline.mcp_startup.heartbeat_preparation.DecoratorRegistry"
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
            "_mcp_mesh.pipeline.mcp_startup.heartbeat_preparation.DecoratorRegistry"
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
            "_mcp_mesh.pipeline.mcp_startup.heartbeat_preparation.DecoratorRegistry"
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
            "_mcp_mesh.pipeline.mcp_startup.heartbeat_preparation.DecoratorRegistry"
        ) as mock_registry:
            mock_registry.get_mesh_tools.return_value = mock_tools
            mock_registry.get_resolved_agent_config.return_value = mock_agent_config

            # Mock validation to fail
            with patch(
                "_mcp_mesh.pipeline.mcp_startup.heartbeat_preparation.validate_mesh_dependencies"
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
            "_mcp_mesh.pipeline.mcp_startup.heartbeat_preparation.DecoratorRegistry"
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
            "_mcp_mesh.pipeline.mcp_startup.heartbeat_preparation.DecoratorRegistry"
        ) as mock_registry:
            mock_registry.get_mesh_tools.return_value = mock_tools
            mock_registry.get_resolved_agent_config.return_value = mock_agent_config

            with patch(
                "_mcp_mesh.pipeline.mcp_startup.heartbeat_preparation.validate_mesh_dependencies"
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
            "_mcp_mesh.pipeline.mcp_startup.heartbeat_preparation.DecoratorRegistry"
        ) as mock_registry:
            mock_registry.get_mesh_tools.return_value = mock_tools
            mock_registry.get_resolved_agent_config.return_value = mock_agent_config

            with patch(
                "_mcp_mesh.pipeline.mcp_startup.heartbeat_preparation.validate_mesh_dependencies"
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
            "_mcp_mesh.pipeline.mcp_startup.heartbeat_preparation.DecoratorRegistry"
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
            "_mcp_mesh.pipeline.mcp_startup.heartbeat_preparation.DecoratorRegistry"
        ) as mock_registry:
            mock_registry.get_mesh_tools.return_value = {}  # No tools
            mock_registry.get_resolved_agent_config.return_value = mock_agent_config

            result = await step.execute({})

            health_status = result.context["health_status"]
            capabilities = health_status.capabilities

            # Should have default capability
            assert capabilities == ["default"]


class TestHeartbeatPreparationInputSchemaExtraction:
    """Test inputSchema extraction from FastMCP tools (Phase 2: LLM Integration)."""

    @pytest.fixture
    def step(self):
        """Create a HeartbeatPreparationStep instance."""
        return HeartbeatPreparationStep()

    @pytest.fixture
    def mock_agent_config(self):
        """Mock agent configuration."""
        return {"agent_id": "schema-test-001"}

    @pytest.mark.asyncio
    async def test_tool_with_fastmcp_schema_includes_input_schema(
        self, step, mock_agent_config
    ):
        """Test that tools with FastMCP schemas include inputSchema in tool_data."""
        # Create a mock FastMCP tool with inputSchema
        mock_fastmcp_tool = MagicMock()
        mock_fastmcp_tool.name = "test_tool"
        mock_fastmcp_tool.description = "Test tool with schema"
        mock_fastmcp_tool.parameters = {
            "type": "object",
            "properties": {
                "user_email": {"type": "string", "description": "User's email"},
                "count": {"type": "integer", "description": "Count of items"},
            },
            "required": ["user_email"],
        }

        # Create mock function with reference to FastMCP tool
        mock_func = MagicMock()
        mock_func.__name__ = "test_tool"
        mock_func._fastmcp_tool = mock_fastmcp_tool  # Store reference to FastMCP tool

        mock_tools = {
            "test_tool": DecoratedFunction(
                decorator_type="mesh_tool",
                function=mock_func,
                metadata={
                    "capability": "test_capability",
                    "tags": ["test"],
                    "version": "1.0.0",
                    "dependencies": [],
                },
                registered_at=MagicMock(),
            )
        }

        with patch(
            "_mcp_mesh.pipeline.mcp_startup.heartbeat_preparation.DecoratorRegistry"
        ) as mock_registry:
            mock_registry.get_mesh_tools.return_value = mock_tools
            mock_registry.get_resolved_agent_config.return_value = mock_agent_config

            result = await step.execute({})

            assert result.status == PipelineStatus.SUCCESS
            tools_list = result.context["tools_list"]
            assert len(tools_list) == 1

            tool_data = tools_list[0]
            # CRITICAL: inputSchema must be included
            assert (
                "input_schema" in tool_data
            ), "inputSchema should be extracted from FastMCP tool"
            assert tool_data["input_schema"] == mock_fastmcp_tool.parameters
            assert tool_data["input_schema"]["type"] == "object"
            assert "user_email" in tool_data["input_schema"]["properties"]
            assert "count" in tool_data["input_schema"]["properties"]

    @pytest.mark.asyncio
    async def test_tool_without_fastmcp_schema_has_none_input_schema(
        self, step, mock_agent_config
    ):
        """Test that tools without FastMCP schemas have None for inputSchema."""
        # Create mock function WITHOUT FastMCP tool reference
        mock_func = MagicMock(spec=["__name__", "__call__"])
        mock_func.__name__ = "plain_tool"
        # Explicitly ensure no _fastmcp_tool attribute

        mock_tools = {
            "plain_tool": DecoratedFunction(
                decorator_type="mesh_tool",
                function=mock_func,
                metadata={
                    "capability": "plain_capability",
                    "dependencies": [],
                },
                registered_at=MagicMock(),
            )
        }

        with patch(
            "_mcp_mesh.pipeline.mcp_startup.heartbeat_preparation.DecoratorRegistry"
        ) as mock_registry:
            mock_registry.get_mesh_tools.return_value = mock_tools
            mock_registry.get_resolved_agent_config.return_value = mock_agent_config

            result = await step.execute({})

            tools_list = result.context["tools_list"]
            tool_data = tools_list[0]

            # Should have input_schema key but with None value
            assert "input_schema" in tool_data
            assert tool_data["input_schema"] is None

    @pytest.mark.asyncio
    async def test_multiple_tools_with_different_schemas(self, step, mock_agent_config):
        """Test multiple tools each with their own inputSchema."""
        # Tool 1: Has schema
        mock_tool1 = MagicMock()
        mock_tool1.name = "tool_with_schema"
        mock_tool1.parameters = {
            "type": "object",
            "properties": {"param1": {"type": "string"}},
        }

        mock_func1 = MagicMock()
        mock_func1.__name__ = "tool_with_schema"
        mock_func1._fastmcp_tool = mock_tool1

        # Tool 2: No schema
        mock_func2 = MagicMock(spec=["__name__", "__call__"])
        mock_func2.__name__ = "tool_without_schema"

        mock_tools = {
            "tool_with_schema": DecoratedFunction(
                decorator_type="mesh_tool",
                function=mock_func1,
                metadata={"capability": "cap1", "dependencies": []},
                registered_at=MagicMock(),
            ),
            "tool_without_schema": DecoratedFunction(
                decorator_type="mesh_tool",
                function=mock_func2,
                metadata={"capability": "cap2", "dependencies": []},
                registered_at=MagicMock(),
            ),
        }

        with patch(
            "_mcp_mesh.pipeline.mcp_startup.heartbeat_preparation.DecoratorRegistry"
        ) as mock_registry:
            mock_registry.get_mesh_tools.return_value = mock_tools
            mock_registry.get_resolved_agent_config.return_value = mock_agent_config

            result = await step.execute({})

            tools_list = result.context["tools_list"]
            assert len(tools_list) == 2

            # Find each tool
            tool_with_schema = next(
                t for t in tools_list if t["function_name"] == "tool_with_schema"
            )
            tool_without_schema = next(
                t for t in tools_list if t["function_name"] == "tool_without_schema"
            )

            # Verify schemas
            assert tool_with_schema["input_schema"] is not None
            assert tool_with_schema["input_schema"]["type"] == "object"

            assert tool_without_schema["input_schema"] is None

    @pytest.mark.asyncio
    async def test_schema_extraction_handles_complex_schemas(
        self, step, mock_agent_config
    ):
        """Test extraction of complex nested schemas."""
        mock_tool = MagicMock()
        mock_tool.name = "complex_tool"
        mock_tool.parameters = {
            "type": "object",
            "properties": {
                "simple_param": {"type": "string"},
                "nested_object": {
                    "type": "object",
                    "properties": {
                        "inner_field": {"type": "number"},
                        "deep_array": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                    },
                },
                "optional_param": {"type": "boolean"},
            },
            "required": ["simple_param", "nested_object"],
        }

        mock_func = MagicMock()
        mock_func.__name__ = "complex_tool"
        mock_func._fastmcp_tool = mock_tool

        mock_tools = {
            "complex_tool": DecoratedFunction(
                decorator_type="mesh_tool",
                function=mock_func,
                metadata={"capability": "complex_cap", "dependencies": []},
                registered_at=MagicMock(),
            )
        }

        with patch(
            "_mcp_mesh.pipeline.mcp_startup.heartbeat_preparation.DecoratorRegistry"
        ) as mock_registry:
            mock_registry.get_mesh_tools.return_value = mock_tools
            mock_registry.get_resolved_agent_config.return_value = mock_agent_config

            result = await step.execute({})

            tools_list = result.context["tools_list"]
            tool_data = tools_list[0]

            # Verify complete schema is preserved
            schema = tool_data["input_schema"]
            assert schema["type"] == "object"
            assert "simple_param" in schema["properties"]
            assert "nested_object" in schema["properties"]
            assert schema["required"] == ["simple_param", "nested_object"]

            # Verify nested structure is intact
            nested = schema["properties"]["nested_object"]
            assert nested["type"] == "object"
            assert "inner_field" in nested["properties"]
            assert "deep_array" in nested["properties"]


class TestHeartbeatPreparationLLMFilter:
    """Test LLM filter integration in heartbeat preparation."""

    @pytest.fixture
    def step(self):
        """Create a HeartbeatPreparationStep instance."""
        return HeartbeatPreparationStep()

    @pytest.fixture
    def mock_agent_config(self):
        """Mock resolved agent configuration."""
        return {
            "agent_id": "llm-agent-123",
            "name": "llm-agent",
            "version": "1.0.0",
            "description": "LLM test agent",
            "http_host": "localhost",
            "http_port": 8080,
            "enable_http": True,
            "namespace": "default",
            "health_interval": 30,
        }

    @pytest.fixture
    def mock_llm_tool_function(self):
        """Create a mock LLM tool function."""
        from pydantic import BaseModel

        class ChatResponse(BaseModel):
            answer: str
            confidence: float

        mock_func = MagicMock()
        mock_func.__name__ = "chat"
        mock_func.__annotations__ = {
            "message": str,
            "llm": "MeshLlmAgent",
            "return": ChatResponse,
        }
        return mock_func

    @pytest.fixture
    def mock_mesh_tools_with_llm(self, mock_llm_tool_function):
        """Mock mesh tools with LLM function."""
        decorated_func = DecoratedFunction(
            decorator_type="mesh_tool",
            function=mock_llm_tool_function,
            metadata={
                "capability": "chat",
                "tags": ["llm", "conversational"],
                "version": "1.0.0",
                "description": "Chat with LLM and tools",
                "dependencies": [],
            },
            registered_at=MagicMock(),
        )
        return {"chat": decorated_func}

    @pytest.mark.asyncio
    async def test_llm_filter_with_simple_string_filter(
        self, step, mock_agent_config, mock_mesh_tools_with_llm
    ):
        """Test LLM filter integration with simple string filter."""
        from datetime import datetime

        from _mcp_mesh.engine.decorator_registry import (
            DecoratorRegistry,
            LLMAgentMetadata,
        )

        # Clear registry first to ensure test isolation
        DecoratorRegistry._mesh_llm_agents.clear()

        # Register LLM agent with simple string filter
        llm_metadata = LLMAgentMetadata(
            function=mock_mesh_tools_with_llm["chat"].function,
            config={
                "filter": "document_processor",
                "filter_mode": "all",
                "provider": "claude",
            },
            output_type=None,
            param_name="llm",
            function_id="chat_abc123",
            registered_at=datetime.now(),
        )
        DecoratorRegistry._mesh_llm_agents["chat_abc123"] = llm_metadata

        try:
            with (
                patch(
                    "_mcp_mesh.engine.decorator_registry.DecoratorRegistry.get_mesh_tools"
                ) as mock_get_tools,
                patch(
                    "_mcp_mesh.engine.decorator_registry.DecoratorRegistry.get_resolved_agent_config"
                ) as mock_get_config,
            ):
                mock_get_tools.return_value = mock_mesh_tools_with_llm
                mock_get_config.return_value = mock_agent_config

                result = await step.execute({})

                tools_list = result.context["tools_list"]
                assert len(tools_list) == 1

                tool_data = tools_list[0]
                assert tool_data["function_name"] == "chat"
                assert "llm_filter" in tool_data
                assert tool_data["llm_filter"] is not None

                llm_filter = tool_data["llm_filter"]
                assert llm_filter["filter"] == [
                    "document_processor"
                ]  # Normalized to array
                assert llm_filter["filter_mode"] == "all"
        finally:
            # Cleanup
            DecoratorRegistry._mesh_llm_agents.clear()

    @pytest.mark.asyncio
    async def test_llm_filter_with_dict_filter(
        self, step, mock_agent_config, mock_mesh_tools_with_llm
    ):
        """Test LLM filter integration with dict filter."""
        from datetime import datetime

        from _mcp_mesh.engine.decorator_registry import (
            DecoratorRegistry,
            LLMAgentMetadata,
        )

        # Register LLM agent with dict filter
        llm_metadata = LLMAgentMetadata(
            function=mock_mesh_tools_with_llm["chat"].function,
            config={
                "filter": {"capability": "document", "tags": ["pdf", "advanced"]},
                "filter_mode": "best_match",
                "provider": "openai",
            },
            output_type=None,
            param_name="llm",
            function_id="chat_def456",
            registered_at=datetime.now(),
        )
        DecoratorRegistry._mesh_llm_agents["chat_def456"] = llm_metadata

        try:
            with (
                patch(
                    "_mcp_mesh.engine.decorator_registry.DecoratorRegistry.get_mesh_tools"
                ) as mock_get_tools,
                patch(
                    "_mcp_mesh.engine.decorator_registry.DecoratorRegistry.get_resolved_agent_config"
                ) as mock_get_config,
            ):
                mock_get_tools.return_value = mock_mesh_tools_with_llm
                mock_get_config.return_value = mock_agent_config

                result = await step.execute({})

                tools_list = result.context["tools_list"]
                tool_data = tools_list[0]

                llm_filter = tool_data["llm_filter"]
                assert llm_filter["filter"] == [
                    {"capability": "document", "tags": ["pdf", "advanced"]}
                ]
                assert llm_filter["filter_mode"] == "best_match"
        finally:
            DecoratorRegistry._mesh_llm_agents.clear()

    @pytest.mark.asyncio
    async def test_llm_filter_with_list_filter(
        self, step, mock_agent_config, mock_mesh_tools_with_llm
    ):
        """Test LLM filter integration with list of mixed filters."""
        from datetime import datetime

        from _mcp_mesh.engine.decorator_registry import (
            DecoratorRegistry,
            LLMAgentMetadata,
        )

        # Register LLM agent with list filter
        llm_metadata = LLMAgentMetadata(
            function=mock_mesh_tools_with_llm["chat"].function,
            config={
                "filter": [
                    {"capability": "document", "tags": ["pdf"]},
                    "web_search",
                    {"capability": "database", "tags": ["postgres"]},
                ],
                "filter_mode": "all",
                "provider": "claude",
            },
            output_type=None,
            param_name="llm",
            function_id="chat_ghi789",
            registered_at=datetime.now(),
        )
        DecoratorRegistry._mesh_llm_agents["chat_ghi789"] = llm_metadata

        try:
            with (
                patch(
                    "_mcp_mesh.engine.decorator_registry.DecoratorRegistry.get_mesh_tools"
                ) as mock_get_tools,
                patch(
                    "_mcp_mesh.engine.decorator_registry.DecoratorRegistry.get_resolved_agent_config"
                ) as mock_get_config,
            ):
                mock_get_tools.return_value = mock_mesh_tools_with_llm
                mock_get_config.return_value = mock_agent_config

                result = await step.execute({})

                tools_list = result.context["tools_list"]
                tool_data = tools_list[0]

                llm_filter = tool_data["llm_filter"]
                assert isinstance(llm_filter["filter"], list)
                assert len(llm_filter["filter"]) == 3
                assert llm_filter["filter"][0] == {
                    "capability": "document",
                    "tags": ["pdf"],
                }
                assert llm_filter["filter"][1] == "web_search"
                assert llm_filter["filter"][2] == {
                    "capability": "database",
                    "tags": ["postgres"],
                }
                assert llm_filter["filter_mode"] == "all"
        finally:
            DecoratorRegistry._mesh_llm_agents.clear()

    @pytest.mark.asyncio
    async def test_no_llm_filter_for_regular_tools(self, step, mock_agent_config):
        """Test that regular tools (without @mesh.llm) don't have llm_filter."""
        mock_func = MagicMock()
        mock_func.__name__ = "regular_tool"

        decorated_func = DecoratedFunction(
            decorator_type="mesh_tool",
            function=mock_func,
            metadata={
                "capability": "greeting",
                "tags": ["test"],
                "version": "1.0.0",
                "description": "Regular tool without LLM",
                "dependencies": [],
            },
            registered_at=MagicMock(),
        )
        mock_mesh_tools = {"regular_tool": decorated_func}

        with (
            patch(
                "_mcp_mesh.engine.decorator_registry.DecoratorRegistry.get_mesh_tools"
            ) as mock_get_tools,
            patch(
                "_mcp_mesh.engine.decorator_registry.DecoratorRegistry.get_resolved_agent_config"
            ) as mock_get_config,
        ):
            mock_get_tools.return_value = mock_mesh_tools
            mock_get_config.return_value = mock_agent_config

            result = await step.execute({})

            tools_list = result.context["tools_list"]
            tool_data = tools_list[0]

            # Regular tool should have llm_filter as None
            assert tool_data["llm_filter"] is None

    @pytest.mark.asyncio
    async def test_llm_filter_with_none_filter(
        self, step, mock_agent_config, mock_mesh_tools_with_llm
    ):
        """Test LLM filter when filter is None (edge case)."""
        from datetime import datetime

        from _mcp_mesh.engine.decorator_registry import (
            DecoratorRegistry,
            LLMAgentMetadata,
        )

        # Register LLM agent with None filter
        llm_metadata = LLMAgentMetadata(
            function=mock_mesh_tools_with_llm["chat"].function,
            config={
                "filter": None,
                "filter_mode": "all",
                "provider": "claude",
            },
            output_type=None,
            param_name="llm",
            function_id="chat_jkl012",
            registered_at=datetime.now(),
        )
        DecoratorRegistry._mesh_llm_agents["chat_jkl012"] = llm_metadata

        try:
            with (
                patch(
                    "_mcp_mesh.engine.decorator_registry.DecoratorRegistry.get_mesh_tools"
                ) as mock_get_tools,
                patch(
                    "_mcp_mesh.engine.decorator_registry.DecoratorRegistry.get_resolved_agent_config"
                ) as mock_get_config,
            ):
                mock_get_tools.return_value = mock_mesh_tools_with_llm
                mock_get_config.return_value = mock_agent_config

                result = await step.execute({})

                tools_list = result.context["tools_list"]
                tool_data = tools_list[0]

                llm_filter = tool_data["llm_filter"]
                assert llm_filter["filter"] == []  # Empty array for None filter
                assert llm_filter["filter_mode"] == "all"
        finally:
            DecoratorRegistry._mesh_llm_agents.clear()
