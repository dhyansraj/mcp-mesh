"""
Unit tests for ConfigurationStep pipeline step.

Tests the resolution of agent configuration from DecoratorRegistry and context population
for subsequent pipeline steps. Focus on configuration resolution without duplicating
agent ID generation tests from test_01.
"""

from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

from _mcp_mesh.pipeline.shared import PipelineResult, PipelineStatus

# Import the classes under test
from _mcp_mesh.pipeline.startup.configuration import ConfigurationStep


class TestConfigurationStep:
    """Test the ConfigurationStep class initialization and basic properties."""

    def test_initialization(self):
        """Test ConfigurationStep initialization."""
        step = ConfigurationStep()

        assert step.name == "configuration"
        assert step.required is True
        assert step.description == "Resolve agent configuration with defaults"

    def test_inheritance(self):
        """Test ConfigurationStep inherits from PipelineStep."""
        from _mcp_mesh.pipeline.shared import PipelineStep

        step = ConfigurationStep()
        assert isinstance(step, PipelineStep)

    def test_execute_method_exists(self):
        """Test execute method exists and is callable."""
        step = ConfigurationStep()
        assert hasattr(step, "execute")
        assert callable(step.execute)


class TestConfigurationSuccess:
    """Test successful configuration resolution scenarios."""

    @pytest.fixture
    def step(self):
        """Create a ConfigurationStep instance."""
        return ConfigurationStep()

    @pytest.fixture
    def mock_config_with_agent(self):
        """Mock configuration with explicit agent."""
        return {
            "name": "test-agent",
            "version": "1.0.0",
            "description": "Test agent",
            "http_host": "localhost",
            "http_port": 8080,
            "enable_http": True,
            "namespace": "default",
            "health_interval": 30,
            "auto_run": True,
            "auto_run_interval": 10,
            "agent_id": "test-agent-abc12345",
        }

    @pytest.fixture
    def mock_config_synthetic(self):
        """Mock configuration without explicit agent (synthetic)."""
        return {
            "name": None,
            "version": "1.0.0",
            "description": None,
            "http_host": "localhost",
            "http_port": 0,
            "enable_http": True,
            "namespace": "default",
            "health_interval": 30,
            "auto_run": True,
            "auto_run_interval": 10,
            "agent_id": "agent-xyz67890",
        }

    @pytest.mark.asyncio
    async def test_configuration_with_explicit_agent(
        self, step, mock_config_with_agent
    ):
        """Test configuration resolution with explicit @mesh.agent decorator."""
        mock_agents = {"TestAgent": MagicMock()}

        with patch(
            "_mcp_mesh.pipeline.startup.configuration.DecoratorRegistry"
        ) as mock_registry:
            mock_registry.get_resolved_agent_config.return_value = (
                mock_config_with_agent
            )
            mock_registry.get_mesh_agents.return_value = mock_agents

            result = await step.execute({})

            assert result.status == PipelineStatus.SUCCESS
            assert (
                result.message
                == "Configuration resolved for agent 'test-agent-abc12345'"
            )
            assert result.context["agent_config"] == mock_config_with_agent
            assert result.context["agent_id"] == "test-agent-abc12345"
            assert result.context["has_explicit_agent"] is True

    @pytest.mark.asyncio
    async def test_configuration_without_explicit_agent(
        self, step, mock_config_synthetic
    ):
        """Test configuration resolution without explicit agent (tools only)."""
        mock_agents = {}

        with patch(
            "_mcp_mesh.pipeline.startup.configuration.DecoratorRegistry"
        ) as mock_registry:
            mock_registry.get_resolved_agent_config.return_value = mock_config_synthetic
            mock_registry.get_mesh_agents.return_value = mock_agents

            result = await step.execute({})

            assert result.status == PipelineStatus.SUCCESS
            assert result.message == "Configuration resolved for agent 'agent-xyz67890'"
            assert result.context["agent_config"] == mock_config_synthetic
            assert result.context["agent_id"] == "agent-xyz67890"
            assert result.context["has_explicit_agent"] is False

    @pytest.mark.asyncio
    async def test_configuration_with_multiple_agents(
        self, step, mock_config_with_agent
    ):
        """Test configuration resolution with multiple agents (uses first one)."""
        mock_agents = {
            "Agent1": MagicMock(),
            "Agent2": MagicMock(),
            "Agent3": MagicMock(),
        }

        with patch(
            "_mcp_mesh.pipeline.startup.configuration.DecoratorRegistry"
        ) as mock_registry:
            mock_registry.get_resolved_agent_config.return_value = (
                mock_config_with_agent
            )
            mock_registry.get_mesh_agents.return_value = mock_agents

            result = await step.execute({})

            assert result.status == PipelineStatus.SUCCESS
            assert result.context["has_explicit_agent"] is True
            assert len(mock_agents) == 3  # Multiple agents detected

    @pytest.mark.asyncio
    async def test_agent_id_present_in_config(self, step):
        """Test that agent_id is always present in resolved configuration."""
        test_config = {
            "name": "custom-agent",
            "agent_id": "custom-agent-def45678",
            "version": "2.0.0",
        }

        with patch(
            "_mcp_mesh.pipeline.startup.configuration.DecoratorRegistry"
        ) as mock_registry:
            mock_registry.get_resolved_agent_config.return_value = test_config
            mock_registry.get_mesh_agents.return_value = {"CustomAgent": MagicMock()}

            result = await step.execute({})

            assert "agent_id" in result.context["agent_config"]
            assert result.context["agent_id"] == "custom-agent-def45678"

    @pytest.mark.asyncio
    async def test_registry_methods_called(self, step):
        """Test that both registry methods are called during execution."""
        mock_config = {"agent_id": "test-agent-123", "name": "test"}
        mock_agents = {"TestAgent": MagicMock()}

        with patch(
            "_mcp_mesh.pipeline.startup.configuration.DecoratorRegistry"
        ) as mock_registry:
            mock_registry.get_resolved_agent_config.return_value = mock_config
            mock_registry.get_mesh_agents.return_value = mock_agents

            await step.execute({})

            mock_registry.get_resolved_agent_config.assert_called_once()
            mock_registry.get_mesh_agents.assert_called_once()


class TestConfigurationContext:
    """Test context population logic and data structure."""

    @pytest.fixture
    def step(self):
        """Create a ConfigurationStep instance."""
        return ConfigurationStep()

    @pytest.mark.asyncio
    async def test_context_keys_present(self, step):
        """Test that all expected context keys are populated."""
        mock_config = {"agent_id": "test-123", "name": "test"}
        mock_agents = {"Agent": MagicMock()}

        with patch(
            "_mcp_mesh.pipeline.startup.configuration.DecoratorRegistry"
        ) as mock_registry:
            mock_registry.get_resolved_agent_config.return_value = mock_config
            mock_registry.get_mesh_agents.return_value = mock_agents

            result = await step.execute({})

            # Check all required context keys
            required_keys = ["agent_config", "agent_id", "has_explicit_agent"]
            for key in required_keys:
                assert key in result.context, f"Missing context key: {key}"

    @pytest.mark.asyncio
    async def test_context_data_types(self, step):
        """Test that context data has correct types."""
        mock_config = {"agent_id": "test-456", "name": "test", "version": "1.0.0"}
        mock_agents = {"Agent": MagicMock()}

        with patch(
            "_mcp_mesh.pipeline.startup.configuration.DecoratorRegistry"
        ) as mock_registry:
            mock_registry.get_resolved_agent_config.return_value = mock_config
            mock_registry.get_mesh_agents.return_value = mock_agents

            result = await step.execute({})

            # Check data types
            assert isinstance(result.context["agent_config"], dict)
            assert isinstance(result.context["agent_id"], str)
            assert isinstance(result.context["has_explicit_agent"], bool)

    @pytest.mark.asyncio
    async def test_agent_config_structure(self, step):
        """Test that agent_config maintains DecoratorRegistry structure."""
        expected_config = {
            "name": "structured-agent",
            "version": "1.5.0",
            "description": "Test structure",
            "http_host": "custom.host",
            "http_port": 9090,
            "enable_http": False,
            "namespace": "custom",
            "health_interval": 60,
            "auto_run": False,
            "auto_run_interval": 20,
            "agent_id": "structured-agent-hij78901",
        }

        with patch(
            "_mcp_mesh.pipeline.startup.configuration.DecoratorRegistry"
        ) as mock_registry:
            mock_registry.get_resolved_agent_config.return_value = expected_config
            mock_registry.get_mesh_agents.return_value = {"Agent": MagicMock()}

            result = await step.execute({})

            # Verify exact preservation of structure
            assert result.context["agent_config"] == expected_config
            for key, value in expected_config.items():
                assert result.context["agent_config"][key] == value

    @pytest.mark.asyncio
    async def test_has_explicit_agent_boolean_logic(self, step):
        """Test has_explicit_agent boolean logic with different scenarios."""
        mock_config = {"agent_id": "bool-test-789", "name": "test"}

        # Test with explicit agents
        with patch(
            "_mcp_mesh.pipeline.startup.configuration.DecoratorRegistry"
        ) as mock_registry:
            mock_registry.get_resolved_agent_config.return_value = mock_config
            mock_registry.get_mesh_agents.return_value = {"Agent1": MagicMock()}

            result = await step.execute({})
            assert result.context["has_explicit_agent"] is True

        # Test without explicit agents
        with patch(
            "_mcp_mesh.pipeline.startup.configuration.DecoratorRegistry"
        ) as mock_registry:
            mock_registry.get_resolved_agent_config.return_value = mock_config
            mock_registry.get_mesh_agents.return_value = {}

            result = await step.execute({})
            assert result.context["has_explicit_agent"] is False


class TestConfigurationMessages:
    """Test result message formatting."""

    @pytest.fixture
    def step(self):
        """Create a ConfigurationStep instance."""
        return ConfigurationStep()

    @pytest.mark.asyncio
    async def test_success_message_format(self, step):
        """Test success message format with agent_id."""
        test_cases = [
            "test-agent-123",
            "custom-agent-abc456",
            "agent-xyz789",
            "very-long-agent-name-with-uuid-def012",
        ]

        for agent_id in test_cases:
            mock_config = {"agent_id": agent_id, "name": "test"}
            expected_message = f"Configuration resolved for agent '{agent_id}'"

            with patch(
                "_mcp_mesh.pipeline.startup.configuration.DecoratorRegistry"
            ) as mock_registry:
                mock_registry.get_resolved_agent_config.return_value = mock_config
                mock_registry.get_mesh_agents.return_value = {}

                result = await step.execute({})
                assert result.message == expected_message

    @pytest.mark.asyncio
    async def test_message_with_different_agent_ids(self, step):
        """Test message formatting with various agent_id formats."""
        agent_configs = [
            {"agent_id": "simple-123", "name": "simple"},
            {"agent_id": "complex-agent-name-456", "name": "complex"},
            {"agent_id": "agent-789", "name": None},  # Synthetic case
        ]

        for config in agent_configs:
            with patch(
                "_mcp_mesh.pipeline.startup.configuration.DecoratorRegistry"
            ) as mock_registry:
                mock_registry.get_resolved_agent_config.return_value = config
                mock_registry.get_mesh_agents.return_value = {}

                result = await step.execute({})

                expected = f"Configuration resolved for agent '{config['agent_id']}'"
                assert result.message == expected

    @pytest.mark.asyncio
    async def test_default_message_handling(self, step):
        """Test that default message is overridden by success."""
        mock_config = {"agent_id": "default-test-001", "name": "test"}

        with patch(
            "_mcp_mesh.pipeline.startup.configuration.DecoratorRegistry"
        ) as mock_registry:
            mock_registry.get_resolved_agent_config.return_value = mock_config
            mock_registry.get_mesh_agents.return_value = {}

            result = await step.execute({})

            # Should not be the default message
            assert result.message != "Configuration resolution completed"
            assert "Configuration resolved for agent" in result.message


class TestConfigurationErrors:
    """Test error handling scenarios."""

    @pytest.fixture
    def step(self):
        """Create a ConfigurationStep instance."""
        return ConfigurationStep()

    @pytest.mark.asyncio
    async def test_get_resolved_agent_config_exception(self, step):
        """Test exception during get_resolved_agent_config call."""
        error_message = "Configuration resolution failed"

        with patch(
            "_mcp_mesh.pipeline.startup.configuration.DecoratorRegistry"
        ) as mock_registry:
            mock_registry.get_resolved_agent_config.side_effect = Exception(
                error_message
            )

            result = await step.execute({})

            assert result.status == PipelineStatus.FAILED
            assert result.message == f"Configuration resolution failed: {error_message}"
            assert error_message in result.errors

    @pytest.mark.asyncio
    async def test_get_mesh_agents_exception(self, step):
        """Test exception during get_mesh_agents call."""
        error_message = "Agent registry access failed"
        mock_config = {"agent_id": "test-123", "name": "test"}

        with patch(
            "_mcp_mesh.pipeline.startup.configuration.DecoratorRegistry"
        ) as mock_registry:
            mock_registry.get_resolved_agent_config.return_value = mock_config
            mock_registry.get_mesh_agents.side_effect = Exception(error_message)

            result = await step.execute({})

            assert result.status == PipelineStatus.FAILED
            assert result.message == f"Configuration resolution failed: {error_message}"
            assert error_message in result.errors

    @pytest.mark.asyncio
    async def test_general_exception_handling(self, step):
        """Test general exception handling with custom error."""
        error_message = "Unexpected configuration error"

        with patch(
            "_mcp_mesh.pipeline.startup.configuration.DecoratorRegistry"
        ) as mock_registry:
            mock_registry.get_resolved_agent_config.side_effect = RuntimeError(
                error_message
            )

            result = await step.execute({})

            assert result.status == PipelineStatus.FAILED
            assert "Configuration resolution failed:" in result.message
            assert error_message in result.message
            assert len(result.errors) == 1
            assert result.errors[0] == error_message

    @pytest.mark.asyncio
    async def test_error_context_preservation(self, step):
        """Test that context is not populated when error occurs."""
        error_message = "Configuration error"

        with patch(
            "_mcp_mesh.pipeline.startup.configuration.DecoratorRegistry"
        ) as mock_registry:
            mock_registry.get_resolved_agent_config.side_effect = Exception(
                error_message
            )

            result = await step.execute({})

            # Context should be empty on error
            assert len(result.context) == 0

    @pytest.mark.asyncio
    async def test_partial_error_handling(self, step):
        """Test error after successful config resolution but failed agents call."""
        mock_config = {"agent_id": "partial-test-456", "name": "partial"}
        error_message = "Agents call failed"

        with patch(
            "_mcp_mesh.pipeline.startup.configuration.DecoratorRegistry"
        ) as mock_registry:
            mock_registry.get_resolved_agent_config.return_value = mock_config
            mock_registry.get_mesh_agents.side_effect = Exception(error_message)

            result = await step.execute({})

            # Should still fail even though first call succeeded
            assert result.status == PipelineStatus.FAILED
            assert error_message in result.message
            assert len(result.context) == 0  # Context not populated on any error


class TestConfigurationIntegration:
    """Test behavior with different registry states and edge cases."""

    @pytest.fixture
    def step(self):
        """Create a ConfigurationStep instance."""
        return ConfigurationStep()

    @pytest.mark.asyncio
    async def test_configuration_with_existing_context(self, step):
        """Test execute with pre-existing context data."""
        initial_context = {"existing_key": "existing_value", "step_number": 1}
        mock_config = {"agent_id": "context-test-789", "name": "context"}

        with patch(
            "_mcp_mesh.pipeline.startup.configuration.DecoratorRegistry"
        ) as mock_registry:
            mock_registry.get_resolved_agent_config.return_value = mock_config
            mock_registry.get_mesh_agents.return_value = {}

            result = await step.execute(initial_context)

            # Verify new context is added
            assert result.context["agent_config"] == mock_config
            assert result.context["agent_id"] == "context-test-789"
            assert result.context["has_explicit_agent"] is False

            # Original context parameter should be unchanged
            assert initial_context == {
                "existing_key": "existing_value",
                "step_number": 1,
            }

    @pytest.mark.asyncio
    async def test_configuration_precedence_through_pipeline(self, step):
        """Test configuration precedence through pipeline (not direct testing)."""
        # This tests that the pipeline step respects the precedence
        # already resolved by DecoratorRegistry.get_resolved_agent_config()
        env_override_config = {
            "name": "env-override",
            "http_host": "env.host.com",  # From environment
            "http_port": 9999,  # From environment
            "version": "1.0.0",  # Default
            "agent_id": "env-override-ghi123",
        }

        with patch(
            "_mcp_mesh.pipeline.startup.configuration.DecoratorRegistry"
        ) as mock_registry:
            mock_registry.get_resolved_agent_config.return_value = env_override_config
            mock_registry.get_mesh_agents.return_value = {"EnvAgent": MagicMock()}

            result = await step.execute({})

            # Verify the resolved configuration respects precedence
            config = result.context["agent_config"]
            assert config["http_host"] == "env.host.com"
            assert config["http_port"] == 9999
            assert config["agent_id"] == "env-override-ghi123"

    @pytest.mark.asyncio
    async def test_pipeline_result_structure(self, step):
        """Test that PipelineResult has correct structure."""
        mock_config = {"agent_id": "structure-test-012", "name": "structure"}

        with patch(
            "_mcp_mesh.pipeline.startup.configuration.DecoratorRegistry"
        ) as mock_registry:
            mock_registry.get_resolved_agent_config.return_value = mock_config
            mock_registry.get_mesh_agents.return_value = {}

            result = await step.execute({})

            # Test PipelineResult structure
            assert isinstance(result, PipelineResult)
            assert hasattr(result, "status")
            assert hasattr(result, "message")
            assert hasattr(result, "context")
            assert hasattr(result, "errors")
            assert hasattr(result, "timestamp")

            # Test success values
            assert result.status == PipelineStatus.SUCCESS
            assert isinstance(result.context, dict)
            assert isinstance(result.errors, list)
            assert len(result.errors) == 0

    @pytest.mark.asyncio
    async def test_agent_id_format_validation(self, step):
        """Test that agent_id follows expected format in context."""
        test_configs = [
            {"agent_id": "simple-abc123", "name": "simple"},
            {"agent_id": "complex-agent-name-def456", "name": "complex"},
            {"agent_id": "agent-xyz789", "name": None},  # Synthetic
        ]

        for config in test_configs:
            with patch(
                "_mcp_mesh.pipeline.startup.configuration.DecoratorRegistry"
            ) as mock_registry:
                mock_registry.get_resolved_agent_config.return_value = config
                mock_registry.get_mesh_agents.return_value = {}

                result = await step.execute({})

                agent_id = result.context["agent_id"]
                # Verify it's a string and matches expected format pattern
                assert isinstance(agent_id, str)
                assert len(agent_id) > 0
                assert "-" in agent_id  # Should have prefix-suffix format
                assert agent_id == config["agent_id"]
