"""
Integration test for Phase 2: Schema Collection & Propagation.

This test verifies that inputSchemas from FastMCP tools are:
1. Extracted from FastMCP tool objects
2. Included in heartbeat payloads
3. Successfully sent to the registry

This is the critical test to prove Phase 2 is complete.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from _mcp_mesh.engine.decorator_registry import DecoratedFunction
from _mcp_mesh.pipeline.mcp_startup.heartbeat_preparation import (
    HeartbeatPreparationStep,
)


class TestPhase2SchemaToRegistry:
    """Test that inputSchemas reach the registry (Phase 2 completion test)."""

    @pytest.fixture
    def mock_agent_config(self):
        """Mock agent configuration."""
        return {
            "agent_id": "test-agent-phase2",
            "name": "test-agent",
            "version": "1.0.0",
            "http_host": "localhost",
            "http_port": 8080,
            "namespace": "default",
        }

    @pytest.fixture
    def create_fastmcp_tool_with_schema(self):
        """Factory to create mock FastMCP tools with schemas."""

        def _create(name: str, schema: dict):
            mock_tool = MagicMock()
            mock_tool.name = name
            mock_tool.inputSchema = schema

            mock_func = MagicMock()
            mock_func.__name__ = name
            mock_func._fastmcp_tool = mock_tool

            return mock_func

        return _create

    @pytest.mark.asyncio
    async def test_schema_included_in_registration_payload(
        self, mock_agent_config, create_fastmcp_tool_with_schema
    ):
        """Test that inputSchema is included in registration data sent to registry."""
        # Create a tool with a realistic schema
        schema = {
            "type": "object",
            "properties": {
                "user_email": {
                    "type": "string",
                    "format": "email",
                    "description": "User's email address",
                },
                "avatar_id": {
                    "type": "string",
                    "description": "Avatar identifier",
                },
                "prompt": {
                    "type": "string",
                    "description": "Image generation prompt",
                },
                "width": {
                    "type": "integer",
                    "minimum": 512,
                    "maximum": 2048,
                    "default": 768,
                },
            },
            "required": ["user_email", "avatar_id", "prompt"],
        }

        mock_func = create_fastmcp_tool_with_schema("generate_image", schema)

        mesh_tools = {
            "generate_image": DecoratedFunction(
                decorator_type="mesh_tool",
                function=mock_func,
                metadata={
                    "capability": "generate_image",
                    "tags": ["image", "ai"],
                    "version": "1.0.0",
                    "description": "Generate AI images",
                    "dependencies": [],
                },
                registered_at=MagicMock(),
            )
        }

        step = HeartbeatPreparationStep()

        with patch(
            "_mcp_mesh.pipeline.mcp_startup.heartbeat_preparation.DecoratorRegistry"
        ) as mock_registry:
            mock_registry.get_mesh_tools.return_value = mesh_tools
            mock_registry.get_resolved_agent_config.return_value = mock_agent_config

            result = await step.execute({})

            # Verify heartbeat succeeded
            assert result.status.name == "SUCCESS"

            # Get registration payload that would be sent to registry
            registration_data = result.context["registration_data"]
            tools_list = registration_data["tools"]

            # Verify tool is in the list
            assert len(tools_list) == 1
            tool_data = tools_list[0]

            # CRITICAL: Verify inputSchema is in the payload
            assert (
                "input_schema" in tool_data
            ), "input_schema must be in registry payload"
            assert (
                tool_data["input_schema"] is not None
            ), "input_schema must not be None"

            # Verify schema content is preserved exactly
            assert tool_data["input_schema"] == schema
            assert tool_data["input_schema"]["type"] == "object"
            assert "user_email" in tool_data["input_schema"]["properties"]
            assert "avatar_id" in tool_data["input_schema"]["properties"]
            assert "prompt" in tool_data["input_schema"]["properties"]
            assert "width" in tool_data["input_schema"]["properties"]
            assert tool_data["input_schema"]["required"] == [
                "user_email",
                "avatar_id",
                "prompt",
            ]

            # Verify other tool metadata is still present
            assert tool_data["function_name"] == "generate_image"
            assert tool_data["capability"] == "generate_image"
            assert tool_data["tags"] == ["image", "ai"]

    @pytest.mark.asyncio
    async def test_multiple_tools_with_schemas_all_sent(
        self, mock_agent_config, create_fastmcp_tool_with_schema
    ):
        """Test that multiple tools with different schemas are all sent to registry."""
        # Create 3 tools with different schemas
        schema1 = {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        }

        schema2 = {
            "type": "object",
            "properties": {
                "url": {"type": "string", "format": "uri"},
                "timeout": {"type": "integer", "default": 30},
            },
            "required": ["url"],
        }

        schema3 = {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 100},
            },
            "required": ["query"],
        }

        mesh_tools = {
            "process_text": DecoratedFunction(
                decorator_type="mesh_tool",
                function=create_fastmcp_tool_with_schema("process_text", schema1),
                metadata={"capability": "text_processing", "dependencies": []},
                registered_at=MagicMock(),
            ),
            "fetch_url": DecoratedFunction(
                decorator_type="mesh_tool",
                function=create_fastmcp_tool_with_schema("fetch_url", schema2),
                metadata={"capability": "web_fetch", "dependencies": []},
                registered_at=MagicMock(),
            ),
            "search_db": DecoratedFunction(
                decorator_type="mesh_tool",
                function=create_fastmcp_tool_with_schema("search_db", schema3),
                metadata={"capability": "database_search", "dependencies": []},
                registered_at=MagicMock(),
            ),
        }

        step = HeartbeatPreparationStep()

        with patch(
            "_mcp_mesh.pipeline.mcp_startup.heartbeat_preparation.DecoratorRegistry"
        ) as mock_registry:
            mock_registry.get_mesh_tools.return_value = mesh_tools
            mock_registry.get_resolved_agent_config.return_value = mock_agent_config

            result = await step.execute({})

            registration_data = result.context["registration_data"]
            tools_list = registration_data["tools"]

            # Verify all 3 tools are in the payload
            assert len(tools_list) == 3

            # Find each tool and verify its schema
            tools_by_name = {t["function_name"]: t for t in tools_list}

            # Verify process_text
            assert "process_text" in tools_by_name
            assert tools_by_name["process_text"]["input_schema"] == schema1

            # Verify fetch_url
            assert "fetch_url" in tools_by_name
            assert tools_by_name["fetch_url"]["input_schema"] == schema2

            # Verify search_db
            assert "search_db" in tools_by_name
            assert tools_by_name["search_db"]["input_schema"] == schema3

    @pytest.mark.asyncio
    async def test_schema_survives_json_serialization(
        self, mock_agent_config, create_fastmcp_tool_with_schema
    ):
        """Test that schemas can be JSON serialized (required for HTTP transport)."""
        # Create a complex schema
        complex_schema = {
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
                "optional": {"type": "boolean", "default": False},
            },
            "required": ["simple", "nested"],
        }

        mock_func = create_fastmcp_tool_with_schema("complex_tool", complex_schema)

        mesh_tools = {
            "complex_tool": DecoratedFunction(
                decorator_type="mesh_tool",
                function=mock_func,
                metadata={"capability": "complex", "dependencies": []},
                registered_at=MagicMock(),
            )
        }

        step = HeartbeatPreparationStep()

        with patch(
            "_mcp_mesh.pipeline.mcp_startup.heartbeat_preparation.DecoratorRegistry"
        ) as mock_registry:
            mock_registry.get_mesh_tools.return_value = mesh_tools
            mock_registry.get_resolved_agent_config.return_value = mock_agent_config

            result = await step.execute({})

            registration_data = result.context["registration_data"]
            tools_list = registration_data["tools"]

            # Extract the schema
            schema_from_payload = tools_list[0]["input_schema"]

            # CRITICAL: Test JSON serialization (required for HTTP transport to registry)
            try:
                json_str = json.dumps(schema_from_payload)
                deserialized = json.loads(json_str)

                # Verify schema survives round-trip
                assert deserialized == complex_schema
                assert (
                    deserialized["properties"]["nested"]["properties"]["inner"]["type"]
                    == "number"
                )
                assert deserialized["required"] == ["simple", "nested"]

            except (TypeError, ValueError) as e:
                pytest.fail(f"Schema failed JSON serialization: {e}")

    @pytest.mark.asyncio
    async def test_mixed_tools_with_and_without_schemas(
        self, mock_agent_config, create_fastmcp_tool_with_schema
    ):
        """Test that tools with and without schemas coexist in registry payload."""
        # Tool 1: Has FastMCP schema
        tool_with_schema = create_fastmcp_tool_with_schema(
            "tool_with_schema",
            {"type": "object", "properties": {"x": {"type": "string"}}},
        )

        # Tool 2: Plain function without FastMCP
        plain_func = MagicMock(spec=["__name__", "__call__"])
        plain_func.__name__ = "plain_tool"

        mesh_tools = {
            "tool_with_schema": DecoratedFunction(
                decorator_type="mesh_tool",
                function=tool_with_schema,
                metadata={"capability": "with_schema", "dependencies": []},
                registered_at=MagicMock(),
            ),
            "plain_tool": DecoratedFunction(
                decorator_type="mesh_tool",
                function=plain_func,
                metadata={"capability": "plain", "dependencies": []},
                registered_at=MagicMock(),
            ),
        }

        step = HeartbeatPreparationStep()

        with patch(
            "_mcp_mesh.pipeline.mcp_startup.heartbeat_preparation.DecoratorRegistry"
        ) as mock_registry:
            mock_registry.get_mesh_tools.return_value = mesh_tools
            mock_registry.get_resolved_agent_config.return_value = mock_agent_config

            result = await step.execute({})

            registration_data = result.context["registration_data"]
            tools_list = registration_data["tools"]

            # Both tools should be in payload
            assert len(tools_list) == 2

            tools_by_name = {t["function_name"]: t for t in tools_list}

            # Tool with schema should have input_schema set
            assert tools_by_name["tool_with_schema"]["input_schema"] is not None
            assert tools_by_name["tool_with_schema"]["input_schema"]["type"] == "object"

            # Plain tool should have input_schema = None
            assert tools_by_name["plain_tool"]["input_schema"] is None

            # Both should still be sent to registry
            assert "capability" in tools_by_name["tool_with_schema"]
            assert "capability" in tools_by_name["plain_tool"]


class TestPhase2Completion:
    """Final verification that Phase 2 is complete."""

    @pytest.mark.asyncio
    async def test_phase2_complete_end_to_end(self):
        """
        End-to-end test proving Phase 2 is complete.

        When an agent with FastMCP tools registers:
        1. FastMCP schemas are extracted
        2. Schemas are included in heartbeat payload
        3. Payload contains all required fields for registry storage
        """
        # Simulate a realistic agent with multiple FastMCP tools
        tools = {}

        # Tool 1: Image generation (complex schema)
        img_tool = MagicMock()
        img_tool.name = "generate_image"
        img_tool.inputSchema = {
            "type": "object",
            "properties": {
                "prompt": {"type": "string"},
                "width": {"type": "integer", "default": 768},
                "height": {"type": "integer", "default": 1024},
            },
            "required": ["prompt"],
        }
        img_func = MagicMock()
        img_func.__name__ = "generate_image"
        img_func._fastmcp_tool = img_tool

        tools["generate_image"] = DecoratedFunction(
            decorator_type="mesh_tool",
            function=img_func,
            metadata={
                "capability": "generate_image",
                "version": "1.0.0",
                "tags": ["image", "ai"],
                "dependencies": [],
            },
            registered_at=MagicMock(),
        )

        # Tool 2: Text processing (simple schema)
        text_tool = MagicMock()
        text_tool.name = "process_text"
        text_tool.inputSchema = {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        }
        text_func = MagicMock()
        text_func.__name__ = "process_text"
        text_func._fastmcp_tool = text_tool

        tools["process_text"] = DecoratedFunction(
            decorator_type="mesh_tool",
            function=text_func,
            metadata={
                "capability": "text_processing",
                "version": "1.0.0",
                "dependencies": [],
            },
            registered_at=MagicMock(),
        )

        step = HeartbeatPreparationStep()
        agent_config = {
            "agent_id": "phase2-completion-test",
            "version": "1.0.0",
            "http_host": "localhost",
            "http_port": 8080,
        }

        with patch(
            "_mcp_mesh.pipeline.mcp_startup.heartbeat_preparation.DecoratorRegistry"
        ) as mock_registry:
            mock_registry.get_mesh_tools.return_value = tools
            mock_registry.get_resolved_agent_config.return_value = agent_config

            result = await step.execute({})

            # Phase 2 completion criteria:
            assert result.status.name == "SUCCESS"

            registration_data = result.context["registration_data"]
            tools_list = registration_data["tools"]

            # 1. Both tools present
            assert len(tools_list) == 2

            # 2. Both tools have inputSchema
            for tool in tools_list:
                assert (
                    "input_schema" in tool
                ), f"Tool {tool['function_name']} missing input_schema"

            # 3. Schemas are correct
            tools_by_name = {t["function_name"]: t for t in tools_list}

            assert (
                tools_by_name["generate_image"]["input_schema"] == img_tool.inputSchema
            )
            assert (
                tools_by_name["process_text"]["input_schema"] == text_tool.inputSchema
            )

            # 4. Schemas are JSON-serializable (can be sent over HTTP)
            try:
                json.dumps(tools_list)
            except (TypeError, ValueError) as e:
                pytest.fail(f"Tools list not JSON serializable: {e}")

            # 5. All registry-required fields present
            for tool in tools_list:
                assert "function_name" in tool
                assert "capability" in tool
                assert "version" in tool
                assert "input_schema" in tool
                assert "dependencies" in tool

            # SUCCESS: Phase 2 is complete!
            # - FastMCP schemas extracted ✅
            # - Included in heartbeat payload ✅
            # - Ready to be sent to registry ✅
