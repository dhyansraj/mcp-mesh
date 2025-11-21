"""
Unit tests for LLMToolsResolutionStep.

Tests the heartbeat pipeline step that processes llm_tools from
registry responses and updates the LLM agent injection system.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from _mcp_mesh.pipeline.mcp_heartbeat.llm_tools_resolution import (
    LLMToolsResolutionStep,
    _last_llm_tools_hash,
)
from _mcp_mesh.pipeline.shared import PipelineStatus


class TestLLMToolsResolutionStepBasics:
    """Test basic initialization and configuration."""

    def test_step_initialization(self):
        """Test that LLMToolsResolutionStep initializes correctly."""
        step = LLMToolsResolutionStep()

        assert step.name == "llm-tools-resolution"
        assert step.required is False  # Optional step
        assert "LLM tools" in step.description

    def test_step_metadata(self):
        """Test that step has correct metadata."""
        step = LLMToolsResolutionStep()

        assert hasattr(step, "execute")
        assert callable(step.execute)
        assert hasattr(step, "process_llm_tools_from_heartbeat")


class TestLLMToolsResolutionExecution:
    """Test execute method with various contexts."""

    def setup_method(self):
        """Reset global hash before each test."""
        import _mcp_mesh.pipeline.mcp_heartbeat.llm_tools_resolution as module

        module._last_llm_tools_hash = None

    @pytest.mark.asyncio
    async def test_execute_with_no_heartbeat_response(self):
        """Test execution when there's no heartbeat response."""
        step = LLMToolsResolutionStep()
        context = {}  # No heartbeat_response

        result = await step.execute(context)

        assert result.status == PipelineStatus.SUCCESS
        assert "No heartbeat response" in result.message

    @pytest.mark.asyncio
    async def test_execute_with_empty_heartbeat_response(self):
        """Test execution with empty heartbeat response dict."""
        step = LLMToolsResolutionStep()
        context = {"heartbeat_response": {}}

        with patch.object(step, "process_llm_tools_from_heartbeat") as mock_process:
            mock_process.return_value = None

            result = await step.execute(context)

            assert result.status == PipelineStatus.SUCCESS
            mock_process.assert_called_once_with({})

    @pytest.mark.asyncio
    async def test_execute_with_llm_tools_in_response(self):
        """Test execution with llm_tools in heartbeat response."""
        step = LLMToolsResolutionStep()

        llm_tools = {
            "chat_func_123": [
                {
                    "function_name": "extract_pdf",
                    "capability": "document",
                    "endpoint": {"host": "pdf-svc", "port": 8080},
                    "input_schema": {"type": "object"},
                }
            ]
        }

        context = {"heartbeat_response": {"status": "success", "llm_tools": llm_tools}}

        with patch.object(step, "process_llm_tools_from_heartbeat") as mock_process:
            mock_process.return_value = None

            result = await step.execute(context)

            assert result.status == PipelineStatus.SUCCESS
            assert "completed" in result.message.lower()
            assert result.context["llm_function_count"] == 1
            assert result.context["llm_tool_count"] == 1
            mock_process.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_adds_context_data(self):
        """Test that execution adds context data correctly."""
        step = LLMToolsResolutionStep()

        llm_tools = {
            "func1": [{"function_name": "tool1"}, {"function_name": "tool2"}],
            "func2": [{"function_name": "tool3"}],
        }

        context = {"heartbeat_response": {"llm_tools": llm_tools}}

        with patch.object(step, "process_llm_tools_from_heartbeat"):
            result = await step.execute(context)

            assert result.context["llm_function_count"] == 2
            assert result.context["llm_tool_count"] == 3
            assert result.context["llm_tools"] == llm_tools

    @pytest.mark.asyncio
    async def test_execute_handles_exception(self):
        """Test that execution handles exceptions gracefully."""
        step = LLMToolsResolutionStep()
        context = {"heartbeat_response": {"llm_tools": {}}}

        with patch.object(step, "process_llm_tools_from_heartbeat") as mock_process:
            mock_process.side_effect = Exception("Test error")

            result = await step.execute(context)

            assert result.status == PipelineStatus.FAILED
            assert "failed" in result.message.lower()
            assert "Test error" in result.message


class TestLLMToolsStateExtraction:
    """Test LLM tools state extraction and hashing."""

    def test_extract_llm_tools_state_basic(self):
        """Test extracting LLM tools state from heartbeat response."""
        step = LLMToolsResolutionStep()

        heartbeat_response = {
            "llm_tools": {
                "func1": [
                    {"function_name": "tool1", "capability": "doc"},
                    {"function_name": "tool2", "capability": "search"},
                ],
                "func2": [{"function_name": "tool3", "capability": "image"}],
            }
        }

        state = step._extract_llm_tools_state(heartbeat_response)

        assert len(state) == 2
        assert "func1" in state
        assert "func2" in state
        assert len(state["func1"]) == 2
        assert len(state["func2"]) == 1

    def test_extract_llm_tools_state_empty(self):
        """Test extracting empty LLM tools state."""
        step = LLMToolsResolutionStep()

        heartbeat_response = {"llm_tools": {}}

        state = step._extract_llm_tools_state(heartbeat_response)

        assert state == {}

    def test_extract_llm_tools_state_no_field(self):
        """Test extracting when llm_tools field is missing."""
        step = LLMToolsResolutionStep()

        heartbeat_response = {"status": "success"}  # No llm_tools

        state = step._extract_llm_tools_state(heartbeat_response)

        assert state == {}

    def test_extract_llm_tools_state_filters_invalid(self):
        """Test that extraction filters out invalid data."""
        step = LLMToolsResolutionStep()

        heartbeat_response = {
            "llm_tools": {
                "func1": [{"function_name": "tool1"}],
                "func2": "not a list",  # Invalid
                "func3": None,  # Invalid
                "func4": [{"function_name": "tool2"}],
            }
        }

        state = step._extract_llm_tools_state(heartbeat_response)

        assert len(state) == 2  # Only func1 and func4
        assert "func1" in state
        assert "func4" in state
        assert "func2" not in state
        assert "func3" not in state

    def test_hash_llm_tools_state_deterministic(self):
        """Test that hashing is deterministic."""
        step = LLMToolsResolutionStep()

        state = {
            "func1": [{"name": "tool1", "capability": "doc"}],
            "func2": [{"name": "tool2", "capability": "search"}],
        }

        hash1 = step._hash_llm_tools_state(state)
        hash2 = step._hash_llm_tools_state(state)

        assert hash1 == hash2
        assert len(hash1) == 16  # First 16 chars

    def test_hash_llm_tools_state_different(self):
        """Test that different states produce different hashes."""
        step = LLMToolsResolutionStep()

        state1 = {"func1": [{"name": "tool1"}]}
        state2 = {"func1": [{"name": "tool2"}]}

        hash1 = step._hash_llm_tools_state(state1)
        hash2 = step._hash_llm_tools_state(state2)

        assert hash1 != hash2


class TestLLMToolsProcessing:
    """Test LLM tools processing from heartbeat."""

    def setup_method(self):
        """Reset global hash before each test."""
        import _mcp_mesh.pipeline.mcp_heartbeat.llm_tools_resolution as module

        module._last_llm_tools_hash = None

    @pytest.mark.asyncio
    async def test_process_initial_llm_tools(self):
        """Test initial processing of LLM tools calls process_llm_tools."""
        step = LLMToolsResolutionStep()

        llm_tools = {
            "chat_func": [
                {"function_name": "tool1", "endpoint": {"host": "svc1", "port": 8080}}
            ]
        }

        heartbeat_response = {"llm_tools": llm_tools}

        mock_injector = MagicMock()
        mock_injector.process_llm_tools = MagicMock()
        mock_injector.update_llm_tools = MagicMock()

        with patch(
            "_mcp_mesh.pipeline.mcp_heartbeat.llm_tools_resolution.get_global_injector"
        ) as mock_get_injector:
            mock_get_injector.return_value = mock_injector

            await step.process_llm_tools_from_heartbeat(heartbeat_response)

            # Should call process_llm_tools (initial)
            mock_injector.process_llm_tools.assert_called_once_with(llm_tools)
            mock_injector.update_llm_tools.assert_not_called()

    @pytest.mark.asyncio
    async def test_process_updated_llm_tools(self):
        """Test updating LLM tools calls update_llm_tools."""
        step = LLMToolsResolutionStep()

        # Set initial hash to simulate previous state
        import _mcp_mesh.pipeline.mcp_heartbeat.llm_tools_resolution as module

        module._last_llm_tools_hash = "abc123"

        llm_tools = {
            "chat_func": [
                {"function_name": "tool1", "endpoint": {"host": "svc1", "port": 8080}},
                {
                    "function_name": "tool2",
                    "endpoint": {"host": "svc2", "port": 8081},
                },  # New tool
            ]
        }

        heartbeat_response = {"llm_tools": llm_tools}

        mock_injector = MagicMock()
        mock_injector.process_llm_tools = MagicMock()
        mock_injector.update_llm_tools = MagicMock()

        with patch(
            "_mcp_mesh.pipeline.mcp_heartbeat.llm_tools_resolution.get_global_injector"
        ) as mock_get_injector:
            mock_get_injector.return_value = mock_injector

            await step.process_llm_tools_from_heartbeat(heartbeat_response)

            # Should call update_llm_tools (not initial)
            mock_injector.update_llm_tools.assert_called_once_with(llm_tools)
            mock_injector.process_llm_tools.assert_not_called()

    @pytest.mark.asyncio
    async def test_process_unchanged_llm_tools_skips(self):
        """Test that unchanged LLM tools are skipped."""
        step = LLMToolsResolutionStep()

        llm_tools = {"chat_func": [{"function_name": "tool1"}]}
        heartbeat_response = {"llm_tools": llm_tools}

        # First call - process initial
        mock_injector = MagicMock()

        with patch(
            "_mcp_mesh.pipeline.mcp_heartbeat.llm_tools_resolution.get_global_injector"
        ) as mock_get_injector:
            mock_get_injector.return_value = mock_injector

            await step.process_llm_tools_from_heartbeat(heartbeat_response)

            assert mock_injector.process_llm_tools.call_count == 1

            # Second call with same data - should skip
            mock_injector.reset_mock()

            await step.process_llm_tools_from_heartbeat(heartbeat_response)

            # Should not call either method
            mock_injector.process_llm_tools.assert_not_called()
            mock_injector.update_llm_tools.assert_not_called()

    @pytest.mark.asyncio
    async def test_process_no_response_skips_for_resilience(self):
        """Test that no response skips processing for resilience."""
        step = LLMToolsResolutionStep()

        mock_injector = MagicMock()

        with patch(
            "_mcp_mesh.pipeline.mcp_heartbeat.llm_tools_resolution.get_global_injector"
        ) as mock_get_injector:
            mock_get_injector.return_value = mock_injector

            await step.process_llm_tools_from_heartbeat(None)

            # Should not call anything
            mock_injector.process_llm_tools.assert_not_called()
            mock_injector.update_llm_tools.assert_not_called()

    @pytest.mark.asyncio
    async def test_process_empty_llm_tools_clears(self):
        """Test that empty llm_tools from successful response clears tools."""
        step = LLMToolsResolutionStep()

        # Set initial hash to simulate previous state with tools
        import _mcp_mesh.pipeline.mcp_heartbeat.llm_tools_resolution as module

        module._last_llm_tools_hash = "previous_hash"

        # Empty llm_tools
        heartbeat_response = {"llm_tools": {}}

        mock_injector = MagicMock()

        with patch(
            "_mcp_mesh.pipeline.mcp_heartbeat.llm_tools_resolution.get_global_injector"
        ) as mock_get_injector:
            mock_get_injector.return_value = mock_injector

            await step.process_llm_tools_from_heartbeat(heartbeat_response)

            # Should call update with empty dict
            mock_injector.update_llm_tools.assert_called_once_with({})

    @pytest.mark.asyncio
    async def test_process_handles_exception_gracefully(self):
        """Test that processing exceptions don't break heartbeat loop."""
        step = LLMToolsResolutionStep()

        heartbeat_response = {"llm_tools": {"func1": []}}

        mock_injector = MagicMock()
        mock_injector.process_llm_tools.side_effect = Exception("Injector error")

        with patch(
            "_mcp_mesh.pipeline.mcp_heartbeat.llm_tools_resolution.get_global_injector"
        ) as mock_get_injector:
            mock_get_injector.return_value = mock_injector

            # Should not raise - exception is caught and logged
            await step.process_llm_tools_from_heartbeat(heartbeat_response)

            # Verify the method was called (and raised exception internally)
            mock_injector.process_llm_tools.assert_called_once()


class TestHashTracking:
    """Test global hash tracking across multiple calls."""

    def setup_method(self):
        """Reset global hash before each test."""
        import _mcp_mesh.pipeline.mcp_heartbeat.llm_tools_resolution as module

        module._last_llm_tools_hash = None

    @pytest.mark.asyncio
    async def test_hash_updates_after_processing(self):
        """Test that global hash is updated after processing."""
        import _mcp_mesh.pipeline.mcp_heartbeat.llm_tools_resolution as module

        step = LLMToolsResolutionStep()
        llm_tools = {"func1": [{"name": "tool1"}]}
        heartbeat_response = {"llm_tools": llm_tools}

        # Initially None
        assert module._last_llm_tools_hash is None

        mock_injector = MagicMock()

        with patch(
            "_mcp_mesh.pipeline.mcp_heartbeat.llm_tools_resolution.get_global_injector"
        ) as mock_get_injector:
            mock_get_injector.return_value = mock_injector

            await step.process_llm_tools_from_heartbeat(heartbeat_response)

            # Should be set after processing
            assert module._last_llm_tools_hash is not None
            assert len(module._last_llm_tools_hash) == 16

    @pytest.mark.asyncio
    async def test_hash_changes_with_different_tools(self):
        """Test that hash changes when tools change."""
        import _mcp_mesh.pipeline.mcp_heartbeat.llm_tools_resolution as module

        step = LLMToolsResolutionStep()
        mock_injector = MagicMock()

        with patch(
            "_mcp_mesh.pipeline.mcp_heartbeat.llm_tools_resolution.get_global_injector"
        ) as mock_get_injector:
            mock_get_injector.return_value = mock_injector

            # First call
            llm_tools1 = {"func1": [{"name": "tool1"}]}
            await step.process_llm_tools_from_heartbeat({"llm_tools": llm_tools1})
            hash1 = module._last_llm_tools_hash

            # Second call with different tools
            llm_tools2 = {"func1": [{"name": "tool2"}]}
            await step.process_llm_tools_from_heartbeat({"llm_tools": llm_tools2})
            hash2 = module._last_llm_tools_hash

            assert hash1 != hash2
