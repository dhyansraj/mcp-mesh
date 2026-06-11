"""Unit tests for ``simple_shutdown`` signal-handler / uvicorn coordination.

Covers issue #1029 — the SIGTERM signal handler must request graceful
uvicorn shutdown (so the FastAPI lifespan exit phase runs) instead of
just setting a flag and letting the uvicorn worker thread get killed
mid-flight.
"""

from __future__ import annotations

import signal
from types import SimpleNamespace

import pytest

from _mcp_mesh.shared import simple_shutdown


@pytest.fixture
def coordinator():
    """Fresh SimpleShutdownCoordinator per test — avoid global-state spill."""
    return simple_shutdown.SimpleShutdownCoordinator()


@pytest.fixture
def restore_signal_handlers():
    """Snapshot SIGTERM/SIGINT handlers and restore after the test.

    install_signal_handlers() mutates process-wide signal disposition;
    without this fixture, pytest's own KeyboardInterrupt handling would
    be clobbered for the rest of the run.
    """
    saved_int = signal.getsignal(signal.SIGINT)
    saved_term = signal.getsignal(signal.SIGTERM)
    yield
    signal.signal(signal.SIGINT, saved_int)
    signal.signal(signal.SIGTERM, saved_term)


class TestRegisterUvicornServer:
    """register_uvicorn_server stores the handle(s) so the signal handler can
    flip should_exit on every registered server.
    """

    def test_register_stores_server(self, coordinator):
        mock_server = SimpleNamespace(should_exit=False)
        coordinator.register_uvicorn_server(mock_server)
        assert mock_server in coordinator._uvicorn_servers

    def test_register_accumulates_multiple_servers(self, coordinator):
        # Degenerate startups can leave two live servers in the process
        # (immediate decorator server + pipeline-started server). The
        # coordinator must keep BOTH — a single slot would orphan the
        # first server's non-daemon thread on SIGTERM.
        first = SimpleNamespace(should_exit=False)
        second = SimpleNamespace(should_exit=False)
        coordinator.register_uvicorn_server(first)
        coordinator.register_uvicorn_server(second)
        assert coordinator._uvicorn_servers == [first, second]

    def test_register_is_identity_deduplicated(self, coordinator):
        mock_server = SimpleNamespace(should_exit=False)
        coordinator.register_uvicorn_server(mock_server)
        coordinator.register_uvicorn_server(mock_server)
        assert coordinator._uvicorn_servers == [mock_server]

    def test_register_none_is_a_noop(self, coordinator):
        coordinator.register_uvicorn_server(None)
        assert coordinator._uvicorn_servers == []

    def test_module_level_function_delegates_to_global_coordinator(self):
        # The module-level helper just forwards to the global singleton.
        mock_server = SimpleNamespace(should_exit=False)
        previous = list(
            simple_shutdown._simple_shutdown_coordinator._uvicorn_servers
        )
        try:
            simple_shutdown.register_uvicorn_server(mock_server)
            assert (
                mock_server
                in simple_shutdown._simple_shutdown_coordinator._uvicorn_servers
            )
        finally:
            simple_shutdown._simple_shutdown_coordinator._uvicorn_servers = previous


class TestSignalHandlerRequestsUvicornShutdown:
    """Issue #1029 — signal handler must flip server.should_exit so uvicorn
    runs its graceful shutdown (which drives the FastAPI lifespan exit
    phase) instead of having the worker thread killed mid-flight.
    """

    def test_handler_flips_should_exit_on_registered_server(
        self, coordinator, restore_signal_handlers
    ):
        mock_server = SimpleNamespace(should_exit=False)
        coordinator.register_uvicorn_server(mock_server)
        coordinator.install_signal_handlers()

        # Pull the installed handler back out and invoke it directly —
        # this is what os.kill(pid, SIGTERM) would do inside the
        # interpreter, but synchronous and observable.
        installed = signal.getsignal(signal.SIGTERM)
        installed(signal.SIGTERM, None)

        assert mock_server.should_exit is True
        assert coordinator.is_shutdown_requested() is True

    def test_handler_also_handles_sigint(
        self, coordinator, restore_signal_handlers
    ):
        mock_server = SimpleNamespace(should_exit=False)
        coordinator.register_uvicorn_server(mock_server)
        coordinator.install_signal_handlers()

        installed = signal.getsignal(signal.SIGINT)
        installed(signal.SIGINT, None)

        assert mock_server.should_exit is True
        assert coordinator.is_shutdown_requested() is True

    def test_handler_flips_should_exit_on_every_registered_server(
        self, coordinator, restore_signal_handlers
    ):
        # Both the immediate decorator server and a pipeline-started
        # server must receive the graceful-shutdown request — neither
        # non-daemon server thread may be orphaned on SIGTERM.
        first = SimpleNamespace(should_exit=False)
        second = SimpleNamespace(should_exit=False)
        coordinator.register_uvicorn_server(first)
        coordinator.register_uvicorn_server(second)
        coordinator.install_signal_handlers()

        installed = signal.getsignal(signal.SIGTERM)
        installed(signal.SIGTERM, None)

        assert first.should_exit is True
        assert second.should_exit is True
        assert coordinator.is_shutdown_requested() is True

    def test_handler_without_registered_server_just_sets_flag(
        self, coordinator, restore_signal_handlers
    ):
        # No register_uvicorn_server() call — handler must not crash; it
        # still has to set the shutdown-requested flag so the main-thread
        # join loop in start_blocking_loop_with_shutdown_support proceeds.
        coordinator.install_signal_handlers()
        installed = signal.getsignal(signal.SIGTERM)
        installed(signal.SIGTERM, None)

        assert coordinator.is_shutdown_requested() is True
        assert coordinator._uvicorn_servers == []

    def test_handler_idempotent_when_server_already_exiting(
        self, coordinator, restore_signal_handlers
    ):
        # Re-firing the handler is safe — should_exit stays True, no
        # exception. (Real uvicorn observes the flag and bails on second
        # observation; we just have to not crash.)
        mock_server = SimpleNamespace(should_exit=True)
        coordinator.register_uvicorn_server(mock_server)
        coordinator.install_signal_handlers()

        installed = signal.getsignal(signal.SIGTERM)
        installed(signal.SIGTERM, None)
        installed(signal.SIGTERM, None)

        assert mock_server.should_exit is True
