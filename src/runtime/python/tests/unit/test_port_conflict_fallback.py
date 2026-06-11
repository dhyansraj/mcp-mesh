"""
Tests for issue #1194: port bind failure must never produce a phantom
registration (registered port != bound port).

Covers:
- ``bind_server_socket_with_fallback``: exact bind, conflict fallback with
  prominent warning naming the configured port, explicit port-0 auto-assign.
- ``_resolve_registration_port``: the heartbeat-side invariant — the actual
  bound port (from ``bound_port`` / ``existing_server.port`` context) is
  authoritative over the configured port.
- End-to-end serving: uvicorn started on the pre-bound fallback socket
  actually answers HTTP on the auto-assigned port while the configured port
  stays owned by the conflicting listener.
- Startup gate: a bound socket is not a serving socket — the immediate
  server is only recorded as "running" (and thus registrable) after uvicorn
  reports ``started``; post-bind startup failures store no server record.
"""

import logging
import socket
import threading
import time

import pytest

from _mcp_mesh.pipeline.mcp_heartbeat.rust_heartbeat import (
    _resolve_registration_port,
)
from _mcp_mesh.shared.port_binding import bind_server_socket_with_fallback

BIND_HOST = "127.0.0.1"


@pytest.fixture
def occupied_port():
    """Bind a listening socket on an OS-assigned port and keep it open."""
    blocker = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    blocker.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    blocker.bind((BIND_HOST, 0))
    blocker.listen(1)
    port = blocker.getsockname()[1]
    yield port
    blocker.close()


class TestBindServerSocketWithFallback:
    """Unit tests for the pre-bind helper."""

    def test_binds_exact_port_when_free(self):
        """A free configured port is bound exactly — no fallback."""
        # Find a free port, release it, then ask the helper for it.
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        probe.bind((BIND_HOST, 0))
        free_port = probe.getsockname()[1]
        probe.close()

        sock, actual_port = bind_server_socket_with_fallback(BIND_HOST, free_port)
        try:
            assert actual_port == free_port
            assert sock.getsockname()[1] == free_port
        finally:
            sock.close()

    def test_port_zero_auto_assigns(self, caplog):
        """Explicit port 0 binds an OS-assigned port without any warning."""
        with caplog.at_level(logging.WARNING, logger="_mcp_mesh.shared.port_binding"):
            sock, actual_port = bind_server_socket_with_fallback(BIND_HOST, 0)
        try:
            assert actual_port > 0
            assert sock.getsockname()[1] == actual_port
            assert "PORT CONFLICT" not in caplog.text
        finally:
            sock.close()

    def test_conflict_falls_back_to_os_assigned_port(self, occupied_port, caplog):
        """A conflicting configured port falls back to an OS-assigned port,
        with a prominent warning naming the configured port."""
        with caplog.at_level(logging.WARNING, logger="_mcp_mesh.shared.port_binding"):
            sock, actual_port = bind_server_socket_with_fallback(
                BIND_HOST, occupied_port
            )
        try:
            assert actual_port != occupied_port
            assert actual_port > 0
            # The returned port is read back from the bound socket.
            assert sock.getsockname()[1] == actual_port
            # Prominent warning names the conflicting configured port.
            assert "PORT CONFLICT" in caplog.text
            assert str(occupied_port) in caplog.text
        finally:
            sock.close()

    def test_returned_socket_is_actually_bound(self, occupied_port):
        """The fallback socket is owned by this process — a fresh bind to
        the same port must fail (proves we did not just pick a number)."""
        sock, actual_port = bind_server_socket_with_fallback(BIND_HOST, occupied_port)
        try:
            sock.listen(1)
            other = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            with pytest.raises(OSError):
                other.bind((BIND_HOST, actual_port))
            other.close()
        finally:
            sock.close()


class TestResolveRegistrationPort:
    """The heartbeat must register the bound port, never a phantom one."""

    def test_bound_port_context_key_is_authoritative(self, caplog):
        """Orchestrator-bound socket port overrides a conflicting config port."""
        with caplog.at_level(
            logging.WARNING, logger="_mcp_mesh.pipeline.mcp_heartbeat.rust_heartbeat"
        ):
            port = _resolve_registration_port(9000, {"bound_port": 54321})
        assert port == 54321
        assert "ACTUAL bound port 54321" in caplog.text
        assert "9000" in caplog.text

    def test_existing_server_port_is_authoritative(self):
        """Immediate-uvicorn discovered server port overrides the config port."""
        context = {"existing_server": {"port": 54321, "status": "running"}}
        assert _resolve_registration_port(9000, context) == 54321

    def test_port_zero_uses_detected_port(self):
        """Existing port-0 flow: detected port is registered (unchanged behavior)."""
        context = {"existing_server": {"port": 43210}}
        assert _resolve_registration_port(0, context) == 43210

    def test_matching_ports_pass_through_silently(self, caplog):
        """Normal fixed-port flow: bound == configured, no warning."""
        with caplog.at_level(
            logging.WARNING, logger="_mcp_mesh.pipeline.mcp_heartbeat.rust_heartbeat"
        ):
            port = _resolve_registration_port(8080, {"bound_port": 8080})
        assert port == 8080
        assert "ACTUAL bound port" not in caplog.text

    def test_no_bind_info_falls_back_to_configured(self):
        """Without any bind record (synthetic contexts), config port is used."""
        assert _resolve_registration_port(8080, {}) == 8080
        assert _resolve_registration_port(8080, {"existing_server": None}) == 8080
        assert _resolve_registration_port(8080, {"existing_server": {}}) == 8080


class TestImmediateServerStartupGate:
    """Issue #1194 follow-up: a bound socket is not a serving socket.

    ``_start_uvicorn_immediately`` must not record a "running" server (and
    therefore must not let the heartbeat register the port) until uvicorn
    reports ``started``. Previously a post-bind failure — e.g.
    ``uvicorn.Config.load()`` raising on bad TLS cert paths — died inside
    the server thread while the agent advertised a port that refused every
    connection.
    """

    @pytest.fixture(autouse=True)
    def clean_global_state(self):
        """Isolate DecoratorRegistry + shutdown-coordinator global state."""
        from _mcp_mesh.engine.decorator_registry import DecoratorRegistry
        from _mcp_mesh.shared import simple_shutdown

        DecoratorRegistry.clear_immediate_uvicorn_server()
        saved_servers = list(
            simple_shutdown._simple_shutdown_coordinator._uvicorn_servers
        )
        yield
        DecoratorRegistry.clear_immediate_uvicorn_server()
        simple_shutdown._simple_shutdown_coordinator._uvicorn_servers = saved_servers

    def test_post_bind_failure_raises_and_stores_no_server(self, monkeypatch):
        """Server thread dies post-bind (e.g. bad TLS cert paths inside
        ``Config.load()``): no running server record, the bound socket is
        released, and the failure is loud (raises)."""
        import uvicorn

        from _mcp_mesh.engine.decorator_registry import DecoratorRegistry
        from mesh import decorators

        def failing_run(self, sockets=None):
            raise RuntimeError(
                "simulated post-bind startup failure (bad TLS cert path)"
            )

        monkeypatch.setattr(uvicorn.Server, "run", failing_run)

        # Known free port so the socket-release assertion below is exact.
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        probe.bind((BIND_HOST, 0))
        free_port = probe.getsockname()[1]
        probe.close()

        with pytest.raises(decorators.ImmediateServerStartupError):
            decorators._start_uvicorn_immediately(BIND_HOST, free_port)

        # No "running" record — nothing for the heartbeat to register.
        assert DecoratorRegistry.get_immediate_uvicorn_server() is None

        # The pre-bound socket was released: the port is bindable again.
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((BIND_HOST, free_port))
        finally:
            sock.close()

    def test_wedged_startup_stores_no_running_record(self, monkeypatch):
        """Thread alive but ``started`` never flips within the budget: the
        function returns WITHOUT a running record (the pipeline's no-server
        path takes over) and without raising — the wedged server may still
        come up, and the shutdown coordinator signals all servers."""
        import uvicorn

        from _mcp_mesh.engine.decorator_registry import DecoratorRegistry
        from mesh import decorators

        release = threading.Event()

        def wedged_run(self, sockets=None):
            # Never flips self.started — wedged after the bind.
            release.wait(timeout=10)

        monkeypatch.setattr(uvicorn.Server, "run", wedged_run)
        monkeypatch.setattr(
            decorators, "_IMMEDIATE_SERVER_STARTUP_TIMEOUT_SECONDS", 0.3
        )

        try:
            decorators._start_uvicorn_immediately(BIND_HOST, 0)
            assert DecoratorRegistry.get_immediate_uvicorn_server() is None
        finally:
            release.set()


class TestUvicornServesOnFallbackSocket:
    """End-to-end: the agent comes up on the auto-assigned port when the
    configured port is occupied, and the pre-bound socket is what serves."""

    @pytest.mark.slow
    def test_uvicorn_serves_on_fallback_port(self, occupied_port):
        uvicorn = pytest.importorskip("uvicorn")
        fastapi = pytest.importorskip("fastapi")
        import urllib.request

        app = fastapi.FastAPI()

        @app.get("/ping")
        def ping():
            return {"ok": True}

        # Same flow as mesh/decorators._start_uvicorn_immediately:
        # pre-bind with fallback, then hand uvicorn the bound socket.
        sock, actual_port = bind_server_socket_with_fallback(
            BIND_HOST, occupied_port
        )
        assert actual_port != occupied_port

        config = uvicorn.Config(app, host=BIND_HOST, port=actual_port, log_level="error")
        server = uvicorn.Server(config)
        thread = threading.Thread(
            target=lambda: server.run(sockets=[sock]), daemon=True
        )
        thread.start()
        try:
            deadline = time.time() + 10
            while not server.started:
                if time.time() > deadline:
                    pytest.fail("uvicorn did not start on the fallback socket")
                time.sleep(0.05)

            with urllib.request.urlopen(
                f"http://{BIND_HOST}:{actual_port}/ping", timeout=5
            ) as resp:
                assert resp.status == 200

            # Invariant check: the port uvicorn actually serves on is the
            # port we would register.
            served_port = server.servers[0].sockets[0].getsockname()[1]
            assert served_port == actual_port
        finally:
            server.should_exit = True
            thread.join(timeout=10)
