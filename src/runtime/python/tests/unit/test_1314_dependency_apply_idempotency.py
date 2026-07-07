"""Unit tests for issue #1314: idempotency guard on the dependency-apply path.

The Rust core re-emits ``dependency_available`` for every believed-delivered
edge on an independent ~10s wall-clock tick to self-heal dropped applies.
Without a guard the SDK would rebuild the injected proxy (and its connection
pool) every tick even when nothing changed.

The guard records a per-``dep_key`` signature of what was last wired —
``(endpoint, function_name, kwargs_config, agent_id)`` — and skips the rebuild
when an incoming resolution matches it exactly. A genuine change (different
endpoint, function, kwargs, or agent_id) still rebuilds, and unregistering
clears the signature so a later re-add rebuilds.

Covers both the MCP consumer path (``rust_heartbeat.py``) and the API/route
consumer path (``rust_api_heartbeat.py``); both pull from the same reconciling
Rust core and reuse the same shared ``DependencyInjector`` signature store.
"""

from __future__ import annotations

import json

import pytest


def _register_consumer():
    """Register a consumer tool with a single ``chat`` dependency.

    Returns ``(consumer_func, dep_key)`` where ``dep_key`` matches what the
    heartbeat position-path builds for ``requesting_function="consumer"`` and
    ``dep_index=0``.
    """
    from _mcp_mesh.engine.decorator_registry import DecoratorRegistry

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
    func_id = f"{consumer.__module__}.{consumer.__qualname__}"
    return consumer, f"{func_id}:dep_0"


async def _apply(rust_heartbeat, *, endpoint, agent_id, producer_kwargs=None):
    await rust_heartbeat._handle_dependency_change(
        capability="chat",
        endpoint=endpoint,
        function_name="chat",
        agent_id=agent_id,
        available=True,
        context={},
        requesting_function="consumer",
        dep_index=0,
        producer_kwargs=producer_kwargs,
    )


class TestDependencyApplyIdempotency:
    @pytest.mark.asyncio
    async def test_identical_reemit_is_noop(self):
        """Two identical applies build + register the proxy exactly once."""
        from unittest.mock import patch

        from _mcp_mesh.engine.decorator_registry import DecoratorRegistry
        from _mcp_mesh.engine.dependency_injector import get_global_injector
        from _mcp_mesh.pipeline.mcp_heartbeat import rust_heartbeat

        _, dep_key = _register_consumer()
        injector = get_global_injector()
        await injector.unregister_dependency(dep_key)  # clean slate

        builds: list = []

        class CountingProxy:
            def __init__(self, endpoint, function_name, kwargs_config=None):
                self.endpoint = endpoint
                self.function_name = function_name
                self.kwargs_config = kwargs_config
                builds.append(self)

        try:
            with patch(
                "_mcp_mesh.engine.unified_mcp_proxy.EnhancedUnifiedMCPProxy",
                CountingProxy,
            ):
                await _apply(
                    rust_heartbeat,
                    endpoint="http://producer:9170",
                    agent_id="producer-id",
                    producer_kwargs=json.dumps({"stream_type": "text"}),
                )
                first_instance = injector.get_dependency(dep_key)

                # Identical re-emit — must be a no-op (no rebuild, no re-register).
                await _apply(
                    rust_heartbeat,
                    endpoint="http://producer:9170",
                    agent_id="producer-id",
                    producer_kwargs=json.dumps({"stream_type": "text"}),
                )
                second_instance = injector.get_dependency(dep_key)

            assert len(builds) == 1
            assert first_instance is second_instance
        finally:
            await injector.unregister_dependency(dep_key)
            DecoratorRegistry.clear_all()

    @pytest.mark.asyncio
    async def test_equal_but_distinct_kwargs_dicts_are_noop(self):
        """kwargs_config is compared by value: equal dicts do not rebuild."""
        from unittest.mock import patch

        from _mcp_mesh.engine.decorator_registry import DecoratorRegistry
        from _mcp_mesh.engine.dependency_injector import get_global_injector
        from _mcp_mesh.pipeline.mcp_heartbeat import rust_heartbeat

        _, dep_key = _register_consumer()
        injector = get_global_injector()
        await injector.unregister_dependency(dep_key)

        builds: list = []

        class CountingProxy:
            def __init__(self, endpoint, function_name, kwargs_config=None):
                builds.append(self)

        try:
            with patch(
                "_mcp_mesh.engine.unified_mcp_proxy.EnhancedUnifiedMCPProxy",
                CountingProxy,
            ):
                # Same key/values, different key ordering in the JSON — must
                # normalize to an equal signature.
                await _apply(
                    rust_heartbeat,
                    endpoint="http://producer:9170",
                    agent_id="producer-id",
                    producer_kwargs=json.dumps({"a": 1, "b": 2}),
                )
                await _apply(
                    rust_heartbeat,
                    endpoint="http://producer:9170",
                    agent_id="producer-id",
                    producer_kwargs=json.dumps({"b": 2, "a": 1}),
                )

            assert len(builds) == 1
        finally:
            await injector.unregister_dependency(dep_key)
            DecoratorRegistry.clear_all()

    @pytest.mark.asyncio
    async def test_different_endpoint_rebuilds(self):
        """A genuine endpoint change rebuilds + re-registers a new instance."""
        from unittest.mock import patch

        from _mcp_mesh.engine.decorator_registry import DecoratorRegistry
        from _mcp_mesh.engine.dependency_injector import get_global_injector
        from _mcp_mesh.pipeline.mcp_heartbeat import rust_heartbeat

        _, dep_key = _register_consumer()
        injector = get_global_injector()
        await injector.unregister_dependency(dep_key)

        builds: list = []

        class CountingProxy:
            def __init__(self, endpoint, function_name, kwargs_config=None):
                self.endpoint = endpoint
                builds.append(self)

        try:
            with patch(
                "_mcp_mesh.engine.unified_mcp_proxy.EnhancedUnifiedMCPProxy",
                CountingProxy,
            ):
                await _apply(
                    rust_heartbeat,
                    endpoint="http://producer:9170",
                    agent_id="producer-id",
                )
                first_instance = injector.get_dependency(dep_key)

                await _apply(
                    rust_heartbeat,
                    endpoint="http://producer-2:9170",
                    agent_id="producer-id",
                )
                second_instance = injector.get_dependency(dep_key)

            assert len(builds) == 2
            assert first_instance is not second_instance
            assert second_instance.endpoint == "http://producer-2:9170"
        finally:
            await injector.unregister_dependency(dep_key)
            DecoratorRegistry.clear_all()

    @pytest.mark.asyncio
    async def test_different_agent_id_rebuilds(self):
        """An agent_id-only change rebuilds (composes with #1315)."""
        from unittest.mock import patch

        from _mcp_mesh.engine.decorator_registry import DecoratorRegistry
        from _mcp_mesh.engine.dependency_injector import get_global_injector
        from _mcp_mesh.pipeline.mcp_heartbeat import rust_heartbeat

        _, dep_key = _register_consumer()
        injector = get_global_injector()
        await injector.unregister_dependency(dep_key)

        builds: list = []

        class CountingProxy:
            def __init__(self, endpoint, function_name, kwargs_config=None):
                builds.append(self)

        try:
            with patch(
                "_mcp_mesh.engine.unified_mcp_proxy.EnhancedUnifiedMCPProxy",
                CountingProxy,
            ):
                await _apply(
                    rust_heartbeat,
                    endpoint="http://producer:9170",
                    agent_id="producer-a",
                )
                await _apply(
                    rust_heartbeat,
                    endpoint="http://producer:9170",
                    agent_id="producer-b",
                )

            assert len(builds) == 2
        finally:
            await injector.unregister_dependency(dep_key)
            DecoratorRegistry.clear_all()

    @pytest.mark.asyncio
    async def test_unregister_clears_signature_so_readd_rebuilds(self):
        """Unregistering clears the signature; re-applying the same rebuilds."""
        from unittest.mock import patch

        from _mcp_mesh.engine.decorator_registry import DecoratorRegistry
        from _mcp_mesh.engine.dependency_injector import get_global_injector
        from _mcp_mesh.pipeline.mcp_heartbeat import rust_heartbeat

        _, dep_key = _register_consumer()
        injector = get_global_injector()
        await injector.unregister_dependency(dep_key)

        builds: list = []

        class CountingProxy:
            def __init__(self, endpoint, function_name, kwargs_config=None):
                builds.append(self)

        try:
            with patch(
                "_mcp_mesh.engine.unified_mcp_proxy.EnhancedUnifiedMCPProxy",
                CountingProxy,
            ):
                await _apply(
                    rust_heartbeat,
                    endpoint="http://producer:9170",
                    agent_id="producer-id",
                )
                assert len(builds) == 1

                # Dependency goes away — clears the stored signature.
                await rust_heartbeat._handle_dependency_change(
                    capability="chat",
                    endpoint=None,
                    function_name=None,
                    agent_id="producer-id",
                    available=False,
                    context={},
                    requesting_function="consumer",
                    dep_index=0,
                )
                assert injector.get_applied_dependency_signature(dep_key) is None

                # Re-add identical resolution — must rebuild (not skipped).
                await _apply(
                    rust_heartbeat,
                    endpoint="http://producer:9170",
                    agent_id="producer-id",
                )

            assert len(builds) == 2
        finally:
            await injector.unregister_dependency(dep_key)
            DecoratorRegistry.clear_all()


def _register_route(dependencies=("chat",)):
    """Register a route wrapper with the given dependency capabilities.

    Returns ``(wrapper, route_id)``. ``route_id`` matches the API path's
    ``{method}:{path}`` convention, and the signature key it uses is
    ``api:{route_id}:dep_{index}``.
    """
    from unittest.mock import MagicMock

    from _mcp_mesh.engine.decorator_registry import DecoratorRegistry

    DecoratorRegistry.clear_all()

    wrapper = MagicMock()
    wrapper._mesh_update_dependency = MagicMock()
    DecoratorRegistry.register_route_wrapper(
        method="POST",
        path="/api/chat",
        wrapper=wrapper,
        dependencies=list(dependencies),
    )
    return wrapper, "POST:/api/chat"


async def _apply_api(rust_api_heartbeat, *, endpoint, agent_id, producer_kwargs=None):
    await rust_api_heartbeat._handle_api_dependency_change(
        capability="chat",
        endpoint=endpoint,
        function_name="chat",
        agent_id=agent_id,
        available=True,
        context={},
        producer_kwargs=producer_kwargs,
    )


class TestApiDependencyApplyIdempotency:
    """The API/route consumer path (@mesh.route gateways) shares the guard.

    It reuses the same global ``DependencyInjector`` signature store as the MCP
    path, keyed ``api:{route_id}:dep_{N}`` since routes are wired via route
    wrappers rather than injector registration.
    """

    @pytest.mark.asyncio
    async def test_identical_reemit_is_noop(self):
        from unittest.mock import patch

        from _mcp_mesh.engine.decorator_registry import DecoratorRegistry
        from _mcp_mesh.engine.dependency_injector import get_global_injector
        from _mcp_mesh.pipeline.api_heartbeat import rust_api_heartbeat

        wrapper, route_id = _register_route()
        injector = get_global_injector()
        sig_key = f"api:{route_id}:dep_0"
        injector.clear_applied_dependency_signature(sig_key)

        builds: list = []

        class CountingProxy:
            def __init__(self, endpoint, function_name, kwargs_config=None):
                builds.append(self)

        try:
            with patch(
                "_mcp_mesh.engine.unified_mcp_proxy.EnhancedUnifiedMCPProxy",
                CountingProxy,
            ):
                await _apply_api(
                    rust_api_heartbeat,
                    endpoint="http://producer:9170",
                    agent_id="producer-id",
                    producer_kwargs=json.dumps({"stream_type": "text"}),
                )
                # Identical re-emit — no rebuild, no wrapper re-update.
                await _apply_api(
                    rust_api_heartbeat,
                    endpoint="http://producer:9170",
                    agent_id="producer-id",
                    producer_kwargs=json.dumps({"stream_type": "text"}),
                )

            assert len(builds) == 1
            assert wrapper._mesh_update_dependency.call_count == 1
        finally:
            injector.clear_applied_dependency_signature(sig_key)
            DecoratorRegistry.clear_all()

    @pytest.mark.asyncio
    async def test_different_endpoint_rebuilds(self):
        from unittest.mock import patch

        from _mcp_mesh.engine.decorator_registry import DecoratorRegistry
        from _mcp_mesh.engine.dependency_injector import get_global_injector
        from _mcp_mesh.pipeline.api_heartbeat import rust_api_heartbeat

        wrapper, route_id = _register_route()
        injector = get_global_injector()
        sig_key = f"api:{route_id}:dep_0"
        injector.clear_applied_dependency_signature(sig_key)

        builds: list = []

        class CountingProxy:
            def __init__(self, endpoint, function_name, kwargs_config=None):
                self.endpoint = endpoint
                builds.append(self)

        try:
            with patch(
                "_mcp_mesh.engine.unified_mcp_proxy.EnhancedUnifiedMCPProxy",
                CountingProxy,
            ):
                await _apply_api(
                    rust_api_heartbeat,
                    endpoint="http://producer:9170",
                    agent_id="producer-id",
                )
                await _apply_api(
                    rust_api_heartbeat,
                    endpoint="http://producer-2:9170",
                    agent_id="producer-id",
                )

            assert len(builds) == 2
            assert wrapper._mesh_update_dependency.call_count == 2
        finally:
            injector.clear_applied_dependency_signature(sig_key)
            DecoratorRegistry.clear_all()

    @pytest.mark.asyncio
    async def test_different_agent_id_rebuilds(self):
        from unittest.mock import patch

        from _mcp_mesh.engine.decorator_registry import DecoratorRegistry
        from _mcp_mesh.engine.dependency_injector import get_global_injector
        from _mcp_mesh.pipeline.api_heartbeat import rust_api_heartbeat

        wrapper, route_id = _register_route()
        injector = get_global_injector()
        sig_key = f"api:{route_id}:dep_0"
        injector.clear_applied_dependency_signature(sig_key)

        builds: list = []

        class CountingProxy:
            def __init__(self, endpoint, function_name, kwargs_config=None):
                builds.append(self)

        try:
            with patch(
                "_mcp_mesh.engine.unified_mcp_proxy.EnhancedUnifiedMCPProxy",
                CountingProxy,
            ):
                await _apply_api(
                    rust_api_heartbeat,
                    endpoint="http://producer:9170",
                    agent_id="producer-a",
                )
                await _apply_api(
                    rust_api_heartbeat,
                    endpoint="http://producer:9170",
                    agent_id="producer-b",
                )

            assert len(builds) == 2
            assert wrapper._mesh_update_dependency.call_count == 2
        finally:
            injector.clear_applied_dependency_signature(sig_key)
            DecoratorRegistry.clear_all()

    @pytest.mark.asyncio
    async def test_unavailable_clears_signature_so_readd_rebuilds(self):
        from unittest.mock import patch

        from _mcp_mesh.engine.decorator_registry import DecoratorRegistry
        from _mcp_mesh.engine.dependency_injector import get_global_injector
        from _mcp_mesh.pipeline.api_heartbeat import rust_api_heartbeat

        wrapper, route_id = _register_route()
        injector = get_global_injector()
        sig_key = f"api:{route_id}:dep_0"
        injector.clear_applied_dependency_signature(sig_key)

        builds: list = []

        class CountingProxy:
            def __init__(self, endpoint, function_name, kwargs_config=None):
                builds.append(self)

        try:
            with patch(
                "_mcp_mesh.engine.unified_mcp_proxy.EnhancedUnifiedMCPProxy",
                CountingProxy,
            ):
                await _apply_api(
                    rust_api_heartbeat,
                    endpoint="http://producer:9170",
                    agent_id="producer-id",
                )
                assert len(builds) == 1

                # Dependency goes away — clears the stored signature.
                await rust_api_heartbeat._handle_api_dependency_change(
                    capability="chat",
                    endpoint=None,
                    function_name=None,
                    agent_id=None,
                    available=False,
                    context={},
                    producer_kwargs=None,
                )
                assert injector.get_applied_dependency_signature(sig_key) is None

                # Re-add identical resolution — must rebuild (not skipped).
                await _apply_api(
                    rust_api_heartbeat,
                    endpoint="http://producer:9170",
                    agent_id="producer-id",
                )

            assert len(builds) == 2
        finally:
            injector.clear_applied_dependency_signature(sig_key)
            DecoratorRegistry.clear_all()
