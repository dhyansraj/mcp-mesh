"""
End-to-end test for heartbeat pipeline with llm_tools processing.

Tests the complete flow:
1. Heartbeat response contains llm_tools from registry
2. HeartbeatPipeline processes the response
3. LLMToolsResolutionStep extracts and processes llm_tools
4. DependencyInjector.process_llm_tools() is called
5. MeshLlmAgent instances are created and available
"""

import weakref
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest

import mesh
from _mcp_mesh.engine.decorator_registry import DecoratorRegistry
from _mcp_mesh.engine.dependency_injector import get_global_injector
from _mcp_mesh.engine.mesh_llm_agent_injector import get_global_llm_injector
from _mcp_mesh.pipeline.mcp_heartbeat.heartbeat_pipeline import HeartbeatPipeline
from _mcp_mesh.shared.fast_heartbeat_status import FastHeartbeatStatus


@pytest.fixture
def cleanup_registries():
    """Clean up registries and injector state before and after each test."""
    # Clean DecoratorRegistry
    DecoratorRegistry._mesh_llm_agents = {}

    # Clean LLM injector state
    from _mcp_mesh.engine.mesh_llm_agent_injector import get_global_llm_injector

    llm_injector = get_global_llm_injector()
    llm_injector._llm_agents = {}
    llm_injector._function_registry = weakref.WeakValueDictionary()

    # Reset hash tracking
    import _mcp_mesh.pipeline.mcp_heartbeat.llm_tools_resolution as module

    module._last_llm_tools_hash = None

    yield

    # Clean up after test
    DecoratorRegistry._mesh_llm_agents = {}
    llm_injector._llm_agents = {}
    llm_injector._function_registry = weakref.WeakValueDictionary()
    module._last_llm_tools_hash = None


def create_mock_registry_wrapper(function_id: str):
    """Create a mock registry wrapper for heartbeat context with dynamic function_id."""
    from _mcp_mesh.shared.fast_heartbeat_status import FastHeartbeatStatus

    wrapper = MagicMock()
    wrapper.registry_url = "http://test-registry:5000"
    wrapper.is_connected.return_value = True

    # Mock fast heartbeat check (returns status indicating topology changed)
    async def mock_check_fast_heartbeat(agent_id):
        return FastHeartbeatStatus.TOPOLOGY_CHANGED

    wrapper.check_fast_heartbeat = AsyncMock(side_effect=mock_check_fast_heartbeat)

    # Mock full heartbeat POST request - uses the actual function_id
    async def mock_send_heartbeat_with_dependency_resolution(health_status):
        return {
            "status": "success",
            "topology_hash": "abc123",
            "dependencies_resolved": {},
            "llm_tools": {
                function_id: [
                    {
                        "function_name": "extract_pdf_text",
                        "capability": "document",
                        "endpoint": {"host": "pdf-service", "port": 8080},
                        "input_schema": {
                            "type": "object",
                            "properties": {"file_path": {"type": "string"}},
                        },
                    },
                    {
                        "function_name": "summarize_document",
                        "capability": "document",
                        "endpoint": {"host": "pdf-service", "port": 8080},
                        "input_schema": {
                            "type": "object",
                            "properties": {"text": {"type": "string"}},
                        },
                    },
                ]
            },
        }

    wrapper.send_heartbeat_with_dependency_resolution = AsyncMock(
        side_effect=mock_send_heartbeat_with_dependency_resolution
    )

    return wrapper


class ChatResponse:
    """Simple response model for testing."""

    def __init__(self, answer: str, confidence: float):
        self.answer = answer
        self.confidence = confidence


class TestHeartbeatLLMToolsEndToEnd:
    """Test end-to-end flow of llm_tools through heartbeat pipeline."""

    @pytest.mark.asyncio
    async def test_heartbeat_with_llm_tools_creates_agents(self, cleanup_registries):
        """Test that heartbeat response with llm_tools creates MeshLlmAgent instances."""

        # 1. Register an LLM function in DecoratorRegistry
        @mesh.llm(filter={"capability": "document"}, provider="claude")
        def document_chat(message: str, llm: mesh.MeshLlmAgent = None) -> ChatResponse:
            return ChatResponse(answer="test", confidence=0.9)

        function_id = None
        for fid, metadata in DecoratorRegistry._mesh_llm_agents.items():
            if metadata.function.__name__ == "document_chat":
                function_id = fid
                break

        assert function_id is not None, "LLM function not registered"

        # 2. Create mock registry wrapper with actual function_id
        mock_registry_wrapper = create_mock_registry_wrapper(function_id)

        # 3. Create heartbeat pipeline and context
        pipeline = HeartbeatPipeline()

        heartbeat_context = {
            "registry_wrapper": mock_registry_wrapper,
            "agent_id": "test-agent-123",
            "health_status": {"status": "healthy"},
            "current_topology_hash": None,  # Force full heartbeat
        }

        # 3. Execute heartbeat cycle
        result = await pipeline.execute_heartbeat_cycle(heartbeat_context)

        # 4. Verify pipeline succeeded
        assert result.is_success(), f"Pipeline failed: {result.message}"

        # 5. Verify llm_tools were processed
        assert "llm_function_count" in result.context
        assert result.context["llm_function_count"] == 1
        assert result.context["llm_tool_count"] == 2

        # 6. Verify MeshLlmAgent was created in the injector
        llm_injector = get_global_llm_injector()
        llm_agent_data = llm_injector.get_llm_agent_data(function_id)

        assert llm_agent_data is not None, "LLM agent not created"
        # Config includes default values, check key fields
        assert llm_agent_data["config"]["provider"] == "claude"
        assert llm_agent_data["config"]["filter"] == {"capability": "document"}
        assert llm_agent_data["output_type"] == ChatResponse
        assert len(llm_agent_data["tools"]) == 2

        # 7. Verify tool proxies were created
        tool_names = [tool.function_name for tool in llm_agent_data["tools"]]
        assert "extract_pdf_text" in tool_names
        assert "summarize_document" in tool_names

    @pytest.mark.asyncio
    async def test_heartbeat_updates_existing_llm_agents(self, cleanup_registries):
        """Test that subsequent heartbeats update existing LLM agents."""

        # 1. Register LLM function
        @mesh.llm(filter={"capability": "document"}, provider="claude")
        def document_chat(message: str, llm: mesh.MeshLlmAgent = None) -> ChatResponse:
            return ChatResponse(answer="test", confidence=0.9)

        function_id = None
        for fid, metadata in DecoratorRegistry._mesh_llm_agents.items():
            if metadata.function.__name__ == "document_chat":
                function_id = fid
                break

        # 2. First heartbeat - initial processing
        mock_registry_wrapper = create_mock_registry_wrapper(function_id)
        pipeline = HeartbeatPipeline()

        heartbeat_context_1 = {
            "registry_wrapper": mock_registry_wrapper,
            "agent_id": "test-agent-123",
            "health_status": {"status": "healthy"},
            "current_topology_hash": None,
        }

        result1 = await pipeline.execute_heartbeat_cycle(heartbeat_context_1)
        assert result1.is_success()

        llm_injector = get_global_llm_injector()
        initial_agent_data = llm_injector.get_llm_agent_data(function_id)
        assert len(initial_agent_data["tools"]) == 2

        # 3. Second heartbeat with updated tools (one new tool)
        updated_wrapper = MagicMock()
        updated_wrapper.registry_url = "http://test-registry:5000"
        updated_wrapper.is_connected.return_value = True

        async def mock_updated_check_fast_heartbeat(agent_id):
            return FastHeartbeatStatus.TOPOLOGY_CHANGED

        updated_wrapper.check_fast_heartbeat = AsyncMock(
            side_effect=mock_updated_check_fast_heartbeat
        )

        async def mock_updated_send_heartbeat_with_dependency_resolution(health_status):
            return {
                "status": "success",
                "topology_hash": "def456",  # Different hash
                "dependencies_resolved": {},
                "llm_tools": {
                    function_id: [
                        {
                            "function_name": "extract_pdf_text",
                            "capability": "document",
                            "endpoint": {"host": "pdf-service", "port": 8080},
                            "input_schema": {"type": "object"},
                        },
                        {
                            "function_name": "summarize_document",
                            "capability": "document",
                            "endpoint": {"host": "pdf-service", "port": 8080},
                            "input_schema": {"type": "object"},
                        },
                        {
                            "function_name": "translate_document",  # NEW TOOL
                            "capability": "document",
                            "endpoint": {"host": "pdf-service", "port": 8080},
                            "input_schema": {"type": "object"},
                        },
                    ]
                },
            }

        updated_wrapper.send_heartbeat_with_dependency_resolution = AsyncMock(
            side_effect=mock_updated_send_heartbeat_with_dependency_resolution
        )

        heartbeat_context_2 = {
            "registry_wrapper": updated_wrapper,
            "agent_id": "test-agent-123",
            "health_status": {"status": "healthy"},
            "current_topology_hash": "abc123",  # Old hash
        }

        result2 = await pipeline.execute_heartbeat_cycle(heartbeat_context_2)
        assert result2.is_success()

        # 4. Verify LLM agent was updated with new tool
        updated_agent_data = llm_injector.get_llm_agent_data(function_id)
        assert len(updated_agent_data["tools"]) == 3

        tool_names = [tool.function_name for tool in updated_agent_data["tools"]]
        assert "translate_document" in tool_names

    @pytest.mark.asyncio
    async def test_heartbeat_skips_llm_tools_on_no_changes(self, cleanup_registries):
        """Test that NO_CHANGES status skips LLM tools processing."""

        # 1. Register LLM function
        @mesh.llm(filter={"capability": "document"}, provider="claude")
        def document_chat(message: str, llm: mesh.MeshLlmAgent = None) -> ChatResponse:
            return ChatResponse(answer="test", confidence=0.9)

        # 2. Mock wrapper for NO_CHANGES scenario
        no_change_wrapper = MagicMock()
        no_change_wrapper.registry_url = "http://test-registry:5000"
        no_change_wrapper.is_connected.return_value = True

        async def mock_no_change_check_fast_heartbeat(agent_id):
            return FastHeartbeatStatus.NO_CHANGES

        no_change_wrapper.check_fast_heartbeat = AsyncMock(
            side_effect=mock_no_change_check_fast_heartbeat
        )

        # send_heartbeat_with_dependency_resolution should NOT be called in NO_CHANGES scenario
        no_change_wrapper.send_heartbeat_with_dependency_resolution = AsyncMock()

        # 3. Execute heartbeat with matching hash (NO_CHANGES)
        pipeline = HeartbeatPipeline()

        heartbeat_context = {
            "registry_wrapper": no_change_wrapper,
            "agent_id": "test-agent-123",
            "health_status": {"status": "healthy"},
            "current_topology_hash": "abc123",  # Same as response
        }

        result = await pipeline.execute_heartbeat_cycle(heartbeat_context)

        # 4. Verify pipeline succeeded and skipped conditional steps
        assert result.is_success()
        assert (
            "optimization" in result.message.lower()
            or "skipped" in result.message.lower()
        )

        # 5. Verify send_heartbeat_with_dependency_resolution was NOT called (optimization)
        no_change_wrapper.send_heartbeat_with_dependency_resolution.assert_not_called()

    @pytest.mark.asyncio
    async def test_heartbeat_handles_empty_llm_tools(self, cleanup_registries):
        """Test that empty llm_tools in response clears existing agents."""

        # 1. Register LLM function and process initial tools
        @mesh.llm(filter={"capability": "document"}, provider="claude")
        def document_chat(message: str, llm: mesh.MeshLlmAgent = None) -> ChatResponse:
            return ChatResponse(answer="test", confidence=0.9)

        function_id = None
        for fid, metadata in DecoratorRegistry._mesh_llm_agents.items():
            if metadata.function.__name__ == "document_chat":
                function_id = fid
                break

        mock_registry_wrapper = create_mock_registry_wrapper(function_id)
        pipeline = HeartbeatPipeline()

        heartbeat_context_1 = {
            "registry_wrapper": mock_registry_wrapper,
            "agent_id": "test-agent-123",
            "health_status": {"status": "healthy"},
            "current_topology_hash": None,
        }

        result1 = await pipeline.execute_heartbeat_cycle(heartbeat_context_1)
        assert result1.is_success()

        llm_injector = get_global_llm_injector()
        initial_agent_data = llm_injector.get_llm_agent_data(function_id)
        assert initial_agent_data is not None

        # 2. Send heartbeat with empty llm_tools
        empty_wrapper = MagicMock()
        empty_wrapper.registry_url = "http://test-registry:5000"
        empty_wrapper.is_connected.return_value = True

        async def mock_empty_check_fast_heartbeat(agent_id):
            return FastHeartbeatStatus.TOPOLOGY_CHANGED

        empty_wrapper.check_fast_heartbeat = AsyncMock(
            side_effect=mock_empty_check_fast_heartbeat
        )

        async def mock_empty_send_heartbeat_with_dependency_resolution(health_status):
            return {
                "status": "success",
                "topology_hash": "empty123",
                "dependencies_resolved": {},
                "llm_tools": {},  # Empty - no LLM tools
            }

        empty_wrapper.send_heartbeat_with_dependency_resolution = AsyncMock(
            side_effect=mock_empty_send_heartbeat_with_dependency_resolution
        )

        heartbeat_context_2 = {
            "registry_wrapper": empty_wrapper,
            "agent_id": "test-agent-123",
            "health_status": {"status": "healthy"},
            "current_topology_hash": "abc123",
        }

        result2 = await pipeline.execute_heartbeat_cycle(heartbeat_context_2)
        assert result2.is_success()

        # 3. Verify LLM agent was cleared
        cleared_agent_data = llm_injector.get_llm_agent_data(function_id)
        assert (
            cleared_agent_data is None
        ), "LLM agent should be cleared when llm_tools is empty"
