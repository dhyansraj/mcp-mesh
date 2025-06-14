"""
Test MCP Mesh registration system - TDD approach.

Starting with basic skeleton and adding tests incrementally.
"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from mcp.server.fastmcp import FastMCP

import mesh
from mcp_mesh.registry_client_generated.mcp_mesh_registry_client.models.mesh_agent_registration import (
    MeshAgentRegistration,
)
from mcp_mesh.runtime.registry_client import RegistryClient


class TestMeshRegistration:
    """Test the new MCP Mesh registration system."""

    @pytest.mark.asyncio
    async def test_basic_tool_registration_with_schema_validation(self):
        """Test basic @mesh.tool registration and validate against OpenAPI schema."""
        # Clear any existing decorators
        from mcp_mesh import DecoratorRegistry

        DecoratorRegistry.clear_all()

        # Mock registry to capture the request
        captured_request_body = None

        async def capture_post(endpoint, **kwargs):
            nonlocal captured_request_body
            # Capture the request body from json parameter
            captured_request_body = kwargs.get("json")

            return MagicMock(
                status=201,
                json=AsyncMock(
                    return_value={"status": "success", "agent_id": "test-agent"}
                ),
            )

        mock_registry = AsyncMock(spec=RegistryClient)
        mock_registry.post = AsyncMock(side_effect=capture_post)

        # Create server and simple tool
        server = FastMCP("test-basic")

        @server.tool()
        @mesh.tool(capability="greeting")
        def greet(name: str) -> str:
            return f"Hello {name}"

        # Process registration
        from mcp_mesh.runtime.processor import DecoratorProcessor

        processor = DecoratorProcessor("http://localhost:8080")
        processor.registry_client = mock_registry
        processor.mesh_tool_processor.registry_client = mock_registry

        # Debug: Verify the mock is set correctly
        print(
            f"🔍 DecoratorProcessor registry_client: {type(processor.registry_client)}"
        )
        print(
            f"🔍 MeshToolProcessor registry_client: {type(processor.mesh_tool_processor.registry_client)}"
        )
        print(
            f"🔍 Mock registry post method: {processor.mesh_tool_processor.registry_client.post}"
        )

        await processor.process_all_decorators()

        # Basic assertion - registration was called
        assert mock_registry.post.call_count == 1
        assert captured_request_body is not None

        # Parse captured request body
        if isinstance(captured_request_body, str):
            request_data = json.loads(captured_request_body)
        else:
            request_data = captured_request_body

        # Validate against OpenAPI schema using generated models
        try:
            # Create MeshAgentRegistration instance to validate structure
            agent_registration = MeshAgentRegistration.from_dict(request_data)

            # Validate required fields exist
            assert hasattr(agent_registration, "agent_id")
            assert hasattr(agent_registration, "tools")
            assert agent_registration.agent_id is not None
            assert agent_registration.tools is not None
            assert len(agent_registration.tools) >= 1

            # Validate tool structure
            tool = agent_registration.tools[0]
            if hasattr(tool, "function_name"):
                assert tool.function_name == "greet"
            if hasattr(tool, "capability"):
                assert tool.capability == "greeting"

            print(
                f"✅ Schema validation passed for agent_id: {agent_registration.agent_id}"
            )
            print(
                f"✅ Tool registered: {tool.function_name if hasattr(tool, 'function_name') else 'unknown'} -> {tool.capability if hasattr(tool, 'capability') else 'unknown'}"
            )

        except Exception as e:
            print(f"❌ Schema validation failed: {e}")
            print(f"📋 Captured request body: {json.dumps(request_data, indent=2)}")
            raise AssertionError(f"Request body validation failed: {e}")

        print("✅ Basic tool registration with schema validation passed")
