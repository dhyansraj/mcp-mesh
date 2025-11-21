"""
Unit tests for FastMCPSchemaExtractor utility.

Tests schema extraction from FastMCP tools for LLM integration (Phase 2).
"""

from unittest.mock import MagicMock

import pytest

from _mcp_mesh.engine.decorator_registry import DecoratedFunction
from _mcp_mesh.utils.fastmcp_schema_extractor import FastMCPSchemaExtractor


class TestFastMCPSchemaExtractorBasics:
    """Test basic functionality of FastMCPSchemaExtractor."""

    def test_extractor_exists(self):
        """Test that FastMCPSchemaExtractor class exists."""
        assert FastMCPSchemaExtractor is not None

    def test_extract_input_schema_method_exists(self):
        """Test that extract_input_schema method exists."""
        assert hasattr(FastMCPSchemaExtractor, "extract_input_schema")
        assert callable(FastMCPSchemaExtractor.extract_input_schema)

    def test_extract_all_schemas_from_tools_method_exists(self):
        """Test that extract_all_schemas_from_tools method exists."""
        assert hasattr(FastMCPSchemaExtractor, "extract_all_schemas_from_tools")
        assert callable(FastMCPSchemaExtractor.extract_all_schemas_from_tools)


class TestExtractInputSchema:
    """Test extract_input_schema method."""

    def test_function_with_fastmcp_tool_returns_schema(self):
        """Test that function with FastMCP tool returns inputSchema."""
        # Create mock FastMCP tool with schema
        mock_tool = MagicMock()
        mock_tool.parameters = {
            "type": "object",
            "properties": {
                "param1": {"type": "string", "description": "First parameter"},
                "param2": {"type": "integer", "description": "Second parameter"},
            },
            "required": ["param1"],
        }

        # Create mock function with FastMCP tool reference
        mock_func = MagicMock()
        mock_func.__name__ = "test_function"
        mock_func._fastmcp_tool = mock_tool

        # Extract schema
        schema = FastMCPSchemaExtractor.extract_input_schema(mock_func)

        # Verify schema is extracted correctly
        assert schema is not None
        assert schema == mock_tool.parameters
        assert schema["type"] == "object"
        assert "param1" in schema["properties"]
        assert "param2" in schema["properties"]
        assert schema["required"] == ["param1"]

    def test_function_without_fastmcp_tool_returns_none(self):
        """Test that function without FastMCP tool returns None."""
        # Create mock function WITHOUT FastMCP tool
        mock_func = MagicMock(spec=["__name__", "__call__"])
        mock_func.__name__ = "plain_function"

        # Extract schema
        schema = FastMCPSchemaExtractor.extract_input_schema(mock_func)

        # Should return None
        assert schema is None

    def test_function_with_fastmcp_tool_but_no_schema_returns_none(self):
        """Test that function with FastMCP tool but no inputSchema returns None."""
        # Create mock FastMCP tool WITHOUT inputSchema
        mock_tool = MagicMock(spec=["name", "description"])
        mock_tool.name = "tool_without_schema"

        # Create mock function
        mock_func = MagicMock()
        mock_func.__name__ = "test_function"
        mock_func._fastmcp_tool = mock_tool

        # Extract schema
        schema = FastMCPSchemaExtractor.extract_input_schema(mock_func)

        # Should return None
        assert schema is None

    def test_complex_nested_schema_extraction(self):
        """Test extraction of complex nested schemas."""
        mock_tool = MagicMock()
        mock_tool.parameters = {
            "type": "object",
            "properties": {
                "simple": {"type": "string"},
                "nested": {
                    "type": "object",
                    "properties": {
                        "inner": {"type": "number"},
                        "array": {"type": "array", "items": {"type": "string"}},
                    },
                },
                "union": {"anyOf": [{"type": "string"}, {"type": "number"}]},
            },
            "required": ["simple", "nested"],
            "additionalProperties": False,
        }

        mock_func = MagicMock()
        mock_func.__name__ = "complex_function"
        mock_func._fastmcp_tool = mock_tool

        schema = FastMCPSchemaExtractor.extract_input_schema(mock_func)

        # Verify entire schema structure is preserved
        assert schema is not None
        assert schema["type"] == "object"
        assert schema["required"] == ["simple", "nested"]
        assert schema["additionalProperties"] is False

        # Verify nested structure
        assert "nested" in schema["properties"]
        nested = schema["properties"]["nested"]
        assert nested["type"] == "object"
        assert "inner" in nested["properties"]
        assert "array" in nested["properties"]

        # Verify union type
        assert "union" in schema["properties"]
        assert "anyOf" in schema["properties"]["union"]


class TestExtractAllSchemasFromTools:
    """Test extract_all_schemas_from_tools method."""

    def test_extract_from_empty_tools_dict(self):
        """Test extraction from empty tools dictionary."""
        result = FastMCPSchemaExtractor.extract_all_schemas_from_tools({})

        assert result == {}

    def test_extract_from_single_tool_with_schema(self):
        """Test extraction from single tool with schema."""
        mock_tool = MagicMock()
        mock_tool.parameters = {"type": "object", "properties": {}}

        mock_func = MagicMock()
        mock_func.__name__ = "tool1"
        mock_func._fastmcp_tool = mock_tool

        decorated_func = DecoratedFunction(
            decorator_type="mesh_tool",
            function=mock_func,
            metadata={},
            registered_at=MagicMock(),
        )

        mesh_tools = {"tool1": decorated_func}

        result = FastMCPSchemaExtractor.extract_all_schemas_from_tools(mesh_tools)

        assert len(result) == 1
        assert "tool1" in result
        assert result["tool1"] == mock_tool.parameters

    def test_extract_from_multiple_tools_mixed(self):
        """Test extraction from multiple tools with mixed schema availability."""
        # Tool 1: Has schema
        mock_tool1 = MagicMock()
        mock_tool1.parameters = {
            "type": "object",
            "properties": {"param1": {"type": "string"}},
        }
        mock_func1 = MagicMock()
        mock_func1.__name__ = "tool_with_schema"
        mock_func1._fastmcp_tool = mock_tool1

        # Tool 2: No FastMCP tool
        mock_func2 = MagicMock(spec=["__name__", "__call__"])
        mock_func2.__name__ = "tool_without_fastmcp"

        # Tool 3: Has FastMCP tool but no schema
        mock_tool3 = MagicMock(spec=["name"])
        mock_tool3.name = "tool3"
        mock_func3 = MagicMock()
        mock_func3.__name__ = "tool_with_fastmcp_no_schema"
        mock_func3._fastmcp_tool = mock_tool3

        mesh_tools = {
            "tool_with_schema": DecoratedFunction(
                decorator_type="mesh_tool",
                function=mock_func1,
                metadata={},
                registered_at=MagicMock(),
            ),
            "tool_without_fastmcp": DecoratedFunction(
                decorator_type="mesh_tool",
                function=mock_func2,
                metadata={},
                registered_at=MagicMock(),
            ),
            "tool_with_fastmcp_no_schema": DecoratedFunction(
                decorator_type="mesh_tool",
                function=mock_func3,
                metadata={},
                registered_at=MagicMock(),
            ),
        }

        result = FastMCPSchemaExtractor.extract_all_schemas_from_tools(mesh_tools)

        # Should have entries for all 3 tools
        assert len(result) == 3
        assert "tool_with_schema" in result
        assert "tool_without_fastmcp" in result
        assert "tool_with_fastmcp_no_schema" in result

        # Verify schema states
        assert result["tool_with_schema"] is not None
        assert result["tool_with_schema"]["type"] == "object"

        assert result["tool_without_fastmcp"] is None
        assert result["tool_with_fastmcp_no_schema"] is None

    def test_extract_preserves_all_schema_details(self):
        """Test that extraction preserves all schema details exactly."""
        original_schema = {
            "type": "object",
            "title": "My Tool Input",
            "description": "Input parameters for my tool",
            "properties": {
                "email": {
                    "type": "string",
                    "format": "email",
                    "description": "User email address",
                },
                "count": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 100,
                    "default": 10,
                },
            },
            "required": ["email"],
            "additionalProperties": False,
        }

        mock_tool = MagicMock()
        mock_tool.parameters = original_schema

        mock_func = MagicMock()
        mock_func.__name__ = "my_tool"
        mock_func._fastmcp_tool = mock_tool

        mesh_tools = {
            "my_tool": DecoratedFunction(
                decorator_type="mesh_tool",
                function=mock_func,
                metadata={},
                registered_at=MagicMock(),
            )
        }

        result = FastMCPSchemaExtractor.extract_all_schemas_from_tools(mesh_tools)

        # Verify exact schema is preserved
        assert result["my_tool"] == original_schema
        assert result["my_tool"]["title"] == "My Tool Input"
        assert result["my_tool"]["description"] == "Input parameters for my tool"
        assert result["my_tool"]["properties"]["email"]["format"] == "email"
        assert result["my_tool"]["properties"]["count"]["minimum"] == 1
        assert result["my_tool"]["properties"]["count"]["maximum"] == 100
        assert result["my_tool"]["properties"]["count"]["default"] == 10


class TestSchemaExtractionEdgeCases:
    """Test edge cases and error handling."""

    def test_function_without_name_attribute(self):
        """Test extraction from function without __name__ attribute."""
        mock_tool = MagicMock()
        mock_tool.parameters = {"type": "object"}

        mock_func = MagicMock(spec=["_fastmcp_tool"])
        mock_func._fastmcp_tool = mock_tool

        # Should not raise error
        schema = FastMCPSchemaExtractor.extract_input_schema(mock_func)

        # Should still extract schema
        assert schema == mock_tool.parameters

    def test_none_input_returns_none(self):
        """Test that None input returns None gracefully."""
        schema = FastMCPSchemaExtractor.extract_input_schema(None)
        assert schema is None

    def test_empty_schema_is_preserved(self):
        """Test that empty schema object is preserved (not converted to None)."""
        mock_tool = MagicMock()
        mock_tool.parameters = {}  # Empty schema object

        mock_func = MagicMock()
        mock_func.__name__ = "empty_schema_tool"
        mock_func._fastmcp_tool = mock_tool

        schema = FastMCPSchemaExtractor.extract_input_schema(mock_func)

        # Empty schema should be preserved
        assert schema is not None
        assert schema == {}

    def test_schema_with_no_properties(self):
        """Test schema with no properties defined."""
        mock_tool = MagicMock()
        mock_tool.parameters = {"type": "object"}  # No properties

        mock_func = MagicMock()
        mock_func.__name__ = "no_props_tool"
        mock_func._fastmcp_tool = mock_tool

        schema = FastMCPSchemaExtractor.extract_input_schema(mock_func)

        assert schema is not None
        assert schema["type"] == "object"
        assert "properties" not in schema


# ============================================================================
# Phase 0: Enhanced Schema Extraction for MeshContextModel
# ============================================================================
# These tests verify that MeshContextModel parameters are detected and their
# Pydantic Field descriptions are extracted into the tool schema for better
# LLM chain composition.


class TestMeshContextModelDetection:
    """Test detection of MeshContextModel parameters (Phase 0.1 - TDD)."""

    def test_detect_mesh_context_model_parameter(self):
        """Test: Detect parameter with MeshContextModel type hint."""
        from pydantic import Field

        from mesh import MeshContextModel

        class AnalysisContext(MeshContextModel):
            domain: str = Field(description="Analysis domain")
            user_level: str = Field(default="beginner", description="User expertise")

        def analyze_system(request: str, ctx: AnalysisContext):
            pass

        # Create mock tool
        mock_tool = MagicMock()
        mock_tool.parameters = {
            "type": "object",
            "properties": {
                "request": {"type": "string"},
                "ctx": {"type": "object"},  # Basic schema without descriptions
            },
        }
        analyze_system._fastmcp_tool = mock_tool

        # Extract schema - should detect MeshContextModel and enhance it
        result = FastMCPSchemaExtractor.extract_input_schema(analyze_system)

        # Verify MeshContextModel parameter was detected and enhanced
        assert "ctx" in result["properties"]
        ctx_schema = result["properties"]["ctx"]

        # Should have enhanced properties with descriptions
        assert "properties" in ctx_schema
        assert "domain" in ctx_schema["properties"]
        assert "description" in ctx_schema["properties"]["domain"]
        assert ctx_schema["properties"]["domain"]["description"] == "Analysis domain"

        assert "user_level" in ctx_schema["properties"]
        assert "description" in ctx_schema["properties"]["user_level"]
        assert ctx_schema["properties"]["user_level"]["description"] == "User expertise"

    def test_detect_mesh_context_model_subclass(self):
        """Test: Detect parameter with MeshContextModel subclass."""
        from pydantic import Field

        from mesh import MeshContextModel

        class BaseContext(MeshContextModel):
            user_name: str = Field(description="Name of user")

        class AnalysisContext(BaseContext):
            domain: str = Field(description="Analysis domain")

        def analyze(query: str, ctx: AnalysisContext):
            pass

        mock_tool = MagicMock()
        mock_tool.parameters = {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "ctx": {"type": "object"},
            },
        }
        analyze._fastmcp_tool = mock_tool

        result = FastMCPSchemaExtractor.extract_input_schema(analyze)

        # Should detect subclass and include fields from both base and derived
        ctx_schema = result["properties"]["ctx"]
        assert "user_name" in ctx_schema["properties"]
        assert "domain" in ctx_schema["properties"]
        assert ctx_schema["properties"]["user_name"]["description"] == "Name of user"
        assert ctx_schema["properties"]["domain"]["description"] == "Analysis domain"

    def test_ignore_regular_parameters(self):
        """Test: Ignore regular parameters (not MeshContextModel)."""
        from mesh import MeshLlmAgent

        def chat(message: str, user_id: int, llm: MeshLlmAgent = None):
            pass

        mock_tool = MagicMock()
        mock_tool.parameters = {
            "type": "object",
            "properties": {
                "message": {"type": "string"},
                "user_id": {"type": "integer"},
            },
        }
        chat._fastmcp_tool = mock_tool

        result = FastMCPSchemaExtractor.extract_input_schema(chat)

        # Should preserve original schema (no enhancement for non-MeshContextModel)
        assert result["properties"]["message"]["type"] == "string"
        assert result["properties"]["user_id"]["type"] == "integer"
        # No extra descriptions added
        assert "description" not in result["properties"]["message"]

    def test_handle_multiple_parameters_mixed(self):
        """Test: Handle multiple parameters (some context, some regular)."""
        from pydantic import Field

        from mesh import MeshContextModel

        class ChatContext(MeshContextModel):
            domain: str = Field(description="Chat domain")

        def chat(message: str, ctx: ChatContext, user_id: int):
            pass

        mock_tool = MagicMock()
        mock_tool.parameters = {
            "type": "object",
            "properties": {
                "message": {"type": "string"},
                "ctx": {"type": "object"},
                "user_id": {"type": "integer"},
            },
        }
        chat._fastmcp_tool = mock_tool

        result = FastMCPSchemaExtractor.extract_input_schema(chat)

        # ctx should be enhanced
        assert "domain" in result["properties"]["ctx"]["properties"]
        assert (
            result["properties"]["ctx"]["properties"]["domain"]["description"]
            == "Chat domain"
        )

        # Other params unchanged
        assert result["properties"]["message"]["type"] == "string"
        assert result["properties"]["user_id"]["type"] == "integer"

    def test_handle_optional_mesh_context_model(self):
        """Test: Handle optional MeshContextModel (| None)."""
        from typing import Optional

        from pydantic import Field

        from mesh import MeshContextModel

        class AnalysisContext(MeshContextModel):
            domain: str = Field(description="Analysis domain")

        def analyze(query: str, ctx: Optional[AnalysisContext] = None):
            pass

        mock_tool = MagicMock()
        mock_tool.parameters = {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "ctx": {"type": "object"},
            },
        }
        analyze._fastmcp_tool = mock_tool

        result = FastMCPSchemaExtractor.extract_input_schema(analyze)

        # Should still detect and enhance Optional[MeshContextModel]
        assert "domain" in result["properties"]["ctx"]["properties"]
        assert (
            result["properties"]["ctx"]["properties"]["domain"]["description"]
            == "Analysis domain"
        )


class TestFieldDescriptionExtraction:
    """Test extraction of Pydantic Field descriptions (Phase 0.3 - TDD)."""

    def test_extract_simple_field_descriptions(self):
        """Test: Extract Field description for simple fields."""
        from pydantic import Field

        from mesh import MeshContextModel

        class SimpleContext(MeshContextModel):
            name: str = Field(description="User name")
            age: int = Field(description="User age")

        def process(ctx: SimpleContext):
            pass

        mock_tool = MagicMock()
        mock_tool.parameters = {
            "type": "object",
            "properties": {"ctx": {"type": "object"}},
        }
        process._fastmcp_tool = mock_tool

        result = FastMCPSchemaExtractor.extract_input_schema(process)

        ctx_props = result["properties"]["ctx"]["properties"]
        assert ctx_props["name"]["type"] == "string"
        assert ctx_props["name"]["description"] == "User name"
        assert ctx_props["age"]["type"] == "integer"
        assert ctx_props["age"]["description"] == "User age"

    def test_extract_optional_fields_with_defaults(self):
        """Test: Extract Field description for optional fields with defaults."""
        from pydantic import Field

        from mesh import MeshContextModel

        class ConfigContext(MeshContextModel):
            timeout: int = Field(default=30, description="Timeout in seconds")
            retry: bool = Field(default=True, description="Enable retries")

        def configure(ctx: ConfigContext):
            pass

        mock_tool = MagicMock()
        mock_tool.parameters = {
            "type": "object",
            "properties": {"ctx": {"type": "object"}},
        }
        configure._fastmcp_tool = mock_tool

        result = FastMCPSchemaExtractor.extract_input_schema(configure)

        ctx_props = result["properties"]["ctx"]["properties"]
        assert ctx_props["timeout"]["description"] == "Timeout in seconds"
        assert ctx_props["timeout"]["default"] == 30
        assert ctx_props["retry"]["description"] == "Enable retries"
        assert ctx_props["retry"]["default"] is True

    def test_extract_complex_types(self):
        """Test: Extract Field description for complex types (list, dict)."""
        from pydantic import Field

        from mesh import MeshContextModel

        class ComplexContext(MeshContextModel):
            tags: list[str] = Field(description="List of tags")
            metadata: dict[str, str] = Field(description="Metadata key-value pairs")

        def process(ctx: ComplexContext):
            pass

        mock_tool = MagicMock()
        mock_tool.parameters = {
            "type": "object",
            "properties": {"ctx": {"type": "object"}},
        }
        process._fastmcp_tool = mock_tool

        result = FastMCPSchemaExtractor.extract_input_schema(process)

        ctx_props = result["properties"]["ctx"]["properties"]
        assert ctx_props["tags"]["description"] == "List of tags"
        assert ctx_props["tags"]["type"] == "array"
        assert ctx_props["metadata"]["description"] == "Metadata key-value pairs"
        assert ctx_props["metadata"]["type"] == "object"

    def test_extract_nested_mesh_context_model(self):
        """Test: Extract Field description for nested MeshContextModel."""
        from pydantic import Field

        from mesh import MeshContextModel

        class UserInfo(MeshContextModel):
            name: str = Field(description="User name")
            role: str = Field(description="User role")

        class TaskContext(MeshContextModel):
            user: UserInfo = Field(description="User information")
            task_type: str = Field(description="Task type")

        def execute_task(ctx: TaskContext):
            pass

        mock_tool = MagicMock()
        mock_tool.parameters = {
            "type": "object",
            "properties": {"ctx": {"type": "object"}},
        }
        execute_task._fastmcp_tool = mock_tool

        result = FastMCPSchemaExtractor.extract_input_schema(execute_task)

        ctx_props = result["properties"]["ctx"]["properties"]
        assert ctx_props["user"]["description"] == "User information"
        # Nested models may use $ref (Pydantic default) or inline properties
        if "$ref" in ctx_props["user"]:
            # Using $ref - check $defs contains UserInfo
            assert "$defs" in result["properties"]["ctx"]
            user_info_def = result["properties"]["ctx"]["$defs"]["UserInfo"]
            assert user_info_def["properties"]["name"]["description"] == "User name"
            assert user_info_def["properties"]["role"]["description"] == "User role"
        else:
            # Inline properties
            assert "properties" in ctx_props["user"]
            assert ctx_props["user"]["properties"]["name"]["description"] == "User name"
            assert ctx_props["user"]["properties"]["role"]["description"] == "User role"
        assert ctx_props["task_type"]["description"] == "Task type"

    def test_fields_without_descriptions(self):
        """Test: Handle fields without descriptions (use type only)."""
        from mesh import MeshContextModel

        class MinimalContext(MeshContextModel):
            name: str
            age: int

        def process(ctx: MinimalContext):
            pass

        mock_tool = MagicMock()
        mock_tool.parameters = {
            "type": "object",
            "properties": {"ctx": {"type": "object"}},
        }
        process._fastmcp_tool = mock_tool

        result = FastMCPSchemaExtractor.extract_input_schema(process)

        ctx_props = result["properties"]["ctx"]["properties"]
        assert "name" in ctx_props
        assert ctx_props["name"]["type"] == "string"
        # No description field if not provided
        assert (
            "description" not in ctx_props["name"]
            or ctx_props["name"]["description"] == ""
        )

    def test_preserve_non_mesh_context_params(self):
        """Test: Preserve original schema for non-MeshContextModel params."""
        from pydantic import Field

        from mesh import MeshContextModel

        class AnalysisContext(MeshContextModel):
            domain: str = Field(description="Analysis domain")

        def analyze(query: str, ctx: AnalysisContext, limit: int):
            pass

        mock_tool = MagicMock()
        mock_tool.parameters = {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "ctx": {"type": "object"},
                "limit": {"type": "integer", "description": "Result limit"},
            },
        }
        analyze._fastmcp_tool = mock_tool

        result = FastMCPSchemaExtractor.extract_input_schema(analyze)

        # Non-MeshContextModel params preserved exactly
        assert result["properties"]["query"]["description"] == "Search query"
        assert result["properties"]["limit"]["description"] == "Result limit"

        # MeshContextModel param enhanced
        assert "domain" in result["properties"]["ctx"]["properties"]


class TestEnhancedSchemaGeneration:
    """Test complete enhanced schema generation (Phase 0.5 - TDD)."""

    def test_enhanced_schema_includes_descriptions(self):
        """Test: Enhanced schema includes MeshContextModel field descriptions."""
        from pydantic import Field

        from mesh import MeshContextModel

        class AnalysisContext(MeshContextModel):
            domain: str = Field(description="Analysis domain: infrastructure, security")
            user_level: str = Field(
                default="beginner",
                description="User expertise: beginner, intermediate, expert",
            )

        def analyze(query: str, ctx: AnalysisContext):
            pass

        mock_tool = MagicMock()
        mock_tool.parameters = {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "ctx": {"type": "object"},
            },
        }
        analyze._fastmcp_tool = mock_tool

        result = FastMCPSchemaExtractor.extract_input_schema(analyze)

        # Verify complete enhanced schema structure
        assert result["type"] == "object"
        assert "properties" in result

        # ctx should have enhanced schema
        ctx_schema = result["properties"]["ctx"]
        assert "properties" in ctx_schema
        assert "domain" in ctx_schema["properties"]
        assert (
            ctx_schema["properties"]["domain"]["description"]
            == "Analysis domain: infrastructure, security"
        )
        assert (
            ctx_schema["properties"]["user_level"]["description"]
            == "User expertise: beginner, intermediate, expert"
        )

    def test_enhanced_schema_includes_defaults(self):
        """Test: Enhanced schema includes default values."""
        from pydantic import Field

        from mesh import MeshContextModel

        class ConfigContext(MeshContextModel):
            timeout: int = Field(default=60, description="Timeout in seconds")
            max_retries: int = Field(default=3, description="Maximum retries")

        def configure(ctx: ConfigContext):
            pass

        mock_tool = MagicMock()
        mock_tool.parameters = {
            "type": "object",
            "properties": {"ctx": {"type": "object"}},
        }
        configure._fastmcp_tool = mock_tool

        result = FastMCPSchemaExtractor.extract_input_schema(configure)

        ctx_props = result["properties"]["ctx"]["properties"]
        assert ctx_props["timeout"]["default"] == 60
        assert ctx_props["max_retries"]["default"] == 3

    def test_enhanced_schema_marks_context_param(self):
        """Test: Enhanced schema marks context params with description."""
        from pydantic import Field

        from mesh import MeshContextModel

        class ChatContext(MeshContextModel):
            domain: str = Field(description="Chat domain")

        def chat(message: str, ctx: ChatContext):
            pass

        mock_tool = MagicMock()
        mock_tool.parameters = {
            "type": "object",
            "properties": {
                "message": {"type": "string"},
                "ctx": {"type": "object"},
            },
        }
        chat._fastmcp_tool = mock_tool

        result = FastMCPSchemaExtractor.extract_input_schema(chat)

        # ctx itself should be marked as context for prompt template
        ctx_schema = result["properties"]["ctx"]
        assert "description" in ctx_schema
        assert (
            "context" in ctx_schema["description"].lower()
            or "prompt" in ctx_schema["description"].lower()
        )

    def test_enhanced_schema_preserves_all_fields(self):
        """Test: Enhanced schema preserves all original fields."""
        from pydantic import Field

        from mesh import MeshContextModel

        class AnalysisContext(MeshContextModel):
            domain: str = Field(description="Analysis domain")

        def analyze(query: str, ctx: AnalysisContext, limit: int, offset: int):
            pass

        mock_tool = MagicMock()
        mock_tool.parameters = {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "ctx": {"type": "object"},
                "limit": {"type": "integer"},
                "offset": {"type": "integer"},
            },
            "required": ["query", "ctx"],
        }
        analyze._fastmcp_tool = mock_tool

        result = FastMCPSchemaExtractor.extract_input_schema(analyze)

        # All original fields preserved
        assert "query" in result["properties"]
        assert "ctx" in result["properties"]
        assert "limit" in result["properties"]
        assert "offset" in result["properties"]
        assert result["required"] == ["query", "ctx"]

    def test_schema_filtering_still_works(self):
        """Test: Schema filtering still works (dependency params removed)."""
        from pydantic import Field

        from mesh import MeshContextModel, MeshLlmAgent

        class AnalysisContext(MeshContextModel):
            domain: str = Field(description="Analysis domain")

        def analyze(query: str, ctx: AnalysisContext, llm: MeshLlmAgent = None):
            pass

        mock_tool = MagicMock()
        mock_tool.parameters = {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "ctx": {"type": "object"},
                # llm should be filtered out
            },
        }
        analyze._fastmcp_tool = mock_tool

        result = FastMCPSchemaExtractor.extract_input_schema(analyze)

        # llm parameter should not be in schema (dependency injection)
        assert "llm" not in result["properties"]

        # ctx should be enhanced
        assert "domain" in result["properties"]["ctx"]["properties"]

    def test_complete_schema_is_valid_json_schema(self):
        """Test: Complete schema sent to registry is valid JSON Schema."""
        from pydantic import Field

        from mesh import MeshContextModel

        class AnalysisContext(MeshContextModel):
            domain: str = Field(description="Analysis domain")
            focus_areas: list[str] = Field(
                default_factory=list, description="Focus areas"
            )

        def analyze(request: str, ctx: AnalysisContext):
            pass

        mock_tool = MagicMock()
        mock_tool.parameters = {
            "type": "object",
            "properties": {
                "request": {"type": "string"},
                "ctx": {"type": "object"},
            },
        }
        analyze._fastmcp_tool = mock_tool

        result = FastMCPSchemaExtractor.extract_input_schema(analyze)

        # Valid JSON Schema structure
        assert result["type"] == "object"
        assert "properties" in result
        assert isinstance(result["properties"], dict)

        # Each property is valid
        for prop_name, prop_schema in result["properties"].items():
            assert isinstance(prop_schema, dict)
            assert "type" in prop_schema or "$ref" in prop_schema  # Valid JSON Schema
