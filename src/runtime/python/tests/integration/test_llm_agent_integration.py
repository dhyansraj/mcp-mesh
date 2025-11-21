"""
Integration tests for LLM agent flow.

Tests the complete integration from registry response to LLM agent injection,
mocking external services (registry, LLM API, MCP tools) but testing real
integration logic.

This verifies:
1. Registry llm_tools response → MeshLlmAgentInjector → MeshLlmAgent injection
2. MeshLlmAgent agentic loop with mocked LLM/tool responses
3. Topology updates propagating to existing wrappers
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest
from pydantic import BaseModel

import mesh
from _mcp_mesh.engine.decorator_registry import DecoratorRegistry
from _mcp_mesh.engine.dependency_injector import DependencyInjector
from _mcp_mesh.engine.mesh_llm_agent_injector import get_global_llm_injector


# Test output types
class ChatResponse(BaseModel):
    """Standard chat response for testing."""

    answer: str
    confidence: float


class AnalysisResponse(BaseModel):
    """Analysis response with metadata."""

    summary: str
    key_points: list[str]
    confidence: float


class TestRegistryToInjection:
    """Test flow from registry llm_tools response to MeshLlmAgent injection."""

    def setup_method(self):
        """Clear registries before each test."""
        DecoratorRegistry._mesh_llm_agents = {}
        # Reset global LLM injector
        from _mcp_mesh.engine import mesh_llm_agent_injector

        mesh_llm_agent_injector._global_llm_injector = None

    @pytest.mark.asyncio
    async def test_registry_response_to_injection_flow(self):
        """
        Test complete flow: registry llm_tools → DependencyInjector → MeshLlmAgentInjector → injection.

        This simulates:
        1. Agent receives heartbeat response with llm_tools from registry
        2. DependencyInjector.process_llm_tools() is called
        3. MeshLlmAgentInjector creates UnifiedMCPProxy instances
        4. MeshLlmAgent is created with config and tools
        5. Function wrapper injects MeshLlmAgent into parameter
        """

        # Step 1: Define an LLM function and register it
        @mesh.llm(
            filter={"capability": "document"},
            provider="claude",
            model="claude-3-5-sonnet-20241022",
            max_iterations=5,
        )
        def document_chat(message: str, llm: mesh.MeshLlmAgent = None) -> ChatResponse:
            """Chat about documents using LLM with document tools."""
            # In real usage, llm would be injected automatically
            return ChatResponse(answer="test", confidence=0.9)

        # Get function_id from registry
        llm_agents = DecoratorRegistry.get_mesh_llm_agents()
        assert len(llm_agents) == 1
        function_id = list(llm_agents.keys())[0]

        # Step 2: Simulate registry response with llm_tools
        # This is what the registry returns after filtering tools based on llm_filter
        registry_llm_tools = {
            function_id: [
                {
                    "function_name": "extract_pdf",
                    "capability": "document",
                    "tags": ["pdf", "extraction"],
                    "description": "Extract text from PDF documents",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "file_path": {
                                "type": "string",
                                "description": "Path to PDF file",
                            }
                        },
                        "required": ["file_path"],
                    },
                    "endpoint": {"host": "pdf-service", "port": 8080},
                    "version": "1.0.0",
                },
                {
                    "function_name": "search_docs",
                    "capability": "document",
                    "tags": ["search", "document"],
                    "description": "Search through documents",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "Search query"}
                        },
                        "required": ["query"],
                    },
                    "endpoint": {"host": "search-service", "port": 8081},
                    "version": "1.0.0",
                },
            ]
        }

        # Step 3: Process llm_tools via DependencyInjector
        injector = DependencyInjector()
        injector.process_llm_tools(registry_llm_tools)

        # Step 4: Verify MeshLlmAgentInjector processed the tools
        llm_injector = get_global_llm_injector()
        llm_agent_data = llm_injector.get_llm_agent_data(function_id)

        assert llm_agent_data is not None, "LLM agent data should be created"
        assert len(llm_agent_data["tools"]) == 2, "Should have 2 tool proxies"
        assert llm_agent_data["config"]["provider"] == "claude"
        assert llm_agent_data["config"]["model"] == "claude-3-5-sonnet-20241022"
        assert llm_agent_data["config"]["max_iterations"] == 5
        assert llm_agent_data["output_type"] == ChatResponse

        # Step 5: Create injection wrapper
        wrapper = injector.create_llm_injection_wrapper(document_chat, function_id)

        assert wrapper is not None, "Wrapper should be created"
        assert hasattr(wrapper, "_mesh_llm_agent"), "Wrapper should have LLM agent"
        assert wrapper._mesh_llm_agent is not None

        # Step 6: Verify injection works when calling the function
        # Track what was injected
        injected_agent = None

        @mesh.llm(filter={"capability": "document"}, provider="claude")
        def test_chat(message: str, llm: mesh.MeshLlmAgent = None) -> ChatResponse:
            nonlocal injected_agent
            injected_agent = llm
            return ChatResponse(answer="ok", confidence=1.0)

        # Register and create wrapper
        llm_agents = DecoratorRegistry.get_mesh_llm_agents()
        test_function_id = [k for k in llm_agents.keys() if "test_chat" in k][0]

        # Process same tools for this function
        injector.process_llm_tools({test_function_id: registry_llm_tools[function_id]})
        test_wrapper = injector.create_llm_injection_wrapper(
            test_chat, test_function_id
        )

        # Call without providing llm parameter
        result = test_wrapper("Hello")

        # Verify injection happened
        assert injected_agent is not None, "LLM agent should be injected"
        assert hasattr(injected_agent, "tools"), "Injected agent should have tools"
        assert result.answer == "ok"


class TestLLMAgentMockedFlow:
    """Test MeshLlmAgent with mocked LLM and tool responses."""

    def setup_method(self):
        """Clear registries before each test."""
        DecoratorRegistry._mesh_llm_agents = {}
        from _mcp_mesh.engine import mesh_llm_agent_injector

        mesh_llm_agent_injector._global_llm_injector = None

    @pytest.mark.asyncio
    async def test_llm_agent_agentic_loop_with_tool_calls(self):
        """
        Test MeshLlmAgent agentic loop with mocked LLM responses and tool execution.

        Simulates:
        1. LLM requests tool call
        2. Tool executes (mocked)
        3. LLM receives result and returns final answer
        """
        from _mcp_mesh.engine.mesh_llm_agent import MeshLlmAgent

        # Create mock tool proxy - use spec to avoid MagicMock auto-creating attributes
        mock_tool_proxy = MagicMock()
        # Configure name as a simple string property (not a Mock)
        type(mock_tool_proxy).name = PropertyMock(return_value="search_docs")
        mock_tool_proxy.description = "Search through documents"
        mock_tool_proxy.input_schema = {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        }

        # Mock async call_tool method
        async def mock_call_tool(**kwargs):
            return {"results": ["Document 1", "Document 2"], "count": 2}

        mock_tool_proxy.call_tool = mock_call_tool

        # Create MeshLlmAgent with mocked tool
        llm_agent = MeshLlmAgent(
            provider="claude",
            model="claude-3-5-sonnet-20241022",
            api_key="test-key",
            filtered_tools=[mock_tool_proxy],
            max_iterations=5,
            output_type=ChatResponse,
        )

        # Mock LiteLLM completion to simulate tool use then final response
        # Create properly structured mock function object
        mock_function = MagicMock()
        mock_function.name = "search_docs"  # Direct assignment
        mock_function.arguments = '{"query": "test query"}'

        mock_tool_call = MagicMock()
        mock_tool_call.id = "call_123"
        mock_tool_call.function = mock_function

        mock_responses = [
            # First call: LLM requests tool use
            MagicMock(
                choices=[
                    MagicMock(
                        message=MagicMock(content=None, tool_calls=[mock_tool_call])
                    )
                ]
            ),
            # Second call: LLM returns final answer
            MagicMock(
                choices=[
                    MagicMock(
                        message=MagicMock(
                            content='{"answer": "Found 2 documents matching your query", "confidence": 0.95}',
                            tool_calls=None,
                        )
                    )
                ]
            ),
        ]

        with patch("_mcp_mesh.engine.mesh_llm_agent.completion") as mock_completion:
            # Make completion synchronous but return mock responses
            def mock_completion_fn(*args, **kwargs):
                return mock_responses.pop(0)

            mock_completion.side_effect = mock_completion_fn

            # Call the LLM agent
            result = await llm_agent("Search for test documents")

            # Verify result
            assert isinstance(result, ChatResponse)
            assert "2 documents" in result.answer
            assert result.confidence == 0.95

            # Verify completion was called twice (tool use + final answer)
            assert mock_completion.call_count == 2


class TestTopologyUpdates:
    """Test topology update propagation to existing wrappers."""

    def setup_method(self):
        """Clear registries before each test."""
        DecoratorRegistry._mesh_llm_agents = {}
        from _mcp_mesh.engine import mesh_llm_agent_injector

        mesh_llm_agent_injector._global_llm_injector = None

    @pytest.mark.asyncio
    async def test_topology_update_propagates_to_wrappers(self):
        """
        Test that llm_tools updates (topology changes) propagate to existing wrappers.

        Simulates:
        1. Initial registration with 1 tool
        2. Function wrapper created
        3. Heartbeat brings new tool (topology change)
        4. Existing wrapper's LLM agent updated with new tools
        """

        # Step 1: Register LLM function
        @mesh.llm(filter={"capability": "document"}, provider="claude")
        def analyze_docs(query: str, llm: mesh.MeshLlmAgent = None) -> AnalysisResponse:
            """Analyze documents using LLM."""
            return AnalysisResponse(summary="test", key_points=[], confidence=0.9)

        llm_agents = DecoratorRegistry.get_mesh_llm_agents()
        function_id = list(llm_agents.keys())[0]

        # Step 2: Initial llm_tools (1 tool)
        initial_llm_tools = {
            function_id: [
                {
                    "function_name": "extract_pdf",
                    "capability": "document",
                    "description": "Extract text from PDF",
                    "endpoint": {"host": "pdf-service", "port": 8080},
                    "input_schema": {"type": "object"},
                }
            ]
        }

        injector = DependencyInjector()
        injector.process_llm_tools(initial_llm_tools)

        # Step 3: Create wrapper
        wrapper = injector.create_llm_injection_wrapper(analyze_docs, function_id)
        initial_agent = wrapper._mesh_llm_agent

        assert initial_agent is not None
        assert len(initial_agent.tools) == 1, "Should have 1 tool initially"

        # Step 4: Topology update - new tool joins
        updated_llm_tools = {
            function_id: [
                {
                    "function_name": "extract_pdf",
                    "capability": "document",
                    "description": "Extract text from PDF",
                    "endpoint": {"host": "pdf-service", "port": 8080},
                    "input_schema": {"type": "object"},
                },
                {
                    "function_name": "search_docs",  # NEW TOOL
                    "capability": "document",
                    "description": "Search documents",
                    "endpoint": {"host": "search-service", "port": 8081},
                    "input_schema": {"type": "object"},
                },
                {
                    "function_name": "summarize_doc",  # NEW TOOL
                    "capability": "document",
                    "description": "Summarize documents",
                    "endpoint": {"host": "summary-service", "port": 8082},
                    "input_schema": {"type": "object"},
                },
            ]
        }

        # Step 5: Update via DependencyInjector (simulates heartbeat)
        injector.update_llm_tools(updated_llm_tools)

        # Step 6: Verify wrapper's agent was updated
        updated_agent = wrapper._mesh_llm_agent

        assert updated_agent is not None
        assert len(updated_agent.tools) == 3, "Should have 3 tools after update"

        # Verify new agent was created (not same instance)
        assert (
            updated_agent is not initial_agent
        ), "New agent instance should be created"

    @pytest.mark.asyncio
    async def test_topology_update_removes_tools(self):
        """Test that tools are removed when they leave the topology."""

        # Register LLM function
        @mesh.llm(filter={"capability": "document"}, provider="claude")
        def process_docs(msg: str, llm: mesh.MeshLlmAgent = None) -> ChatResponse:
            return ChatResponse(answer="test", confidence=0.9)

        llm_agents = DecoratorRegistry.get_mesh_llm_agents()
        function_id = list(llm_agents.keys())[0]

        # Initial state: 3 tools
        initial_llm_tools = {
            function_id: [
                {
                    "function_name": "tool1",
                    "capability": "document",
                    "endpoint": {"host": "svc1", "port": 8080},
                    "input_schema": {},
                },
                {
                    "function_name": "tool2",
                    "capability": "document",
                    "endpoint": {"host": "svc2", "port": 8081},
                    "input_schema": {},
                },
                {
                    "function_name": "tool3",
                    "capability": "document",
                    "endpoint": {"host": "svc3", "port": 8082},
                    "input_schema": {},
                },
            ]
        }

        injector = DependencyInjector()
        injector.process_llm_tools(initial_llm_tools)
        wrapper = injector.create_llm_injection_wrapper(process_docs, function_id)

        assert len(wrapper._mesh_llm_agent.tools) == 3

        # Topology update: tool2 and tool3 leave
        updated_llm_tools = {
            function_id: [
                {
                    "function_name": "tool1",
                    "capability": "document",
                    "endpoint": {"host": "svc1", "port": 8080},
                    "input_schema": {},
                },
            ]
        }

        injector.update_llm_tools(updated_llm_tools)

        # Verify only 1 tool remains
        assert len(wrapper._mesh_llm_agent.tools) == 1
        assert wrapper._mesh_llm_agent.tools[0].function_name == "tool1"


class TestErrorHandling:
    """Test error handling in integration flow."""

    def setup_method(self):
        """Clear registries before each test."""
        DecoratorRegistry._mesh_llm_agents = {}
        from _mcp_mesh.engine import mesh_llm_agent_injector

        mesh_llm_agent_injector._global_llm_injector = None

    @pytest.mark.asyncio
    async def test_handles_missing_endpoint_gracefully(self):
        """Test that invalid tool endpoints are handled gracefully."""

        @mesh.llm(filter={"capability": "test"}, provider="claude")
        def test_func(msg: str, llm: mesh.MeshLlmAgent = None) -> ChatResponse:
            return ChatResponse(answer="test", confidence=0.9)

        llm_agents = DecoratorRegistry.get_mesh_llm_agents()
        function_id = list(llm_agents.keys())[0]

        # llm_tools with invalid endpoint
        llm_tools_invalid = {
            function_id: [
                {
                    "function_name": "bad_tool",
                    "capability": "test",
                    "endpoint": None,  # Invalid!
                    "input_schema": {},
                },
            ]
        }

        injector = DependencyInjector()

        # Should not raise, but log error and skip tool
        injector.process_llm_tools(llm_tools_invalid)

        llm_injector = get_global_llm_injector()
        llm_agent_data = llm_injector.get_llm_agent_data(function_id)

        # Function should be registered but with no tools
        assert llm_agent_data is not None
        assert len(llm_agent_data["tools"]) == 0

    @pytest.mark.asyncio
    async def test_handles_empty_llm_tools(self):
        """Test handling of empty llm_tools (no matching tools from registry)."""

        @mesh.llm(filter={"capability": "rare"}, provider="claude")
        def test_func(msg: str, llm: mesh.MeshLlmAgent = None) -> ChatResponse:
            return ChatResponse(answer="test", confidence=0.9)

        llm_agents = DecoratorRegistry.get_mesh_llm_agents()
        function_id = list(llm_agents.keys())[0]

        # Empty llm_tools (no tools matched filter)
        llm_tools_empty = {function_id: []}

        injector = DependencyInjector()
        injector.process_llm_tools(llm_tools_empty)

        # Should create agent with empty tool list
        wrapper = injector.create_llm_injection_wrapper(test_func, function_id)
        assert wrapper._mesh_llm_agent is not None
        assert len(wrapper._mesh_llm_agent.tools) == 0
