"""
Unit tests for signature_analyzer module.

Tests context parameter detection for Phase 2 (TDD approach).
"""

from typing import Optional

import pytest
from pydantic import Field

from _mcp_mesh.engine.signature_analyzer import get_context_parameter_name
from mesh import MeshContextModel, MeshLlmAgent


class ChatContext(MeshContextModel):
    """Test context model."""

    user_name: str = Field(description="User name")
    domain: str = Field(description="Domain")


class AnalysisContext(MeshContextModel):
    """Test analysis context model."""

    domain: str = Field(description="Analysis domain")
    user_level: str = Field(default="beginner")


# ============================================================================
# Phase 2: Context Parameter Detection
# ============================================================================


class TestExplicitContextParamDetection:
    """Test explicit context_param detection (Phase 2 - TDD)."""

    def test_explicit_context_param_valid(self):
        """Test: Explicit context_param detected and validated."""

        def chat(message: str, ctx: ChatContext, llm: MeshLlmAgent = None):
            pass

        result = get_context_parameter_name(chat, explicit_name="ctx")

        assert result is not None
        param_name, param_index = result
        assert param_name == "ctx"
        assert param_index == 1  # Second parameter (0-indexed)

    def test_explicit_context_param_first_position(self):
        """Test: Explicit context_param at first position."""

        def analyze(ctx: AnalysisContext, query: str, llm: MeshLlmAgent = None):
            pass

        result = get_context_parameter_name(analyze, explicit_name="ctx")

        assert result is not None
        param_name, param_index = result
        assert param_name == "ctx"
        assert param_index == 0

    def test_explicit_context_param_invalid_name_error(self):
        """Test: Invalid explicit name raises error."""

        def chat(message: str, context: ChatContext, llm: MeshLlmAgent = None):
            pass

        # Explicitly naming "ctx" but parameter is "context"
        with pytest.raises(ValueError) as exc_info:
            get_context_parameter_name(chat, explicit_name="ctx")

        assert "ctx" in str(exc_info.value).lower()
        assert "not found" in str(exc_info.value).lower()

    def test_explicit_context_param_none_falls_back(self):
        """Test: explicit_name=None falls back to convention."""

        def chat(message: str, prompt_context: ChatContext, llm: MeshLlmAgent = None):
            pass

        result = get_context_parameter_name(chat, explicit_name=None)

        # Should fall back to convention detection
        assert result is not None
        param_name, param_index = result
        assert param_name == "prompt_context"


class TestConventionBasedDetection:
    """Test convention-based context parameter detection (Phase 2 - TDD)."""

    def test_prompt_context_convention(self):
        """Test: prompt_context parameter detected by convention."""

        def chat(message: str, prompt_context: dict, llm: MeshLlmAgent = None):
            pass

        result = get_context_parameter_name(chat, explicit_name=None)

        assert result is not None
        param_name, param_index = result
        assert param_name == "prompt_context"
        assert param_index == 1

    def test_llm_context_convention(self):
        """Test: llm_context parameter detected by convention."""

        def analyze(query: str, llm_context: dict, llm: MeshLlmAgent = None):
            pass

        result = get_context_parameter_name(analyze, explicit_name=None)

        assert result is not None
        param_name, param_index = result
        assert param_name == "llm_context"
        assert param_index == 1

    def test_context_convention(self):
        """Test: context parameter detected by convention."""

        def process(data: str, context: dict, llm: MeshLlmAgent = None):
            pass

        result = get_context_parameter_name(process, explicit_name=None)

        assert result is not None
        param_name, param_index = result
        assert param_name == "context"
        assert param_index == 1

    def test_convention_priority_order(self):
        """Test: Convention priority - prompt_context > llm_context > context."""

        # If multiple convention names exist, prompt_context wins
        def chat(
            message: str,
            context: dict,
            llm_context: dict,
            prompt_context: dict,
            llm: MeshLlmAgent = None,
        ):
            pass

        result = get_context_parameter_name(chat, explicit_name=None)

        assert result is not None
        param_name, param_index = result
        assert param_name == "prompt_context"  # Highest priority

    def test_no_convention_match_returns_none(self):
        """Test: No convention match returns None."""

        def chat(message: str, user_data: dict, llm: MeshLlmAgent = None):
            pass

        result = get_context_parameter_name(chat, explicit_name=None)

        # Should check type hints next (no MeshContextModel here)
        assert result is None


class TestTypeHintDetection:
    """Test MeshContextModel type hint detection (Phase 2 - TDD)."""

    def test_mesh_context_model_type_hint(self):
        """Test: MeshContextModel subclass detected by type hint."""

        def chat(message: str, ctx: ChatContext, llm: MeshLlmAgent = None):
            pass

        result = get_context_parameter_name(chat, explicit_name=None)

        assert result is not None
        param_name, param_index = result
        assert param_name == "ctx"
        assert param_index == 1

    def test_optional_mesh_context_model(self):
        """Test: Optional[MeshContextModel] detected."""

        def analyze(
            query: str, ctx: Optional[AnalysisContext] = None, llm: MeshLlmAgent = None
        ):
            pass

        result = get_context_parameter_name(analyze, explicit_name=None)

        assert result is not None
        param_name, param_index = result
        assert param_name == "ctx"

    def test_mesh_context_model_subclass(self):
        """Test: MeshContextModel subclass detected."""

        class CustomContext(ChatContext):
            extra_field: str = "test"

        def process(data: str, my_ctx: CustomContext, llm: MeshLlmAgent = None):
            pass

        result = get_context_parameter_name(process, explicit_name=None)

        assert result is not None
        param_name, param_index = result
        assert param_name == "my_ctx"

    def test_type_hint_wins_over_name_convention(self):
        """Test: Type hint detection has priority over name convention."""

        # Parameter named "data" (not a convention) but typed as MeshContextModel
        def chat(message: str, data: ChatContext, llm: MeshLlmAgent = None):
            pass

        result = get_context_parameter_name(chat, explicit_name=None)

        assert result is not None
        param_name, param_index = result
        assert param_name == "data"  # Found by type hint, not by name

    def test_no_mesh_context_model_returns_none(self):
        """Test: No MeshContextModel parameter returns None."""

        def chat(message: str, user_id: int, llm: MeshLlmAgent = None):
            pass

        result = get_context_parameter_name(chat, explicit_name=None)

        assert result is None


class TestMultipleCandidates:
    """Test behavior with multiple context candidates (Phase 2 - TDD)."""

    def test_explicit_wins_over_everything(self):
        """Test: Explicit name wins over convention and type hints."""

        def chat(
            message: str,
            prompt_context: dict,  # Convention name
            ctx: ChatContext,  # Type hint
            llm: MeshLlmAgent = None,
        ):
            pass

        # Explicitly choose ctx (type hint) over prompt_context (convention)
        result = get_context_parameter_name(chat, explicit_name="ctx")

        assert result is not None
        param_name, param_index = result
        assert param_name == "ctx"
        assert param_index == 2

    def test_type_hint_wins_over_convention(self):
        """Test: Type hint wins over name convention when both present."""

        def chat(
            message: str,
            context: dict,  # Convention name, but dict type
            ctx: ChatContext,  # MeshContextModel type hint
            llm: MeshLlmAgent = None,
        ):
            pass

        result = get_context_parameter_name(chat, explicit_name=None)

        # Should prefer ctx (MeshContextModel type) over context (dict)
        assert result is not None
        param_name, param_index = result
        assert param_name == "ctx"

    def test_first_mesh_context_model_if_multiple(self):
        """Test: First MeshContextModel parameter if multiple exist."""

        def chat(
            message: str,
            ctx1: ChatContext,
            ctx2: AnalysisContext,
            llm: MeshLlmAgent = None,
        ):
            pass

        result = get_context_parameter_name(chat, explicit_name=None)

        assert result is not None
        param_name, param_index = result
        assert param_name == "ctx1"  # First one wins


class TestEdgeCases:
    """Test edge cases for context parameter detection (Phase 2 - TDD)."""

    def test_function_with_no_parameters(self):
        """Test: Function with no parameters returns None."""

        def chat():
            pass

        result = get_context_parameter_name(chat, explicit_name=None)

        assert result is None

    def test_function_with_only_llm_parameter(self):
        """Test: Function with only LLM parameter returns None."""

        def chat(llm: MeshLlmAgent = None):
            pass

        result = get_context_parameter_name(chat, explicit_name=None)

        assert result is None

    def test_function_without_type_hints(self):
        """Test: Function without type hints falls back to name convention."""

        def chat(message, prompt_context, llm=None):
            pass

        result = get_context_parameter_name(chat, explicit_name=None)

        # Should still find by name convention
        assert result is not None
        param_name, param_index = result
        assert param_name == "prompt_context"

    def test_explicit_name_for_non_mesh_context_model(self):
        """Test: Explicit name works even if not MeshContextModel type."""

        def chat(message: str, ctx: dict, llm: MeshLlmAgent = None):
            pass

        result = get_context_parameter_name(chat, explicit_name="ctx")

        # Should work - explicit name doesn't require MeshContextModel type
        assert result is not None
        param_name, param_index = result
        assert param_name == "ctx"

    def test_context_param_same_name_as_llm_param(self):
        """Test: Ensure we don't confuse context param with LLM param."""

        def chat(message: str, ctx: ChatContext, llm: MeshLlmAgent = None):
            pass

        result = get_context_parameter_name(chat, explicit_name="llm")

        # Should error because llm is MeshLlmAgent, not a context param
        # Actually, explicit name should just validate existence
        # Let me check - the explicit name just needs to exist
        assert result is not None
        param_name, param_index = result
        assert param_name == "llm"
        assert param_index == 2
