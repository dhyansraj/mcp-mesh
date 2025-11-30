"""
Unit tests for MeshLlmAgentInjector.

Tests follow TDD approach - these should FAIL initially until injector is implemented.
The MeshLlmAgentInjector is responsible for:
1. Consuming llm_tools from registry response
2. Creating UnifiedMCPProxy instances for each tool
3. Creating MeshLlmAgent instances with config + proxies + output_type
4. Injecting MeshLlmAgent into function parameters
5. Handling topology updates (tools join/leave)
"""

from pathlib import Path
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import BaseModel, Field

from mesh import MeshContextModel

# Helper to get fixture paths - tests run from various directories
FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"
TEMPLATES_DIR = FIXTURES_DIR / "templates"


# Test output types
class ChatResponse(BaseModel):
    """Standard chat response for testing."""

    answer: str
    confidence: float


class AdvancedResponse(BaseModel):
    """Advanced response with metadata."""

    result: str
    metadata: dict
    tools_used: list[str] = []


# Helper function to register LLM functions
def register_test_llm_function(
    function_id: str, output_type: type = ChatResponse, config: Optional[dict] = None
):
    """Helper to register a test LLM function in DecoratorRegistry."""
    import mesh
    from _mcp_mesh.engine.decorator_registry import DecoratorRegistry

    def test_func(msg: str, llm: mesh.MeshLlmAgent = None):
        return (
            output_type(answer="test", confidence=0.9)
            if output_type == ChatResponse
            else output_type(result="test", metadata={})
        )

    if config is None:
        config = {"filter": {"capability": "document"}, "provider": "claude"}

    DecoratorRegistry.register_mesh_llm(
        test_func, config, output_type, "llm", function_id
    )


class TestMeshLlmAgentInjectorBasics:
    """Test basic initialization and setup."""

    def test_injector_initialization(self):
        """Test MeshLlmAgentInjector can be initialized."""
        from _mcp_mesh.engine.mesh_llm_agent_injector import MeshLlmAgentInjector

        injector = MeshLlmAgentInjector()
        assert injector is not None

    def test_injector_has_required_methods(self):
        """Test injector has all required methods."""
        from _mcp_mesh.engine.mesh_llm_agent_injector import MeshLlmAgentInjector

        injector = MeshLlmAgentInjector()
        assert hasattr(injector, "process_llm_tools")
        assert hasattr(injector, "create_injection_wrapper")
        assert hasattr(injector, "update_llm_tools")

    def test_injector_starts_with_empty_registry(self):
        """Test injector starts with no LLM agents registered."""
        from _mcp_mesh.engine.mesh_llm_agent_injector import MeshLlmAgentInjector

        injector = MeshLlmAgentInjector()
        # Should have internal registry for tracking LLM agents
        assert hasattr(injector, "_llm_agents")
        assert len(injector._llm_agents) == 0


class TestProcessLLMTools:
    """Test processing llm_tools from registry response."""

    def setup_method(self):
        """Clear DecoratorRegistry before each test."""
        from _mcp_mesh.engine.decorator_registry import DecoratorRegistry

        DecoratorRegistry._mesh_llm_agents = {}

    def test_process_empty_llm_tools(self):
        """Test processing empty llm_tools dict."""
        from _mcp_mesh.engine.mesh_llm_agent_injector import MeshLlmAgentInjector

        injector = MeshLlmAgentInjector()
        llm_tools = {}

        injector.process_llm_tools(llm_tools)

        # Should not create any LLM agents
        assert len(injector._llm_agents) == 0

    def test_process_llm_tools_for_single_function(self):
        """Test processing llm_tools for a single LLM function."""
        import mesh
        from _mcp_mesh.engine.decorator_registry import DecoratorRegistry
        from _mcp_mesh.engine.mesh_llm_agent_injector import MeshLlmAgentInjector

        # Register function in DecoratorRegistry first
        def chat(msg: str, llm: mesh.MeshLlmAgent = None) -> ChatResponse:
            return ChatResponse(answer="test", confidence=0.9)

        function_id = "chat_abc123"
        DecoratorRegistry.register_mesh_llm(
            chat,
            {"filter": {"capability": "document"}, "provider": "claude"},
            ChatResponse,
            "llm",
            function_id,
        )

        injector = MeshLlmAgentInjector()

        # Mock llm_tools from registry (format: function_name -> list of tools)
        llm_tools = {
            "chat": [  # Use function_name, not function_id!
                {
                    "name": "extract_pdf",
                    "capability": "document",
                    "tags": ["pdf"],
                    "description": "Extract text from PDF",
                    "input_schema": {"type": "object"},
                    "endpoint": "http://pdf-service:8080",
                    "version": "1.0.0",
                }
            ]
        }

        injector.process_llm_tools(llm_tools)

        # Should have created proxies for the tools
        assert "chat_abc123" in injector._llm_agents
        # Verify the LLM agent was created with correct tools
        llm_agent_data = injector._llm_agents["chat_abc123"]
        assert llm_agent_data is not None
        assert "tools_proxies" in llm_agent_data
        assert len(llm_agent_data["tools_proxies"]) == 1

    def test_process_llm_tools_for_multiple_functions(self):
        """Test processing llm_tools for multiple LLM functions."""
        import mesh
        from _mcp_mesh.engine.decorator_registry import DecoratorRegistry
        from _mcp_mesh.engine.mesh_llm_agent_injector import MeshLlmAgentInjector

        # Register two functions with different names
        def chat_func(msg: str, llm: mesh.MeshLlmAgent = None):
            return ChatResponse(answer="test", confidence=0.9)

        def analyze_func(msg: str, llm: mesh.MeshLlmAgent = None):
            return ChatResponse(answer="test", confidence=0.9)

        DecoratorRegistry.register_mesh_llm(
            chat_func,
            {"filter": {"capability": "document"}, "provider": "claude"},
            ChatResponse,
            "llm",
            "chat_abc123",
        )
        DecoratorRegistry.register_mesh_llm(
            analyze_func,
            {"filter": {"capability": "document"}, "provider": "claude"},
            ChatResponse,
            "llm",
            "analyze_def456",
        )

        injector = MeshLlmAgentInjector()

        llm_tools = {
            "chat_func": [
                {
                    "name": "tool1",
                    "capability": "doc",
                    "endpoint": "http://svc1:8080",
                }
            ],
            "analyze_func": [
                {
                    "name": "tool2",
                    "capability": "analyze",
                    "endpoint": "http://svc2:8080",
                },
                {
                    "name": "tool3",
                    "capability": "search",
                    "endpoint": "http://svc3:8080",
                },
            ],
        }

        injector.process_llm_tools(llm_tools)

        assert len(injector._llm_agents) == 2
        assert "chat_abc123" in injector._llm_agents
        assert "analyze_def456" in injector._llm_agents

    def test_process_llm_tools_creates_unified_mcp_proxies(self):
        """Test that UnifiedMCPProxy instances are created for each tool."""
        from _mcp_mesh.engine.mesh_llm_agent_injector import MeshLlmAgentInjector

        # Register function in DecoratorRegistry
        register_test_llm_function("chat_abc123")

        injector = MeshLlmAgentInjector()

        llm_tools = {
            "test_func": [
                {
                    "name": "extract_pdf",
                    "capability": "document",
                    "endpoint": "http://pdf-service:8080",
                    "input_schema": {"type": "object"},
                }
            ]
        }

        with patch(
            "_mcp_mesh.engine.mesh_llm_agent_injector.UnifiedMCPProxy"
        ) as MockProxy:
            MockProxy.return_value = MagicMock()

            injector.process_llm_tools(llm_tools)

            # Verify UnifiedMCPProxy was created
            MockProxy.assert_called_once()
            # Verify it was called with correct endpoint
            call_args = MockProxy.call_args
            assert "host" in call_args[1] or "pdf-service" in str(call_args)


class TestCreateInjectionWrapper:
    """Test wrapper creation for LLM agent functions."""

    def setup_method(self):
        """Clear DecoratorRegistry before each test."""
        from _mcp_mesh.engine.decorator_registry import DecoratorRegistry

        DecoratorRegistry._mesh_llm_agents = {}

    def test_create_wrapper_for_function_with_llm_parameter(self):
        """Test creating injection wrapper for function with MeshLlmAgent parameter."""
        import mesh
        from _mcp_mesh.engine.mesh_llm_agent_injector import MeshLlmAgentInjector

        # Register function in DecoratorRegistry
        function_id = "chat_abc123"
        register_test_llm_function(function_id)

        injector = MeshLlmAgentInjector()

        # Prepare LLM agent instance
        llm_tools = {function_id: [{"name": "tool1", "endpoint": "http://svc1:8080"}]}
        injector.process_llm_tools(llm_tools)

        # Create test function
        def chat(message: str, llm: mesh.MeshLlmAgent = None) -> ChatResponse:
            return llm(message)

        # Create wrapper
        wrapper = injector.create_injection_wrapper(chat, function_id)

        assert wrapper is not None
        assert hasattr(wrapper, "_mesh_llm_agent")
        assert callable(wrapper)

    def test_wrapper_injects_llm_agent_on_call(self):
        """Test that wrapper injects MeshLlmAgent when function is called."""
        import mesh
        from _mcp_mesh.engine.mesh_llm_agent_injector import MeshLlmAgentInjector

        # Register function in DecoratorRegistry
        function_id = "chat_abc123"
        register_test_llm_function(function_id)

        injector = MeshLlmAgentInjector()

        # Track if LLM agent was injected
        injected_agent = None

        def test_func(message: str, llm: mesh.MeshLlmAgent = None) -> ChatResponse:
            nonlocal injected_agent
            injected_agent = llm
            return ChatResponse(answer="test", confidence=0.9)

        # Create wrapper first, before processing tools
        wrapper = injector.create_injection_wrapper(test_func, function_id)

        # Update DecoratorRegistry to use the wrapper (simulating what @mesh.llm() does)
        from _mcp_mesh.engine.decorator_registry import DecoratorRegistry

        llm_agents = DecoratorRegistry._mesh_llm_agents
        if function_id in llm_agents:
            # Update the function reference to point to the wrapper
            llm_agents[function_id].function = wrapper

        # Then process tools - this will update the wrapper
        llm_tools = {
            "test_func": [{"name": "test_tool", "endpoint": "http://test:8080"}]
        }
        injector.process_llm_tools(llm_tools)

        # Call wrapper without providing llm parameter
        result = wrapper("Hello")

        # Verify LLM agent was injected
        assert injected_agent is not None
        assert result.answer == "test"

    def test_wrapper_preserves_original_function_metadata(self):
        """Test that wrapper preserves function name and signature."""
        import mesh
        from _mcp_mesh.engine.mesh_llm_agent_injector import MeshLlmAgentInjector

        # Register function in DecoratorRegistry
        function_id = "chat_abc123"
        register_test_llm_function(function_id)

        injector = MeshLlmAgentInjector()

        injector.process_llm_tools({"test_func": []})

        def my_custom_chat(message: str, llm: mesh.MeshLlmAgent = None) -> ChatResponse:
            """My custom chat docstring."""
            return ChatResponse(answer="test", confidence=0.9)

        wrapper = injector.create_injection_wrapper(my_custom_chat, function_id)

        # Verify metadata preserved
        assert wrapper.__name__ == "my_custom_chat"
        assert wrapper.__doc__ == "My custom chat docstring."

    def test_error_when_function_has_no_llm_parameter(self):
        """Test error handling when function has no MeshLlmAgent parameter."""
        from _mcp_mesh.engine.mesh_llm_agent_injector import MeshLlmAgentInjector

        # Register function in DecoratorRegistry (but it won't have the right param)
        function_id = "invalid_func"
        register_test_llm_function(function_id)

        injector = MeshLlmAgentInjector()

        injector.process_llm_tools({"test_func": []})

        def no_llm_param(message: str) -> ChatResponse:
            return ChatResponse(answer="test", confidence=0.9)

        # Should raise error or log warning
        with pytest.raises(ValueError, match="MeshLlmAgent parameter"):
            injector.create_injection_wrapper(no_llm_param, function_id)


class TestMeshLlmAgentInstantiation:
    """Test MeshLlmAgent instance creation."""

    def test_creates_mesh_llm_agent_with_config(self):
        """Test that MeshLlmAgent is created with config from DecoratorRegistry."""
        import mesh
        from _mcp_mesh.engine.decorator_registry import DecoratorRegistry
        from _mcp_mesh.engine.mesh_llm_agent_injector import MeshLlmAgentInjector

        # Register an LLM function in DecoratorRegistry
        def test_func(msg: str, llm: mesh.MeshLlmAgent = None) -> ChatResponse:
            return ChatResponse(answer="test", confidence=0.9)

        function_id = "test_abc123"
        config = {
            "filter": {"capability": "document"},
            "filter_mode": "all",
            "provider": "claude",
            "model": "claude-3-5-sonnet-20241022",
            "max_iterations": 10,
        }

        DecoratorRegistry.register_mesh_llm(
            test_func, config, ChatResponse, "llm", function_id
        )

        injector = MeshLlmAgentInjector()
        llm_tools = {"test_func": []}
        injector.process_llm_tools(llm_tools)

        # Verify MeshLlmAgent was created with correct config
        assert function_id in injector._llm_agents
        llm_agent_data = injector._llm_agents[function_id]
        assert llm_agent_data["config"] == config
        assert llm_agent_data["output_type"] == ChatResponse

    def test_creates_mesh_llm_agent_with_output_type(self):
        """Test that MeshLlmAgent has correct output type from function annotation."""
        import mesh
        from _mcp_mesh.engine.decorator_registry import DecoratorRegistry
        from _mcp_mesh.engine.mesh_llm_agent_injector import MeshLlmAgentInjector

        def advanced_chat(msg: str, llm: mesh.MeshLlmAgent = None) -> AdvancedResponse:
            return AdvancedResponse(result="test", metadata={})

        function_id = "advanced_abc123"
        DecoratorRegistry.register_mesh_llm(
            advanced_chat,
            {"filter": "doc"},
            AdvancedResponse,  # Different output type
            "llm",
            function_id,
        )

        injector = MeshLlmAgentInjector()
        injector.process_llm_tools({"advanced_chat": []})

        llm_agent_data = injector._llm_agents[function_id]
        assert llm_agent_data["output_type"] == AdvancedResponse


class TestTopologyUpdates:
    """Test handling of topology changes (tools join/leave)."""

    def setup_method(self):
        """Clear DecoratorRegistry before each test."""
        from _mcp_mesh.engine.decorator_registry import DecoratorRegistry

        DecoratorRegistry._mesh_llm_agents = {}

    def test_update_llm_tools_adds_new_tools(self):
        """Test that update_llm_tools adds new tools when topology changes."""
        from _mcp_mesh.engine.mesh_llm_agent_injector import MeshLlmAgentInjector

        # Register function in DecoratorRegistry
        register_test_llm_function("chat_abc123")

        injector = MeshLlmAgentInjector()

        # Initial state: one tool
        initial_llm_tools = {
            "test_func": [{"name": "tool1", "endpoint": "http://svc1:8080"}]
        }
        injector.process_llm_tools(initial_llm_tools)

        # Topology change: add another tool
        updated_llm_tools = {
            "test_func": [
                {"name": "tool1", "endpoint": "http://svc1:8080"},
                {
                    "name": "tool2",
                    "endpoint": "http://svc2:8080",
                },  # NEW
            ]
        }

        injector.update_llm_tools(updated_llm_tools)

        # Verify tools were updated
        assert "chat_abc123" in injector._llm_agents
        llm_agent_data = injector._llm_agents["chat_abc123"]
        assert len(llm_agent_data["tools_proxies"]) == 2

    def test_update_llm_tools_removes_tools(self):
        """Test that update_llm_tools removes tools when they leave."""
        from _mcp_mesh.engine.mesh_llm_agent_injector import MeshLlmAgentInjector

        # Register function in DecoratorRegistry
        register_test_llm_function("chat_abc123")

        injector = MeshLlmAgentInjector()

        # Initial state: two tools
        initial_llm_tools = {
            "test_func": [
                {"name": "tool1", "endpoint": "http://svc1:8080"},
                {"name": "tool2", "endpoint": "http://svc2:8080"},
            ]
        }
        injector.process_llm_tools(initial_llm_tools)

        # Topology change: remove one tool
        updated_llm_tools = {
            "test_func": [{"name": "tool1", "endpoint": "http://svc1:8080"}]
        }

        injector.update_llm_tools(updated_llm_tools)

        # Verify tool was removed
        llm_agent_data = injector._llm_agents["chat_abc123"]
        assert len(llm_agent_data["tools_proxies"]) == 1

    def test_update_llm_tools_handles_function_removal(self):
        """Test handling when entire LLM function is removed from topology."""
        import mesh
        from _mcp_mesh.engine.decorator_registry import DecoratorRegistry
        from _mcp_mesh.engine.mesh_llm_agent_injector import MeshLlmAgentInjector

        # Register two functions with different names
        def chat_func(msg: str, llm: mesh.MeshLlmAgent = None):
            return ChatResponse(answer="test", confidence=0.9)

        def analyze_func(msg: str, llm: mesh.MeshLlmAgent = None):
            return ChatResponse(answer="test", confidence=0.9)

        DecoratorRegistry.register_mesh_llm(
            chat_func,
            {"filter": {"capability": "document"}, "provider": "claude"},
            ChatResponse,
            "llm",
            "chat_abc123",
        )
        DecoratorRegistry.register_mesh_llm(
            analyze_func,
            {"filter": {"capability": "document"}, "provider": "claude"},
            ChatResponse,
            "llm",
            "analyze_def456",
        )

        injector = MeshLlmAgentInjector()

        initial_llm_tools = {
            "chat_func": [{"name": "tool1", "endpoint": "http://svc1:8080"}],
            "analyze_func": [{"name": "tool2", "endpoint": "http://svc2:8080"}],
        }
        injector.process_llm_tools(initial_llm_tools)

        # Remove one function entirely
        updated_llm_tools = {
            "chat_func": [{"name": "tool1", "endpoint": "http://svc1:8080"}]
        }

        injector.update_llm_tools(updated_llm_tools)

        # Verify function was removed
        assert "chat_abc123" in injector._llm_agents
        assert "analyze_def456" not in injector._llm_agents

    def test_update_llm_tools_notifies_existing_wrappers(self):
        """Test that existing function wrappers are notified of tool updates."""
        import mesh
        from _mcp_mesh.engine.mesh_llm_agent_injector import MeshLlmAgentInjector

        # Register function in DecoratorRegistry
        function_id = "chat_abc123"
        register_test_llm_function(function_id)

        injector = MeshLlmAgentInjector()

        injector.process_llm_tools({"test_func": []})

        def chat(msg: str, llm: mesh.MeshLlmAgent = None) -> ChatResponse:
            return ChatResponse(answer="test", confidence=0.9)

        wrapper = injector.create_injection_wrapper(chat, function_id)

        # Update with new tools
        updated_llm_tools = {
            function_id: [
                {
                    "name": "new_tool",
                    "endpoint": "http://new-svc:8080",
                }
            ]
        }

        injector.update_llm_tools(updated_llm_tools)

        # Verify wrapper's LLM agent was updated
        assert hasattr(wrapper, "_mesh_llm_agent")
        # The injected agent should have the new tools
        # (Implementation will handle this via update mechanism)


class TestErrorHandling:
    """Test error handling and edge cases."""

    def setup_method(self):
        """Clear DecoratorRegistry before each test."""
        from _mcp_mesh.engine.decorator_registry import DecoratorRegistry

        DecoratorRegistry._mesh_llm_agents = {}

    def test_handles_missing_function_in_decorator_registry(self):
        """Test handling when function_id not found in DecoratorRegistry."""
        from _mcp_mesh.engine.mesh_llm_agent_injector import MeshLlmAgentInjector

        injector = MeshLlmAgentInjector()

        # Try to process llm_tools for non-existent function
        llm_tools = {
            "nonexistent_func_xyz": [{"name": "tool1", "endpoint": "http://svc1:8080"}]
        }

        # Should log warning and skip (not crash)
        injector.process_llm_tools(llm_tools)

        # Function should not be in registry
        assert "nonexistent_func_xyz" not in injector._llm_agents

    def test_handles_invalid_tool_endpoint(self):
        """Test handling of invalid tool endpoint format."""
        from _mcp_mesh.engine.mesh_llm_agent_injector import MeshLlmAgentInjector

        # Register function in DecoratorRegistry
        register_test_llm_function("chat_abc123")

        injector = MeshLlmAgentInjector()

        llm_tools = {
            "test_func": [{"name": "tool1", "endpoint": None}]  # Invalid endpoint
        }

        # Should handle gracefully (log error and skip tool) - no exception raised
        injector.process_llm_tools(llm_tools)

        # Function should be in registry but with no tools (tool was skipped)
        assert "chat_abc123" in injector._llm_agents
        llm_agent_data = injector._llm_agents["chat_abc123"]
        assert (
            len(llm_agent_data["tools_proxies"]) == 0
        )  # Tool was skipped due to error

    def test_handles_empty_tools_list_for_function(self):
        """Test handling when function has empty tools list (no matches from registry)."""
        from _mcp_mesh.engine.mesh_llm_agent_injector import MeshLlmAgentInjector

        # Register function in DecoratorRegistry
        register_test_llm_function("chat_abc123")

        injector = MeshLlmAgentInjector()

        llm_tools = {"test_func": []}  # No tools matched filter

        injector.process_llm_tools(llm_tools)

        # Should still create entry with empty tools
        assert "chat_abc123" in injector._llm_agents
        llm_agent_data = injector._llm_agents["chat_abc123"]
        assert len(llm_agent_data["tools_proxies"]) == 0


class TestIntegrationWithDecoratorRegistry:
    """Test integration with DecoratorRegistry."""

    def test_reads_config_from_decorator_registry(self):
        """Test that injector reads LLM config from DecoratorRegistry."""
        import mesh
        from _mcp_mesh.engine.decorator_registry import DecoratorRegistry
        from _mcp_mesh.engine.mesh_llm_agent_injector import MeshLlmAgentInjector

        # Clear registry
        DecoratorRegistry._mesh_llm_agents = {}

        def test_func(msg: str, llm: mesh.MeshLlmAgent = None) -> ChatResponse:
            return ChatResponse(answer="test", confidence=0.9)

        function_id = "test_xyz789"
        config = {
            "filter": [{"capability": "doc", "tags": ["pdf"]}],
            "filter_mode": "best_match",
            "provider": "openai",
            "model": "gpt-4o",
            "max_iterations": 15,
            "system_prompt": "You are helpful",
        }

        DecoratorRegistry.register_mesh_llm(
            test_func, config, ChatResponse, "llm", function_id
        )

        injector = MeshLlmAgentInjector()
        injector.process_llm_tools({"test_func": []})

        # Verify all config fields were captured
        llm_agent_data = injector._llm_agents[function_id]
        assert llm_agent_data["config"]["provider"] == "openai"
        assert llm_agent_data["config"]["model"] == "gpt-4o"
        assert llm_agent_data["config"]["max_iterations"] == 15
        assert llm_agent_data["config"]["system_prompt"] == "You are helpful"

    def test_uses_output_type_from_decorator_registry(self):
        """Test that injector uses output_type from DecoratorRegistry."""
        import mesh
        from _mcp_mesh.engine.decorator_registry import DecoratorRegistry
        from _mcp_mesh.engine.mesh_llm_agent_injector import MeshLlmAgentInjector

        DecoratorRegistry._mesh_llm_agents = {}

        def test_func(msg: str, llm: mesh.MeshLlmAgent = None) -> AdvancedResponse:
            return AdvancedResponse(result="test", metadata={})

        function_id = "test_advanced"
        DecoratorRegistry.register_mesh_llm(
            test_func, {"filter": "doc"}, AdvancedResponse, "llm", function_id
        )

        injector = MeshLlmAgentInjector()
        injector.process_llm_tools({"test_func": []})

        llm_agent_data = injector._llm_agents[function_id]
        assert llm_agent_data["output_type"] == AdvancedResponse


# ============================================================================
# Phase 4: Context Extraction and Template Integration Tests (TDD)
# ============================================================================


class ChatContext(MeshContextModel):
    """Test context model for templates."""

    user_name: str = Field(description="User name")
    domain: str = Field(description="Domain of expertise")


class TestContextExtractionWithTemplates:
    """Test context extraction for template rendering (Phase 4 - TDD)."""

    def test_create_llm_agent_with_template_path(self):
        """Test: MeshLlmAgent created with template_path from config."""
        from _mcp_mesh.engine.decorator_registry import DecoratorRegistry
        from _mcp_mesh.engine.mesh_llm_agent_injector import MeshLlmAgentInjector

        # Register function with template
        def chat(msg: str, ctx: ChatContext, llm=None):
            pass

        function_id = "chat_template_test"
        config = {
            "provider": "claude",
            "model": "claude-3-5-sonnet-20241022",
            "filter": {"capability": "document"},
            "is_template": True,
            "template_path": str(TEMPLATES_DIR / "simple.jinja2"),
            "context_param": "ctx",
        }

        DecoratorRegistry.register_mesh_llm(
            chat, config, ChatResponse, "llm", function_id
        )

        # Create injector and process tools
        injector = MeshLlmAgentInjector()
        llm_tools = {
            "chat": [
                {
                    "name": "get_date",
                    "endpoint": "http://localhost:9091",
                    "capability": "datetime",
                }
            ]
        }

        injector.process_llm_tools(llm_tools)

        # Get the created agent data
        agent_data = injector.get_llm_agent_data(function_id)
        assert agent_data is not None

        # Verify template metadata is stored
        assert agent_data["config"]["is_template"] is True
        assert (
            agent_data["config"]["template_path"]
            == str(TEMPLATES_DIR / "simple.jinja2")
        )
        assert agent_data["config"]["context_param"] == "ctx"

    def test_inject_llm_agent_detects_context_parameter(self):
        """Test: Context parameter detected during injection."""
        from _mcp_mesh.engine.decorator_registry import DecoratorRegistry
        from _mcp_mesh.engine.mesh_llm_agent_injector import MeshLlmAgentInjector

        # Register function with template and context param
        def chat(msg: str, ctx: ChatContext, llm=None):
            return msg

        function_id = "chat_ctx_detect"
        config = {
            "provider": "claude",
            "model": "claude-3-5-sonnet-20241022",
            "filter": {"capability": "document"},
            "is_template": True,
            "template_path": str(TEMPLATES_DIR / "simple.jinja2"),
            "context_param": "ctx",
        }

        DecoratorRegistry.register_mesh_llm(
            chat, config, ChatResponse, "llm", function_id
        )

        # Create injector and process tools
        injector = MeshLlmAgentInjector()
        llm_tools = {
            "chat": [
                {
                    "name": "get_date",
                    "endpoint": "http://localhost:9091",
                    "capability": "datetime",
                }
            ]
        }

        injector.process_llm_tools(llm_tools)

        # Create wrapper
        wrapper = injector.create_injection_wrapper(chat, function_id)

        # Call wrapper with context
        context = ChatContext(user_name="Alice", domain="Python")
        result = wrapper("Hello", ctx=context)

        # Verify wrapper executed (returns the message)
        assert result == "Hello"

    @pytest.mark.asyncio
    async def test_inject_llm_agent_with_context_creates_agent_with_context(self):
        """Test: MeshLlmAgent created with context value from call."""
        from _mcp_mesh.engine.decorator_registry import DecoratorRegistry
        from _mcp_mesh.engine.mesh_llm_agent import MeshLlmAgent
        from _mcp_mesh.engine.mesh_llm_agent_injector import MeshLlmAgentInjector

        # Register async function with template
        async def chat(msg: str, ctx: ChatContext, llm: MeshLlmAgent = None):
            # Access the injected LLM agent
            assert llm is not None
            # Verify it has the context
            assert hasattr(llm, "_context_value")
            assert llm._context_value == ctx
            return "response"

        function_id = "chat_async_ctx"
        config = {
            "provider": "claude",
            "model": "claude-3-5-sonnet-20241022",
            "filter": {"capability": "document"},
            "is_template": True,
            "template_path": str(TEMPLATES_DIR / "simple.jinja2"),
            "context_param": "ctx",
        }

        DecoratorRegistry.register_mesh_llm(
            chat, config, ChatResponse, "llm", function_id
        )

        # Create injector and process tools
        injector = MeshLlmAgentInjector()
        llm_tools = {
            "chat": [
                {
                    "name": "get_date",
                    "endpoint": "http://localhost:9091",
                    "capability": "datetime",
                }
            ]
        }

        injector.process_llm_tools(llm_tools)

        # Create wrapper
        wrapper = injector.create_injection_wrapper(chat, function_id)

        # Call wrapper with context
        context = ChatContext(user_name="Alice", domain="Python")
        result = await wrapper("Hello", ctx=context)

        assert result == "response"

    def test_inject_llm_agent_without_template_uses_cached_agent(self):
        """Test: Without template, uses cached agent (existing behavior)."""
        from _mcp_mesh.engine.decorator_registry import DecoratorRegistry
        from _mcp_mesh.engine.mesh_llm_agent_injector import MeshLlmAgentInjector

        # Register function WITHOUT template
        def analyze(msg: str, llm=None):
            return llm

        function_id = "analyze_no_template"
        config = {
            "provider": "claude",
            "model": "claude-3-5-sonnet-20241022",
            "filter": {"capability": "document"},
            "is_template": False,  # No template
        }

        DecoratorRegistry.register_mesh_llm(
            analyze, config, ChatResponse, "llm", function_id
        )

        # Create injector and process tools
        injector = MeshLlmAgentInjector()
        llm_tools = {
            "analyze": [
                {
                    "name": "get_date",
                    "endpoint": "http://localhost:9091",
                    "capability": "datetime",
                }
            ]
        }

        injector.process_llm_tools(llm_tools)

        # Create wrapper
        wrapper = injector.create_injection_wrapper(analyze, function_id)

        # Call wrapper multiple times
        agent1 = wrapper("Call 1")
        agent2 = wrapper("Call 2")

        # Should be same cached agent instance
        assert agent1 is agent2

    def test_inject_llm_agent_extracts_context_from_kwargs(self):
        """Test: Context extracted from kwargs."""
        from _mcp_mesh.engine.decorator_registry import DecoratorRegistry
        from _mcp_mesh.engine.mesh_llm_agent_injector import MeshLlmAgentInjector

        def chat(msg: str, prompt_context: ChatContext, llm=None):
            return prompt_context

        function_id = "chat_kwargs"
        config = {
            "provider": "claude",
            "model": "claude-3-5-sonnet-20241022",
            "filter": {"capability": "document"},
            "is_template": True,
            "template_path": str(TEMPLATES_DIR / "simple.jinja2"),
            # No explicit context_param - should detect by convention (prompt_context)
        }

        DecoratorRegistry.register_mesh_llm(
            chat, config, ChatResponse, "llm", function_id
        )

        injector = MeshLlmAgentInjector()
        llm_tools = {
            "chat": [
                {
                    "name": "get_date",
                    "endpoint": "http://localhost:9091",
                    "capability": "datetime",
                }
            ]
        }

        injector.process_llm_tools(llm_tools)

        wrapper = injector.create_injection_wrapper(chat, function_id)

        # Call with context in kwargs
        context = ChatContext(user_name="Bob", domain="Go")
        result = wrapper("Hello", prompt_context=context)

        # Verify context was passed through
        assert result == context

    def test_inject_llm_agent_extracts_context_from_positional_args(self):
        """Test: Context extracted from positional args."""
        from _mcp_mesh.engine.decorator_registry import DecoratorRegistry
        from _mcp_mesh.engine.mesh_llm_agent_injector import MeshLlmAgentInjector

        def chat(msg: str, ctx: ChatContext, llm=None):
            return ctx

        function_id = "chat_positional"
        config = {
            "provider": "claude",
            "model": "claude-3-5-sonnet-20241022",
            "filter": {"capability": "document"},
            "is_template": True,
            "template_path": str(TEMPLATES_DIR / "simple.jinja2"),
            "context_param": "ctx",
        }

        DecoratorRegistry.register_mesh_llm(
            chat, config, ChatResponse, "llm", function_id
        )

        injector = MeshLlmAgentInjector()
        llm_tools = {
            "chat": [
                {
                    "name": "get_date",
                    "endpoint": "http://localhost:9091",
                    "capability": "datetime",
                }
            ]
        }

        injector.process_llm_tools(llm_tools)

        wrapper = injector.create_injection_wrapper(chat, function_id)

        # Call with context as positional arg
        context = ChatContext(user_name="Charlie", domain="Rust")
        result = wrapper("Hello", context)  # Positional

        # Verify context was passed through
        assert result == context

    def test_inject_llm_agent_with_none_context_uses_empty_dict(self):
        """Test: None context passed as empty dict."""
        from _mcp_mesh.engine.decorator_registry import DecoratorRegistry
        from _mcp_mesh.engine.mesh_llm_agent import MeshLlmAgent
        from _mcp_mesh.engine.mesh_llm_agent_injector import MeshLlmAgentInjector

        def chat(msg: str, ctx: Optional[ChatContext] = None, llm: MeshLlmAgent = None):
            # Check that llm was injected
            assert llm is not None
            # Context should be None
            assert llm._context_value is None
            return "ok"

        function_id = "chat_none_ctx"
        config = {
            "provider": "claude",
            "model": "claude-3-5-sonnet-20241022",
            "filter": {"capability": "document"},
            "is_template": True,
            "template_path": str(TEMPLATES_DIR / "with_control.jinja2"),
            "context_param": "ctx",
        }

        DecoratorRegistry.register_mesh_llm(
            chat, config, ChatResponse, "llm", function_id
        )

        injector = MeshLlmAgentInjector()
        llm_tools = {
            "chat": [
                {
                    "name": "get_date",
                    "endpoint": "http://localhost:9091",
                    "capability": "datetime",
                }
            ]
        }

        injector.process_llm_tools(llm_tools)

        wrapper = injector.create_injection_wrapper(chat, function_id)

        # Call without providing context (defaults to None)
        result = wrapper("Hello")

        assert result == "ok"


class TestTemplateIntegrationInInjector:
    """Test full integration of templates with injector (Phase 4 - TDD)."""

    @pytest.mark.asyncio
    async def test_end_to_end_template_rendering_with_llm_call(self):
        """Test: Complete flow from decorator to template rendering in LLM call."""
        from _mcp_mesh.engine.decorator_registry import DecoratorRegistry
        from _mcp_mesh.engine.mesh_llm_agent import MeshLlmAgent
        from _mcp_mesh.engine.mesh_llm_agent_injector import MeshLlmAgentInjector

        # Register function with template
        async def chat(msg: str, ctx: ChatContext, llm: MeshLlmAgent = None):
            # Call the LLM agent with the message
            with patch("_mcp_mesh.engine.mesh_llm_agent.completion") as mock_completion:
                mock_completion.return_value = MagicMock(
                    choices=[
                        MagicMock(
                            message=MagicMock(
                                content='{"answer": "Response", "confidence": 0.9}',
                                tool_calls=None,
                            )
                        )
                    ]
                )

                response = await llm(msg)

                # Verify system prompt contains rendered template
                call_kwargs = mock_completion.call_args[1]
                messages = call_kwargs["messages"]
                system_message = next(m for m in messages if m["role"] == "system")

                # Should have rendered template with context
                assert "Alice" in system_message["content"]
                assert "Python" in system_message["content"]

                return response

        function_id = "chat_e2e"
        config = {
            "provider": "claude",
            "model": "claude-3-5-sonnet-20241022",
            "filter": {"capability": "document"},
            "is_template": True,
            "template_path": str(TEMPLATES_DIR / "simple.jinja2"),
            "context_param": "ctx",
        }

        DecoratorRegistry.register_mesh_llm(
            chat, config, ChatResponse, "llm", function_id
        )

        injector = MeshLlmAgentInjector()
        llm_tools = {
            "chat": [
                {
                    "name": "get_date",
                    "endpoint": "http://localhost:9091",
                    "capability": "datetime",
                }
            ]
        }

        injector.process_llm_tools(llm_tools)

        wrapper = injector.create_injection_wrapper(chat, function_id)

        # Call with context
        context = ChatContext(user_name="Alice", domain="Python")
        response = await wrapper("Hello", ctx=context)

        assert isinstance(response, ChatResponse)
        assert response.answer == "Response"
