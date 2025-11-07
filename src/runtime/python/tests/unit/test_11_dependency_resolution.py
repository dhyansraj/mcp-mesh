"""
Unit tests for DependencyResolutionStep pipeline step.

Tests the dependency resolution logic including hash-based change detection,
dependency injection management, self-dependency handling, and registry
response processing without making actual dependency injections.
"""

import hashlib
import json
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

# Import the classes under test
from _mcp_mesh.pipeline.mcp_heartbeat.dependency_resolution import (
    DependencyResolutionStep,
)
from _mcp_mesh.pipeline.shared import PipelineResult, PipelineStatus


class TestDependencyResolutionStep:
    """Test the DependencyResolutionStep class initialization and basic properties."""

    def test_initialization(self):
        """Test DependencyResolutionStep initialization."""
        step = DependencyResolutionStep()

        assert step.name == "dependency-resolution"
        assert step.required is False  # Optional step
        assert step.description == "Process dependency resolution from registry"

    def test_inheritance(self):
        """Test DependencyResolutionStep inherits from PipelineStep."""
        from _mcp_mesh.pipeline.shared import PipelineStep

        step = DependencyResolutionStep()
        assert isinstance(step, PipelineStep)

    def test_execute_method_exists(self):
        """Test execute method exists and is callable."""
        step = DependencyResolutionStep()
        assert hasattr(step, "execute")
        assert callable(step.execute)

    def test_helper_methods_exist(self):
        """Test helper methods exist."""
        step = DependencyResolutionStep()
        helper_methods = [
            "_extract_dependency_state",
            "_hash_dependency_state",
            "process_heartbeat_response_for_rewiring",
        ]

        for method_name in helper_methods:
            assert hasattr(step, method_name)
            assert callable(getattr(step, method_name))


class TestNoDataScenarios:
    """Test scenarios with missing or empty data."""

    @pytest.fixture
    def step(self):
        """Create a DependencyResolutionStep instance."""
        return DependencyResolutionStep()

    @pytest.mark.asyncio
    async def test_execute_no_heartbeat_response(self, step):
        """Test execute with no heartbeat response."""
        context = {"registry_wrapper": MagicMock()}

        result = await step.execute(context)

        assert result.status == PipelineStatus.SUCCESS
        assert (
            "No heartbeat response or registry wrapper - completed successfully"
            in result.message
        )

    @pytest.mark.asyncio
    async def test_execute_no_registry_wrapper(self, step):
        """Test execute with no registry wrapper."""
        context = {"heartbeat_response": {"status": "success"}}

        result = await step.execute(context)

        assert result.status == PipelineStatus.SUCCESS
        assert (
            "No heartbeat response or registry wrapper - completed successfully"
            in result.message
        )

    @pytest.mark.asyncio
    async def test_execute_empty_context(self, step):
        """Test execute with completely empty context."""
        result = await step.execute({})

        assert result.status == PipelineStatus.SUCCESS
        assert (
            "No heartbeat response or registry wrapper - completed successfully"
            in result.message
        )

    @pytest.mark.asyncio
    async def test_execute_none_values(self, step):
        """Test execute with None values."""
        context = {"heartbeat_response": None, "registry_wrapper": None}

        result = await step.execute(context)

        assert result.status == PipelineStatus.SUCCESS
        assert (
            "No heartbeat response or registry wrapper - completed successfully"
            in result.message
        )

    @pytest.mark.asyncio
    async def test_execute_empty_heartbeat_response(self, step):
        """Test execute with empty heartbeat response."""
        context = {"heartbeat_response": {}, "registry_wrapper": MagicMock()}

        result = await step.execute(context)

        assert result.status == PipelineStatus.SUCCESS
        assert (
            "No heartbeat response or registry wrapper - completed successfully"
            in result.message
        )

    @pytest.mark.asyncio
    async def test_no_data_logging(self, step, caplog):
        """Test no data scenario logs appropriate info message."""
        import logging

        caplog.set_level(logging.INFO)

        result = await step.execute({})

        assert result.status == PipelineStatus.SUCCESS
        assert "No heartbeat response to process - this is normal" in caplog.text


class TestDependencyStateExtraction:
    """Test dependency state extraction logic."""

    @pytest.fixture
    def step(self):
        """Create a DependencyResolutionStep instance."""
        return DependencyResolutionStep()

    def test_extract_dependency_state_empty(self, step):
        """Test extracting dependency state from empty response."""
        heartbeat_response = {}

        result = step._extract_dependency_state(heartbeat_response)

        assert result == {}

    def test_extract_dependency_state_no_dependencies(self, step):
        """Test extracting dependency state with no dependencies_resolved."""
        heartbeat_response = {"status": "success", "other_data": "value"}

        result = step._extract_dependency_state(heartbeat_response)

        assert result == {}

    def test_extract_dependency_state_simple(self, step):
        """Test extracting dependency state with simple dependencies."""
        heartbeat_response = {
            "dependencies_resolved": {
                "my_function": [
                    {
                        "capability": "tool1",
                        "endpoint": "http://agent1:8080/mcp",
                        "function_name": "tool1_impl",
                        "status": "available",
                        "agent_id": "agent1",
                    }
                ]
            }
        }

        result = step._extract_dependency_state(heartbeat_response)

        # Expected format is now array-based to preserve order and support duplicates
        expected = {
            "my_function": [
                {
                    "capability": "tool1",
                    "endpoint": "http://agent1:8080/mcp",
                    "function_name": "tool1_impl",
                    "status": "available",
                    "agent_id": "agent1",
                    "kwargs": {},
                }
            ]
        }
        assert result == expected

    def test_extract_dependency_state_complex(self, step):
        """Test extracting dependency state with multiple functions and capabilities."""
        heartbeat_response = {
            "dependencies_resolved": {
                "function1": [
                    {
                        "capability": "tool1",
                        "endpoint": "http://agent1:8080/mcp",
                        "function_name": "tool1_impl",
                        "status": "available",
                        "agent_id": "agent1",
                    },
                    {
                        "capability": "tool2",
                        "endpoint": "http://agent2:8080/mcp",
                        "function_name": "tool2_impl",
                        "status": "available",
                        "agent_id": "agent2",
                    },
                ],
                "function2": [
                    {
                        "capability": "tool3",
                        "endpoint": "http://agent3:8080/mcp",
                        "function_name": "tool3_impl",
                        "status": "available",
                        "agent_id": "agent3",
                    }
                ],
            }
        }

        result = step._extract_dependency_state(heartbeat_response)

        # Expected format is now array-based to preserve order and support duplicates
        expected = {
            "function1": [
                {
                    "capability": "tool1",
                    "endpoint": "http://agent1:8080/mcp",
                    "function_name": "tool1_impl",
                    "status": "available",
                    "agent_id": "agent1",
                    "kwargs": {},
                },
                {
                    "capability": "tool2",
                    "endpoint": "http://agent2:8080/mcp",
                    "function_name": "tool2_impl",
                    "status": "available",
                    "agent_id": "agent2",
                    "kwargs": {},
                },
            ],
            "function2": [
                {
                    "capability": "tool3",
                    "endpoint": "http://agent3:8080/mcp",
                    "function_name": "tool3_impl",
                    "status": "available",
                    "agent_id": "agent3",
                    "kwargs": {},
                }
            ],
        }
        assert result == expected

    def test_extract_dependency_state_missing_fields(self, step):
        """Test extracting dependency state with missing optional fields."""
        heartbeat_response = {
            "dependencies_resolved": {
                "my_function": [
                    {
                        "capability": "tool1",
                        "status": "available",
                        # Missing endpoint, function_name, agent_id
                    }
                ]
            }
        }

        result = step._extract_dependency_state(heartbeat_response)

        # Expected format is now array-based to preserve order and support duplicates
        expected = {
            "my_function": [
                {
                    "capability": "tool1",
                    "endpoint": "",
                    "function_name": "",
                    "status": "available",
                    "agent_id": "",
                    "kwargs": {},
                }
            ]
        }
        assert result == expected

    def test_extract_dependency_state_invalid_data(self, step):
        """Test extracting dependency state with invalid data types."""
        heartbeat_response = {
            "dependencies_resolved": {
                "function1": "not_a_list",  # Should be ignored
                "function2": [
                    "not_a_dict",  # Should be ignored
                    {"missing_capability": "value"},  # Should be ignored
                    {
                        "capability": "tool1",
                        "status": "available",
                    },  # Should be included
                ],
            }
        }

        result = step._extract_dependency_state(heartbeat_response)

        # Expected format is now array-based to preserve order and support duplicates
        expected = {
            "function2": [
                {
                    "capability": "tool1",
                    "endpoint": "",
                    "function_name": "",
                    "status": "available",
                    "agent_id": "",
                    "kwargs": {},
                }
            ]
        }
        assert result == expected


class TestHashGeneration:
    """Test dependency state hashing logic."""

    @pytest.fixture
    def step(self):
        """Create a DependencyResolutionStep instance."""
        return DependencyResolutionStep()

    def test_hash_dependency_state_empty(self, step):
        """Test hashing empty dependency state."""
        state = {}

        result = step._hash_dependency_state(state)

        # Should be consistent hash of empty dict
        assert isinstance(result, str)
        assert len(result) == 16  # First 16 chars of SHA256

        # Should be deterministic
        result2 = step._hash_dependency_state(state)
        assert result == result2

    def test_hash_dependency_state_simple(self, step):
        """Test hashing simple dependency state."""
        state = {
            "function1": {
                "tool1": {
                    "endpoint": "http://agent1:8080/mcp",
                    "function_name": "tool1_impl",
                    "status": "available",
                    "agent_id": "agent1",
                }
            }
        }

        result = step._hash_dependency_state(state)

        assert isinstance(result, str)
        assert len(result) == 16

        # Should be deterministic
        result2 = step._hash_dependency_state(state)
        assert result == result2

    def test_hash_dependency_state_order_independence(self, step):
        """Test that hash is independent of dictionary order."""
        state1 = {
            "function1": {"tool1": {"endpoint": "http://agent1:8080"}},
            "function2": {"tool2": {"endpoint": "http://agent2:8080"}},
        }

        state2 = {
            "function2": {"tool2": {"endpoint": "http://agent2:8080"}},
            "function1": {"tool1": {"endpoint": "http://agent1:8080"}},
        }

        hash1 = step._hash_dependency_state(state1)
        hash2 = step._hash_dependency_state(state2)

        assert hash1 == hash2

    def test_hash_dependency_state_change_detection(self, step):
        """Test that different states produce different hashes."""
        state1 = {
            "function1": {
                "tool1": {"endpoint": "http://agent1:8080/mcp", "status": "available"}
            }
        }

        state2 = {
            "function1": {
                "tool1": {
                    "endpoint": "http://agent2:8080/mcp",  # Different endpoint
                    "status": "available",
                }
            }
        }

        hash1 = step._hash_dependency_state(state1)
        hash2 = step._hash_dependency_state(state2)

        assert hash1 != hash2

    def test_hash_dependency_state_validates_json_serializable(self, step):
        """Test that hash generation validates JSON serializable data."""
        # This should work fine
        valid_state = {"function1": {"tool1": {"endpoint": "http://test"}}}
        result = step._hash_dependency_state(valid_state)
        assert isinstance(result, str)


class TestSuccessfulExecution:
    """Test successful execution scenarios."""

    @pytest.fixture
    def step(self):
        """Create a DependencyResolutionStep instance."""
        return DependencyResolutionStep()

    @pytest.fixture
    def mock_registry_wrapper(self):
        """Mock registry wrapper with parse_tool_dependencies method."""
        wrapper = MagicMock()
        wrapper.parse_tool_dependencies.return_value = {
            "function1": ["tool1", "tool2"],
            "function2": ["tool3"],
        }
        return wrapper

    @pytest.fixture
    def mock_heartbeat_response(self):
        """Mock heartbeat response with dependencies."""
        return {
            "status": "success",
            "dependencies_resolved": {
                "function1": [
                    {
                        "capability": "tool1",
                        "endpoint": "http://agent1:8080/mcp",
                        "function_name": "tool1_impl",
                        "status": "available",
                        "agent_id": "agent1",
                    }
                ]
            },
        }

    @pytest.mark.asyncio
    @patch(
        "_mcp_mesh.pipeline.mcp_heartbeat.dependency_resolution.DependencyResolutionStep.process_heartbeat_response_for_rewiring"
    )
    async def test_execute_successful_processing(
        self, mock_rewiring, step, mock_heartbeat_response, mock_registry_wrapper
    ):
        """Test successful execution of dependency resolution."""
        context = {
            "heartbeat_response": mock_heartbeat_response,
            "registry_wrapper": mock_registry_wrapper,
        }

        mock_rewiring.return_value = None  # Async method returns None

        result = await step.execute(context)

        assert result.status == PipelineStatus.SUCCESS
        assert (
            "Dependency resolution completed (efficient hash-based)" in result.message
        )

        # Verify rewiring was called
        mock_rewiring.assert_called_once_with(mock_heartbeat_response)

        # Verify registry wrapper was called
        mock_registry_wrapper.parse_tool_dependencies.assert_called_once_with(
            mock_heartbeat_response
        )

        # Verify context data
        assert result.context.get("dependency_count") == 3  # 2 + 1 from mock
        assert result.context.get("dependencies_resolved") == {
            "function1": ["tool1", "tool2"],
            "function2": ["tool3"],
        }

    @pytest.mark.asyncio
    @patch(
        "_mcp_mesh.pipeline.mcp_heartbeat.dependency_resolution.DependencyResolutionStep.process_heartbeat_response_for_rewiring"
    )
    async def test_execute_zero_dependencies(
        self, mock_rewiring, step, mock_registry_wrapper
    ):
        """Test execution with zero dependencies."""
        context = {
            "heartbeat_response": {"status": "success", "dependencies_resolved": {}},
            "registry_wrapper": mock_registry_wrapper,
        }

        mock_registry_wrapper.parse_tool_dependencies.return_value = {}
        mock_rewiring.return_value = None

        result = await step.execute(context)

        assert result.status == PipelineStatus.SUCCESS
        assert result.context.get("dependency_count") == 0
        assert result.context.get("dependencies_resolved") == {}

    @pytest.mark.asyncio
    @patch(
        "_mcp_mesh.pipeline.mcp_heartbeat.dependency_resolution.DependencyResolutionStep.process_heartbeat_response_for_rewiring"
    )
    async def test_execute_complex_dependency_count(
        self, mock_rewiring, step, mock_registry_wrapper
    ):
        """Test dependency count calculation with complex data."""
        context = {
            "heartbeat_response": {"status": "success"},
            "registry_wrapper": mock_registry_wrapper,
        }

        # Mock complex parsed dependencies
        mock_registry_wrapper.parse_tool_dependencies.return_value = {
            "function1": ["tool1", "tool2", "tool3"],  # 3 deps
            "function2": ["tool4"],  # 1 dep
            "function3": ["tool5", "tool6"],  # 2 deps
            "function4": "not_a_list",  # Should be ignored (0 deps)
        }
        mock_rewiring.return_value = None

        result = await step.execute(context)

        assert result.status == PipelineStatus.SUCCESS
        assert result.context.get("dependency_count") == 6  # 3 + 1 + 2 + 0


class TestErrorHandling:
    """Test error handling scenarios."""

    @pytest.fixture
    def step(self):
        """Create a DependencyResolutionStep instance."""
        return DependencyResolutionStep()

    @pytest.fixture
    def mock_registry_wrapper(self):
        """Mock registry wrapper."""
        return MagicMock()

    @pytest.mark.asyncio
    @patch(
        "_mcp_mesh.pipeline.mcp_heartbeat.dependency_resolution.DependencyResolutionStep.process_heartbeat_response_for_rewiring"
    )
    async def test_execute_rewiring_exception(
        self, mock_rewiring, step, mock_registry_wrapper
    ):
        """Test execution when rewiring raises exception."""
        context = {
            "heartbeat_response": {"status": "success"},
            "registry_wrapper": mock_registry_wrapper,
        }

        mock_rewiring.side_effect = Exception("Rewiring failed")

        result = await step.execute(context)

        assert result.status == PipelineStatus.FAILED
        assert "Dependency resolution failed: Rewiring failed" in result.message
        assert "Rewiring failed" in result.errors

    @pytest.mark.asyncio
    @patch(
        "_mcp_mesh.pipeline.mcp_heartbeat.dependency_resolution.DependencyResolutionStep.process_heartbeat_response_for_rewiring"
    )
    async def test_execute_parse_dependencies_exception(
        self, mock_rewiring, step, mock_registry_wrapper
    ):
        """Test execution when parse_tool_dependencies raises exception."""
        context = {
            "heartbeat_response": {"status": "success"},
            "registry_wrapper": mock_registry_wrapper,
        }

        mock_rewiring.return_value = None
        mock_registry_wrapper.parse_tool_dependencies.side_effect = Exception(
            "Parse failed"
        )

        result = await step.execute(context)

        assert result.status == PipelineStatus.FAILED
        assert "Dependency resolution failed: Parse failed" in result.message
        assert "Parse failed" in result.errors

    @pytest.mark.asyncio
    async def test_execute_general_exception(self, step):
        """Test execution with general exception."""
        # Create context that will cause exception during processing
        context = {
            "heartbeat_response": {"status": "success"},
            "registry_wrapper": "not_a_mock",  # Will cause attribute error
        }

        result = await step.execute(context)

        assert result.status == PipelineStatus.FAILED
        assert "Dependency resolution failed:" in result.message
        assert len(result.errors) > 0

    @pytest.mark.asyncio
    async def test_error_logging(self, step, caplog):
        """Test error logging behavior."""
        import logging

        context = {
            "heartbeat_response": {"status": "success"},
            "registry_wrapper": "not_a_mock",  # Will cause exception
        }

        caplog.set_level(logging.ERROR)

        result = await step.execute(context)

        assert result.status == PipelineStatus.FAILED
        assert "Dependency resolution failed:" in caplog.text


class TestRewiring:
    """Test the rewiring process (mocked dependencies)."""

    @pytest.fixture
    def step(self):
        """Create a DependencyResolutionStep instance."""
        return DependencyResolutionStep()

    @pytest.fixture
    def clear_global_hash(self):
        """Clear the global hash state before each test."""
        import _mcp_mesh.pipeline.mcp_heartbeat.dependency_resolution as dep_module

        dep_module._last_dependency_hash = None
        yield
        dep_module._last_dependency_hash = None

    @pytest.mark.asyncio
    async def test_process_heartbeat_response_for_rewiring_no_response(
        self, step, caplog, clear_global_hash
    ):
        """Test rewiring with no response (skip for resilience)."""
        import logging

        caplog.set_level(logging.DEBUG)
        step.logger.setLevel(logging.DEBUG)

        await step.process_heartbeat_response_for_rewiring(None)

        assert "No heartbeat response - skipping rewiring for resilience" in caplog.text

    @pytest.mark.asyncio
    async def test_process_heartbeat_response_for_rewiring_empty_response(
        self, step, caplog, clear_global_hash
    ):
        """Test rewiring with empty response (skip for resilience)."""
        import logging

        caplog.set_level(logging.DEBUG)
        step.logger.setLevel(logging.DEBUG)

        await step.process_heartbeat_response_for_rewiring({})

        assert "No heartbeat response - skipping rewiring for resilience" in caplog.text

    @pytest.mark.asyncio
    @patch("_mcp_mesh.engine.dependency_injector.get_global_injector")
    async def test_process_heartbeat_response_initial_state(
        self, mock_get_injector, step, caplog, clear_global_hash
    ):
        """Test rewiring with initial dependency state."""
        import logging

        # Mock injector
        mock_injector = MagicMock()
        mock_injector._dependencies = {}
        mock_injector.register_dependency = AsyncMock()
        mock_injector.unregister_dependency = AsyncMock()
        mock_get_injector.return_value = mock_injector

        heartbeat_response = {
            "dependencies_resolved": {
                "function1": [
                    {
                        "capability": "tool1",
                        "endpoint": "http://agent1:8080/mcp",
                        "function_name": "tool1_impl",
                        "status": "available",
                        "agent_id": "agent1",
                    }
                ]
            }
        }

        caplog.set_level(logging.INFO)

        await step.process_heartbeat_response_for_rewiring(heartbeat_response)

        assert (
            "Initial dependency state detected: 1 functions, 1 dependencies"
            in caplog.text
        )
        mock_injector.register_dependency.assert_called_once()

    @pytest.mark.asyncio
    @patch("_mcp_mesh.engine.dependency_injector.get_global_injector")
    async def test_process_heartbeat_response_hash_unchanged(
        self, mock_get_injector, step, caplog, clear_global_hash
    ):
        """Test rewiring with unchanged hash (skip rewiring)."""
        import logging

        import _mcp_mesh.pipeline.mcp_heartbeat.dependency_resolution as dep_module

        # Mock injector
        mock_injector = MagicMock()
        mock_get_injector.return_value = mock_injector

        heartbeat_response = {
            "dependencies_resolved": {
                "function1": [
                    {
                        "capability": "tool1",
                        "endpoint": "http://agent1:8080/mcp",
                        "function_name": "tool1_impl",
                        "status": "available",
                    }
                ]
            }
        }

        # Set a fake previous hash to match current state
        current_state = step._extract_dependency_state(heartbeat_response)
        current_hash = step._hash_dependency_state(current_state)
        dep_module._last_dependency_hash = current_hash

        caplog.set_level(logging.DEBUG)
        step.logger.setLevel(logging.DEBUG)

        await step.process_heartbeat_response_for_rewiring(heartbeat_response)

        assert (
            f"Dependency state unchanged (hash: {current_hash}), skipping rewiring"
            in caplog.text
        )
        # Should not call injector methods
        mock_injector.register_dependency.assert_not_called()

    @pytest.mark.asyncio
    @patch("_mcp_mesh.engine.dependency_injector.get_global_injector")
    async def test_process_heartbeat_response_self_dependency(
        self, mock_get_injector, step, caplog, clear_global_hash
    ):
        """Test rewiring with self-dependency detection."""
        import logging

        # Mock injector with original function
        mock_injector = MagicMock()
        mock_injector._dependencies = {}
        mock_injector.register_dependency = AsyncMock()
        mock_injector.unregister_dependency = AsyncMock()
        mock_original_func = MagicMock()
        mock_injector.find_original_function.return_value = mock_original_func
        mock_get_injector.return_value = mock_injector

        heartbeat_response = {
            "dependencies_resolved": {
                "function1": [
                    {
                        "capability": "tool1",
                        "endpoint": "http://self:8080/mcp",
                        "function_name": "tool1_impl",
                        "status": "available",
                        "agent_id": "current-agent",  # Same as DecoratorRegistry agent_id
                    }
                ]
            }
        }

        caplog.set_level(logging.WARNING)

        # Mock DecoratorRegistry to return the same agent_id as in heartbeat response
        # Also need to mock get_mesh_tools for composite key mapping
        with patch(
            "_mcp_mesh.engine.decorator_registry.DecoratorRegistry"
        ) as mock_decorator_registry:
            mock_config = {"agent_id": "current-agent"}
            mock_decorator_registry.get_resolved_agent_config.return_value = mock_config

            # Mock get_mesh_tools to return tool name -> function mapping
            mock_func = MagicMock()
            mock_func.__module__ = "test_module"
            mock_func.__qualname__ = "test_function"
            mock_decorated = MagicMock()
            mock_decorated.function = mock_func
            mock_decorator_registry.get_mesh_tools.return_value = {
                "function1": mock_decorated
            }

            with patch(
                "_mcp_mesh.engine.self_dependency_proxy.SelfDependencyProxy"
            ) as mock_self_proxy:
                mock_proxy_instance = MagicMock()
                mock_self_proxy.return_value = mock_proxy_instance

                await step.process_heartbeat_response_for_rewiring(heartbeat_response)

                assert "SELF-DEPENDENCY: Using direct function call" in caplog.text
                mock_self_proxy.assert_called_once_with(
                    mock_original_func, "tool1_impl"
                )
                # Now expects composite key format: "func_id:dep_0"
                mock_injector.register_dependency.assert_called_once_with(
                    "test_module.test_function:dep_0", mock_proxy_instance
                )

    @pytest.mark.asyncio
    @patch("_mcp_mesh.engine.dependency_injector.get_global_injector")
    async def test_process_heartbeat_response_unwiring(
        self, mock_get_injector, step, caplog, clear_global_hash
    ):
        """Test rewiring with dependency unwiring."""
        import logging

        # Mock injector with existing dependencies (using composite keys)
        mock_injector = MagicMock()
        mock_injector._dependencies = {
            "old_function:dep_0": MagicMock(),  # Old dependency to be removed
            "test_module.test_function:dep_0": MagicMock(),  # Existing dependency for function1
        }
        mock_injector.register_dependency = AsyncMock()
        mock_injector.unregister_dependency = AsyncMock()
        mock_get_injector.return_value = mock_injector

        heartbeat_response = {
            "dependencies_resolved": {
                "function1": [
                    {
                        "capability": "tool1",  # Keep this one
                        "endpoint": "http://agent1:8080/mcp",
                        "function_name": "tool1_impl",
                        "status": "available",
                    }
                ]
                # "old_function:dep_0" is not in new dependencies, should be unwired
            }
        }

        caplog.set_level(logging.INFO)

        # Mock DecoratorRegistry for composite key mapping
        with patch(
            "_mcp_mesh.engine.decorator_registry.DecoratorRegistry"
        ) as mock_decorator_registry:
            # Mock get_mesh_tools to return tool name -> function mapping
            mock_func = MagicMock()
            mock_func.__module__ = "test_module"
            mock_func.__qualname__ = "test_function"
            mock_decorated = MagicMock()
            mock_decorated.function = mock_func
            mock_decorator_registry.get_mesh_tools.return_value = {
                "function1": mock_decorated
            }

            await step.process_heartbeat_response_for_rewiring(heartbeat_response)

            assert "Unwired dependency 'old_function:dep_0'" in caplog.text
            mock_injector.unregister_dependency.assert_called_once_with(
                "old_function:dep_0"
            )


class TestContextHandling:
    """Test context data handling and preservation."""

    @pytest.fixture
    def step(self):
        """Create a DependencyResolutionStep instance."""
        return DependencyResolutionStep()

    @pytest.mark.asyncio
    @patch(
        "_mcp_mesh.pipeline.mcp_heartbeat.dependency_resolution.DependencyResolutionStep.process_heartbeat_response_for_rewiring"
    )
    async def test_execute_preserves_existing_context(self, mock_rewiring, step):
        """Test execute preserves existing context data."""
        mock_registry_wrapper = MagicMock()
        mock_registry_wrapper.parse_tool_dependencies.return_value = {}

        context = {
            "heartbeat_response": {"status": "success"},
            "registry_wrapper": mock_registry_wrapper,
            "existing_data": {"key": "value"},
            "other_step_result": "preserved",
        }

        mock_rewiring.return_value = None

        result = await step.execute(context)

        assert result.status == PipelineStatus.SUCCESS
        # New context should be added
        assert result.context.get("dependency_count") == 0
        assert result.context.get("dependencies_resolved") == {}
        # Original context should remain unchanged
        assert context.get("existing_data") == {"key": "value"}
        assert context.get("other_step_result") == "preserved"

    @pytest.mark.asyncio
    async def test_execute_preserves_context_on_error(self, step):
        """Test execute preserves context even on error."""
        context = {
            "heartbeat_response": {"status": "success"},
            "registry_wrapper": "invalid",  # Will cause error
            "existing_data": "should_be_preserved",
        }

        result = await step.execute(context)

        assert result.status == PipelineStatus.FAILED
        # Original context should remain unchanged
        assert context.get("existing_data") == "should_be_preserved"
        # Error context should not contain partial results
        assert "dependency_count" not in result.context
        assert "dependencies_resolved" not in result.context


class TestLogging:
    """Test logging behavior in various scenarios."""

    @pytest.fixture
    def step(self):
        """Create a DependencyResolutionStep instance."""
        return DependencyResolutionStep()

    @pytest.mark.asyncio
    @patch(
        "_mcp_mesh.pipeline.mcp_heartbeat.dependency_resolution.DependencyResolutionStep.process_heartbeat_response_for_rewiring"
    )
    async def test_debug_logging(self, mock_rewiring, step, caplog):
        """Test debug logging during processing."""
        import logging

        mock_registry_wrapper = MagicMock()
        mock_registry_wrapper.parse_tool_dependencies.return_value = {}

        context = {
            "heartbeat_response": {"status": "success"},
            "registry_wrapper": mock_registry_wrapper,
        }

        mock_rewiring.return_value = None

        caplog.set_level(logging.DEBUG)
        step.logger.setLevel(logging.DEBUG)

        result = await step.execute(context)

        assert result.status == PipelineStatus.SUCCESS
        assert "Processing dependency resolution..." in caplog.text
        assert (
            "Dependency resolution step completed using hash-based change detection"
            in caplog.text
        )

    @pytest.mark.asyncio
    async def test_error_logging_detail(self, step, caplog):
        """Test detailed error logging."""
        import logging

        context = {
            "heartbeat_response": {"status": "success"},
            "registry_wrapper": "invalid_type",  # Will cause AttributeError
        }

        caplog.set_level(logging.ERROR)

        result = await step.execute(context)

        assert result.status == PipelineStatus.FAILED
        assert "Dependency resolution failed:" in caplog.text
