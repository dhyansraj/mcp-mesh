"""Unit tests for MediaParam type annotation and schema enhancement."""

import sys
from pathlib import Path
from typing import Annotated, Optional, get_args, get_origin

import pytest

# Add the Python runtime source to the path so imports work outside tox
sys.path.insert(
    0, str(Path(__file__).resolve().parents[2] / "src" / "runtime" / "python")
)

from mesh.types import MediaParam, _MediaParamInfo


class TestMediaParamType:
    """Test MediaParam() type annotation creation."""

    def test_creates_annotated_type(self):
        """MediaParam returns an Annotated type."""
        param_type = MediaParam("image/*")
        assert get_origin(param_type) is Annotated

    def test_default_media_type(self):
        """MediaParam() defaults to */*."""
        param_type = MediaParam()
        args = get_args(param_type)
        media_info = None
        for arg in args:
            if isinstance(arg, _MediaParamInfo):
                media_info = arg
                break
        assert media_info is not None
        assert media_info.media_type == "*/*"

    def test_custom_media_type(self):
        """MediaParam("image/*") stores the media type."""
        param_type = MediaParam("image/*")
        args = get_args(param_type)
        media_info = None
        for arg in args:
            if isinstance(arg, _MediaParamInfo):
                media_info = arg
                break
        assert media_info is not None
        assert media_info.media_type == "image/*"

    def test_media_param_info_frozen(self):
        """_MediaParamInfo is immutable."""
        info = _MediaParamInfo("image/png")
        with pytest.raises(AttributeError):
            info.media_type = "text/plain"


class TestSchemaEnhancement:
    """Test enhance_schema_with_media_params on FastMCPSchemaExtractor."""

    def test_adds_x_media_type(self):
        """enhance_schema_with_media_params adds x-media-type to annotated params."""
        from _mcp_mesh.utils.fastmcp_schema_extractor import FastMCPSchemaExtractor

        async def test_func(
            question: str, image: MediaParam("image/*") = None
        ):
            pass

        schema = {
            "type": "object",
            "properties": {
                "question": {"type": "string"},
                "image": {"type": "string", "default": None},
            },
        }

        enhanced = FastMCPSchemaExtractor.enhance_schema_with_media_params(
            schema, test_func
        )
        assert enhanced["properties"]["image"]["x-media-type"] == "image/*"
        assert "image/*" in enhanced["properties"]["image"]["description"]

    def test_appends_media_note_to_existing_description(self):
        """Media note is appended to existing description without duplication."""
        from _mcp_mesh.utils.fastmcp_schema_extractor import FastMCPSchemaExtractor

        async def test_func(
            doc: MediaParam("application/pdf") = None,
        ):
            pass

        schema = {
            "type": "object",
            "properties": {
                "doc": {
                    "type": "string",
                    "default": None,
                    "description": "A document to analyze",
                },
            },
        }

        enhanced = FastMCPSchemaExtractor.enhance_schema_with_media_params(
            schema, test_func
        )
        desc = enhanced["properties"]["doc"]["description"]
        assert desc.startswith("A document to analyze")
        assert "(accepts media URI: application/pdf)" in desc

    def test_no_media_param_unchanged(self):
        """Functions without MediaParam have unchanged schema."""
        from _mcp_mesh.utils.fastmcp_schema_extractor import FastMCPSchemaExtractor

        async def test_func(question: str):
            pass

        schema = {
            "type": "object",
            "properties": {"question": {"type": "string"}},
        }

        enhanced = FastMCPSchemaExtractor.enhance_schema_with_media_params(
            schema, test_func
        )
        assert "x-media-type" not in enhanced["properties"]["question"]

    def test_empty_schema_unchanged(self):
        """Empty or None schemas pass through safely."""
        from _mcp_mesh.utils.fastmcp_schema_extractor import FastMCPSchemaExtractor

        async def test_func():
            pass

        assert FastMCPSchemaExtractor.enhance_schema_with_media_params({}, test_func) == {}
        assert FastMCPSchemaExtractor.enhance_schema_with_media_params(None, test_func) is None

    def test_multiple_media_params(self):
        """Multiple MediaParam annotations are all enhanced."""
        from _mcp_mesh.utils.fastmcp_schema_extractor import FastMCPSchemaExtractor

        async def test_func(
            image: MediaParam("image/*") = None,
            audio: MediaParam("audio/*") = None,
        ):
            pass

        schema = {
            "type": "object",
            "properties": {
                "image": {"type": "string", "default": None},
                "audio": {"type": "string", "default": None},
            },
        }

        enhanced = FastMCPSchemaExtractor.enhance_schema_with_media_params(
            schema, test_func
        )
        assert enhanced["properties"]["image"]["x-media-type"] == "image/*"
        assert enhanced["properties"]["audio"]["x-media-type"] == "audio/*"


class TestToolSchemaBuilderMediaEnrichment:
    """Test that ToolSchemaBuilder enriches descriptions with media info."""

    def test_description_enriched_with_media(self):
        """Tool description includes media parameter info."""
        from _mcp_mesh.engine.tool_schema_builder import ToolSchemaBuilder

        tool = {
            "name": "analyze_image",
            "description": "Analyze an image",
            "input_schema": {
                "type": "object",
                "properties": {
                    "question": {"type": "string"},
                    "image": {
                        "type": "string",
                        "x-media-type": "image/*",
                        "description": "(accepts media URI: image/*)",
                    },
                },
            },
        }

        schema = ToolSchemaBuilder._build_from_dict(tool)
        desc = schema["function"]["description"]
        assert "Accepts media:" in desc
        assert "'image' accepts image/* URIs" in desc

    def test_no_media_description_unchanged(self):
        """Tool without media params has unchanged description."""
        from _mcp_mesh.engine.tool_schema_builder import ToolSchemaBuilder

        tool = {
            "name": "greet",
            "description": "Greet someone",
            "input_schema": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                },
            },
        }

        schema = ToolSchemaBuilder._build_from_dict(tool)
        assert schema["function"]["description"] == "Greet someone"


class TestProviderHandlerMediaInstructions:
    """Test that provider handlers add media instructions to system prompts."""

    def test_has_media_params_detects_media_tools(self):
        """has_media_params returns True when tools have x-media-type."""
        from _mcp_mesh.engine.provider_handlers.base_provider_handler import (
            has_media_params,
        )

        tool_schemas = [
            {
                "type": "function",
                "function": {
                    "name": "analyze",
                    "parameters": {
                        "properties": {
                            "image": {"type": "string", "x-media-type": "image/*"},
                        }
                    },
                },
            }
        ]
        assert has_media_params(tool_schemas) is True

    def test_has_media_params_returns_false_without_media(self):
        """has_media_params returns False for non-media tools."""
        from _mcp_mesh.engine.provider_handlers.base_provider_handler import (
            has_media_params,
        )

        tool_schemas = [
            {
                "type": "function",
                "function": {
                    "name": "greet",
                    "parameters": {
                        "properties": {"name": {"type": "string"}},
                    },
                },
            }
        ]
        assert has_media_params(tool_schemas) is False

    def test_has_media_params_none_tools(self):
        """has_media_params returns False for None."""
        from _mcp_mesh.engine.provider_handlers.base_provider_handler import (
            has_media_params,
        )

        assert has_media_params(None) is False
        assert has_media_params([]) is False

    def test_claude_handler_adds_media_instructions(self):
        """ClaudeHandler adds MEDIA PARAMETERS block when tools have media."""
        from _mcp_mesh.engine.provider_handlers.claude_handler import ClaudeHandler

        handler = ClaudeHandler()
        tool_schemas = [
            {
                "type": "function",
                "function": {
                    "name": "analyze",
                    "parameters": {
                        "properties": {
                            "image": {"type": "string", "x-media-type": "image/*"},
                        }
                    },
                },
            }
        ]

        prompt = handler.format_system_prompt(
            base_prompt="You are an assistant.",
            tool_schemas=tool_schemas,
            output_type=str,
        )
        assert "MEDIA PARAMETERS" in prompt
        assert "x-media-type" in prompt

    def test_claude_handler_no_media_instructions_without_media(self):
        """ClaudeHandler omits MEDIA PARAMETERS when no tools have media."""
        from _mcp_mesh.engine.provider_handlers.claude_handler import ClaudeHandler

        handler = ClaudeHandler()
        tool_schemas = [
            {
                "type": "function",
                "function": {
                    "name": "greet",
                    "parameters": {
                        "properties": {"name": {"type": "string"}},
                    },
                },
            }
        ]

        prompt = handler.format_system_prompt(
            base_prompt="You are an assistant.",
            tool_schemas=tool_schemas,
            output_type=str,
        )
        assert "MEDIA PARAMETERS" not in prompt

    def test_openai_handler_adds_media_instructions(self):
        """OpenAIHandler adds MEDIA PARAMETERS block when tools have media."""
        from _mcp_mesh.engine.provider_handlers.openai_handler import OpenAIHandler

        handler = OpenAIHandler()
        tool_schemas = [
            {
                "type": "function",
                "function": {
                    "name": "analyze",
                    "parameters": {
                        "properties": {
                            "image": {"type": "string", "x-media-type": "image/*"},
                        }
                    },
                },
            }
        ]

        prompt = handler.format_system_prompt(
            base_prompt="You are an assistant.",
            tool_schemas=tool_schemas,
            output_type=str,
        )
        assert "MEDIA PARAMETERS" in prompt

    def test_generic_handler_adds_media_instructions(self):
        """GenericHandler adds MEDIA PARAMETERS block when tools have media."""
        from _mcp_mesh.engine.provider_handlers.generic_handler import GenericHandler

        handler = GenericHandler()
        tool_schemas = [
            {
                "type": "function",
                "function": {
                    "name": "analyze",
                    "parameters": {
                        "properties": {
                            "image": {"type": "string", "x-media-type": "image/*"},
                        }
                    },
                },
            }
        ]

        prompt = handler.format_system_prompt(
            base_prompt="You are an assistant.",
            tool_schemas=tool_schemas,
            output_type=str,
        )
        assert "MEDIA PARAMETERS" in prompt


class TestMediaParamImport:
    """Test that MediaParam is accessible via mesh module."""

    def test_import_from_mesh(self):
        """MediaParam is importable via mesh.MediaParam."""
        import mesh

        param = mesh.MediaParam("image/*")
        assert get_origin(param) is Annotated
