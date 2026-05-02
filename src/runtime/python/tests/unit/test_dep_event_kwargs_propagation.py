"""Unit tests for issue #645 bugs 1+2: producer @mesh.tool kwargs must reach
the consumer-side proxy via the registry's resolved dependency event.

Before the fix:
- Consumer's heartbeat handler read ``dependencies[idx]["kwargs"]`` (the
  CONSUMER's declared dep kwargs), which is almost always empty because
  consumers don't predict producer behavior.
- API gateways constructed ``EnhancedUnifiedMCPProxy`` without any
  kwargs_config at all — so even when the producer correctly advertised
  ``stream_type=text``, the gateway-side proxy had no idea.

After the fix:
- The Rust core's dependency_available / dependency_changed events carry a
  ``kwargs`` JSON string (the producer's @mesh.tool kwargs).
- Both the MCP heartbeat path AND the API heartbeat path parse that JSON and
  pass it as ``kwargs_config=`` to the proxy.
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# MCP heartbeat path (rust_heartbeat.py)
# ---------------------------------------------------------------------------


class TestMcpHeartbeatProducerKwargs:
    @pytest.mark.asyncio
    async def test_position_path_passes_producer_kwargs_to_proxy(self):
        """When event.kwargs has stream_type=text, proxy must see it."""
        from _mcp_mesh.engine.decorator_registry import DecoratorRegistry
        from _mcp_mesh.pipeline.mcp_heartbeat import rust_heartbeat

        DecoratorRegistry.clear_all()

        # A consumer with a single ``chat`` dependency and no consumer-side kwargs.
        async def consumer(prompt: str, chat=None):
            return chat

        DecoratorRegistry.register_mesh_tool(
            consumer,
            {
                "capability": "consumer_tool",
                "dependencies": [{"capability": "chat"}],
            },
        )

        captured_kwargs: dict = {}

        class FakeProxy:
            def __init__(self, endpoint, function_name, kwargs_config=None):
                captured_kwargs["endpoint"] = endpoint
                captured_kwargs["function_name"] = function_name
                captured_kwargs["kwargs_config"] = kwargs_config

        injector = MagicMock()
        injector.register_dependency = AsyncMock()
        injector.unregister_dependency = AsyncMock()

        with patch(
            "_mcp_mesh.engine.dependency_injector.get_global_injector",
            return_value=injector,
        ), patch(
            "_mcp_mesh.engine.unified_mcp_proxy.EnhancedUnifiedMCPProxy", FakeProxy
        ):
            await rust_heartbeat._handle_dependency_change(
                capability="chat",
                endpoint="http://producer:9170",
                function_name="chat",
                agent_id="producer-id",
                available=True,
                context={},
                requesting_function="consumer",
                dep_index=0,
                producer_kwargs=json.dumps({"stream_type": "text", "timeout": 90}),
            )

        assert captured_kwargs["endpoint"] == "http://producer:9170"
        assert captured_kwargs["function_name"] == "chat"
        assert captured_kwargs["kwargs_config"] == {
            "stream_type": "text",
            "timeout": 90,
        }
        injector.register_dependency.assert_awaited_once()

        DecoratorRegistry.clear_all()

    @pytest.mark.asyncio
    async def test_position_path_no_producer_kwargs_yields_empty_config(self):
        """When the producer ships no kwargs the proxy still gets ``{}``."""
        from _mcp_mesh.engine.decorator_registry import DecoratorRegistry
        from _mcp_mesh.pipeline.mcp_heartbeat import rust_heartbeat

        DecoratorRegistry.clear_all()

        async def consumer(prompt: str, chat=None):
            return chat

        DecoratorRegistry.register_mesh_tool(
            consumer,
            {
                "capability": "consumer_tool",
                "dependencies": [{"capability": "chat"}],
            },
        )

        captured_kwargs: dict = {}

        class FakeProxy:
            def __init__(self, endpoint, function_name, kwargs_config=None):
                captured_kwargs["kwargs_config"] = kwargs_config

        injector = MagicMock()
        injector.register_dependency = AsyncMock()

        with patch(
            "_mcp_mesh.engine.dependency_injector.get_global_injector",
            return_value=injector,
        ), patch(
            "_mcp_mesh.engine.unified_mcp_proxy.EnhancedUnifiedMCPProxy", FakeProxy
        ):
            await rust_heartbeat._handle_dependency_change(
                capability="chat",
                endpoint="http://producer:9170",
                function_name="chat",
                agent_id="producer-id",
                available=True,
                context={},
                requesting_function="consumer",
                dep_index=0,
                producer_kwargs=None,
            )

        assert captured_kwargs["kwargs_config"] == {}
        DecoratorRegistry.clear_all()

    @pytest.mark.asyncio
    async def test_position_path_invalid_json_logs_warning_and_falls_back(self, caplog):
        from _mcp_mesh.engine.decorator_registry import DecoratorRegistry
        from _mcp_mesh.pipeline.mcp_heartbeat import rust_heartbeat

        DecoratorRegistry.clear_all()

        async def consumer(prompt: str, chat=None):
            return chat

        DecoratorRegistry.register_mesh_tool(
            consumer,
            {
                "capability": "consumer_tool",
                "dependencies": [{"capability": "chat"}],
            },
        )

        captured_kwargs: dict = {}

        class FakeProxy:
            def __init__(self, endpoint, function_name, kwargs_config=None):
                captured_kwargs["kwargs_config"] = kwargs_config

        injector = MagicMock()
        injector.register_dependency = AsyncMock()

        with caplog.at_level("WARNING"), patch(
            "_mcp_mesh.engine.dependency_injector.get_global_injector",
            return_value=injector,
        ), patch(
            "_mcp_mesh.engine.unified_mcp_proxy.EnhancedUnifiedMCPProxy", FakeProxy
        ):
            await rust_heartbeat._handle_dependency_change(
                capability="chat",
                endpoint="http://producer:9170",
                function_name="chat",
                agent_id="producer-id",
                available=True,
                context={},
                requesting_function="consumer",
                dep_index=0,
                producer_kwargs="not-json{",
            )

        assert captured_kwargs["kwargs_config"] == {}
        assert any(
            "Could not parse producer kwargs" in r.message for r in caplog.records
        )
        DecoratorRegistry.clear_all()

    @pytest.mark.asyncio
    async def test_event_dispatch_threads_kwargs_into_handler(self):
        """The event dispatcher must forward ``event.kwargs`` to the handler."""
        from _mcp_mesh.pipeline.mcp_heartbeat import rust_heartbeat

        event = SimpleNamespace(
            event_type="dependency_available",
            capability="chat",
            endpoint="http://producer:9170",
            function_name="chat",
            agent_id="producer-id",
            requesting_function="consumer",
            dep_index=0,
            kwargs=json.dumps({"stream_type": "text"}),
        )

        with patch.object(
            rust_heartbeat,
            "_handle_dependency_change",
            new=AsyncMock(),
        ) as mock_handle:
            await rust_heartbeat._handle_mesh_event(event, context={})

        mock_handle.assert_awaited_once()
        call_kwargs = mock_handle.call_args.kwargs
        assert call_kwargs["producer_kwargs"] == json.dumps({"stream_type": "text"})


# ---------------------------------------------------------------------------
# API heartbeat path (rust_api_heartbeat.py) — issue #645 bug 1
# ---------------------------------------------------------------------------


class TestApiHeartbeatProducerKwargs:
    @pytest.mark.asyncio
    async def test_api_dependency_change_passes_producer_kwargs_to_proxy(self):
        """Bug 1: API gateways must pass kwargs_config to EnhancedUnifiedMCPProxy."""
        from _mcp_mesh.engine.decorator_registry import DecoratorRegistry
        from _mcp_mesh.pipeline.api_heartbeat import rust_api_heartbeat

        DecoratorRegistry.clear_all()

        # Register a route wrapper that depends on "chat".
        wrapper = MagicMock()
        wrapper._mesh_update_dependency = MagicMock()
        DecoratorRegistry.register_route_wrapper(
            method="POST",
            path="/api/chat",
            wrapper=wrapper,
            dependencies=["chat"],
        )

        captured: dict = {}

        class FakeProxy:
            def __init__(self, endpoint, function_name, kwargs_config=None):
                captured["endpoint"] = endpoint
                captured["function_name"] = function_name
                captured["kwargs_config"] = kwargs_config

        with patch(
            "_mcp_mesh.engine.unified_mcp_proxy.EnhancedUnifiedMCPProxy", FakeProxy
        ):
            await rust_api_heartbeat._handle_api_dependency_change(
                capability="chat",
                endpoint="http://producer:9170",
                function_name="chat",
                agent_id="producer-id",
                available=True,
                context={},
                producer_kwargs=json.dumps({"stream_type": "text"}),
            )

        assert captured["kwargs_config"] == {"stream_type": "text"}
        wrapper._mesh_update_dependency.assert_called_once()
        DecoratorRegistry.clear_all()

    @pytest.mark.asyncio
    async def test_api_event_dispatch_threads_kwargs_into_handler(self):
        from _mcp_mesh.pipeline.api_heartbeat import rust_api_heartbeat

        event = SimpleNamespace(
            event_type="dependency_available",
            capability="chat",
            endpoint="http://producer:9170",
            function_name="chat",
            agent_id="producer-id",
            kwargs=json.dumps({"stream_type": "text"}),
        )

        with patch.object(
            rust_api_heartbeat,
            "_handle_api_dependency_change",
            new=AsyncMock(),
        ) as mock_handle:
            await rust_api_heartbeat._handle_api_mesh_event(event, context={})

        mock_handle.assert_awaited_once()
        call_kwargs = mock_handle.call_args.kwargs
        assert call_kwargs["producer_kwargs"] == json.dumps({"stream_type": "text"})

    @pytest.mark.asyncio
    async def test_api_dependency_change_no_producer_kwargs_yields_empty_config(self):
        """Without producer kwargs, gateway proxy still constructs cleanly."""
        from _mcp_mesh.engine.decorator_registry import DecoratorRegistry
        from _mcp_mesh.pipeline.api_heartbeat import rust_api_heartbeat

        DecoratorRegistry.clear_all()

        wrapper = MagicMock()
        wrapper._mesh_update_dependency = MagicMock()
        DecoratorRegistry.register_route_wrapper(
            method="POST",
            path="/api/chat",
            wrapper=wrapper,
            dependencies=["chat"],
        )

        captured: dict = {}

        class FakeProxy:
            def __init__(self, endpoint, function_name, kwargs_config=None):
                captured["kwargs_config"] = kwargs_config

        with patch(
            "_mcp_mesh.engine.unified_mcp_proxy.EnhancedUnifiedMCPProxy", FakeProxy
        ):
            await rust_api_heartbeat._handle_api_dependency_change(
                capability="chat",
                endpoint="http://producer:9170",
                function_name="chat",
                agent_id="producer-id",
                available=True,
                context={},
                producer_kwargs=None,
            )

        assert captured["kwargs_config"] == {}
        DecoratorRegistry.clear_all()
