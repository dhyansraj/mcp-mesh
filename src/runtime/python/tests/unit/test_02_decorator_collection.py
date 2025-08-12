"""
Unit tests for DecoratorCollectionStep pipeline step.

Tests the collection of decorators from DecoratorRegistry and context population
for subsequent pipeline steps. Focus on pure unit testing without external dependencies.
"""

from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

from _mcp_mesh.engine.decorator_registry import DecoratedFunction
from _mcp_mesh.pipeline.shared import PipelineResult, PipelineStatus

# Import the classes under test
from _mcp_mesh.pipeline.mcp_startup.decorator_collection import DecoratorCollectionStep


class TestDecoratorCollectionStep:
    """Test the DecoratorCollectionStep class initialization and basic properties."""

    def test_initialization(self):
        """Test DecoratorCollectionStep initialization."""
        step = DecoratorCollectionStep()

        assert step.name == "decorator-collection"
        assert step.required is True
        assert (
            step.description
            == "Collect all registered @mesh.agent and @mesh.tool decorators"
        )

    def test_inheritance(self):
        """Test DecoratorCollectionStep inherits from PipelineStep."""
        from _mcp_mesh.pipeline.shared import PipelineStep

        step = DecoratorCollectionStep()
        assert isinstance(step, PipelineStep)

    def test_execute_method_exists(self):
        """Test execute method exists and is callable."""
        step = DecoratorCollectionStep()
        assert hasattr(step, "execute")
        assert callable(step.execute)


class TestDecoratorCollectionSuccess:
    """Test successful decorator collection scenarios."""

    @pytest.fixture
    def step(self):
        """Create a DecoratorCollectionStep instance."""
        return DecoratorCollectionStep()

    @pytest.fixture
    def mock_agent(self):
        """Create a mock decorated agent."""
        mock_func = MagicMock()
        mock_func.__name__ = "test_agent_function"
        return DecoratedFunction(
            decorator_type="mesh_agent",
            function=mock_func,
            metadata={"name": "test-agent", "version": "1.0.0"},
            registered_at=MagicMock(),
        )

    @pytest.fixture
    def mock_tool(self):
        """Create a mock decorated tool."""
        mock_func = MagicMock()
        mock_func.__name__ = "test_tool_function"
        return DecoratedFunction(
            decorator_type="mesh_tool",
            function=mock_func,
            metadata={"capability": "test-tool", "dependencies": []},
            registered_at=MagicMock(),
        )

    @pytest.mark.asyncio
    async def test_collect_agents_only(self, step, mock_agent):
        """Test collection with agents only."""
        mock_agents = {"test_agent": mock_agent}
        mock_tools = {}

        with patch(
            "_mcp_mesh.pipeline.mcp_startup.decorator_collection.DecoratorRegistry"
        ) as mock_registry:
            mock_registry.get_mesh_agents.return_value = mock_agents
            mock_registry.get_mesh_tools.return_value = mock_tools

            result = await step.execute({})

            assert result.status == PipelineStatus.SUCCESS
            assert result.message == "Collected 1 agents and 0 tools"
            assert result.context["mesh_agents"] == mock_agents
            assert result.context["mesh_tools"] == mock_tools
            assert result.context["agent_count"] == 1
            assert result.context["tool_count"] == 0

    @pytest.mark.asyncio
    async def test_collect_tools_only(self, step, mock_tool):
        """Test collection with tools only."""
        mock_agents = {}
        mock_tools = {"test_tool": mock_tool}

        with patch(
            "_mcp_mesh.pipeline.mcp_startup.decorator_collection.DecoratorRegistry"
        ) as mock_registry:
            mock_registry.get_mesh_agents.return_value = mock_agents
            mock_registry.get_mesh_tools.return_value = mock_tools

            result = await step.execute({})

            assert result.status == PipelineStatus.SUCCESS
            assert result.message == "Collected 0 agents and 1 tools"
            assert result.context["mesh_agents"] == mock_agents
            assert result.context["mesh_tools"] == mock_tools
            assert result.context["agent_count"] == 0
            assert result.context["tool_count"] == 1

    @pytest.mark.asyncio
    async def test_collect_both_agents_and_tools(self, step, mock_agent, mock_tool):
        """Test collection with both agents and tools."""
        mock_agents = {"test_agent": mock_agent}
        mock_tools = {"test_tool": mock_tool}

        with patch(
            "_mcp_mesh.pipeline.mcp_startup.decorator_collection.DecoratorRegistry"
        ) as mock_registry:
            mock_registry.get_mesh_agents.return_value = mock_agents
            mock_registry.get_mesh_tools.return_value = mock_tools

            result = await step.execute({})

            assert result.status == PipelineStatus.SUCCESS
            assert result.message == "Collected 1 agents and 1 tools"
            assert result.context["mesh_agents"] == mock_agents
            assert result.context["mesh_tools"] == mock_tools
            assert result.context["agent_count"] == 1
            assert result.context["tool_count"] == 1

    @pytest.mark.asyncio
    async def test_collect_multiple_decorators(self, step):
        """Test collection with multiple agents and tools."""
        mock_agents = {
            "agent1": MagicMock(),
            "agent2": MagicMock(),
            "agent3": MagicMock(),
        }
        mock_tools = {"tool1": MagicMock(), "tool2": MagicMock()}

        with patch(
            "_mcp_mesh.pipeline.mcp_startup.decorator_collection.DecoratorRegistry"
        ) as mock_registry:
            mock_registry.get_mesh_agents.return_value = mock_agents
            mock_registry.get_mesh_tools.return_value = mock_tools

            result = await step.execute({})

            assert result.status == PipelineStatus.SUCCESS
            assert result.message == "Collected 3 agents and 2 tools"
            assert result.context["agent_count"] == 3
            assert result.context["tool_count"] == 2


class TestDecoratorCollectionEmpty:
    """Test empty registry scenarios."""

    @pytest.fixture
    def step(self):
        """Create a DecoratorCollectionStep instance."""
        return DecoratorCollectionStep()

    @pytest.mark.asyncio
    async def test_empty_registry(self, step):
        """Test collection with completely empty registry."""
        mock_agents = {}
        mock_tools = {}

        with patch(
            "_mcp_mesh.pipeline.mcp_startup.decorator_collection.DecoratorRegistry"
        ) as mock_registry:
            mock_registry.get_mesh_agents.return_value = mock_agents
            mock_registry.get_mesh_tools.return_value = mock_tools

            result = await step.execute({})

            assert result.status == PipelineStatus.SKIPPED
            assert result.message == "No decorators found to process"
            assert result.context["mesh_agents"] == mock_agents
            assert result.context["mesh_tools"] == mock_tools
            assert result.context["agent_count"] == 0
            assert result.context["tool_count"] == 0

    @pytest.mark.asyncio
    async def test_empty_registry_context_population(self, step):
        """Test that context is still populated even with empty registry."""
        mock_agents = {}
        mock_tools = {}

        with patch(
            "_mcp_mesh.pipeline.mcp_startup.decorator_collection.DecoratorRegistry"
        ) as mock_registry:
            mock_registry.get_mesh_agents.return_value = mock_agents
            mock_registry.get_mesh_tools.return_value = mock_tools

            result = await step.execute({})

            # Verify all expected context keys are present
            assert "mesh_agents" in result.context
            assert "mesh_tools" in result.context
            assert "agent_count" in result.context
            assert "tool_count" in result.context

            # Verify values are correct
            assert result.context["mesh_agents"] == {}
            assert result.context["mesh_tools"] == {}
            assert result.context["agent_count"] == 0
            assert result.context["tool_count"] == 0


class TestDecoratorCollectionContext:
    """Test context population logic and data structure."""

    @pytest.fixture
    def step(self):
        """Create a DecoratorCollectionStep instance."""
        return DecoratorCollectionStep()

    @pytest.mark.asyncio
    async def test_context_keys_present(self, step):
        """Test that all expected context keys are populated."""
        mock_agents = {"agent1": MagicMock()}
        mock_tools = {"tool1": MagicMock()}

        with patch(
            "_mcp_mesh.pipeline.mcp_startup.decorator_collection.DecoratorRegistry"
        ) as mock_registry:
            mock_registry.get_mesh_agents.return_value = mock_agents
            mock_registry.get_mesh_tools.return_value = mock_tools

            result = await step.execute({})

            # Check all required context keys
            required_keys = ["mesh_agents", "mesh_tools", "agent_count", "tool_count"]
            for key in required_keys:
                assert key in result.context, f"Missing context key: {key}"

    @pytest.mark.asyncio
    async def test_context_data_types(self, step):
        """Test that context data has correct types."""
        mock_agents = {"agent1": MagicMock()}
        mock_tools = {"tool1": MagicMock()}

        with patch(
            "_mcp_mesh.pipeline.mcp_startup.decorator_collection.DecoratorRegistry"
        ) as mock_registry:
            mock_registry.get_mesh_agents.return_value = mock_agents
            mock_registry.get_mesh_tools.return_value = mock_tools

            result = await step.execute({})

            # Check data types
            assert isinstance(result.context["mesh_agents"], dict)
            assert isinstance(result.context["mesh_tools"], dict)
            assert isinstance(result.context["agent_count"], int)
            assert isinstance(result.context["tool_count"], int)

    @pytest.mark.asyncio
    async def test_context_data_preservation(self, step):
        """Test that registry data is preserved exactly in context."""
        mock_agents = {"agent1": MagicMock(), "agent2": MagicMock()}
        mock_tools = {"tool1": MagicMock()}

        with patch(
            "_mcp_mesh.pipeline.mcp_startup.decorator_collection.DecoratorRegistry"
        ) as mock_registry:
            mock_registry.get_mesh_agents.return_value = mock_agents
            mock_registry.get_mesh_tools.return_value = mock_tools

            result = await step.execute({})

            # Verify data is preserved exactly (same object references)
            assert result.context["mesh_agents"] is mock_agents
            assert result.context["mesh_tools"] is mock_tools

    @pytest.mark.asyncio
    async def test_context_counts_accuracy(self, step):
        """Test that counts accurately reflect dictionary lengths."""
        mock_agents = {f"agent{i}": MagicMock() for i in range(5)}
        mock_tools = {f"tool{i}": MagicMock() for i in range(3)}

        with patch(
            "_mcp_mesh.pipeline.mcp_startup.decorator_collection.DecoratorRegistry"
        ) as mock_registry:
            mock_registry.get_mesh_agents.return_value = mock_agents
            mock_registry.get_mesh_tools.return_value = mock_tools

            result = await step.execute({})

            assert result.context["agent_count"] == len(mock_agents) == 5
            assert result.context["tool_count"] == len(mock_tools) == 3


class TestDecoratorCollectionMessages:
    """Test result message formatting."""

    @pytest.fixture
    def step(self):
        """Create a DecoratorCollectionStep instance."""
        return DecoratorCollectionStep()

    @pytest.mark.asyncio
    async def test_success_message_format(self, step):
        """Test success message format with various counts."""
        test_cases = [
            (1, 0, "Collected 1 agents and 0 tools"),
            (0, 1, "Collected 0 agents and 1 tools"),
            (2, 3, "Collected 2 agents and 3 tools"),
            (10, 5, "Collected 10 agents and 5 tools"),
        ]

        for agent_count, tool_count, expected_message in test_cases:
            mock_agents = {f"agent{i}": MagicMock() for i in range(agent_count)}
            mock_tools = {f"tool{i}": MagicMock() for i in range(tool_count)}

            with patch(
                "_mcp_mesh.pipeline.mcp_startup.decorator_collection.DecoratorRegistry"
            ) as mock_registry:
                mock_registry.get_mesh_agents.return_value = mock_agents
                mock_registry.get_mesh_tools.return_value = mock_tools

                result = await step.execute({})

                assert result.message == expected_message

    @pytest.mark.asyncio
    async def test_empty_message_exact(self, step):
        """Test exact message for empty registry."""
        mock_agents = {}
        mock_tools = {}

        with patch(
            "_mcp_mesh.pipeline.mcp_startup.decorator_collection.DecoratorRegistry"
        ) as mock_registry:
            mock_registry.get_mesh_agents.return_value = mock_agents
            mock_registry.get_mesh_tools.return_value = mock_tools

            result = await step.execute({})

            assert result.message == "No decorators found to process"

    @pytest.mark.asyncio
    async def test_default_message_on_init(self, step):
        """Test that PipelineResult starts with default message."""
        # This tests the initial state before registry calls
        mock_agents = {"agent1": MagicMock()}
        mock_tools = {"tool1": MagicMock()}

        with patch(
            "_mcp_mesh.pipeline.mcp_startup.decorator_collection.DecoratorRegistry"
        ) as mock_registry:
            mock_registry.get_mesh_agents.return_value = mock_agents
            mock_registry.get_mesh_tools.return_value = mock_tools

            result = await step.execute({})

            # Message should be updated from default
            assert result.message != "Decorator collection completed"
            assert result.message == "Collected 1 agents and 1 tools"


class TestDecoratorCollectionErrors:
    """Test error handling scenarios."""

    @pytest.fixture
    def step(self):
        """Create a DecoratorCollectionStep instance."""
        return DecoratorCollectionStep()

    @pytest.mark.asyncio
    async def test_get_mesh_agents_exception(self, step):
        """Test exception during get_mesh_agents call."""
        error_message = "Registry agents access failed"

        with patch(
            "_mcp_mesh.pipeline.mcp_startup.decorator_collection.DecoratorRegistry"
        ) as mock_registry:
            mock_registry.get_mesh_agents.side_effect = Exception(error_message)

            result = await step.execute({})

            assert result.status == PipelineStatus.FAILED
            assert result.message == f"Failed to collect decorators: {error_message}"
            assert error_message in result.errors

    @pytest.mark.asyncio
    async def test_get_mesh_tools_exception(self, step):
        """Test exception during get_mesh_tools call."""
        error_message = "Registry tools access failed"

        with patch(
            "_mcp_mesh.pipeline.mcp_startup.decorator_collection.DecoratorRegistry"
        ) as mock_registry:
            mock_registry.get_mesh_agents.return_value = {}
            mock_registry.get_mesh_tools.side_effect = Exception(error_message)

            result = await step.execute({})

            assert result.status == PipelineStatus.FAILED
            assert result.message == f"Failed to collect decorators: {error_message}"
            assert error_message in result.errors

    @pytest.mark.asyncio
    async def test_general_exception_handling(self, step):
        """Test general exception handling with custom error."""
        error_message = "Unexpected registry error"

        with patch(
            "_mcp_mesh.pipeline.mcp_startup.decorator_collection.DecoratorRegistry"
        ) as mock_registry:
            mock_registry.get_mesh_agents.side_effect = RuntimeError(error_message)

            result = await step.execute({})

            assert result.status == PipelineStatus.FAILED
            assert "Failed to collect decorators:" in result.message
            assert error_message in result.message
            assert len(result.errors) == 1
            assert result.errors[0] == error_message

    @pytest.mark.asyncio
    async def test_error_context_preservation(self, step):
        """Test that context is not populated when error occurs."""
        error_message = "Registry access failed"

        with patch(
            "_mcp_mesh.pipeline.mcp_startup.decorator_collection.DecoratorRegistry"
        ) as mock_registry:
            mock_registry.get_mesh_agents.side_effect = Exception(error_message)

            result = await step.execute({})

            # Context should be empty on error
            assert len(result.context) == 0

    @pytest.mark.asyncio
    async def test_multiple_registry_calls_on_success(self, step):
        """Test that both registry methods are called on success."""
        mock_agents = {"agent1": MagicMock()}
        mock_tools = {"tool1": MagicMock()}

        with patch(
            "_mcp_mesh.pipeline.mcp_startup.decorator_collection.DecoratorRegistry"
        ) as mock_registry:
            mock_registry.get_mesh_agents.return_value = mock_agents
            mock_registry.get_mesh_tools.return_value = mock_tools

            await step.execute({})

            # Verify both methods were called exactly once
            mock_registry.get_mesh_agents.assert_called_once()
            mock_registry.get_mesh_tools.assert_called_once()

    @pytest.mark.asyncio
    async def test_error_prevents_second_registry_call(self, step):
        """Test that error in first call prevents second call."""
        with patch(
            "_mcp_mesh.pipeline.mcp_startup.decorator_collection.DecoratorRegistry"
        ) as mock_registry:
            mock_registry.get_mesh_agents.side_effect = Exception("First call failed")

            await step.execute({})

            # First method should be called, second should not
            mock_registry.get_mesh_agents.assert_called_once()
            mock_registry.get_mesh_tools.assert_not_called()


class TestDecoratorCollectionIntegration:
    """Test behavior with different input contexts and edge cases."""

    @pytest.fixture
    def step(self):
        """Create a DecoratorCollectionStep instance."""
        return DecoratorCollectionStep()

    @pytest.mark.asyncio
    async def test_execute_with_existing_context(self, step):
        """Test execute with pre-existing context data."""
        initial_context = {"existing_key": "existing_value", "number": 42}
        mock_agents = {"agent1": MagicMock()}
        mock_tools = {}

        with patch(
            "_mcp_mesh.pipeline.mcp_startup.decorator_collection.DecoratorRegistry"
        ) as mock_registry:
            mock_registry.get_mesh_agents.return_value = mock_agents
            mock_registry.get_mesh_tools.return_value = mock_tools

            result = await step.execute(initial_context)

            # Verify new context is added without affecting the original context parameter
            assert result.context["mesh_agents"] == mock_agents
            assert result.context["mesh_tools"] == mock_tools
            assert result.context["agent_count"] == 1
            assert result.context["tool_count"] == 0

            # The original context parameter should be unchanged
            assert initial_context == {"existing_key": "existing_value", "number": 42}

    @pytest.mark.asyncio
    async def test_execute_with_empty_context(self, step):
        """Test execute with empty context dictionary."""
        mock_agents = {}
        mock_tools = {"tool1": MagicMock()}

        with patch(
            "_mcp_mesh.pipeline.mcp_startup.decorator_collection.DecoratorRegistry"
        ) as mock_registry:
            mock_registry.get_mesh_agents.return_value = mock_agents
            mock_registry.get_mesh_tools.return_value = mock_tools

            result = await step.execute({})

            assert result.status == PipelineStatus.SUCCESS
            assert result.context["tool_count"] == 1
            assert result.context["agent_count"] == 0

    @pytest.mark.asyncio
    async def test_pipeline_result_structure(self, step):
        """Test that PipelineResult has correct structure."""
        mock_agents = {"agent1": MagicMock()}
        mock_tools = {"tool1": MagicMock()}

        with patch(
            "_mcp_mesh.pipeline.mcp_startup.decorator_collection.DecoratorRegistry"
        ) as mock_registry:
            mock_registry.get_mesh_agents.return_value = mock_agents
            mock_registry.get_mesh_tools.return_value = mock_tools

            result = await step.execute({})

            # Test PipelineResult structure
            assert isinstance(result, PipelineResult)
            assert hasattr(result, "status")
            assert hasattr(result, "message")
            assert hasattr(result, "context")
            assert hasattr(result, "errors")
            assert hasattr(result, "timestamp")

            # Test default values
            assert result.status == PipelineStatus.SUCCESS
            assert isinstance(result.context, dict)
            assert isinstance(result.errors, list)
            assert len(result.errors) == 0  # No errors in success case
