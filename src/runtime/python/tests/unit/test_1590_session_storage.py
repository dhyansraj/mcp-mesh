"""Unit tests for issue #1590: session-affinity storage must not block the
uvicorn loop, must bound its fallback, and must recover from a Redis blip.

``SessionStorage`` is reached exclusively from ASGI middleware on the serving
event loop. The original implementation used the SYNCHRONOUS ``redis`` client
with no socket timeout, pinged it from ``__init__``, kept an unbounded
in-memory fallback with no TTL, and latched ``redis_available = False``
permanently on the first failure.
"""

from __future__ import annotations

import asyncio
import inspect
import time

import pytest

from _mcp_mesh.engine.http_wrapper import (
    MEMORY_STORE_MAX_ENTRIES,
    REDIS_OP_TIMEOUT_SECS,
    SessionStorage,
)


class _FakeRedis:
    """Async stand-in for ``redis.asyncio.Redis``."""

    def __init__(self, *, fail_on=(), hang_on=()):
        self.store: dict[str, str] = {}
        self.fail_on = set(fail_on)
        self.hang_on = set(hang_on)
        self.pings = 0
        self.closed = False

    async def _maybe_fail(self, op):
        if op in self.hang_on:
            await asyncio.sleep(3600)
        if op in self.fail_on:
            raise ConnectionError(f"redis {op} down")

    async def ping(self):
        self.pings += 1
        await self._maybe_fail("ping")
        return True

    async def get(self, key):
        await self._maybe_fail("get")
        return self.store.get(key)

    async def setex(self, key, ttl, value):
        await self._maybe_fail("setex")
        self.store[key] = value
        return True

    async def keys(self, pattern):
        await self._maybe_fail("keys")
        return list(self.store)

    async def aclose(self):
        self.closed = True


def _install_fake_redis_module(monkeypatch, from_url):
    """Replace ``redis.asyncio`` for the duration of a test.

    Both ``sys.modules`` and the attribute on the parent ``redis`` package
    have to be patched: ``import redis.asyncio as x`` resolves ``x`` via
    ``getattr(redis, "asyncio")`` when the parent is already imported.
    """
    import sys
    import types

    import redis

    mod = types.ModuleType("redis.asyncio")
    mod.from_url = from_url
    monkeypatch.setitem(sys.modules, "redis.asyncio", mod)
    monkeypatch.setattr(redis, "asyncio", mod, raising=False)
    return mod


def _patch_redis(monkeypatch, fake):
    """Make ``_ensure_redis`` build ``fake`` instead of a real client."""
    seen: dict = {}

    def from_url(url, **kw):
        seen.update(kw)
        return fake

    mod = _install_fake_redis_module(monkeypatch, from_url)
    mod._kwargs_seen = seen
    return mod


class TestNoSynchronousRedisOnTheLoop:
    def test_constructor_does_not_touch_redis(self, monkeypatch):
        # The old __init__ ran a blocking from_url(...).ping() — on a
        # black-holed REDIS_URL that hung agent startup outright.
        def _boom(*a, **k):
            raise AssertionError("SessionStorage.__init__ touched Redis")

        _install_fake_redis_module(monkeypatch, _boom)

        storage = SessionStorage()
        assert storage.redis_client is None
        assert storage.redis_available is False

    def test_accessors_are_coroutine_functions(self):
        assert inspect.iscoroutinefunction(SessionStorage.get_session_pod)
        assert inspect.iscoroutinefunction(SessionStorage.assign_session_pod)
        # get_stats had to become async too — a sync reader of an asyncio
        # client hands back un-awaited coroutines.
        assert inspect.iscoroutinefunction(SessionStorage.get_stats)

    def test_client_is_built_with_connect_and_socket_timeouts(self, monkeypatch):
        fake = _FakeRedis()
        mod = _patch_redis(monkeypatch, fake)
        storage = SessionStorage()

        asyncio.run(storage.assign_session_pod("s1", "10.0.0.1"))

        assert mod._kwargs_seen["socket_timeout"] == REDIS_OP_TIMEOUT_SECS
        assert mod._kwargs_seen["socket_connect_timeout"] == REDIS_OP_TIMEOUT_SECS

    def test_a_hung_redis_does_not_hang_the_caller(self, monkeypatch):
        # Belt-and-braces on top of the socket timeout: a pool that never
        # returns must not stall the request (and with it /health and /ready).
        fake = _FakeRedis(hang_on={"get"})
        _patch_redis(monkeypatch, fake)
        storage = SessionStorage()

        async def go():
            await storage.assign_session_pod("s1", "10.0.0.1")
            started = time.monotonic()
            result = await storage.get_session_pod("s1")
            return result, time.monotonic() - started

        # Shrink the budget so the test is fast; the mechanism is the same.
        monkeypatch.setattr("_mcp_mesh.engine.http_wrapper.REDIS_OP_TIMEOUT_SECS", 0.2)
        result, elapsed = asyncio.run(go())

        assert elapsed < 2.0, "get() was not bounded by a timeout"
        # Degraded rather than raising: the request proceeds without session
        # affinity (the assign above did reach Redis, so nothing is in the
        # memory fallback to answer with).
        assert result is None
        assert storage.redis_available is False


class TestBoundedMemoryFallback:
    def test_entries_expire(self, monkeypatch):
        monkeypatch.setattr("_mcp_mesh.engine.http_wrapper.SESSION_TTL", 1)
        storage = SessionStorage()
        storage._memory_set("session:s1", "10.0.0.1", ttl=0)

        assert storage._memory_get("session:s1") is None
        # ...and the expired entry is reaped, not merely hidden.
        assert "session:s1" not in storage.memory_store

    def test_live_entry_survives(self):
        storage = SessionStorage()
        storage._memory_set("session:s1", "10.0.0.1", ttl=60)
        assert storage._memory_get("session:s1") == "10.0.0.1"

    def test_store_is_capped(self, monkeypatch):
        monkeypatch.setattr(
            "_mcp_mesh.engine.http_wrapper.MEMORY_STORE_MAX_ENTRIES", 10
        )
        storage = SessionStorage()
        for i in range(50):
            storage._memory_set(f"session:{i}", f"10.0.0.{i}", ttl=60 + i)

        assert len(storage.memory_store) <= 10

    def test_cap_evicts_the_soonest_to_expire(self, monkeypatch):
        monkeypatch.setattr("_mcp_mesh.engine.http_wrapper.MEMORY_STORE_MAX_ENTRIES", 3)
        storage = SessionStorage()
        storage._memory_set("session:short", "a", ttl=10)
        storage._memory_set("session:mid", "b", ttl=100)
        storage._memory_set("session:long", "c", ttl=1000)
        storage._memory_set("session:new", "d", ttl=1000)

        assert "session:short" not in storage.memory_store
        assert storage._memory_get("session:new") == "d"

    def test_default_cap_is_finite(self):
        assert 0 < MEMORY_STORE_MAX_ENTRIES < 10**7

    def test_fallback_round_trips_through_the_public_api(self, monkeypatch):
        def _refuse(url, **kw):
            raise ConnectionError("nope")

        _install_fake_redis_module(monkeypatch, _refuse)

        storage = SessionStorage()

        async def go():
            await storage.assign_session_pod("s1", "10.0.0.7")
            return await storage.get_session_pod("s1")

        assert asyncio.run(go()) == "10.0.0.7"


class TestRedisReprobe:
    def test_failure_schedules_a_backoff_probe(self, monkeypatch):
        fake = _FakeRedis(fail_on={"ping"})
        _patch_redis(monkeypatch, fake)
        storage = SessionStorage()

        asyncio.run(storage.get_session_pod("s1"))

        assert storage.redis_available is False
        assert storage._redis_failures == 1
        assert storage._next_redis_probe > time.monotonic()

    def test_backoff_suppresses_probes_inside_the_window(self, monkeypatch):
        fake = _FakeRedis(fail_on={"ping"})
        _patch_redis(monkeypatch, fake)
        storage = SessionStorage()

        async def go():
            for _ in range(5):
                await storage.get_session_pod("s1")

        asyncio.run(go())
        # One probe, not five: the backoff window keeps the request path off
        # a dead Redis.
        assert fake.pings == 1

    def test_sessions_assigned_during_an_outage_survive_recovery(self, monkeypatch):
        # An established sticky session must not be silently re-homed just
        # because Redis came back without it.
        fake = _FakeRedis(fail_on={"ping"})
        _patch_redis(monkeypatch, fake)
        storage = SessionStorage()

        async def go():
            # Outage: the assignment lands in memory only.
            await storage.assign_session_pod("s1", "10.0.0.5")
            assert storage.redis_available is False
            # Redis returns, empty.
            fake.fail_on.clear()
            storage._next_redis_probe = 0.0
            return await storage.get_session_pod("s1")

        found = asyncio.run(go())

        assert found == "10.0.0.5", "sticky session was lost on Redis recovery"
        # ...and the recovered value is written back so the next pod agrees.
        assert fake.store["session:s1"] == "10.0.0.5"

    def test_redis_recovers_after_the_window(self, monkeypatch):
        fake = _FakeRedis(fail_on={"ping"})
        _patch_redis(monkeypatch, fake)
        storage = SessionStorage()

        async def go():
            await storage.get_session_pod("s1")
            assert storage.redis_available is False
            # Redis comes back; simulate the backoff window elapsing.
            fake.fail_on.clear()
            storage._next_redis_probe = 0.0
            await storage.assign_session_pod("s1", "10.0.0.9")
            return storage.redis_available, fake.store

        available, store = asyncio.run(go())

        # The old code latched redis_available=False forever, permanently
        # downgrading the process to the leaking fallback.
        assert available is True
        assert store["session:s1"] == "10.0.0.9"

    def test_backoff_grows_and_is_capped(self, monkeypatch):
        from _mcp_mesh.engine import http_wrapper as hw

        storage = SessionStorage()

        async def go():
            delays = []
            for _ in range(8):
                # Each iteration is a fresh probe CYCLE: the previous window
                # has elapsed, we retried, and failed again.
                storage._next_redis_probe = 0.0
                before = time.monotonic()
                await storage._mark_redis_down(ConnectionError("x"), "ping")
                delays.append(storage._next_redis_probe - before)
            return delays

        delays = asyncio.run(go())

        assert delays[0] == pytest.approx(hw.REDIS_REPROBE_BASE_SECS, abs=0.5)
        assert delays[1] > delays[0]
        assert max(delays) <= hw.REDIS_REPROBE_MAX_SECS + 0.5

    def test_a_burst_of_failures_advances_the_backoff_once(self):
        # Ten concurrent requests hitting the same dead Redis must schedule ONE
        # 5s probe, not jump to the 300s cap and defeat fast recovery.
        storage = SessionStorage()

        async def go():
            await asyncio.gather(
                *(
                    storage._mark_redis_down(ConnectionError("x"), "get")
                    for _ in range(10)
                )
            )

        asyncio.run(go())

        assert storage._redis_failures == 1

    def test_concurrent_first_requests_build_one_client(self, monkeypatch):
        # Without single-flight each concurrent first request builds its own
        # client; the last one wins and the rest leak sockets.
        built: list = []

        def from_url(url, **kw):
            fake = _FakeRedis()
            built.append(fake)
            return fake

        _install_fake_redis_module(monkeypatch, from_url)
        storage = SessionStorage()

        async def go():
            await asyncio.gather(*(storage.get_session_pod(f"s{i}") for i in range(10)))

        asyncio.run(go())

        assert len(built) == 1
        assert storage.redis_client is built[0]

    def test_success_resets_the_failure_counter(self, monkeypatch):
        fake = _FakeRedis(fail_on={"ping"})
        _patch_redis(monkeypatch, fake)
        storage = SessionStorage()

        async def go():
            await storage.get_session_pod("s1")
            fake.fail_on.clear()
            storage._next_redis_probe = 0.0
            await storage.get_session_pod("s1")

        asyncio.run(go())
        assert storage._redis_failures == 0
        assert storage._next_redis_probe == 0.0


class TestLoopAffinity:
    def test_the_replaced_client_is_closed_on_its_own_still_live_loop(
        self, monkeypatch
    ):
        # Dropping a live redis.asyncio pool leaks its open sockets, and it
        # cannot legally be closed from the new loop. It has to be closed on
        # the loop that built it.
        import threading

        built: list = []

        def from_url(url, **kw):
            fake = _FakeRedis()
            built.append(fake)
            return fake

        _install_fake_redis_module(monkeypatch, from_url)
        storage = SessionStorage()

        ready = threading.Event()
        release = threading.Event()

        def first_loop_owner():
            async def go():
                await storage.assign_session_pod("s1", "10.0.0.1")
                ready.set()
                # Stay alive so the close can actually be scheduled on us.
                while not release.is_set():
                    await asyncio.sleep(0.01)

            asyncio.run(go())

        t = threading.Thread(target=first_loop_owner)
        t.start()
        assert ready.wait(timeout=5)

        try:
            # A second loop drives the same storage -> rebuild.
            asyncio.run(storage.assign_session_pod("s2", "10.0.0.2"))
            assert len(built) == 2
            deadline = time.monotonic() + 3.0
            while not built[0].closed and time.monotonic() < deadline:
                time.sleep(0.01)
            assert built[0].closed is True, "the replaced client leaked"
        finally:
            release.set()
            t.join(timeout=5)

    def test_a_client_whose_loop_is_gone_is_not_awaited(self, monkeypatch):
        # A closed loop has already torn its transports down; scheduling on it
        # would just hang. Must degrade quietly, not raise.
        built: list = []

        def from_url(url, **kw):
            fake = _FakeRedis()
            built.append(fake)
            return fake

        _install_fake_redis_module(monkeypatch, from_url)
        storage = SessionStorage()

        asyncio.run(storage.assign_session_pod("s1", "10.0.0.1"))
        asyncio.run(storage.assign_session_pod("s2", "10.0.0.2"))

        assert len(built) == 2
        assert storage.redis_client is built[1]

    def test_client_is_rebuilt_for_a_second_event_loop(self, monkeypatch):
        # An asyncio Redis pool built on one loop and awaited on another is
        # the #1565 failure shape. SessionStorage is constructed on the
        # transient startup pipeline loop and used on the uvicorn loop.
        clients: list = []

        def from_url(url, **kw):
            fake = _FakeRedis()
            clients.append(fake)
            return fake

        _install_fake_redis_module(monkeypatch, from_url)

        storage = SessionStorage()

        asyncio.run(storage.assign_session_pod("s1", "10.0.0.1"))
        asyncio.run(storage.assign_session_pod("s2", "10.0.0.2"))

        assert len(clients) == 2, "client was reused across event loops"


class TestStats:
    def test_stats_report_the_memory_backend(self):
        storage = SessionStorage()
        storage._memory_set("session:live", "a", ttl=60)
        storage._memory_set("session:dead", "b", ttl=0)

        stats = asyncio.run(storage.get_stats())

        assert stats["storage_type"] == "memory"
        assert stats["redis_available"] is False
        # Expired entries are not counted as sessions.
        assert stats["total_sessions"] == 1
