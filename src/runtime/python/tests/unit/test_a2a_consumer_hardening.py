"""Unit tests for the A2A consumer hardening fixes (issue #912).

Covers the five follow-ups deferred from PR #913 + PR #914 reviews:

    1. ``A2AClient._http`` per-loop client tracking (fork / new-loop safety).
    2. Multi-``@mesh.agent`` diagnostic warning in
       ``_resolve_pending_consumer_self_tags``.
    3. Use-after-close raises ``RuntimeError`` from ``A2AClient._http``.
    4. atexit hook flips ``_closed`` on every living A2AClient.
    5. ``A2AStream`` GC without explicit aclose triggers a leak warning
       via ``weakref.finalize``.
"""

from __future__ import annotations

import asyncio
import gc
import logging
from datetime import datetime
from typing import Any

import pytest

import mesh
from _mcp_mesh.engine.decorator_registry import DecoratedFunction, DecoratorRegistry
from mesh._a2a_consumer import (
    _ACTIVE_CLIENTS,
    _atexit_close_active_clients,
    A2AClient,
    A2AStream,
)
from mesh.decorators import (
    _MESH_CONSUMER_SELF_SENTINEL,
    _resolve_pending_consumer_self_tags,
)


# ---------------------------------------------------------------------------
# Fix 1 — per-loop httpx.AsyncClient caching
# ---------------------------------------------------------------------------


def test_a2a_client_per_loop_isolation():
    """A new loop sees a fresh httpx.AsyncClient instance — the cached
    one from a previous (closed) loop must NOT be reused."""
    client = A2AClient(url="http://localhost", skill_id="x", timeout_default=5)

    async def grab():
        return await client._http()

    loop_a = asyncio.new_event_loop()
    loop_b = asyncio.new_event_loop()
    try:
        http_a = loop_a.run_until_complete(grab())
        http_b = loop_b.run_until_complete(grab())
    finally:
        loop_a.close()
        loop_b.close()

    assert http_a is not http_b, (
        "Per-loop tracking should produce distinct AsyncClient instances "
        "across event loops"
    )


def test_a2a_client_same_loop_reuses_client():
    """Within a single loop, repeated _http() calls share the same client."""
    client = A2AClient(url="http://localhost", skill_id="x", timeout_default=5)

    async def go():
        c1 = await client._http()
        c2 = await client._http()
        return c1, c2

    loop = asyncio.new_event_loop()
    try:
        c1, c2 = loop.run_until_complete(go())
    finally:
        loop.close()

    assert c1 is c2


# ---------------------------------------------------------------------------
# Fix 3 — use-after-close raises
# ---------------------------------------------------------------------------


def test_a2a_client_raises_after_aclose():
    """``_http()`` after ``aclose()`` must raise RuntimeError to surface
    the lifecycle bug rather than silently rebuilding state."""
    client = A2AClient(url="http://localhost", skill_id="x")

    async def go():
        await client._http()
        await client.aclose()
        with pytest.raises(RuntimeError, match="closed"):
            await client._http()

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(go())
    finally:
        loop.close()


def test_a2a_client_aclose_idempotent():
    """``aclose()`` called twice does not raise."""
    client = A2AClient(url="http://localhost", skill_id="x")

    async def go():
        await client._http()
        await client.aclose()
        await client.aclose()

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(go())
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# Fix 4 — atexit hook marks live clients closed
# ---------------------------------------------------------------------------


def test_atexit_hook_flips_closed_flag_on_live_clients():
    """Simulating the atexit drain marks every tracked client closed."""
    client = A2AClient(url="http://localhost", skill_id="x")
    assert client in _ACTIVE_CLIENTS
    assert client._closed is False

    _atexit_close_active_clients()

    assert client._closed is True


# ---------------------------------------------------------------------------
# Fix 5 — A2AStream weakref.finalize warns on leak
# ---------------------------------------------------------------------------


class _FakeResponse:
    """Minimal httpx.Response stand-in for finalizer tests — only
    ``close()`` is exercised."""

    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


def test_a2a_stream_gc_without_aclose_warns(caplog):
    """Dropping a stream without aclose triggers the leak warning AND
    invokes sync close on the underlying response."""
    response = _FakeResponse()
    with caplog.at_level(logging.WARNING, logger="mesh._a2a_consumer"):
        stream = A2AStream(response=response, task_id="t-leak")
        del stream
        gc.collect()

    assert response.closed, "finalizer should sync-close the response"
    assert any(
        "garbage-collected without explicit aclose" in r.getMessage()
        for r in caplog.records
    ), "expected leak warning, got: " + repr([r.getMessage() for r in caplog.records])


def test_a2a_stream_explicit_aclose_suppresses_warning(caplog):
    """Explicit ``aclose()`` detaches the finalizer — no warning fires
    when the stream is later GC'd."""
    response = _FakeResponse()

    async def go():
        stream = A2AStream(response=response, task_id="t-clean")
        await stream.aclose()
        return stream

    loop = asyncio.new_event_loop()
    try:
        with caplog.at_level(logging.WARNING, logger="mesh._a2a_consumer"):
            stream = loop.run_until_complete(go())
            del stream
            gc.collect()
    finally:
        loop.close()

    assert not any(
        "garbage-collected without explicit aclose" in r.getMessage()
        for r in caplog.records
    ), "explicit aclose() should suppress the leak warning"


# ---------------------------------------------------------------------------
# Fix 2 — multi-@mesh.agent diagnostic warning
# ---------------------------------------------------------------------------


@pytest.fixture
def _clean_tools():
    """Snapshot + restore the mesh-tools registry around the test so
    the in-process global state doesn't leak."""
    snapshot = DecoratorRegistry._mesh_tools.copy()
    DecoratorRegistry._mesh_tools.clear()
    yield
    DecoratorRegistry._mesh_tools.clear()
    DecoratorRegistry._mesh_tools.update(snapshot)


def _register_consumer_tool(
    *, name: str, pending: bool, consumer_name: str
) -> None:
    """Helper: register a fake @mesh.a2a_consumer-shaped tool in the
    DecoratorRegistry. ``pending`` controls whether the resolution flag
    is set (True = waiting for @mesh.agent), ``consumer_name`` controls
    the resolved consumer-name field on the consumer metadata dict."""

    def _fn() -> None:
        pass

    _fn.__name__ = name
    _fn._mesh_a2a_consumer_pending_self_tag = pending
    # Simulate the marker stamped by _resolve_pending_consumer_self_tags when
    # a prior @mesh.agent has already substituted the sentinel for this tool.
    _fn._mesh_a2a_consumer_self_resolved = (
        not pending
        and bool(consumer_name)
        and consumer_name != _MESH_CONSUMER_SELF_SENTINEL
    )
    _fn._mesh_a2a_consumer_metadata = {
        "consumer_name": consumer_name,
        "tags": [consumer_name] if consumer_name else [],
    }
    _fn._mesh_tool_metadata = {
        "tags": [consumer_name] if consumer_name else [],
    }

    DecoratorRegistry._mesh_tools[name] = DecoratedFunction(
        decorator_type="mesh_tool",
        function=_fn,
        metadata={"tags": [consumer_name] if consumer_name else []},
        registered_at=datetime.now(),
    )


def test_resolve_pending_warns_when_zero_pending_and_already_resolved(
    _clean_tools, caplog
):
    """Second @mesh.agent in the same process logs a clear warning when
    no pending tools remain but a prior resolution stamped a real name."""
    _register_consumer_tool(
        name="tool_already_resolved", pending=False, consumer_name="agent-1"
    )

    with caplog.at_level(logging.WARNING, logger="mesh.decorators"):
        _resolve_pending_consumer_self_tags("agent-2")

    msgs = [r.getMessage() for r in caplog.records]
    assert any("agent-2" in m and "first @mesh.agent wins" in m for m in msgs), (
        "expected multi-agent warning, got: " + repr(msgs)
    )


def test_resolve_pending_silent_when_no_consumers_at_all(_clean_tools, caplog):
    """No pending and no resolved consumers — no warning, no error."""
    with caplog.at_level(logging.WARNING, logger="mesh.decorators"):
        _resolve_pending_consumer_self_tags("agent-x")

    assert not any(
        "first @mesh.agent wins" in r.getMessage() for r in caplog.records
    )


def test_resolve_pending_does_substitute_when_pending(_clean_tools, caplog):
    """A pending tool gets the sentinel swapped for the agent name AND
    no diagnostic warning fires."""
    _register_consumer_tool(
        name="tool_pending",
        pending=True,
        consumer_name=_MESH_CONSUMER_SELF_SENTINEL,
    )
    # Re-stamp the tag list with the sentinel so the swap is observable.
    fn = DecoratorRegistry._mesh_tools["tool_pending"].function
    fn._mesh_a2a_consumer_metadata["tags"] = [_MESH_CONSUMER_SELF_SENTINEL]
    fn._mesh_tool_metadata["tags"] = [_MESH_CONSUMER_SELF_SENTINEL]
    DecoratorRegistry._mesh_tools["tool_pending"].metadata["tags"] = [
        _MESH_CONSUMER_SELF_SENTINEL
    ]

    with caplog.at_level(logging.WARNING, logger="mesh.decorators"):
        _resolve_pending_consumer_self_tags("agent-1")

    assert fn._mesh_a2a_consumer_metadata["consumer_name"] == "agent-1"
    assert fn._mesh_a2a_consumer_metadata["tags"] == ["agent-1"]
    assert fn._mesh_tool_metadata["tags"] == ["agent-1"]
    assert (
        DecoratorRegistry._mesh_tools["tool_pending"].metadata["tags"]
        == ["agent-1"]
    )
    assert fn._mesh_a2a_consumer_pending_self_tag is False
    assert fn._mesh_a2a_consumer_self_resolved is True
    assert not any(
        "first @mesh.agent wins" in r.getMessage() for r in caplog.records
    )


# ---------------------------------------------------------------------------
# Smoke — public re-exports still resolve
# ---------------------------------------------------------------------------


def test_public_reexports_resolve():
    assert mesh.A2AClient is A2AClient
    assert mesh.A2AStream is A2AStream
