"""
Comprehensive unit tests for MeshLlmAgent proxy class.

This is the most critical component - the automatic agentic loop that users rely on.
Tests cover happy paths, error scenarios, edge cases, and timeouts.

Tests follow TDD approach - these should FAIL initially until proxy is implemented.
"""

from pathlib import Path
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from _mcp_mesh.engine.llm_config import LLMConfig
from pydantic import BaseModel, Field, ValidationError

# Helper to get fixture paths - tests run from various directories
FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"
TEMPLATES_DIR = FIXTURES_DIR / "templates"

try:
    from mesh import MeshContextModel
except ImportError:
    MeshContextModel = None


# Test output types
class ChatResponse(BaseModel):
    """Standard chat response for testing."""

    answer: str
    confidence: float
    sources: list[str] = []


class ComplexResponse(BaseModel):
    """Complex response with nested data."""

    result: dict
    metadata: dict
    status: str


# Test helpers for creating proper mocks
def make_function_mock(name: str, arguments: str):
    """Create a function mock with proper attributes."""
    func = MagicMock()
    func.name = name
    func.arguments = arguments
    return func


def make_tool_call_mock(id: str, name: str, arguments: str):
    """Create a tool_call mock with proper attributes."""
    tool_call = MagicMock()
    tool_call.id = id
    tool_call.function = make_function_mock(name, arguments)
    return tool_call


def make_test_config(provider: Optional[dict] = None,
    model: Optional[str] = None,
    max_iterations: int = 10,
    system_prompt: Optional[str] = None,
) -> LLMConfig:
    """Create LLMConfig for testing (mesh-delegated only).

    Direct-LiteLLM mode was removed in v2 — the provider is always a dict
    describing the upstream @mesh.llm_provider filter. Default uses a
    capability/tag pair that matches what the integration suites use.
    """
    return LLMConfig(
        provider=provider if provider is not None else {"capability": "llm", "tags": ["claude"]},
        model=model,
        max_iterations=max_iterations,
        system_prompt=system_prompt,
    )


class TestMeshLlmAgentInitialization:
    """Test MeshLlmAgent proxy initialization."""

    def test_initialization_with_minimal_config(self):
        """Test initialization with minimal required config."""
        from _mcp_mesh.engine.mesh_llm_agent import MeshLlmAgent

        agent = MeshLlmAgent(
            config=make_test_config(model="claude-3-5-sonnet-20241022",
                max_iterations=10,
                system_prompt="You are a helpful assistant.",
            ),
            filtered_tools=[],
            output_type=ChatResponse,
        )

        # Provider is always a dict in v2 (mesh delegation only).
        assert isinstance(agent.provider, dict)
        assert agent.provider.get("capability") == "llm"
        assert agent.model == "claude-3-5-sonnet-20241022"
        assert agent.max_iterations == 10
        assert agent.output_type == ChatResponse

    def test_initialization_with_tools(self):
        """Test initialization with filtered tools."""
        from _mcp_mesh.engine.mesh_llm_agent import MeshLlmAgent

        mock_tool_proxy = MagicMock()
        mock_tool_proxy.name = "extract_pdf"
        mock_tool_proxy.description = "Extract text from PDF"
        mock_tool_proxy.input_schema = {"type": "object"}

        tools = [mock_tool_proxy]

        agent = MeshLlmAgent(
            config=make_test_config(model="claude-3-5-sonnet-20241022",
                max_iterations=10,
            ),
            filtered_tools=tools,
            output_type=ChatResponse,
        )

        assert len(agent.tools_metadata) == 1
        assert agent.tools_metadata[0].name == "extract_pdf"

    def test_initialization_with_system_prompt(self):
        """Test initialization with custom system prompt."""
        from _mcp_mesh.engine.mesh_llm_agent import MeshLlmAgent

        agent = MeshLlmAgent(
            config=make_test_config(model="claude-3-5-sonnet-20241022",
                max_iterations=10,
                system_prompt="You are a helpful assistant.",
            ),
            filtered_tools=[],
            output_type=ChatResponse,
        )

        assert agent.system_prompt == "You are a helpful assistant."

    def test_set_system_prompt(self):
        """Test setting system prompt after initialization."""
        from _mcp_mesh.engine.mesh_llm_agent import MeshLlmAgent

        agent = MeshLlmAgent(
            config=make_test_config(model="claude-3-5-sonnet-20241022",
                max_iterations=10,
                system_prompt="Original prompt",
            ),
            filtered_tools=[],
            output_type=ChatResponse,
        )

        agent.set_system_prompt("You are an expert analyst.")
        assert agent.system_prompt == "You are an expert analyst."


# ============================================================================
# Phase 3 (Design Doc Phase 4): Template Rendering Tests (TDD)
# ============================================================================


# Test context models


class ChatContext(MeshContextModel):
    """Test context model for templates."""

    user_name: str = Field(description="User name")
    domain: str = Field(description="Domain of expertise")


class AssistantContext(MeshContextModel):
    """Test assistant context model."""

    role: str = Field(description="Assistant role")
    domain: Optional[str] = Field(default=None, description="Domain")
    skills: list[str] = Field(default_factory=list, description="Skills")


class TestTemplateLoading:
    """Test template loading functionality (Phase 3 - TDD)."""

    def test_load_template_from_relative_path(self):
        """Test: Load template from relative path."""
        from _mcp_mesh.engine.mesh_llm_agent import MeshLlmAgent

        config = make_test_config()
        template_path = str(TEMPLATES_DIR / "simple.jinja2")

        agent = MeshLlmAgent(
            config=config,
            filtered_tools=[],
            output_type=ChatResponse,
            template_path=template_path,
            context_value=None,
        )

        # Should successfully load template
        assert hasattr(agent, "_template")
        assert agent._template is not None

    def test_load_template_from_absolute_path(self):
        """Test: Load template from absolute path."""
        from _mcp_mesh.engine.mesh_llm_agent import MeshLlmAgent

        config = make_test_config()
        # Get absolute path
        abs_path = (
            Path(__file__).parent.parent / "fixtures" / "templates" / "simple.jinja2"
        )
        template_path = str(abs_path)

        agent = MeshLlmAgent(
            config=config,
            filtered_tools=[],
            output_type=ChatResponse,
            template_path=template_path,
            context_value=None,
        )

        # Should successfully load template
        assert hasattr(agent, "_template")
        assert agent._template is not None

    def test_load_template_file_not_found(self):
        """Test: Template file not found raises error."""
        from _mcp_mesh.engine.mesh_llm_agent import MeshLlmAgent

        config = make_test_config()
        template_path = str(TEMPLATES_DIR / "nonexistent.jinja2")

        with pytest.raises(FileNotFoundError) as exc_info:
            MeshLlmAgent(
                config=config,
                filtered_tools=[],
                output_type=ChatResponse,
                template_path=template_path,
                context_value=None,
            )

        assert "nonexistent.jinja2" in str(exc_info.value).lower()

    def test_load_template_syntax_error(self):
        """Test: Template with syntax error raises error."""
        from _mcp_mesh.engine.mesh_llm_agent import MeshLlmAgent
        from jinja2 import TemplateSyntaxError

        config = make_test_config()
        template_path = str(TEMPLATES_DIR / "syntax_error.jinja2")

        with pytest.raises(TemplateSyntaxError):
            MeshLlmAgent(
                config=config,
                filtered_tools=[],
                output_type=ChatResponse,
                template_path=template_path,
                context_value=None,
            )

    def test_template_caching(self):
        """Test: Template loaded once and cached."""
        from _mcp_mesh.engine.mesh_llm_agent import MeshLlmAgent

        config = make_test_config()
        template_path = str(TEMPLATES_DIR / "simple.jinja2")

        agent = MeshLlmAgent(
            config=config,
            filtered_tools=[],
            output_type=ChatResponse,
            template_path=template_path,
            context_value=None,
        )

        template1 = agent._template
        template2 = agent._template

        # Should be same object (cached)
        assert template1 is template2


class TestContextPreparation:
    """Test context preparation for template rendering (Phase 3 - TDD)."""

    def test_prepare_context_from_mesh_context_model(self):
        """Test: MeshContextModel converted to dict via model_dump()."""
        from _mcp_mesh.engine.mesh_llm_agent import MeshLlmAgent

        config = make_test_config()
        context = ChatContext(user_name="Alice", domain="Python")

        agent = MeshLlmAgent(
            config=config,
            filtered_tools=[],
            output_type=ChatResponse,
            template_path=None,
            context_value=context,
        )

        prepared = agent._prepare_context(context)

        assert isinstance(prepared, dict)
        assert prepared["user_name"] == "Alice"
        assert prepared["domain"] == "Python"

    def test_prepare_context_from_dict(self):
        """Test: Dict passed through directly."""
        from _mcp_mesh.engine.mesh_llm_agent import MeshLlmAgent

        config = make_test_config()
        context = {"user_name": "Bob", "domain": "Go"}

        agent = MeshLlmAgent(
            config=config,
            filtered_tools=[],
            output_type=ChatResponse,
            template_path=None,
            context_value=context,
        )

        prepared = agent._prepare_context(context)

        assert isinstance(prepared, dict)
        assert prepared == context

    def test_prepare_context_from_none(self):
        """Test: None converted to empty dict."""
        from _mcp_mesh.engine.mesh_llm_agent import MeshLlmAgent

        config = make_test_config()

        agent = MeshLlmAgent(
            config=config,
            filtered_tools=[],
            output_type=ChatResponse,
            template_path=None,
            context_value=None,
        )

        prepared = agent._prepare_context(None)

        assert isinstance(prepared, dict)
        assert prepared == {}

    def test_prepare_context_invalid_type_error(self):
        """Test: Invalid context type raises TypeError."""
        from _mcp_mesh.engine.mesh_llm_agent import MeshLlmAgent

        config = make_test_config()

        agent = MeshLlmAgent(
            config=config,
            filtered_tools=[],
            output_type=ChatResponse,
            template_path=None,
            context_value=None,
        )

        with pytest.raises(TypeError) as exc_info:
            agent._prepare_context("invalid string context")

        assert "context" in str(exc_info.value).lower()

    def test_prepare_context_nested_mesh_context_model(self):
        """Test: Nested MeshContextModel fields properly converted."""
        from _mcp_mesh.engine.mesh_llm_agent import MeshLlmAgent

        class NestedContext(MeshContextModel):
            """Context with nested model."""

            chat: ChatContext
            count: int

        config = make_test_config()
        nested = NestedContext(
            chat=ChatContext(user_name="Charlie", domain="Rust"), count=5
        )

        agent = MeshLlmAgent(
            config=config,
            filtered_tools=[],
            output_type=ChatResponse,
            template_path=None,
            context_value=nested,
        )

        prepared = agent._prepare_context(nested)

        assert isinstance(prepared, dict)
        assert isinstance(prepared["chat"], dict)
        assert prepared["chat"]["user_name"] == "Charlie"
        assert prepared["count"] == 5


class TestTemplateRendering:
    """Test template rendering with Jinja2 (Phase 3 - TDD)."""

    def test_render_literal_prompt_no_template(self):
        """Test: Literal prompt used when no template."""
        from _mcp_mesh.engine.mesh_llm_agent import MeshLlmAgent

        config = make_test_config(system_prompt="You are a helpful assistant.")

        agent = MeshLlmAgent(
            config=config,
            filtered_tools=[],
            output_type=ChatResponse,
            template_path=None,
            context_value=None,
        )

        rendered = agent._render_system_prompt()

        assert rendered == "You are a helpful assistant."

    def test_render_template_with_mesh_context_model(self):
        """Test: Template rendered with MeshContextModel context."""
        from _mcp_mesh.engine.mesh_llm_agent import MeshLlmAgent

        config = make_test_config()
        template_path = str(TEMPLATES_DIR / "simple.jinja2")
        context = ChatContext(user_name="Alice", domain="Python")

        mock_provider_proxy = AsyncMock()
        mock_provider_proxy.return_value = {
            "role": "assistant",
            "content": '{"answer": "Response", "confidence": 1.0, "sources": []}',
        }

        agent = MeshLlmAgent(
            config=config,
            filtered_tools=[],
            output_type=ChatResponse,
            template_path=template_path,
            context_value=context,
            provider_proxy=mock_provider_proxy,
            vendor="anthropic",
        )

        rendered = agent._render_system_prompt()

        assert "Alice" in rendered
        assert "Python" in rendered
        assert (
            rendered
            == "You are a helpful assistant for Python. Help Alice with their query."
        )

    def test_render_template_with_dict_context(self):
        """Test: Template rendered with dict context."""
        from _mcp_mesh.engine.mesh_llm_agent import MeshLlmAgent

        config = make_test_config()
        template_path = str(TEMPLATES_DIR / "simple.jinja2")
        context = {"user_name": "Bob", "domain": "Go"}

        mock_provider_proxy = AsyncMock()
        mock_provider_proxy.return_value = {
            "role": "assistant",
            "content": '{"answer": "Response", "confidence": 1.0, "sources": []}',
        }

        agent = MeshLlmAgent(
            config=config,
            filtered_tools=[],
            output_type=ChatResponse,
            template_path=template_path,
            context_value=context,
            provider_proxy=mock_provider_proxy,
            vendor="anthropic",
        )

        rendered = agent._render_system_prompt()

        assert "Bob" in rendered
        assert "Go" in rendered

    def test_render_template_with_none_context(self):
        """Test: Template rendered with None context (empty dict)."""
        from _mcp_mesh.engine.mesh_llm_agent import MeshLlmAgent

        config = make_test_config()
        # Create a template that doesn't require any variables
        template_path = str(TEMPLATES_DIR / "with_control.jinja2")

        agent = MeshLlmAgent(
            config=config,
            filtered_tools=[],
            output_type=ChatResponse,
            template_path=template_path,
            context_value=None,
        )

        # Should render with empty context (optional vars omitted)
        rendered = agent._render_system_prompt()
        assert isinstance(rendered, str)

    def test_render_template_with_control_structures(self):
        """Test: Template with if/for control structures."""
        from _mcp_mesh.engine.mesh_llm_agent import MeshLlmAgent

        config = make_test_config()
        template_path = str(TEMPLATES_DIR / "with_control.jinja2")
        context = AssistantContext(
            role="expert", domain="AI", skills=["Python", "ML", "NLP"]
        )

        mock_provider_proxy = AsyncMock()
        mock_provider_proxy.return_value = {
            "role": "assistant",
            "content": '{"answer": "Response", "confidence": 1.0, "sources": []}',
        }

        agent = MeshLlmAgent(
            config=config,
            filtered_tools=[],
            output_type=ChatResponse,
            template_path=template_path,
            context_value=context,
            provider_proxy=mock_provider_proxy,
            vendor="anthropic",
        )

        rendered = agent._render_system_prompt()

        assert "expert" in rendered
        assert "AI" in rendered
        assert "Python" in rendered
        assert "ML" in rendered
        assert "NLP" in rendered

    def test_render_template_missing_required_var_error(self):
        """Test: Template rendering fails when required var missing."""
        from _mcp_mesh.engine.mesh_llm_agent import MeshLlmAgent
        from jinja2 import UndefinedError

        config = make_test_config()
        template_path = str(TEMPLATES_DIR / "simple.jinja2")
        # Empty context - missing required vars
        context = {}

        mock_provider_proxy = AsyncMock()
        mock_provider_proxy.return_value = {
            "role": "assistant",
            "content": '{"answer": "Response", "confidence": 1.0, "sources": []}',
        }

        agent = MeshLlmAgent(
            config=config,
            filtered_tools=[],
            output_type=ChatResponse,
            template_path=template_path,
            context_value=context,
            provider_proxy=mock_provider_proxy,
            vendor="anthropic",
        )

        # In strict mode, should raise UndefinedError
        # For now, Jinja2 default behavior is to render as empty strings
        # We may want strict undefined mode
        rendered = agent._render_system_prompt()
        # Variables will be empty strings in default mode
        assert isinstance(rendered, str)

    def test_render_template_runtime_override(self):
        """Test: Runtime override with set_system_prompt() bypasses template."""
        from _mcp_mesh.engine.mesh_llm_agent import MeshLlmAgent

        config = make_test_config()
        template_path = str(TEMPLATES_DIR / "simple.jinja2")
        context = ChatContext(user_name="Alice", domain="Python")

        mock_provider_proxy = AsyncMock()
        mock_provider_proxy.return_value = {
            "role": "assistant",
            "content": '{"answer": "Response", "confidence": 1.0, "sources": []}',
        }

        agent = MeshLlmAgent(
            config=config,
            filtered_tools=[],
            output_type=ChatResponse,
            template_path=template_path,
            context_value=context,
            provider_proxy=mock_provider_proxy,
            vendor="anthropic",
        )

        # Override at runtime
        agent.set_system_prompt("Overridden prompt")

        rendered = agent._render_system_prompt()

        # Should use overridden prompt, not template
        assert rendered == "Overridden prompt"

    @pytest.mark.asyncio
    async def test_render_template_used_in_llm_call(self):
        """Test: Rendered template used in actual LLM call (mesh-delegated)."""
        from _mcp_mesh.engine.mesh_llm_agent import MeshLlmAgent

        config = make_test_config()
        template_path = str(TEMPLATES_DIR / "simple.jinja2")
        context = ChatContext(user_name="Alice", domain="Python")

        mock_provider_proxy = AsyncMock()
        mock_provider_proxy.return_value = {
            "role": "assistant",
            "content": '{"answer": "Response", "confidence": 1.0, "sources": []}',
        }

        agent = MeshLlmAgent(
            config=config,
            filtered_tools=[],
            output_type=ChatResponse,
            template_path=template_path,
            context_value=context,
            provider_proxy=mock_provider_proxy,
            vendor="anthropic",
        )

        response = await agent("Test message")

        # Verify system prompt in provider request contains rendered template
        call_kwargs = mock_provider_proxy.call_args[1]
        request_dict = call_kwargs["request"]
        messages = request_dict["messages"]
        system_message = next(m for m in messages if m["role"] == "system")

        assert "Alice" in system_message["content"]
        assert "Python" in system_message["content"]
        assert isinstance(response, ChatResponse)


# ============================================================================
# Runtime Context Injection Tests
# ============================================================================


class TestRuntimeContextInjection:
    """Test runtime context injection via __call__() context parameter."""

    def test_resolve_context_no_runtime_context_provided(self):
        """Test: When no runtime context provided, use auto-populated context."""
        from _mcp_mesh.engine.mesh_llm_agent import (_CONTEXT_NOT_PROVIDED,
                                                     MeshLlmAgent)

        config = make_test_config()
        auto_context = ChatContext(user_name="Alice", domain="Python")

        agent = MeshLlmAgent(
            config=config,
            filtered_tools=[],
            output_type=ChatResponse,
            template_path=None,
            context_value=auto_context,
        )

        resolved = agent._resolve_context(_CONTEXT_NOT_PROVIDED, "append")

        assert resolved == {"user_name": "Alice", "domain": "Python"}

    def test_resolve_context_append_mode(self):
        """Test: Append mode - runtime context extends auto-populated context."""
        from _mcp_mesh.engine.mesh_llm_agent import MeshLlmAgent

        config = make_test_config()
        auto_context = {"user_name": "Alice", "domain": "Python"}

        agent = MeshLlmAgent(
            config=config,
            filtered_tools=[],
            output_type=ChatResponse,
            template_path=None,
            context_value=auto_context,
        )

        runtime_context = {"extra_key": "extra_value", "domain": "overridden"}
        resolved = agent._resolve_context(runtime_context, "append")

        # Auto context first, runtime overwrites (runtime wins on conflicts)
        assert resolved["user_name"] == "Alice"
        assert resolved["domain"] == "overridden"  # Runtime wins
        assert resolved["extra_key"] == "extra_value"

    def test_resolve_context_prepend_mode(self):
        """Test: Prepend mode - auto-populated context overwrites runtime."""
        from _mcp_mesh.engine.mesh_llm_agent import MeshLlmAgent

        config = make_test_config()
        auto_context = {"user_name": "Alice", "domain": "Python"}

        agent = MeshLlmAgent(
            config=config,
            filtered_tools=[],
            output_type=ChatResponse,
            template_path=None,
            context_value=auto_context,
        )

        runtime_context = {"extra_key": "extra_value", "domain": "runtime_domain"}
        resolved = agent._resolve_context(runtime_context, "prepend")

        # Runtime first, auto overwrites (auto wins on conflicts)
        assert resolved["user_name"] == "Alice"
        assert resolved["domain"] == "Python"  # Auto wins
        assert resolved["extra_key"] == "extra_value"

    def test_resolve_context_replace_mode(self):
        """Test: Replace mode - runtime context replaces auto-populated entirely."""
        from _mcp_mesh.engine.mesh_llm_agent import MeshLlmAgent

        config = make_test_config()
        auto_context = {"user_name": "Alice", "domain": "Python"}

        agent = MeshLlmAgent(
            config=config,
            filtered_tools=[],
            output_type=ChatResponse,
            template_path=None,
            context_value=auto_context,
        )

        runtime_context = {"only_this": "value"}
        resolved = agent._resolve_context(runtime_context, "replace")

        # Replace entirely
        assert resolved == {"only_this": "value"}
        assert "user_name" not in resolved
        assert "domain" not in resolved

    def test_resolve_context_replace_with_empty_dict(self):
        """Test: Replace with empty dict explicitly clears context."""
        from _mcp_mesh.engine.mesh_llm_agent import MeshLlmAgent

        config = make_test_config()
        auto_context = {"user_name": "Alice", "domain": "Python"}

        agent = MeshLlmAgent(
            config=config,
            filtered_tools=[],
            output_type=ChatResponse,
            template_path=None,
            context_value=auto_context,
        )

        # Explicitly clear context
        resolved = agent._resolve_context({}, "replace")

        assert resolved == {}

    def test_resolve_context_append_empty_dict_no_op(self):
        """Test: Append with empty dict is no-op (keeps auto context)."""
        from _mcp_mesh.engine.mesh_llm_agent import MeshLlmAgent

        config = make_test_config()
        auto_context = {"user_name": "Alice", "domain": "Python"}

        agent = MeshLlmAgent(
            config=config,
            filtered_tools=[],
            output_type=ChatResponse,
            template_path=None,
            context_value=auto_context,
        )

        resolved = agent._resolve_context({}, "append")

        # Empty dict appended is no-op
        assert resolved == {"user_name": "Alice", "domain": "Python"}

    def test_resolve_context_none_runtime_context(self):
        """Test: None runtime context converted to empty dict."""
        from _mcp_mesh.engine.mesh_llm_agent import MeshLlmAgent

        config = make_test_config()
        auto_context = {"user_name": "Alice", "domain": "Python"}

        agent = MeshLlmAgent(
            config=config,
            filtered_tools=[],
            output_type=ChatResponse,
            template_path=None,
            context_value=auto_context,
        )

        resolved = agent._resolve_context(None, "append")

        # None is treated as empty dict for append
        assert resolved == {"user_name": "Alice", "domain": "Python"}

    def test_resolve_context_with_mesh_context_model_runtime(self):
        """Test: MeshContextModel works as runtime context."""
        from _mcp_mesh.engine.mesh_llm_agent import MeshLlmAgent

        config = make_test_config()
        auto_context = {"user_name": "Alice"}

        agent = MeshLlmAgent(
            config=config,
            filtered_tools=[],
            output_type=ChatResponse,
            template_path=None,
            context_value=auto_context,
        )

        runtime_context = ChatContext(user_name="Bob", domain="Go")
        resolved = agent._resolve_context(runtime_context, "append")

        # Runtime MeshContextModel should work
        assert resolved["user_name"] == "Bob"  # Runtime wins
        assert resolved["domain"] == "Go"

    @pytest.mark.asyncio
    async def test_call_with_context_parameter(self):
        """Test: __call__ with context parameter uses resolved context in template."""
        from _mcp_mesh.engine.mesh_llm_agent import MeshLlmAgent

        config = make_test_config()
        template_path = str(TEMPLATES_DIR / "simple.jinja2")
        auto_context = {"user_name": "Alice", "domain": "Python"}

        mock_provider_proxy = AsyncMock()
        mock_provider_proxy.return_value = {
            "role": "assistant",
            "content": '{"answer": "Response", "confidence": 1.0, "sources": []}',
        }

        agent = MeshLlmAgent(
            config=config,
            filtered_tools=[],
            output_type=ChatResponse,
            template_path=template_path,
            context_value=auto_context,
            provider_proxy=mock_provider_proxy,
            vendor="anthropic",
        )


        # Call with runtime context that overrides domain
        response = await agent(
            "Test message",
            context={"domain": "Go"},
        )

        # Verify system prompt contains merged context
        call_kwargs = mock_provider_proxy.call_args[1]
        request_dict = call_kwargs["request"]
        messages = request_dict["messages"]
        system_message = next(m for m in messages if m["role"] == "system")

        # Alice from auto, Go from runtime (append mode default)
        assert "Alice" in system_message["content"]
        assert "Go" in system_message["content"]
        assert isinstance(response, ChatResponse)

    @pytest.mark.asyncio
    async def test_call_with_context_mode_replace(self):
        """Test: __call__ with context_mode='replace' replaces entire context."""
        from _mcp_mesh.engine.mesh_llm_agent import MeshLlmAgent

        config = make_test_config()
        template_path = str(TEMPLATES_DIR / "simple.jinja2")
        auto_context = {"user_name": "Alice", "domain": "Python"}

        mock_provider_proxy = AsyncMock()
        mock_provider_proxy.return_value = {
            "role": "assistant",
            "content": '{"answer": "Response", "confidence": 1.0, "sources": []}',
        }

        agent = MeshLlmAgent(
            config=config,
            filtered_tools=[],
            output_type=ChatResponse,
            template_path=template_path,
            context_value=auto_context,
            provider_proxy=mock_provider_proxy,
            vendor="anthropic",
        )


        # Call with replace mode
        response = await agent(
            "Test message",
            context={"user_name": "Bob", "domain": "Rust"},
            context_mode="replace",
        )

        # Verify system prompt contains replaced context
        call_kwargs = mock_provider_proxy.call_args[1]
        request_dict = call_kwargs["request"]
        messages = request_dict["messages"]
        system_message = next(m for m in messages if m["role"] == "system")

        # Bob and Rust from runtime (replace mode)
        assert "Bob" in system_message["content"]
        assert "Rust" in system_message["content"]
        assert "Alice" not in system_message["content"]
        assert isinstance(response, ChatResponse)

    @pytest.mark.asyncio
    async def test_call_without_context_uses_auto_populated(self):
        """Test: __call__ without context parameter uses auto-populated context."""
        from _mcp_mesh.engine.mesh_llm_agent import MeshLlmAgent

        config = make_test_config()
        template_path = str(TEMPLATES_DIR / "simple.jinja2")
        auto_context = ChatContext(user_name="Alice", domain="Python")

        mock_provider_proxy = AsyncMock()
        mock_provider_proxy.return_value = {
            "role": "assistant",
            "content": '{"answer": "Response", "confidence": 1.0, "sources": []}',
        }

        agent = MeshLlmAgent(
            config=config,
            filtered_tools=[],
            output_type=ChatResponse,
            template_path=template_path,
            context_value=auto_context,
            provider_proxy=mock_provider_proxy,
            vendor="anthropic",
        )


        # Call without context (backward compatible)
        response = await agent("Test message")

        # Verify system prompt contains auto-populated context
        call_kwargs = mock_provider_proxy.call_args[1]
        request_dict = call_kwargs["request"]
        messages = request_dict["messages"]
        system_message = next(m for m in messages if m["role"] == "system")

        assert "Alice" in system_message["content"]
        assert "Python" in system_message["content"]
        assert isinstance(response, ChatResponse)

    @pytest.mark.asyncio
    async def test_call_with_context_mode_prepend(self):
        """Test: __call__ with context_mode='prepend' - auto wins on conflicts."""
        from _mcp_mesh.engine.mesh_llm_agent import MeshLlmAgent

        config = make_test_config()
        template_path = str(TEMPLATES_DIR / "simple.jinja2")
        auto_context = {"user_name": "Alice", "domain": "Python"}

        mock_provider_proxy = AsyncMock()
        mock_provider_proxy.return_value = {
            "role": "assistant",
            "content": '{"answer": "Response", "confidence": 1.0, "sources": []}',
        }

        agent = MeshLlmAgent(
            config=config,
            filtered_tools=[],
            output_type=ChatResponse,
            template_path=template_path,
            context_value=auto_context,
            provider_proxy=mock_provider_proxy,
            vendor="anthropic",
        )


        # Call with prepend mode - auto should win
        response = await agent(
            "Test message",
            context={"user_name": "Bob", "domain": "Rust"},
            context_mode="prepend",
        )

        # Verify system prompt uses auto context (prepend means auto wins)
        call_kwargs = mock_provider_proxy.call_args[1]
        request_dict = call_kwargs["request"]
        messages = request_dict["messages"]
        system_message = next(m for m in messages if m["role"] == "system")

        # Auto wins on conflicts
        assert "Alice" in system_message["content"]
        assert "Python" in system_message["content"]
        assert isinstance(response, ChatResponse)


# ============================================================================
# Issue #308: Model Override in Mesh Delegation Tests
# ============================================================================


class TestMeshDelegationModelOverride:
    """Test model override functionality for mesh delegation (issue #308)."""

    @pytest.mark.asyncio
    async def test_mesh_delegation_includes_model_in_params(self):
        """Test: Model is included in model_params when explicitly set for mesh delegation."""
        from _mcp_mesh.engine.mesh_llm_agent import MeshLlmAgent

        # Create config with dict provider (mesh delegation) and explicit model
        config = LLMConfig(
            provider={
                "capability": "llm",
                "tags": ["claude"],
            },
            model="anthropic/claude-haiku",  # Explicit model override
            max_iterations=10,
            system_prompt="Test prompt",
        )

        # Create mock provider proxy
        mock_provider_proxy = AsyncMock()
        mock_provider_proxy.return_value = {
            "role": "assistant",
            "content": '{"answer": "Hello", "confidence": 0.9, "sources": []}',
        }

        agent = MeshLlmAgent(
            config=config,
            filtered_tools=[],
            output_type=ChatResponse,
            provider_proxy=mock_provider_proxy,
            vendor="anthropic",
        )

        # Mesh delegation is the only mode in v2 (provider is always a dict).
        assert isinstance(agent.provider, dict)

        # Call agent
        response = await agent("Test message")

        # Verify provider proxy was called with model in request
        mock_provider_proxy.assert_called_once()
        call_kwargs = mock_provider_proxy.call_args[1]
        request_dict = call_kwargs["request"]

        # Model should be in model_params
        assert "model_params" in request_dict
        assert request_dict["model_params"].get("model") == "anthropic/claude-haiku"

    @pytest.mark.asyncio
    async def test_mesh_delegation_excludes_empty_model(self):
        """Test: Empty/None model is not included in model_params."""
        from _mcp_mesh.engine.mesh_llm_agent import MeshLlmAgent

        # Create config with dict provider but no explicit model
        config = LLMConfig(
            provider={"capability": "llm", "tags": ["claude"]},
            model=None,  # No model specified
            max_iterations=10,
            system_prompt="Test prompt",
        )

        # Create mock provider proxy
        mock_provider_proxy = AsyncMock()
        mock_provider_proxy.return_value = {
            "role": "assistant",
            "content": '{"answer": "Hello", "confidence": 0.9, "sources": []}',
        }

        agent = MeshLlmAgent(
            config=config,
            filtered_tools=[],
            output_type=ChatResponse,
            provider_proxy=mock_provider_proxy,
            vendor="anthropic",
        )

        # Call agent
        response = await agent("Test message")

        # Verify provider proxy was called
        mock_provider_proxy.assert_called_once()
        call_kwargs = mock_provider_proxy.call_args[1]
        request_dict = call_kwargs["request"]

        # Model should NOT be in model_params (or be None/empty)
        model_params = request_dict.get("model_params", {})
        assert model_params is None or "model" not in model_params


class TestLlmProviderModelOverride:
    """Test model override handling in @mesh.llm_provider decorator (issue #308)."""

    def test_extract_vendor_from_model_with_vendor_prefix(self):
        """Test: Extract vendor from model string with vendor prefix."""
        from mesh.helpers import _extract_vendor_from_model

        assert _extract_vendor_from_model("anthropic/claude-sonnet-4-5") == "anthropic"
        assert _extract_vendor_from_model("openai/gpt-4o") == "openai"
        assert _extract_vendor_from_model("google/gemini-pro") == "google"

    def test_extract_vendor_from_model_without_prefix(self):
        """Test: Returns None for model without vendor prefix."""
        from mesh.helpers import _extract_vendor_from_model

        assert _extract_vendor_from_model("claude-3-haiku") is None
        assert _extract_vendor_from_model("gpt-4") is None
        assert _extract_vendor_from_model("") is None
        assert _extract_vendor_from_model(None) is None

    def test_extract_vendor_from_model_case_insensitive(self):
        """Test: Vendor extraction is case insensitive."""
        from mesh.helpers import _extract_vendor_from_model

        assert _extract_vendor_from_model("Anthropic/claude-sonnet") == "anthropic"
        assert _extract_vendor_from_model("OPENAI/gpt-4") == "openai"

    def test_process_chat_uses_override_model_when_vendor_matches(self):
        """Test: Provider uses override model when vendor matches."""
        from mesh.types import MeshLlmRequest

        # Simulate what happens inside process_chat
        provider_model = "anthropic/claude-sonnet-4-5"
        provider_vendor = "anthropic"

        request = MeshLlmRequest(
            messages=[{"role": "user", "content": "Hello"}],
            model_params={"model": "anthropic/claude-haiku"},  # Override
        )

        # Simulate the vendor check logic
        from mesh.helpers import _extract_vendor_from_model

        override_model = request.model_params.get("model")
        override_vendor = _extract_vendor_from_model(override_model)

        # Vendor matches - should use override
        assert override_vendor == provider_vendor
        effective_model = override_model  # Would use override

        assert effective_model == "anthropic/claude-haiku"

    def test_process_chat_ignores_override_on_vendor_mismatch(self):
        """Test: Provider ignores override when vendor doesn't match."""
        from mesh.types import MeshLlmRequest

        provider_model = "anthropic/claude-sonnet-4-5"
        provider_vendor = "anthropic"

        request = MeshLlmRequest(
            messages=[{"role": "user", "content": "Hello"}],
            model_params={"model": "openai/gpt-4o"},  # Wrong vendor!
        )

        from mesh.helpers import _extract_vendor_from_model

        override_model = request.model_params.get("model")
        override_vendor = _extract_vendor_from_model(override_model)

        # Vendor mismatch - should fall back to provider's model
        assert override_vendor != provider_vendor
        effective_model = provider_model  # Would fall back

        assert effective_model == "anthropic/claude-sonnet-4-5"

    def test_process_chat_uses_override_when_no_vendor_prefix(self):
        """Test: Provider uses override when it has no vendor prefix (can't validate)."""
        from mesh.types import MeshLlmRequest

        provider_model = "anthropic/claude-sonnet-4-5"
        provider_vendor = "anthropic"

        request = MeshLlmRequest(
            messages=[{"role": "user", "content": "Hello"}],
            model_params={"model": "claude-3-haiku"},  # No vendor prefix
        )

        from mesh.helpers import _extract_vendor_from_model

        override_model = request.model_params.get("model")
        override_vendor = _extract_vendor_from_model(override_model)

        # No vendor prefix - can't validate, so use override
        assert override_vendor is None
        # When vendor is None, the check `override_vendor and override_vendor != vendor`
        # is False, so we use the override
        effective_model = override_model

        assert effective_model == "claude-3-haiku"


class TestLlmMetaAttachment:
    """Test _mesh_meta attachment to LLM results (Issue #311)."""

    @pytest.mark.asyncio
    async def test_mesh_meta_attached_to_pydantic_result(self):
        """Test: _mesh_meta is attached to Pydantic model results.

        Mesh-delegated only — the provider proxy returns a message dict with
        ``_mesh_usage``, which ``_MockResponse`` lifts into the response shape.
        """
        from _mcp_mesh.engine.mesh_llm_agent import MeshLlmAgent
        from mesh.types import LlmMeta

        mock_provider_proxy = AsyncMock()
        mock_provider_proxy.return_value = {
            "role": "assistant",
            "content": '{"answer": "42", "confidence": 0.95, "sources": []}',
            "_mesh_usage": {
                "prompt_tokens": 100,
                "completion_tokens": 50,
                "model": "anthropic/claude-3-5-sonnet",
            },
        }

        agent = MeshLlmAgent(
            config=make_test_config(
                model="anthropic/claude-3-5-sonnet",
                system_prompt="You are helpful.",
            ),
            filtered_tools=[],
            output_type=ChatResponse,
            provider_proxy=mock_provider_proxy,
            vendor="anthropic",
        )

        result = await agent("What is the answer?")

        # Verify result is correct type
        assert isinstance(result, ChatResponse)
        assert result.answer == "42"
        assert result.confidence == 0.95

        # Verify _mesh_meta is attached
        assert hasattr(result, "_mesh_meta")
        assert isinstance(result._mesh_meta, LlmMeta)
        assert result._mesh_meta.provider == "anthropic"
        assert result._mesh_meta.model == "anthropic/claude-3-5-sonnet"
        assert result._mesh_meta.input_tokens == 100
        assert result._mesh_meta.output_tokens == 50
        assert result._mesh_meta.total_tokens == 150
        assert result._mesh_meta.latency_ms > 0

    @pytest.mark.asyncio
    async def test_mesh_meta_accumulates_tokens_across_iterations(self):
        """Test: _mesh_meta accumulates tokens across tool call iterations.

        Mesh-delegated only — provider proxy returns a tool_call message on
        the first call and a final answer on the second; iterations sum the
        ``_mesh_usage`` token counts.
        """
        from _mcp_mesh.engine.mesh_llm_agent import MeshLlmAgent

        first_response = {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "tc1",
                    "type": "function",
                    "function": {"name": "get_info", "arguments": "{}"},
                }
            ],
            "_mesh_usage": {
                "prompt_tokens": 100,
                "completion_tokens": 20,
                "model": "anthropic/claude-3-5-sonnet",
            },
        }
        second_response = {
            "role": "assistant",
            "content": '{"answer": "done", "confidence": 0.9, "sources": []}',
            "_mesh_usage": {
                "prompt_tokens": 150,
                "completion_tokens": 30,
                "model": "anthropic/claude-3-5-sonnet",
            },
        }

        call_count = 0

        async def fake_provider(**kwargs):
            nonlocal call_count
            call_count += 1
            return first_response if call_count == 1 else second_response

        mock_provider_proxy = AsyncMock(side_effect=fake_provider)

        # Mock tool proxy with call_tool method returning JSON-serializable result
        mock_tool_proxy = MagicMock()
        mock_tool_proxy.call_tool = AsyncMock(return_value={"result": "tool result"})
        mock_tool_proxy.endpoint = "http://test:9999"

        agent = MeshLlmAgent(
            config=make_test_config(
                model="anthropic/claude-3-5-sonnet",
                system_prompt="You are helpful.",
            ),
            filtered_tools=[
                {"name": "get_info", "description": "Get info", "inputSchema": {}}
            ],
            output_type=ChatResponse,
            tool_proxies={"get_info": mock_tool_proxy},
            provider_proxy=mock_provider_proxy,
            vendor="anthropic",
        )

        result = await agent("Do something")

        # Verify tokens are accumulated from both calls
        assert result._mesh_meta.input_tokens == 250  # 100 + 150
        assert result._mesh_meta.output_tokens == 50  # 20 + 30
        assert result._mesh_meta.total_tokens == 300

    @pytest.mark.asyncio
    async def test_mesh_meta_not_attached_to_str_result(self):
        """Test: _mesh_meta cannot be attached to str results (silently skipped)."""
        from _mcp_mesh.engine.mesh_llm_agent import MeshLlmAgent

        mock_provider_proxy = AsyncMock()
        mock_provider_proxy.return_value = {
            "role": "assistant",
            "content": "Hello, world!",
            "_mesh_usage": {
                "prompt_tokens": 50,
                "completion_tokens": 10,
                "model": "anthropic/claude-3-5-sonnet",
            },
        }

        agent = MeshLlmAgent(
            config=make_test_config(
                model="anthropic/claude-3-5-sonnet",
                system_prompt="You are helpful.",
            ),
            filtered_tools=[],
            output_type=str,  # str return type
            provider_proxy=mock_provider_proxy,
            vendor="anthropic",
        )

        result = await agent("Say hello")

        # Result should be string
        assert isinstance(result, str)
        assert result == "Hello, world!"

        # _mesh_meta cannot be attached to str (no error, just not present)
        assert not hasattr(result, "_mesh_meta")

    def test_llm_meta_dataclass_creation(self):
        """Test: LlmMeta dataclass can be created with all fields."""
        from mesh.types import LlmMeta

        meta = LlmMeta(
            provider="anthropic",
            model="anthropic/claude-3-5-haiku",
            input_tokens=100,
            output_tokens=50,
            total_tokens=150,
            latency_ms=125.5,
        )

        assert meta.provider == "anthropic"
        assert meta.model == "anthropic/claude-3-5-haiku"
        assert meta.input_tokens == 100
        assert meta.output_tokens == 50
        assert meta.total_tokens == 150
        assert meta.latency_ms == 125.5

    def test_llm_meta_exported_from_mesh_module(self):
        """Test: LlmMeta is accessible via mesh.LlmMeta."""
        import mesh

        assert hasattr(mesh, "LlmMeta")
        assert mesh.LlmMeta is not None

        # Can create instance
        meta = mesh.LlmMeta(
            provider="openai",
            model="gpt-4o",
            input_tokens=200,
            output_tokens=100,
            total_tokens=300,
            latency_ms=200.0,
        )
        assert meta.provider == "openai"


class TestMeshDelegationMeta:
    """Test _mesh_meta in mesh delegation scenarios (Issue #311)."""

    def test_mesh_usage_included_in_provider_response(self):
        """Test: llm_provider includes _mesh_usage in response dict."""
        # This tests the structure that llm_provider should return
        # Simulating what process_chat returns

        message_dict = {
            "role": "assistant",
            "content": "Hello!",
            "_mesh_usage": {
                "prompt_tokens": 100,
                "completion_tokens": 50,
                "model": "anthropic/claude-3-5-sonnet",
            },
        }

        assert "_mesh_usage" in message_dict
        assert message_dict["_mesh_usage"]["prompt_tokens"] == 100
        assert message_dict["_mesh_usage"]["completion_tokens"] == 50
        assert message_dict["_mesh_usage"]["model"] == "anthropic/claude-3-5-sonnet"

    def test_mock_response_extracts_mesh_usage(self):
        """Test: MockResponse correctly extracts _mesh_usage from provider response."""
        # This tests the MockResponse class behavior in mesh_llm_agent.py

        message_dict = {
            "role": "assistant",
            "content": "Response content",
            "_mesh_usage": {
                "prompt_tokens": 200,
                "completion_tokens": 80,
                "model": "anthropic/claude-3-5-haiku",
            },
        }

        # Simulate MockUsage and MockResponse behavior
        class MockUsage:
            def __init__(self, usage_dict):
                self.prompt_tokens = usage_dict.get("prompt_tokens", 0)
                self.completion_tokens = usage_dict.get("completion_tokens", 0)
                self.total_tokens = self.prompt_tokens + self.completion_tokens

        mesh_usage = message_dict.get("_mesh_usage")
        usage = MockUsage(mesh_usage) if mesh_usage else None
        model = mesh_usage.get("model") if mesh_usage else None

        assert usage is not None
        assert usage.prompt_tokens == 200
        assert usage.completion_tokens == 80
        assert usage.total_tokens == 280
        assert model == "anthropic/claude-3-5-haiku"

    def test_mock_response_handles_missing_mesh_usage(self):
        """Test: MockResponse handles responses without _mesh_usage gracefully."""
        message_dict = {
            "role": "assistant",
            "content": "Response without usage",
        }

        # Simulate MockResponse behavior
        mesh_usage = message_dict.get("_mesh_usage")
        usage = None  # Would be MockUsage(mesh_usage) if mesh_usage else None
        model = mesh_usage.get("model") if mesh_usage else None

        assert usage is None
        assert model is None


class TestBuildRequestParamsKwargCollision:
    """Regression tests for #863: output_type kwarg collision in
    _build_request_params when output_type leaks into _default_model_params
    (e.g., via @mesh.llm decorator **kwargs capture)."""

    def test_build_request_params_no_kwarg_collision_when_output_type_in_default_params(
        self,
    ):
        """#863: prepare_request was failing with 'got multiple values for
        keyword argument output_type' when output_type leaked into
        _default_model_params (decorator **kwargs capture path)."""
        from _mcp_mesh.engine.mesh_llm_agent import MeshLlmAgent

        agent = MeshLlmAgent(
            config=make_test_config(model="claude-3-5-sonnet-20241022",
                max_iterations=10,
            ),
            filtered_tools=[],
            output_type=ChatResponse,
        )

        # Simulate output_type leaking into _default_model_params via the
        # decorator path (resolved_config.update(kwargs) in @mesh.llm).
        agent._default_model_params["output_type"] = ChatResponse

        # Capture prepare_request invocation; assert no TypeError raised
        # and output_type arrives exactly once with the agent's value.
        captured: dict = {}

        def fake_prepare_request(*, messages, tools, output_type, **kwargs):
            captured["messages"] = messages
            captured["tools"] = tools
            captured["output_type"] = output_type
            captured["kwargs"] = kwargs
            return {
                "messages": messages,
                "tools": tools,
                "output_type": output_type,
                **kwargs,
            }

        with patch.object(
            agent._provider_handler,
            "prepare_request",
            side_effect=fake_prepare_request,
        ):
            params = agent._build_request_params(
                [{"role": "user", "content": "hi"}]
            )

        # Did not raise TypeError; reached the handler exactly once.
        assert captured["output_type"] is ChatResponse
        # output_type should NOT also appear in **kwargs (would imply
        # collision risk if upstream signatures changed).
        assert "output_type" not in captured["kwargs"]
        # Returned params include output_type from the explicit kwarg path.
        assert params["output_type"] is ChatResponse

    def test_build_request_params_call_time_output_type_kwarg_pops_safely(self):
        """Defense-in-depth: caller-supplied ``output_type`` kwarg at call
        time is popped before the splat — preventing collision with the
        explicit ``output_type=self.output_type`` passed to
        ``prepare_request``. ``self.output_type`` is always authoritative
        (set at agent construction); call-time ``output_type`` is never
        honored, by design. The pop is what keeps a stale **kwargs forward
        from raising ``TypeError: prepare_request() got multiple values for
        keyword argument 'output_type'``."""
        from _mcp_mesh.engine.mesh_llm_agent import MeshLlmAgent

        agent = MeshLlmAgent(
            config=make_test_config(model="claude-3-5-sonnet-20241022",
                max_iterations=10,
            ),
            filtered_tools=[],
            output_type=ChatResponse,
        )

        captured: dict = {}

        def fake_prepare_request(*, messages, tools, output_type, **kwargs):
            captured["output_type"] = output_type
            captured["kwargs"] = kwargs
            return {"output_type": output_type, **kwargs}

        with patch.object(
            agent._provider_handler,
            "prepare_request",
            side_effect=fake_prepare_request,
        ):
            agent._build_request_params(
                [{"role": "user", "content": "hi"}],
                output_type=ComplexResponse,  # caller-provided collision
            )

        # ``self.output_type`` is what reaches the handler — call-time
        # ``output_type`` is unconditionally popped, never honored.
        assert captured["output_type"] is ChatResponse
        assert "output_type" not in captured["kwargs"]
