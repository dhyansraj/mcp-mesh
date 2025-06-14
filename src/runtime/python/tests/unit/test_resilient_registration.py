"""
Unit tests for resilient registration behavior.

Tests that agents continue with health monitoring even when initial registration fails.
"""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import jsonschema
import pytest
import yaml

from mcp_mesh import DecoratorRegistry
from mcp_mesh.runtime.processor import DecoratorProcessor, MeshAgentProcessor
from mcp_mesh.runtime.registry_client import RegistryClient


def load_openapi_schema():
    """Load the OpenAPI schema for validation."""
    # Find the API spec file relative to the project root
    current_dir = Path(__file__).parent
    project_root = (
        current_dir.parent.parent.parent.parent.parent
    )  # Go up to project root
    api_spec_path = project_root / "api" / "mcp-mesh-registry.openapi.yaml"

    if not api_spec_path.exists():
        pytest.skip(f"OpenAPI spec not found at {api_spec_path}")

    with open(api_spec_path) as f:
        return yaml.safe_load(f)


def fix_schema_refs(schema_obj):
    """Recursively fix $ref paths from #/components/schemas/ to #/definitions/"""
    if isinstance(schema_obj, dict):
        if "$ref" in schema_obj:
            ref = schema_obj["$ref"]
            if ref.startswith("#/components/schemas/"):
                schema_obj["$ref"] = ref.replace(
                    "#/components/schemas/", "#/definitions/"
                )
        for key, value in schema_obj.items():
            fix_schema_refs(value)
    elif isinstance(schema_obj, list):
        for item in schema_obj:
            fix_schema_refs(item)


def validate_agent_registration_request(payload):
    """Validate agent registration payload against OpenAPI schema."""
    schema = load_openapi_schema()

    # Fix all $ref paths in the components
    components = schema["components"]["schemas"].copy()
    fix_schema_refs(components)

    # Use the new flattened MeshAgentRegistration schema
    complete_schema = {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "$ref": "#/definitions/MeshAgentRegistration",
        "definitions": components,
    }

    # Validate the payload directly (no metadata wrapper needed)
    try:
        jsonschema.validate(instance=payload, schema=complete_schema)
        return True
    except jsonschema.ValidationError as e:
        pytest.fail(f"OpenAPI schema validation failed: {e.message}")
    except Exception as e:
        pytest.fail(f"Schema validation error: {e}")


class TestResilientRegistration:
    """Test resilient registration behavior when registry is unavailable."""

    @pytest.fixture
    def mock_registry_client(self):
        """Create a mock registry client."""
        client = AsyncMock(spec=RegistryClient)
        client.url = "http://localhost:8000"
        return client

    @pytest.fixture
    def processor(self, mock_registry_client):
        """Create a processor with mocked registry client."""
        processor = DecoratorProcessor("http://localhost:8000")
        processor.registry_client = mock_registry_client
        processor.mesh_agent_processor = MeshAgentProcessor(mock_registry_client)
        processor.mesh_agent_processor.registry_client = mock_registry_client
        return processor

    @pytest.mark.asyncio
    async def test_health_monitor_starts_when_registration_fails(self, processor):
        """Test that health monitoring starts even if initial registration fails."""
        # Capture ALL requests sent to registry (registration + heartbeats)
        captured_requests = []

        async def mock_post(url, json=None, **kwargs):
            nonlocal captured_requests
            request_type = "heartbeat" if "heartbeat" in url else "registration"
            print(f"🔍 Captured {request_type} request to {url}")
            if json:
                print(f"   Payload keys: {list(json.keys())}")
            captured_requests.append(
                {"url": url, "payload": json, "type": request_type}
            )
            return MagicMock(
                status=500, json=AsyncMock(return_value={"error": "Connection failed"})
            )

        # Setup: Mock registry to fail all requests but capture them
        processor.mesh_agent_processor.registry_client.post = AsyncMock(
            side_effect=mock_post
        )

        # Create a test function with metadata
        test_func = MagicMock(__name__="test_agent")
        metadata = {
            "capability": "test",
            "capabilities": ["test"],
            "health_interval": 30,
            "dependencies": [],
            "agent_name": "test_agent",
        }

        # Process the agent
        result = await processor.mesh_agent_processor.process_single_agent(
            "test_agent", MagicMock(function=test_func, metadata=metadata)
        )

        # Wait longer for health monitor to send heartbeat requests
        await asyncio.sleep(0.5)

        # Verify we captured requests and validate them
        assert len(captured_requests) > 0, "No requests were captured"

        # Validate registration requests
        registration_requests = [
            r for r in captured_requests if r["type"] == "registration"
        ]
        assert len(registration_requests) > 0, "No registration requests captured"

        for req in registration_requests:
            validate_agent_registration_request(req["payload"])
            print(
                f"✅ Registration request to {req['url']} validates against OpenAPI schema"
            )

        # Show what heartbeat requests were sent (if any)
        heartbeat_requests = [r for r in captured_requests if r["type"] == "heartbeat"]
        if heartbeat_requests:
            print(
                f"📡 Health monitor sent {len(heartbeat_requests)} heartbeat requests via POST"
            )
            for req in heartbeat_requests:
                print(f"   - Heartbeat to {req['url']}: {req['payload']}")

        print(
            f"📊 Total requests captured: {len(captured_requests)} ({len(registration_requests)} registration, {len(heartbeat_requests)} heartbeat)"
        )

        # Verify health monitor was started despite registration failure
        assert result is True  # Should return True for standalone mode
        assert len(processor.mesh_agent_processor._health_tasks) == 1
        assert "test_agent" in processor.mesh_agent_processor._health_tasks
        assert (
            "test_agent" not in processor.mesh_agent_processor._processed_agents
        )  # Not marked as processed

        # Cleanup
        task = processor.mesh_agent_processor._health_tasks["test_agent"]
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    @pytest.mark.asyncio
    async def test_heartbeat_uses_same_format_as_registration(self):
        """Test that heartbeat requests use the same MeshAgentRegistration format."""
        # Create a real registry client instance for testing
        from mcp_mesh.runtime.registry_client import RegistryClient

        # Capture heartbeat request payload directly
        captured_heartbeat_payload = None

        async def mock_make_request(method, url, json=None, **kwargs):
            nonlocal captured_heartbeat_payload
            print(f"🔍 _make_request called: {method} {url}")
            if "/heartbeat" in url:
                captured_heartbeat_payload = json
                print(f"✅ Captured heartbeat request: {method} {url}")
                print(f"   Payload keys: {list(json.keys()) if json else 'None'}")
            return {"status": "success"}  # Return dict directly

        # Create real registry client and mock its _make_request method
        registry_client = RegistryClient("http://localhost:8000")
        registry_client._make_request = AsyncMock(side_effect=mock_make_request)

        # Create a HealthStatus object for heartbeat testing
        from datetime import datetime, timezone

        from mcp_mesh.runtime.shared.types import HealthStatus, HealthStatusType

        health_status = HealthStatus(
            agent_name="test_agent",
            status=HealthStatusType.HEALTHY,
            capabilities=["test_capability"],
            timestamp=datetime.now(timezone.utc),
            checks={},
            errors=[],
            uptime_seconds=0,
            version="1.0.0",
            metadata={
                "endpoint": "stdio://test_agent",
                "health_interval": 30,
                "description": "Test agent",
            },
        )

        # Send heartbeat directly using real client
        print("📡 Calling send_heartbeat...")
        result = await registry_client.send_heartbeat(health_status)
        print(f"📡 Heartbeat result: {result}")

        # Verify heartbeat payload was captured and validates against schema
        assert (
            captured_heartbeat_payload is not None
        ), "No heartbeat payload was captured"
        validate_agent_registration_request(captured_heartbeat_payload)
        print(
            "✅ Heartbeat request payload validates against MeshAgentRegistration schema"
        )
        print(
            "✅ Heartbeat uses same format as registration - unified approach working!"
        )

        # Verify expected MeshAgentRegistration fields are present
        expected_fields = ["agent_id", "tools", "agent_type", "timestamp"]
        for field in expected_fields:
            assert (
                field in captured_heartbeat_payload
            ), f"Missing required field: {field}"

        # Verify tools array format
        assert isinstance(
            captured_heartbeat_payload["tools"], list
        ), "tools should be an array"
        assert (
            len(captured_heartbeat_payload["tools"]) > 0
        ), "tools array should not be empty"

        tool = captured_heartbeat_payload["tools"][0]
        assert "function_name" in tool, "tool missing function_name"
        assert "capability" in tool, "tool missing capability"

        print(
            "✅ All required MeshAgentRegistration fields present in heartbeat payload"
        )
        print(
            "✅ Simplified heartbeat logic - always sends to /heartbeat, registry handles the rest!"
        )

    @pytest.mark.asyncio
    async def test_health_monitor_continues_sending_heartbeats(self, processor):
        """Test that health monitor continues sending heartbeats regardless of failures."""
        # Capture all heartbeat requests
        captured_heartbeat_calls = []

        async def mock_send_heartbeat(health_status):
            captured_heartbeat_calls.append(
                {
                    "agent_name": health_status.agent_name,
                    "capabilities": health_status.capabilities,
                    "timestamp": health_status.timestamp.isoformat(),
                }
            )
            return {"status": "success"}  # Return dict response

        # Mock registration to fail
        processor.mesh_agent_processor.registry_client.post = AsyncMock(
            return_value=MagicMock(
                status=500, json=AsyncMock(return_value={"error": "Connection failed"})
            )
        )

        # Mock heartbeat to track calls
        processor.mesh_agent_processor.registry_client.send_heartbeat_with_response = (
            AsyncMock(side_effect=mock_send_heartbeat)
        )

        # Create test agent
        test_func = MagicMock(__name__="test_agent")
        metadata = {
            "capability": "test",
            "capabilities": ["test"],
            "health_interval": 0.1,  # Very short for testing
            "dependencies": [],
            "agent_name": "test_agent",
        }

        # Process agent (registration fails but health monitor starts)
        result = await processor.mesh_agent_processor.process_single_agent(
            "test_agent", MagicMock(function=test_func, metadata=metadata)
        )

        assert result is True
        assert "test_agent" not in processor.mesh_agent_processor._processed_agents

        # Wait for multiple heartbeats
        await asyncio.sleep(0.35)

        # Verify multiple heartbeats were sent
        assert (
            len(captured_heartbeat_calls) >= 3
        ), f"Expected at least 3 heartbeats, got {len(captured_heartbeat_calls)}"

        # Verify all heartbeats are for the same agent
        for call in captured_heartbeat_calls:
            assert call["agent_name"] == "test_agent"
            assert call["capabilities"] == ["test"]

        print(
            f"✅ Health monitor sent {len(captured_heartbeat_calls)} heartbeats successfully"
        )
        print(
            "✅ Simplified architecture: no registration retries, just continuous heartbeats"
        )

        # Cleanup
        task = processor.mesh_agent_processor._health_tasks["test_agent"]
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    @pytest.mark.asyncio
    async def test_multiple_agents_resilient_registration(self, processor):
        """Test multiple agents can work in standalone mode."""
        # Setup: Registry always fails
        processor.mesh_agent_processor.registry_client.post = AsyncMock(
            return_value=MagicMock(
                status=500, json=AsyncMock(return_value={"error": "Connection failed"})
            )
        )
        processor.mesh_agent_processor.registry_client.send_heartbeat = AsyncMock(
            return_value=False
        )

        # Create multiple test agents
        agents = []
        for i in range(3):
            test_func = MagicMock(__name__=f"test_agent_{i}")
            metadata = {
                "capability": f"test_{i}",
                "capabilities": [f"test_{i}"],
                "health_interval": 30,
                "dependencies": [],
                "agent_name": f"test_agent_{i}",
            }
            agents.append(
                (f"test_agent_{i}", MagicMock(function=test_func, metadata=metadata))
            )

        # Process all agents
        results = {}
        for name, agent in agents:
            results[name] = await processor.mesh_agent_processor.process_single_agent(
                name, agent
            )

        # All should succeed in standalone mode
        assert all(results.values())
        assert len(processor.mesh_agent_processor._health_tasks) == 3
        assert (
            len(processor.mesh_agent_processor._processed_agents) == 0
        )  # None registered

        # Cleanup
        for task in processor.mesh_agent_processor._health_tasks.values():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    @pytest.mark.asyncio
    async def test_dependency_injection_after_late_registration(self, processor):
        """Test that dependency injection is set up after late registration."""
        # Mock the internal registration method
        call_count = 0

        async def mock_register(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return None  # First attempt fails
            else:
                return {"status": "success"}  # Second attempt succeeds

        processor.mesh_agent_processor._register_with_mesh_registry = AsyncMock(
            side_effect=mock_register
        )

        processor.mesh_agent_processor.registry_client.send_heartbeat = AsyncMock(
            side_effect=[False, True]
        )

        # Mock the dependency injection setup
        processor.mesh_agent_processor._setup_dependency_injection = AsyncMock()

        # Create test agent with dependencies
        test_func = MagicMock(__name__="test_agent")
        metadata = {
            "capability": "test",
            "capabilities": ["test"],
            "health_interval": 0.1,
            "dependencies": ["ServiceA", "ServiceB"],
            "agent_name": "test_agent",
        }

        decorated_func = MagicMock(function=test_func, metadata=metadata)

        # Mock DecoratorRegistry to return our function
        with patch.object(
            DecoratorRegistry,
            "get_mesh_agents",
            return_value={"test_agent": decorated_func},
        ):
            # Process agent
            await processor.mesh_agent_processor.process_single_agent(
                "test_agent", decorated_func
            )

            # Initially, dependency injection should not be called (registration failed)
            processor.mesh_agent_processor._setup_dependency_injection.assert_not_called()

            # Wait for retry and dependency injection setup
            await asyncio.sleep(0.3)

            # After successful retry, dependency injection should be set up
            processor.mesh_agent_processor._setup_dependency_injection.assert_called_once_with(
                decorated_func
            )

        # Cleanup
        task = processor.mesh_agent_processor._health_tasks["test_agent"]
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
