"""Issue #1589: ``auto_run=False`` must still join the mesh.

``auto_run`` gates the SERVER and the KEEP-ALIVE, not mesh membership. The
orchestrator used to treat a disabled auto-run as "single execution mode":
it ran the pipeline and returned without ever starting a heartbeat, so the
agent wired dependency injection locally and never registered. An agent that
does not register is not in the mesh at all, which is the opposite of what
"embed mesh in your own server loop" is for.

Required behaviour: run the pipeline, start the background heartbeat, do NOT
start uvicorn, do NOT block.
"""

import threading
import time
from datetime import datetime

import pytest

from _mcp_mesh.engine.decorator_registry import DecoratedFunction, DecoratorRegistry
from _mcp_mesh.pipeline.mcp_startup import startup_orchestrator as so
from _mcp_mesh.pipeline.mcp_startup.startup_orchestrator import DebounceCoordinator


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.delenv("MCP_MESH_AUTO_RUN", raising=False)
    DecoratorRegistry.clear_all()
    yield
    DecoratorRegistry.clear_all()


def _register_agent(auto_run):
    def _agent():  # pragma: no cover - never called
        return None

    DecoratorRegistry._mesh_agents["_agent"] = DecoratedFunction(
        decorator_type="mesh_agent",
        function=_agent,
        metadata={"name": "a", "auto_run": auto_run},
        registered_at=datetime.now(),
    )


class _UnwritableConfig(dict):
    """Reads fine, rejects the write _setup_heartbeat_background does first."""

    def __setitem__(self, key, value):
        raise RuntimeError("cannot stage heartbeat config")


class _Recorder:
    """Stands in for the pipeline + uvicorn so the branch logic is observable."""

    def __init__(self, pipeline_type="mcp", status="success"):
        self.pipeline_type = pipeline_type
        self.status = status
        self.heartbeats_fired = threading.Event()
        self.server_started = False
        self.ran_pipeline = False
        self.heartbeat_thread = None
        self.standalone = False
        self.drop_app = False
        self.break_heartbeat_setup = False
        self.raise_error = None

    async def _process(self):
        self.ran_pipeline = True
        if self.raise_error is not None:
            raise self.raise_error
        heartbeat_config = {
            "agent_id": "agent-1",
            "service_id": "agent-1",
            "heartbeat_task_fn": self._heartbeat,
            "standalone_mode": self.standalone,
        }
        if self.break_heartbeat_setup:
            heartbeat_config = _UnwritableConfig(heartbeat_config)
        return {
            "status": self.status,
            "message": "boom" if self.status == "failed" else "",
            "context": {
                "pipeline_context": {
                    "fastapi_app": None if self.drop_app else object(),
                    "fastapi_binding_config": {
                        "bind_host": "127.0.0.1",
                        "bind_port": 0,
                    },
                    "heartbeat_config": heartbeat_config,
                }
            },
        }

    async def _heartbeat(self, heartbeat_config):
        # Runs ON the heartbeat thread, so this is the thread under test.
        self.heartbeat_thread = threading.current_thread()
        self.heartbeats_fired.set()

    def install(self, monkeypatch, coordinator):
        orchestrator = type(
            "FakeOrchestrator",
            (),
            {
                "process_once": lambda _self: self._process(),
                "process_api_once": lambda _self: self._process(),
                "process_a2a_once": lambda _self: self._process(),
            },
        )()
        coordinator.set_orchestrator(orchestrator)
        monkeypatch.setattr(
            coordinator, "_determine_pipeline_type", lambda: self.pipeline_type
        )

        def _no_server(*args, **kwargs):
            self.server_started = True
            time.sleep(30)  # a real blocking server never returns

        monkeypatch.setattr(
            DebounceCoordinator, "_start_blocking_fastapi_server", _no_server
        )
        monkeypatch.setattr(
            so, "abort_agent_process", lambda *a, **k: pytest.fail("aborted")
        )
        return self


def _run(coordinator, timeout=10.0):
    """Execute processing on a worker thread; return True if it RETURNED."""
    done = threading.Event()
    error = []

    def _target():
        try:
            coordinator._execute_processing()
        except BaseException as e:  # noqa: BLE001
            error.append(e)
        finally:
            done.set()

    t = threading.Thread(target=_target, daemon=True)
    t.start()
    returned = done.wait(timeout)
    return returned, error


class TestEmbeddedMode:
    def test_auto_run_false_still_starts_the_heartbeat(self, monkeypatch):
        _register_agent(False)
        c = DebounceCoordinator(delay_seconds=0.01)
        rec = _Recorder().install(monkeypatch, c)

        returned, error = _run(c)

        assert returned, "_execute_processing blocked; it must return"
        assert not error, f"unexpected error: {error}"
        assert rec.ran_pipeline, "pipeline must run so the agent registers"
        assert rec.heartbeats_fired.wait(5), (
            "no heartbeat fired with auto_run=False — the agent registered "
            "once at best and would never stay registered"
        )

    def test_auto_run_false_does_not_start_a_server(self, monkeypatch):
        _register_agent(False)
        c = DebounceCoordinator(delay_seconds=0.01)
        rec = _Recorder().install(monkeypatch, c)

        returned, _ = _run(c)

        assert returned
        assert not rec.server_started, "auto_run=False must not start uvicorn"

    def test_auto_run_false_does_not_keep_the_process_alive(self, monkeypatch):
        """The caller's own loop owns process lifetime, so the call returns."""
        _register_agent(False)
        c = DebounceCoordinator(delay_seconds=0.01)
        _Recorder().install(monkeypatch, c)

        returned, _ = _run(c, timeout=10.0)

        assert returned, "_execute_processing must not block on a keep-alive"

    def test_heartbeat_thread_is_a_daemon(self, monkeypatch):
        """A non-daemon heartbeat would keep the process alive on mesh's behalf."""
        _register_agent(False)
        c = DebounceCoordinator(delay_seconds=0.01)
        rec = _Recorder().install(monkeypatch, c)

        returned, _ = _run(c)
        assert returned
        assert rec.heartbeats_fired.wait(5)

        assert rec.heartbeat_thread is not None
        assert rec.heartbeat_thread is not threading.main_thread()
        assert rec.heartbeat_thread.daemon, (
            "a non-daemon heartbeat thread would keep the interpreter alive, "
            "which is exactly what auto_run=False asks mesh not to do"
        )

    def test_auto_run_true_still_starts_the_server(self, monkeypatch):
        """Regression guard: the auto-run path is unchanged."""
        _register_agent(True)
        c = DebounceCoordinator(delay_seconds=0.01)
        rec = _Recorder().install(monkeypatch, c)

        _run(c, timeout=6.0)

        assert rec.server_started, "auto_run=True must still start uvicorn"

    @pytest.mark.parametrize("value", ["false", "0", "no", "off"])
    def test_env_false_overrides_decorator_true(self, monkeypatch, value):
        """ENV > decorator: env-disabled behaves exactly like auto_run=False."""
        monkeypatch.setenv("MCP_MESH_AUTO_RUN", value)
        _register_agent(True)
        c = DebounceCoordinator(delay_seconds=0.01)
        rec = _Recorder().install(monkeypatch, c)

        returned, _ = _run(c)

        assert returned
        assert not rec.server_started
        assert rec.heartbeats_fired.wait(5), "env-disabled must still heartbeat"

    @pytest.mark.parametrize("pipeline_type", ["api", "a2a"])
    def test_gateway_pipelines_heartbeat_when_auto_run_is_disabled(
        self, monkeypatch, pipeline_type
    ):
        """API/A2A never blocked anyway; they must not lose their heartbeat."""
        monkeypatch.setenv("MCP_MESH_AUTO_RUN", "false")
        c = DebounceCoordinator(delay_seconds=0.01)
        rec = _Recorder(pipeline_type=pipeline_type).install(monkeypatch, c)

        fired = threading.Event()
        module = (
            "_mcp_mesh.pipeline.api_heartbeat.api_lifespan_integration"
            if pipeline_type == "api"
            else "_mcp_mesh.pipeline.a2a_heartbeat.a2a_lifespan_integration"
        )
        name = (
            "api_heartbeat_lifespan_task"
            if pipeline_type == "api"
            else "a2a_heartbeat_lifespan_task"
        )
        import importlib

        async def _task(cfg):
            fired.set()

        monkeypatch.setattr(importlib.import_module(module), name, _task)

        returned, _ = _run(c)

        assert returned
        assert not rec.server_started
        assert fired.wait(5), f"{pipeline_type} lost its heartbeat with auto_run=false"

    def test_pipeline_failure_still_raises_in_embedded_mode(self, monkeypatch):
        _register_agent(False)
        c = DebounceCoordinator(delay_seconds=0.01)
        _Recorder(status="failed").install(monkeypatch, c)

        returned, error = _run(c)

        assert returned
        assert error and isinstance(error[0], RuntimeError)
        assert "pipeline failed" in str(error[0])

    def test_embedded_mode_does_not_prime_the_agent_config_cache(self, monkeypatch):
        monkeypatch.setenv("MCP_MESH_AUTO_RUN", "false")
        c = DebounceCoordinator(delay_seconds=0.01)
        _Recorder(pipeline_type="api").install(monkeypatch, c)

        # Keep the real Rust-backed API heartbeat out of a unit test.
        import _mcp_mesh.pipeline.api_heartbeat.api_lifespan_integration as api_mod

        async def _task(cfg):
            return None

        monkeypatch.setattr(api_mod, "api_heartbeat_lifespan_task", _task)

        assert DecoratorRegistry._cached_agent_config is None
        _run(c)
        assert DecoratorRegistry._cached_agent_config is None


class TestEmbeddedFailureContract:
    """The failure signal must survive the real ``threading.Timer`` path.

    ``_execute_processing`` does not run on the caller's thread — the debounce
    coordinator schedules it on a ``threading.Timer``. A ``raise`` there reaches
    ``threading.excepthook`` and kills that thread; the caller's server keeps
    serving an agent that never registered, and the process still exits 0. That
    is issue #1556. These tests drive the coordinator the way a decorator does
    (``trigger_processing()``), never by calling ``_execute_processing``
    directly, so a contract that only "works" on a collected thread fails here.
    """

    @pytest.fixture(autouse=True)
    def _reset_status(self):
        from _mcp_mesh.pipeline.mcp_startup import embedded_status

        embedded_status.reset()
        yield
        embedded_status.reset()

    def _drive_through_timer(self, coordinator, timeout=10.0):
        """Trigger via the debounce timer and wait for the outcome to land."""
        from _mcp_mesh.pipeline.mcp_startup import embedded_status

        coordinator.trigger_processing()
        deadline = time.time() + timeout
        while time.time() < deadline:
            status = embedded_status.get_status()
            if status["state"] != embedded_status.PENDING:
                return status
            time.sleep(0.05)
        return embedded_status.get_status()

    def test_failure_is_observable_after_the_timer_thread_dies(self, monkeypatch):
        _register_agent(False)
        c = DebounceCoordinator(delay_seconds=0.01)
        _Recorder(status="failed").install(monkeypatch, c)

        status = self._drive_through_timer(c)

        assert status["state"] == "failed", (
            "the pipeline failed on the timer thread and left no trace the "
            "caller can see — this is the #1556 shape"
        )
        assert "boom" in (status["error"] or "")
        assert status["heartbeat"] is False

    def test_failure_is_reachable_through_the_public_accessor(self, monkeypatch):
        import mesh

        _register_agent(False)
        c = DebounceCoordinator(delay_seconds=0.01)
        _Recorder(status="failed").install(monkeypatch, c)

        self._drive_through_timer(c)

        assert mesh.startup_status()["state"] == "failed"

    def test_success_is_observable_through_the_timer_path(self, monkeypatch):
        _register_agent(False)
        c = DebounceCoordinator(delay_seconds=0.01)
        rec = _Recorder().install(monkeypatch, c)

        status = self._drive_through_timer(c)

        assert status["state"] == "ready"
        assert status["pipeline_type"] == "mcp"
        assert status["heartbeat"] is True
        assert status["warnings"] == []
        assert rec.heartbeats_fired.wait(5)

    def test_standalone_mode_is_reported_not_announced_as_success(self, monkeypatch):
        """standalone_mode skips the heartbeat, so the agent will not stay in."""
        _register_agent(False)
        c = DebounceCoordinator(delay_seconds=0.01)
        rec = _Recorder().install(monkeypatch, c)
        rec.standalone = True

        status = self._drive_through_timer(c)

        assert status["state"] == "ready"
        assert status["heartbeat"] is False
        assert any("will not stay registered" in w for w in status["warnings"])

    def test_missing_app_is_reported(self, monkeypatch):
        """A pipeline can succeed and still leave nothing for the caller to serve."""
        _register_agent(False)
        c = DebounceCoordinator(delay_seconds=0.01)
        rec = _Recorder().install(monkeypatch, c)
        rec.drop_app = True

        status = self._drive_through_timer(c)

        assert status["state"] == "ready"
        assert any("nothing for your server loop" in w for w in status["warnings"])

    def test_pipeline_crash_is_observable_as_failed(self, monkeypatch):
        """A RAISING pipeline must not leave the caller polling forever.

        The failed-result branch only fires when the pipeline returns
        ``status == "failed"``. When it raises instead, the exception lands on
        the timer thread and nothing was ever recorded, so
        ``startup_status()`` stayed ``pending`` — worse than ``failed``,
        because a caller cannot tell "still starting" from "crashed and never
        will" and waits indefinitely instead of shutting down.
        """
        _register_agent(False)
        c = DebounceCoordinator(delay_seconds=0.01)
        rec = _Recorder().install(monkeypatch, c)
        rec.raise_error = KeyError("registry_url")

        status = self._drive_through_timer(c)

        assert status["state"] == "failed", (
            "the pipeline raised on the timer thread and left no trace the "
            "caller can see — startup_status() is still 'pending' forever"
        )
        # The class matters: str(KeyError("registry_url")) is just
        # "'registry_url'", which reads like a stray string on its own.
        assert "KeyError" in (status["error"] or "")
        assert "registry_url" in (status["error"] or "")
        assert status["heartbeat"] is False

    def test_crash_still_propagates_to_the_outer_handler(self, monkeypatch):
        """Recording the outcome must not swallow the exception."""
        _register_agent(False)
        c = DebounceCoordinator(delay_seconds=0.01)
        rec = _Recorder().install(monkeypatch, c)
        rec.raise_error = KeyError("registry_url")

        returned, error = _run(c)

        assert returned
        assert error and isinstance(error[0], KeyError)

    def test_failed_result_detail_is_not_overwritten_by_its_own_raise(
        self, monkeypatch
    ):
        """The failed-result branch records, then raises. That raise now passes
        through the crash handler, which must not replace the pipeline's own
        message with a paraphrase of the RuntimeError wrapping it."""
        _register_agent(False)
        c = DebounceCoordinator(delay_seconds=0.01)
        _Recorder(status="failed").install(monkeypatch, c)

        status = self._drive_through_timer(c)

        assert status["state"] == "failed"
        assert status["error"] == "boom", (
            f"the recorded detail was clobbered by the re-raise: {status['error']!r}"
        )

    def test_unsupported_pipeline_type_is_recorded_too(self, monkeypatch):
        """A mesh bug leaves the caller in the same place as a runtime failure.

        Nothing registered and nothing ever will be, so it gets a terminal
        status rather than an indefinite ``pending``.
        """
        _register_agent(False)
        c = DebounceCoordinator(delay_seconds=0.01)
        _Recorder(pipeline_type="bogus").install(monkeypatch, c)

        status = self._drive_through_timer(c)

        assert status["state"] == "failed"
        assert "Unsupported pipeline type" in (status["error"] or "")

    def test_heartbeat_setup_failure_is_not_reported_as_healthy(self, monkeypatch):
        """_setup_heartbeat_background swallows exceptions into a warning.

        Exercised through the real swallow path: the config write it does first
        (``heartbeat_config["context"] = ...``) raises, so setup bails inside
        its own ``except`` without ever starting a thread.
        """
        _register_agent(False)
        c = DebounceCoordinator(delay_seconds=0.01)
        rec = _Recorder().install(monkeypatch, c)
        rec.break_heartbeat_setup = True

        status = self._drive_through_timer(c)

        assert status["state"] == "ready"
        assert status["heartbeat"] is False
        assert any("will not stay registered" in w for w in status["warnings"])
