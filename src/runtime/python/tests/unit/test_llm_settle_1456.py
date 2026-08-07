"""Unit tests for the ``@mesh.llm`` settling-window grace (issue #1456).

``@mesh.llm`` provider injection used to sit OUTSIDE the settling-window
grace (#1193): ``combined_injection_wrapper._mesh_llm_agent`` starts as
``None`` and is only filled by ``update_llm_agent`` when a heartbeat
delivers ``llm_providers``. Because providers and consumers register in the
same instant, the registration heartbeat always reports zero providers — so
any call landing before the SECOND heartbeat injected ``None`` and the user
function died on ``'NoneType' object is not callable``.

These tests pin the fix:

* a call that fires while the provider is unresolved WAITS and proceeds
  early the moment ``_mesh_update_llm_agent`` lands (sync and async paths);
* a provider that never resolves expires against the settle budget and
  falls back to today's ``None`` injection — bounded, never a hang;
* the settle key is per CONSUMER FUNCTION, so one consumer's provider
  resolution cannot wake a different consumer's waiter;
* the sync/async wrapper split that makes both wait primitives reachable.

NOTE: do NOT add ``from __future__ import annotations`` — the @mesh.llm
decorator's MeshLlmAgent detection compares ``param.annotation`` to the
class directly, and PEP 563 would leave it a string.
"""

import asyncio
import threading
import time
from unittest.mock import MagicMock

import pytest

import mesh
from _mcp_mesh.engine import settle
from _mcp_mesh.engine.decorator_registry import DecoratorRegistry
from _mcp_mesh.engine.settle import get_settle_state
from mesh.decorators import _llm_settle_key


@pytest.fixture(autouse=True)
def fresh_state(monkeypatch):
    """Fresh settle state + uncached budget + clean decorator registry."""
    monkeypatch.delenv("MCP_MESH_SETTLE_TIMEOUT", raising=False)
    DecoratorRegistry.clear_all()
    settle._reset_settle_state_for_tests()
    yield
    DecoratorRegistry.clear_all()
    settle._reset_settle_state_for_tests()


def _set_budget(monkeypatch, value: str) -> None:
    """Set the settle budget and re-anchor the settle state on it.

    Must run BEFORE decoration: ``@mesh.llm`` calls ``register_declared``
    at decoration time, and that is what anchors the window.
    """
    monkeypatch.setenv("MCP_MESH_SETTLE_TIMEOUT", value)
    settle._reset_settle_state_for_tests()


def _make_sync_consumer(capability: str, seen: list):
    """A sync ``@mesh.llm`` + ``@mesh.tool`` consumer (committee-agent shape)."""

    @mesh.llm(provider={"capability": "llm"}, max_iterations=1)
    @mesh.tool(capability=capability)
    def consumer(prompt: str, llm: mesh.MeshLlmAgent = None) -> str:
        seen.append(llm)
        return "degraded" if llm is None else "resolved"

    return consumer


def _make_async_consumer(capability: str, seen: list):
    """An async ``@mesh.llm`` + ``@mesh.tool`` consumer (planner shape)."""

    @mesh.llm(provider={"capability": "llm"}, max_iterations=1)
    @mesh.tool(capability=capability)
    async def consumer(prompt: str, llm: mesh.MeshLlmAgent = None) -> str:
        seen.append(llm)
        return "degraded" if llm is None else "resolved"

    return consumer


class TestWrapperAsyncSplit:
    """Both wait primitives must be reachable from real decorated tools."""

    def test_sync_tool_gets_sync_wrapper(self):
        wrapper = _make_sync_consumer("settle1456-split-sync", [])
        assert not asyncio.iscoroutinefunction(wrapper)

    def test_async_tool_gets_async_wrapper(self):
        wrapper = _make_async_consumer("settle1456-split-async", [])
        assert asyncio.iscoroutinefunction(wrapper), (
            "an async @mesh.llm tool must get an async combined wrapper so the "
            "settle grace can await loop-natively instead of blocking a "
            "threadpool thread for the whole window"
        )


class TestDeclarationAndResolution:
    def test_decoration_declares_the_provider_slot(self, monkeypatch):
        _set_budget(monkeypatch, "10")
        wrapper = _make_sync_consumer("settle1456-declare", [])
        key = _llm_settle_key(wrapper._mesh_llm_function_id)

        assert wrapper._mesh_llm_settle_key == key
        assert key in get_settle_state()._declared

    def test_update_llm_agent_marks_resolved(self, monkeypatch):
        _set_budget(monkeypatch, "10")
        wrapper = _make_sync_consumer("settle1456-resolve", [])
        key = wrapper._mesh_llm_settle_key

        assert key not in get_settle_state()._resolved
        wrapper._mesh_update_llm_agent(MagicMock(name="agent"))
        assert key in get_settle_state()._resolved

    def test_settled_steady_state_never_waits(self, monkeypatch):
        """Once resolved, calls take the fast path (no wait primitives)."""
        _set_budget(monkeypatch, "10")
        seen: list = []
        wrapper = _make_sync_consumer("settle1456-steady", seen)
        agent = MagicMock(name="agent")
        wrapper._mesh_update_llm_agent(agent)

        before = get_settle_state().wait_count
        start = time.monotonic()
        assert wrapper(prompt="hi") == "resolved"
        assert wrapper(prompt="hi") == "resolved"
        assert time.monotonic() - start < 1.0
        assert get_settle_state().wait_count == before
        assert seen == [agent, agent]


class TestSyncInjectionPath:
    """Plain ``def`` committee-agent shape — blocking wait on a worker thread."""

    def test_waits_and_succeeds_when_provider_resolves_mid_call(self, monkeypatch):
        _set_budget(monkeypatch, "10")
        seen: list = []
        wrapper = _make_sync_consumer("settle1456-sync-wait", seen)
        agent = MagicMock(name="agent")

        timer = threading.Timer(0.2, lambda: wrapper._mesh_update_llm_agent(agent))
        timer.start()
        start = time.monotonic()
        result = wrapper(prompt="plan my trip")
        elapsed = time.monotonic() - start
        timer.join()

        assert result == "resolved", (
            "pre-fix the unresolved provider injected None and the user "
            "function saw llm=None"
        )
        assert seen == [agent]
        # Woken by the resolution event, not by the 10s budget ceiling.
        assert elapsed < 5.0
        assert get_settle_state().wait_count >= 1

    def test_never_resolves_expires_at_budget_and_injects_none(self, monkeypatch):
        _set_budget(monkeypatch, "0.4")
        seen: list = []
        wrapper = _make_sync_consumer("settle1456-sync-expire", seen)

        start = time.monotonic()
        result = wrapper(prompt="plan my trip")
        elapsed = time.monotonic() - start

        # Today's behavior on expiry: None is injected, user code runs.
        assert result == "degraded"
        assert seen == [None]
        # The wait actually happened...
        assert elapsed >= 0.3
        # ...and was bounded by the budget — never a hang.
        assert elapsed < 5.0


class TestAsyncInjectionPath:
    """``async def`` planner shape — loop-native await, never blocks."""

    @pytest.mark.asyncio
    async def test_waits_and_succeeds_when_provider_resolves_mid_call(
        self, monkeypatch
    ):
        _set_budget(monkeypatch, "10")
        seen: list = []
        wrapper = _make_async_consumer("settle1456-async-wait", seen)
        agent = MagicMock(name="agent")

        # Resolve from ANOTHER thread — the real heartbeat delivers
        # resolutions off the serving loop, so this exercises the
        # call_soon_threadsafe mirror rather than a same-loop shortcut.
        timer = threading.Timer(0.2, lambda: wrapper._mesh_update_llm_agent(agent))
        timer.start()
        start = time.monotonic()
        result = await wrapper(prompt="plan my trip")
        elapsed = time.monotonic() - start
        timer.join()

        assert result == "resolved"
        assert seen == [agent]
        assert elapsed < 5.0
        assert get_settle_state().wait_count >= 1

    @pytest.mark.asyncio
    async def test_async_wait_does_not_touch_the_executor(self, monkeypatch):
        """The grace must not consume shared default-executor capacity."""
        _set_budget(monkeypatch, "10")
        seen: list = []
        wrapper = _make_async_consumer("settle1456-async-noexec", seen)
        agent = MagicMock(name="agent")

        timer = threading.Timer(0.2, lambda: wrapper._mesh_update_llm_agent(agent))
        timer.start()
        monkeypatch.setattr(
            asyncio,
            "to_thread",
            MagicMock(
                side_effect=AssertionError(
                    "settle wait must not consume executor capacity"
                )
            ),
        )
        result = await wrapper(prompt="plan my trip")
        timer.join()

        assert result == "resolved"
        assert seen == [agent]

    @pytest.mark.asyncio
    async def test_never_resolves_expires_at_budget_and_injects_none(self, monkeypatch):
        _set_budget(monkeypatch, "0.4")
        seen: list = []
        wrapper = _make_async_consumer("settle1456-async-expire", seen)

        start = time.monotonic()
        result = await wrapper(prompt="plan my trip")
        elapsed = time.monotonic() - start

        assert result == "degraded"
        assert seen == [None]
        assert elapsed >= 0.3
        assert elapsed < 5.0


class TestSettleKeyIsolation:
    """One consumer's provider resolution must not wake another's waiter.

    Same rationale as the per-slot ``<func_id>:dep_<N>`` composites on the
    ``@mesh.tool`` path: a woken waiter re-reads its OWN
    ``wrapper._mesh_llm_agent``, so a wake it didn't earn just burns the
    grace and injects ``None`` anyway.
    """

    def test_keys_are_per_consumer_not_per_capability(self, monkeypatch):
        _set_budget(monkeypatch, "10")
        a = _make_sync_consumer("settle1456-keys-a", [])
        b = _make_sync_consumer("settle1456-keys-b", [])

        # Same provider capability declared by both consumers...
        assert a._mesh_llm_config["provider"]["capability"] == "llm"
        assert b._mesh_llm_config["provider"]["capability"] == "llm"
        # ...but distinct settle keys.
        assert a._mesh_llm_settle_key != b._mesh_llm_settle_key

    def test_other_consumers_resolution_does_not_wake_this_waiter(self, monkeypatch):
        _set_budget(monkeypatch, "1.0")
        seen_a: list = []
        seen_b: list = []
        a = _make_sync_consumer("settle1456-wake-a", seen_a)
        b = _make_sync_consumer("settle1456-wake-b", seen_b)

        # Consumer A resolves early; consumer B never does.
        timer = threading.Timer(
            0.1, lambda: a._mesh_update_llm_agent(MagicMock(name="agent-a"))
        )
        timer.start()
        start = time.monotonic()
        result = b(prompt="plan my trip")
        elapsed = time.monotonic() - start
        timer.join()

        assert result == "degraded"
        assert seen_b == [None]
        # B must have sat out its own budget rather than being woken at
        # ~0.1s by A's resolution.
        assert elapsed >= 0.9, (
            f"consumer B woke after {elapsed:.2f}s — A's provider resolution "
            "leaked across the settle key"
        )
        assert elapsed < 5.0
