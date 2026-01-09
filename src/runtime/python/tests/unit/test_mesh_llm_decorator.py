"""
Unit tests for @mesh.llm decorator.

Tests follow TDD approach - these should FAIL initially until decorator is implemented.
"""

import os
from typing import get_type_hints

import mesh
import pytest
from _mcp_mesh.engine.decorator_registry import DecoratorRegistry
from pydantic import BaseModel


class ChatResponse(BaseModel):
    """Test output type for LLM functions."""

    answer: str
    confidence: float


class TestMeshLlmDecoratorBasics:
    """Test basic @mesh.llm decorator functionality."""

    def setup_method(self):
        """Clear registry before each test."""
        DecoratorRegistry._mesh_llm_agents = {}

    def test_decorator_exists(self):
        """Test that @mesh.llm decorator is available."""
        assert hasattr(mesh, "llm"), "@mesh.llm decorator should be available"

    def test_decorator_registers_function(self):
        """Test that @mesh.llm decorator registers function in registry."""

        @mesh.llm(filter={"capability": "document"})
        def chat(message: str, llm: mesh.MeshLlmAgent = None) -> ChatResponse:
            return llm(message)

        llm_agents = DecoratorRegistry.get_mesh_llm_agents()
        assert len(llm_agents) == 1, "Should register one LLM agent"
        assert chat.__name__ in [
            agent.function.__name__ for agent in llm_agents.values()
        ]

    def test_decorator_accepts_simple_filter(self):
        """Test decorator with simple string filter."""

        @mesh.llm(filter="document_processor")
        def analyze(message: str, llm: mesh.MeshLlmAgent = None) -> ChatResponse:
            return llm(message)

        llm_agents = DecoratorRegistry.get_mesh_llm_agents()
        agent_data = next(iter(llm_agents.values()))
        assert agent_data.config["filter"] == "document_processor"

    def test_decorator_accepts_dict_filter(self):
        """Test decorator with dict filter (capability + tags)."""

        @mesh.llm(filter={"capability": "document", "tags": ["pdf", "advanced"]})
        def analyze(message: str, llm: mesh.MeshLlmAgent = None) -> ChatResponse:
            return llm(message)

        llm_agents = DecoratorRegistry.get_mesh_llm_agents()
        agent_data = next(iter(llm_agents.values()))
        expected_filter = {"capability": "document", "tags": ["pdf", "advanced"]}
        assert agent_data.config["filter"] == expected_filter

    def test_decorator_accepts_list_filter(self):
        """Test decorator with list of mixed filters."""

        @mesh.llm(
            filter=[
                {"capability": "document", "tags": ["pdf"]},
                "web_search",
                {"capability": "database", "tags": ["postgres"]},
            ]
        )
        def analyze(message: str, llm: mesh.MeshLlmAgent = None) -> ChatResponse:
            return llm(message)

        llm_agents = DecoratorRegistry.get_mesh_llm_agents()
        agent_data = next(iter(llm_agents.values()))
        assert isinstance(agent_data.config["filter"], list)
        assert len(agent_data.config["filter"]) == 3


class TestMeshLlmDecoratorConfiguration:
    """Test configuration parameters and hierarchy."""

    def setup_method(self):
        """Clear registry and environment before each test."""
        DecoratorRegistry._mesh_llm_agents = {}
        # Clear any test environment variables
        for key in list(os.environ.keys()):
            if key.startswith("MESH_LLM_") or key in [
                "ANTHROPIC_API_KEY",
                "OPENAI_API_KEY",
            ]:
                if "TEST" in key:  # Only clear test vars
                    del os.environ[key]

    def test_decorator_default_configuration(self):
        """Test decorator with default configuration values."""

        @mesh.llm(filter={"capability": "document"})
        def chat(message: str, llm: mesh.MeshLlmAgent = None) -> ChatResponse:
            return llm(message)

        llm_agents = DecoratorRegistry.get_mesh_llm_agents()
        agent_data = next(iter(llm_agents.values()))
        config = agent_data.config

        # Check defaults
        assert config["provider"] == "claude"
        assert config["filter_mode"] == "all"
        assert config["max_iterations"] == 10

    def test_decorator_custom_provider(self):
        """Test decorator with custom provider."""

        @mesh.llm(filter={"capability": "document"}, provider="openai")
        def chat(message: str, llm: mesh.MeshLlmAgent = None) -> ChatResponse:
            return llm(message)

        llm_agents = DecoratorRegistry.get_mesh_llm_agents()
        agent_data = next(iter(llm_agents.values()))
        assert agent_data.config["provider"] == "openai"

    def test_decorator_custom_model(self):
        """Test decorator with custom model."""

        @mesh.llm(filter={"capability": "document"}, model="claude-3-5-sonnet-20241022")
        def chat(message: str, llm: mesh.MeshLlmAgent = None) -> ChatResponse:
            return llm(message)

        llm_agents = DecoratorRegistry.get_mesh_llm_agents()
        agent_data = next(iter(llm_agents.values()))
        assert agent_data.config["model"] == "claude-3-5-sonnet-20241022"

    def test_decorator_custom_max_iterations(self):
        """Test decorator with custom max_iterations."""

        @mesh.llm(filter={"capability": "document"}, max_iterations=20)
        def chat(message: str, llm: mesh.MeshLlmAgent = None) -> ChatResponse:
            return llm(message)

        llm_agents = DecoratorRegistry.get_mesh_llm_agents()
        agent_data = next(iter(llm_agents.values()))
        assert agent_data.config["max_iterations"] == 20

    def test_decorator_system_prompt(self):
        """Test decorator with system prompt."""

        @mesh.llm(
            filter={"capability": "document"},
            system_prompt="You are a helpful assistant.",
        )
        def chat(message: str, llm: mesh.MeshLlmAgent = None) -> ChatResponse:
            return llm(message)

        llm_agents = DecoratorRegistry.get_mesh_llm_agents()
        agent_data = next(iter(llm_agents.values()))
        assert agent_data.config["system_prompt"] == "You are a helpful assistant."

    def test_decorator_system_prompt_file(self):
        """Test decorator with system prompt file path."""

        @mesh.llm(
            filter={"capability": "document"},
            system_prompt_file="prompts/chat.jinja2",
        )
        def chat(message: str, llm: mesh.MeshLlmAgent = None) -> ChatResponse:
            return llm(message)

        llm_agents = DecoratorRegistry.get_mesh_llm_agents()
        agent_data = next(iter(llm_agents.values()))
        assert agent_data.config["system_prompt_file"] == "prompts/chat.jinja2"


class TestMeshLlmDecoratorOutputTypeExtraction:
    """Test extraction of output type from return annotation."""

    def setup_method(self):
        """Clear registry before each test."""
        DecoratorRegistry._mesh_llm_agents = {}

    def test_extracts_pydantic_output_type(self):
        """Test that decorator extracts Pydantic BaseModel from return annotation."""

        @mesh.llm(filter={"capability": "document"})
        def chat(message: str, llm: mesh.MeshLlmAgent = None) -> ChatResponse:
            return llm(message)

        llm_agents = DecoratorRegistry.get_mesh_llm_agents()
        agent_data = next(iter(llm_agents.values()))
        assert agent_data.output_type == ChatResponse

    def test_extracts_custom_pydantic_model(self):
        """Test extraction of custom Pydantic model."""

        class CustomResponse(BaseModel):
            result: str
            metadata: dict

        @mesh.llm(filter={"capability": "document"})
        def analyze(message: str, llm: mesh.MeshLlmAgent = None) -> CustomResponse:
            return llm(message)

        llm_agents = DecoratorRegistry.get_mesh_llm_agents()
        agent_data = next(iter(llm_agents.values()))
        assert agent_data.output_type == CustomResponse

    def test_warns_on_non_pydantic_return_type(self):
        """Test warning when return type is not Pydantic BaseModel."""

        with pytest.warns(UserWarning, match="should return a Pydantic BaseModel"):

            @mesh.llm(filter={"capability": "document"})
            def chat(message: str, llm: mesh.MeshLlmAgent = None) -> dict:
                return llm(message)


class TestMeshLlmDecoratorParameterValidation:
    """Test validation of MeshLlmAgent parameters."""

    def setup_method(self):
        """Clear registry before each test."""
        DecoratorRegistry._mesh_llm_agents = {}

    def test_detects_single_mesh_llm_agent_parameter(self):
        """Test detection of single MeshLlmAgent parameter."""

        @mesh.llm(filter={"capability": "document"})
        def chat(message: str, llm: mesh.MeshLlmAgent = None) -> ChatResponse:
            return llm(message)

        llm_agents = DecoratorRegistry.get_mesh_llm_agents()
        agent_data = next(iter(llm_agents.values()))
        assert agent_data.param_name == "llm"

    def test_detects_custom_parameter_name(self):
        """Test detection of custom parameter name."""

        @mesh.llm(filter={"capability": "document"})
        def chat(message: str, document_llm: mesh.MeshLlmAgent = None) -> ChatResponse:
            return document_llm(message)

        llm_agents = DecoratorRegistry.get_mesh_llm_agents()
        agent_data = next(iter(llm_agents.values()))
        assert agent_data.param_name == "document_llm"

    def test_warns_on_multiple_mesh_llm_agent_parameters(self):
        """Test warning when multiple MeshLlmAgent parameters are detected."""

        with pytest.warns(
            UserWarning, match="multiple MeshLlmAgent parameters.*Only.*first"
        ):

            @mesh.llm(filter={"capability": "document"})
            def chat(
                message: str,
                llm1: mesh.MeshLlmAgent = None,
                llm2: mesh.MeshLlmAgent = None,
            ) -> ChatResponse:
                return llm1(message)

        llm_agents = DecoratorRegistry.get_mesh_llm_agents()
        agent_data = next(iter(llm_agents.values()))
        # Should use the first parameter
        assert agent_data.param_name == "llm1"

    def test_error_on_no_mesh_llm_agent_parameter(self):
        """Test error when no MeshLlmAgent parameter is found."""

        with pytest.raises(ValueError, match="must have at least one parameter"):

            @mesh.llm(filter={"capability": "document"})
            def chat(message: str) -> ChatResponse:
                return ChatResponse(answer="test", confidence=0.9)


class TestMeshLlmDecoratorFilterMode:
    """Test filter_mode parameter."""

    def setup_method(self):
        """Clear registry before each test."""
        DecoratorRegistry._mesh_llm_agents = {}

    def test_filter_mode_all(self):
        """Test filter_mode='all'."""

        @mesh.llm(filter={"capability": "document"}, filter_mode="all")
        def chat(message: str, llm: mesh.MeshLlmAgent = None) -> ChatResponse:
            return llm(message)

        llm_agents = DecoratorRegistry.get_mesh_llm_agents()
        agent_data = next(iter(llm_agents.values()))
        assert agent_data.config["filter_mode"] == "all"

    def test_filter_mode_best_match(self):
        """Test filter_mode='best_match'."""

        @mesh.llm(filter={"capability": "document"}, filter_mode="best_match")
        def chat(message: str, llm: mesh.MeshLlmAgent = None) -> ChatResponse:
            return llm(message)

        llm_agents = DecoratorRegistry.get_mesh_llm_agents()
        agent_data = next(iter(llm_agents.values()))
        assert agent_data.config["filter_mode"] == "best_match"

    def test_filter_mode_wildcard(self):
        """Test filter_mode='*' (wildcard)."""

        @mesh.llm(filter={"capability": "document"}, filter_mode="*")
        def chat(message: str, llm: mesh.MeshLlmAgent = None) -> ChatResponse:
            return llm(message)

        llm_agents = DecoratorRegistry.get_mesh_llm_agents()
        agent_data = next(iter(llm_agents.values()))
        assert agent_data.config["filter_mode"] == "*"


class TestMeshLlmDecoratorFunctionIdGeneration:
    """Test function ID generation for registry."""

    def setup_method(self):
        """Clear registry before each test."""
        DecoratorRegistry._mesh_llm_agents = {}

    def test_generates_unique_function_id(self):
        """Test that each decorated function gets unique ID."""

        @mesh.llm(filter={"capability": "document"})
        def chat1(message: str, llm: mesh.MeshLlmAgent = None) -> ChatResponse:
            return llm(message)

        @mesh.llm(filter={"capability": "document"})
        def chat2(message: str, llm: mesh.MeshLlmAgent = None) -> ChatResponse:
            return llm(message)

        llm_agents = DecoratorRegistry.get_mesh_llm_agents()
        assert len(llm_agents) == 2
        function_ids = list(llm_agents.keys())
        assert function_ids[0] != function_ids[1]

    def test_function_id_includes_function_name(self):
        """Test that function ID contains function name."""

        @mesh.llm(filter={"capability": "document"})
        def my_chat_function(
            message: str, llm: mesh.MeshLlmAgent = None
        ) -> ChatResponse:
            return llm(message)

        llm_agents = DecoratorRegistry.get_mesh_llm_agents()
        function_id = next(iter(llm_agents.keys()))
        assert "my_chat_function" in function_id


# ============================================================================
# Phase 1: Template File Support with file:// Prefix
# ============================================================================
# Tests for system_prompt="file://..." and context_param support


class TestTemplateFileSupport:
    """Test @mesh.llm decorator template file support (Phase 1 - TDD)."""

    def setup_method(self):
        """Clear registry before each test."""
        DecoratorRegistry._mesh_llm_agents = {}

    def test_literal_system_prompt_no_prefix(self):
        """Test: Literal system_prompt (no prefix) works as before."""

        @mesh.llm(
            filter={"capability": "chat"},
            system_prompt="You are a helpful assistant.",
        )
        def chat(message: str, llm: mesh.MeshLlmAgent = None) -> ChatResponse:
            return llm(message)

        llm_agents = DecoratorRegistry.get_mesh_llm_agents()
        agent_data = next(iter(llm_agents.values()))

        # Should store literal prompt
        assert agent_data.config.get("system_prompt") == "You are a helpful assistant."
        # Should NOT be marked as template
        assert (
            agent_data.config.get("is_template") is False
            or agent_data.config.get("is_template") is None
        )
        assert agent_data.config.get("template_path") is None

    def test_file_prefix_detection_and_stripping(self):
        """Test: file:// prefix detected and stripped."""

        @mesh.llm(
            filter={"capability": "chat"},
            system_prompt="file://prompts/chat.jinja2",
        )
        def chat(message: str, llm: mesh.MeshLlmAgent = None) -> ChatResponse:
            return llm(message)

        llm_agents = DecoratorRegistry.get_mesh_llm_agents()
        agent_data = next(iter(llm_agents.values()))

        # Should be marked as template
        assert agent_data.config.get("is_template") is True
        # Should strip file:// prefix
        assert agent_data.config.get("template_path") == "prompts/chat.jinja2"
        # Original system_prompt should be preserved
        assert agent_data.config.get("system_prompt") == "file://prompts/chat.jinja2"

    def test_absolute_path_file_prefix(self):
        """Test: Absolute path (file:///...) detected correctly."""

        @mesh.llm(
            filter={"capability": "chat"},
            system_prompt="file:///tmp/prompts/chat.jinja2",
        )
        def chat(message: str, llm: mesh.MeshLlmAgent = None) -> ChatResponse:
            return llm(message)

        llm_agents = DecoratorRegistry.get_mesh_llm_agents()
        agent_data = next(iter(llm_agents.values()))

        assert agent_data.config.get("is_template") is True
        # Should preserve absolute path (3 slashes = 1 from file:// + 2 from //)
        assert agent_data.config.get("template_path") == "/tmp/prompts/chat.jinja2"

    def test_relative_path_resolution(self):
        """Test: Relative path stored correctly."""

        @mesh.llm(
            filter={"capability": "chat"},
            system_prompt="file://./prompts/chat.jinja2",
        )
        def chat(message: str, llm: mesh.MeshLlmAgent = None) -> ChatResponse:
            return llm(message)

        llm_agents = DecoratorRegistry.get_mesh_llm_agents()
        agent_data = next(iter(llm_agents.values()))

        assert agent_data.config.get("is_template") is True
        assert agent_data.config.get("template_path") == "./prompts/chat.jinja2"

    def test_jinja2_extension_auto_detection(self):
        """Test: .jinja2 extension auto-detected as template without file://."""

        @mesh.llm(
            filter={"capability": "chat"},
            system_prompt="prompts/chat.jinja2",  # No file:// prefix
        )
        def chat(message: str, llm: mesh.MeshLlmAgent = None) -> ChatResponse:
            return llm(message)

        llm_agents = DecoratorRegistry.get_mesh_llm_agents()
        agent_data = next(iter(llm_agents.values()))

        # Should auto-detect as template
        assert agent_data.config.get("is_template") is True
        assert agent_data.config.get("template_path") == "prompts/chat.jinja2"

    def test_j2_extension_auto_detection(self):
        """Test: .j2 extension auto-detected as template without file://."""

        @mesh.llm(
            filter={"capability": "chat"},
            system_prompt="prompts/chat.j2",
        )
        def chat(message: str, llm: mesh.MeshLlmAgent = None) -> ChatResponse:
            return llm(message)

        llm_agents = DecoratorRegistry.get_mesh_llm_agents()
        agent_data = next(iter(llm_agents.values()))

        assert agent_data.config.get("is_template") is True
        assert agent_data.config.get("template_path") == "prompts/chat.j2"


class TestContextParamSupport:
    """Test context_param parameter support (Phase 1 - TDD)."""

    def setup_method(self):
        """Clear registry before each test."""
        DecoratorRegistry._mesh_llm_agents = {}

    def test_context_param_stored_in_metadata(self):
        """Test: context_param stored correctly."""

        @mesh.llm(
            filter={"capability": "chat"},
            system_prompt="file://prompts/chat.jinja2",
            context_param="ctx",
        )
        def chat(
            message: str, ctx: dict, llm: mesh.MeshLlmAgent = None
        ) -> ChatResponse:
            return llm(message)

        llm_agents = DecoratorRegistry.get_mesh_llm_agents()
        agent_data = next(iter(llm_agents.values()))

        assert agent_data.config.get("context_param") == "ctx"

    def test_context_param_without_template_warning(self):
        """Test: Warning when context_param without file:// (should log warning)."""
        import logging
        from unittest.mock import patch

        with patch("mesh.decorators.logger") as mock_logger:

            @mesh.llm(
                filter={"capability": "chat"},
                system_prompt="You are helpful.",  # No file://
                context_param="ctx",  # Context param without template
            )
            def chat(message: str, llm: mesh.MeshLlmAgent = None) -> ChatResponse:
                return llm(message)

            # Should log warning
            mock_logger.warning.assert_called()
            warning_message = str(mock_logger.warning.call_args)
            assert "context_param" in warning_message.lower()

    def test_context_param_with_template_no_warning(self):
        """Test: No warning when context_param with file://."""
        import logging
        from unittest.mock import patch

        with patch("mesh.decorators.logger") as mock_logger:

            @mesh.llm(
                filter={"capability": "chat"},
                system_prompt="file://prompts/chat.jinja2",
                context_param="ctx",
            )
            def chat(message: str, llm: mesh.MeshLlmAgent = None) -> ChatResponse:
                return llm(message)

            # Should NOT log warning
            mock_logger.warning.assert_not_called()

    def test_context_param_none_is_valid(self):
        """Test: context_param=None is valid (no error)."""

        @mesh.llm(
            filter={"capability": "chat"},
            system_prompt="file://prompts/chat.jinja2",
            context_param=None,
        )
        def chat(message: str, llm: mesh.MeshLlmAgent = None) -> ChatResponse:
            return llm(message)

        llm_agents = DecoratorRegistry.get_mesh_llm_agents()
        agent_data = next(iter(llm_agents.values()))

        assert agent_data.config.get("context_param") is None


class TestDecoratorRegistryTemplateMetadata:
    """Test DecoratorRegistry stores template metadata correctly (Phase 1 - TDD)."""

    def setup_method(self):
        """Clear registry before each test."""
        DecoratorRegistry._mesh_llm_agents = {}

    def test_is_template_flag_set_correctly(self):
        """Test: is_template flag set for templates."""

        @mesh.llm(
            filter={"capability": "chat"},
            system_prompt="file://prompts/chat.jinja2",
        )
        def chat_template(message: str, llm: mesh.MeshLlmAgent = None) -> ChatResponse:
            return llm(message)

        @mesh.llm(
            filter={"capability": "help"},
            system_prompt="You are helpful.",
        )
        def chat_literal(message: str, llm: mesh.MeshLlmAgent = None) -> ChatResponse:
            return llm(message)

        llm_agents = DecoratorRegistry.get_mesh_llm_agents()

        template_agent = next(
            agent
            for agent in llm_agents.values()
            if agent.function.__name__ == "chat_template"
        )
        literal_agent = next(
            agent
            for agent in llm_agents.values()
            if agent.function.__name__ == "chat_literal"
        )

        assert template_agent.config.get("is_template") is True
        assert (
            literal_agent.config.get("is_template") is False
            or literal_agent.config.get("is_template") is None
        )

    def test_template_path_stored_correctly(self):
        """Test: template_path stored for templates."""

        @mesh.llm(
            filter={"capability": "chat"},
            system_prompt="file://prompts/analyst.jinja2",
        )
        def analyze(message: str, llm: mesh.MeshLlmAgent = None) -> ChatResponse:
            return llm(message)

        llm_agents = DecoratorRegistry.get_mesh_llm_agents()
        agent_data = next(iter(llm_agents.values()))

        assert agent_data.config.get("template_path") == "prompts/analyst.jinja2"

    def test_context_param_name_stored_correctly(self):
        """Test: context_param_name stored in registry."""

        @mesh.llm(
            filter={"capability": "chat"},
            system_prompt="file://prompts/chat.jinja2",
            context_param="analysis_ctx",
        )
        def analyze(
            message: str, analysis_ctx: dict, llm: mesh.MeshLlmAgent = None
        ) -> ChatResponse:
            return llm(message)

        llm_agents = DecoratorRegistry.get_mesh_llm_agents()
        agent_data = next(iter(llm_agents.values()))

        assert agent_data.config.get("context_param") == "analysis_ctx"

    def test_literal_prompts_have_no_template_metadata(self):
        """Test: Literal prompts don't have template metadata."""

        @mesh.llm(
            filter={"capability": "chat"},
            system_prompt="You are helpful.",
        )
        def chat(message: str, llm: mesh.MeshLlmAgent = None) -> ChatResponse:
            return llm(message)

        llm_agents = DecoratorRegistry.get_mesh_llm_agents()
        agent_data = next(iter(llm_agents.values()))

        assert (
            agent_data.config.get("is_template") is False
            or agent_data.config.get("is_template") is None
        )
        assert agent_data.config.get("template_path") is None
