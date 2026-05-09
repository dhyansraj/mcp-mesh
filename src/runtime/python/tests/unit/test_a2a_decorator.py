"""Unit tests for the @mesh.a2a decorator + mesh.a2a.mount helper +
agent card generator + heartbeat plumbing introduced in Phase 1B of
issue #903.

See A2A_SURFACE_DESIGN.org for the full design — these tests cover the
Python runtime surface only:

  * Decorator validation (path required, auth restrictions, dep shape)
  * Decorator-only path: stamps metadata, does NOT mount any routes
  * mesh.a2a.mount(): registers card + JSON-RPC routes on the user's app
  * Agent card generator: A2A v1.0 shape for sync vs streaming surfaces
  * Heartbeat preparation: agent_type=a2a + surfaces array shape
  * Phase-1B JSON-RPC route: returns Method-not-implemented for tasks/*
  * Public-URL cache contract used by the agent-card endpoint
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

import mesh
from _mcp_mesh.engine.a2a_card import build_agent_card
from _mcp_mesh.engine.decorator_registry import DecoratedFunction, DecoratorRegistry
from _mcp_mesh.pipeline.mcp_startup.heartbeat_preparation import (
    HeartbeatPreparationStep,
)
from _mcp_mesh.pipeline.shared import PipelineStatus


# Each test wipes the custom-decorator slot so registrations across tests
# don't leak — DecoratorRegistry is process-global by design.
@pytest.fixture(autouse=True)
def _reset_registry():
    DecoratorRegistry._custom_decorators.pop("mesh_a2a", None)
    yield
    DecoratorRegistry._custom_decorators.pop("mesh_a2a", None)


class TestA2ADecoratorValidation:
    """Decorator-time validation: path, auth, multi-dep warning."""

    def test_path_is_required(self):
        with pytest.raises(TypeError):
            # Missing required keyword arg.
            @mesh.a2a()  # type: ignore[call-arg]
            def f():
                pass

    def test_path_must_start_with_slash(self):
        with pytest.raises(ValueError, match="must start with"):

            @mesh.a2a(path="agents/foo")
            def f():
                pass

    def test_empty_path_rejected(self):
        with pytest.raises(ValueError):

            @mesh.a2a(path="")
            def f():
                pass

    def test_auth_bearer_accepted(self):
        @mesh.a2a(path="/agents/foo", auth="bearer")
        def f():
            pass

        # Resolve to underlying registered function (decorator may wrap).
        registered = DecoratorRegistry.get_all_by_type("mesh_a2a")
        assert "f" in registered
        assert registered["f"].metadata["auth"] == "bearer"

    def test_auth_none_accepted(self):
        @mesh.a2a(path="/agents/foo")
        def f():
            pass

        registered = DecoratorRegistry.get_all_by_type("mesh_a2a")
        assert registered["f"].metadata["auth"] is None

    def test_auth_other_scheme_rejected(self):
        with pytest.raises(ValueError, match="not supported in v1"):

            @mesh.a2a(path="/agents/foo", auth="oauth2")
            def f():
                pass

    def test_skill_id_derived_from_path(self):
        @mesh.a2a(path="/agents/report-generator")
        def f():
            pass

        registered = DecoratorRegistry.get_all_by_type("mesh_a2a")
        assert registered["f"].metadata["skill_id"] == "report-generator"

    def test_skill_name_titlecased_from_skill_id(self):
        @mesh.a2a(path="/agents/quick-lookup")
        def f():
            pass

        registered = DecoratorRegistry.get_all_by_type("mesh_a2a")
        assert registered["f"].metadata["skill_name"] == "Quick Lookup"

    def test_default_input_output_modes_application_json(self):
        @mesh.a2a(path="/agents/foo")
        def f():
            pass

        md = DecoratorRegistry.get_all_by_type("mesh_a2a")["f"].metadata
        assert md["input_modes"] == ["application/json"]
        assert md["output_modes"] == ["application/json"]


class TestDecoratorOnlyDoesNotMount:
    """Bare ``@mesh.a2a`` stamps metadata but does NOT touch any FastAPI app.

    This is the key UX guarantee of the refactor: the decorator is now
    a pure metadata + DI primitive (mirroring ``@mesh.route``), and route
    mounting is opt-in via ``mesh.a2a.mount(app, ...)``.
    """

    def test_decorator_alone_registers_metadata_only(self):
        @mesh.a2a(path="/agents/bare", description="Bare surface")
        def bare_a2a(payload: dict):
            return {"ok": True}

        registered = DecoratorRegistry.get_all_by_type("mesh_a2a")
        assert "bare_a2a" in registered
        md = registered["bare_a2a"].metadata
        assert md["path"] == "/agents/bare"
        assert md["description"] == "Bare surface"
        # The wrapper carries the metadata too (so the heartbeat path
        # can find it regardless of which reference the registry holds).
        assert hasattr(bare_a2a, "_mesh_a2a_metadata")


class TestA2AMountHelper:
    """``mesh.a2a.mount(app, ...)`` — the recommended user-facing entry."""

    def test_mount_is_attached_to_decorator(self):
        # Public surface: ``mesh.a2a.mount`` must be callable.
        assert callable(mesh.a2a.mount)

    def test_mount_registers_card_and_jsonrpc_routes(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        app = FastAPI()

        @mesh.a2a.mount(
            app,
            path="/agents/lookup",
            description="User lookup",
            tags=["users"],
        )
        async def lookup_a2a(payload: dict):
            return {"ok": True}

        with TestClient(app) as client:
            r = client.get("/agents/lookup/.well-known/agent.json")
            assert r.status_code == 200
            card = r.json()
            assert card["skills"][0]["id"] == "lookup"
            assert card["skills"][0]["tags"] == ["users"]
            # No bearer auth declared → schemes=[] (A2A v1.0 has no "none"
            # scheme; an empty list means "no advertised schemes").
            assert card["authentication"]["schemes"] == []

            # Phase 2: tasks/send dispatches into the handler and
            # wraps the result in an A2A v1.0 Task envelope.
            req = {
                "jsonrpc": "2.0",
                "method": "tasks/send",
                "params": {"id": "t-lookup-1", "message": {"role": "user", "parts": []}},
                "id": "req-1",
            }
            r = client.post("/agents/lookup", json=req)
            assert r.status_code == 200
            envelope = r.json()
            assert envelope["jsonrpc"] == "2.0"
            assert envelope["id"] == "req-1"
            assert "error" not in envelope
            task = envelope["result"]
            assert task["id"] == "t-lookup-1"
            assert task["status"]["state"] == "completed"

            # Other tasks/* still return Method-not-implemented.
            other = {
                "jsonrpc": "2.0",
                "method": "tasks/get",
                "params": {"id": "t-lookup-1"},
                "id": "req-2",
            }
            r = client.post("/agents/lookup", json=other)
            assert r.status_code == 200
            envelope = r.json()
            assert envelope["error"]["code"] == -32601
            assert "Method not implemented" in envelope["error"]["message"]

    def test_mount_records_metadata_for_heartbeat(self):
        # mount() should still register the surface in the
        # DecoratorRegistry so HeartbeatPreparationStep emits
        # agent_type=a2a + surfaces array.
        from fastapi import FastAPI

        app = FastAPI()

        @mesh.a2a.mount(
            app,
            path="/agents/metric",
            skill_id="metric",
            skill_name="Metric Surface",
        )
        async def metric_a2a(payload: dict):
            return payload

        registered = DecoratorRegistry.get_all_by_type("mesh_a2a")
        assert "metric_a2a" in registered
        md = registered["metric_a2a"].metadata
        assert md["path"] == "/agents/metric"
        assert md["skill_id"] == "metric"
        assert md["skill_name"] == "Metric Surface"

    def test_mount_returns_callable_for_direct_invocation(self):
        # The decorator returns the wrapped function so the user can
        # still hold a reference to a usable callable (handy for unit
        # tests that exercise the handler directly without HTTP).
        from fastapi import FastAPI

        app = FastAPI()

        @mesh.a2a.mount(app, path="/agents/echo")
        async def echo(payload: dict):
            return {"echoed": payload}

        assert callable(echo)

    def test_mount_bearer_auth_rejects_missing_header(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        app = FastAPI()

        @mesh.a2a.mount(app, path="/agents/secure", auth="bearer")
        async def secure(payload: dict):
            return {}

        with TestClient(app) as client:
            r = client.post(
                "/agents/secure",
                json={"jsonrpc": "2.0", "method": "tasks/send", "id": 1},
            )
            assert r.status_code == 401
            assert r.json()["error"]["code"] == -32001

            r = client.post(
                "/agents/secure",
                headers={"Authorization": "Bearer abc"},
                json={
                    "jsonrpc": "2.0",
                    "method": "tasks/send",
                    "params": {"id": "t-sec-1", "message": {"role": "user", "parts": []}},
                    "id": 1,
                },
            )
            assert r.status_code == 200
            envelope = r.json()
            # With a valid bearer header, Phase 2 dispatches tasks/send.
            assert "error" not in envelope
            assert envelope["result"]["status"]["state"] == "completed"

    def test_mount_rejects_non_fastapi_app(self):
        # Catch the easy mistake of forgetting ``app`` and passing
        # something else as the first positional arg.
        with pytest.raises(ValueError, match="FastAPI"):
            mesh.a2a.mount("not-an-app", path="/agents/oops")  # type: ignore[arg-type]


class TestAgentCardGenerator:
    """build_agent_card shape conformance to A2A v1.0."""

    def test_sync_card_has_streaming_false(self):
        card = build_agent_card(
            name="lookup-svc",
            description="User lookup",
            version="1.0.0",
            public_url="https://agents.acme.com/agents/lookup",
            skill_id="lookup",
            skill_name="Lookup",
            skill_description="Lookup a user",
            input_modes=["application/json"],
            output_modes=["application/json"],
            tags=["users"],
            streaming=False,
            bearer_auth=False,
        )

        assert card["name"] == "lookup-svc"
        assert card["version"] == "1.0.0"
        assert card["url"] == "https://agents.acme.com/agents/lookup"
        assert card["capabilities"]["streaming"] is False
        assert card["capabilities"]["pushNotifications"] is False
        assert card["capabilities"]["stateTransitionHistory"] is False
        assert card["defaultInputModes"] == ["application/json"]
        assert card["defaultOutputModes"] == ["application/json"]
        assert len(card["skills"]) == 1
        skill = card["skills"][0]
        assert skill["id"] == "lookup"
        assert skill["name"] == "Lookup"
        assert skill["description"] == "Lookup a user"
        assert skill["tags"] == ["users"]
        # No bearer → schemes=[] (A2A v1.0 has no "none" scheme).
        assert card["authentication"]["schemes"] == []

    def test_streaming_card_flips_capabilities(self):
        card = build_agent_card(
            name="report-svc",
            description=None,
            version="2.0.0",
            public_url="https://agents.acme.com/agents/report-generator",
            skill_id="generate-report",
            skill_name="Generate Report",
            skill_description=None,
            input_modes=["application/json"],
            output_modes=["application/json"],
            tags=[],
            streaming=True,
            bearer_auth=True,
        )

        assert card["capabilities"]["streaming"] is True
        assert card["authentication"]["schemes"] == ["bearer"]
        # Description fallback to name when not set.
        assert card["description"] == "report-svc"
        # Skill description falls back to skill_name when not set.
        assert card["skills"][0]["description"] == "Generate Report"

    def test_card_omits_url_when_public_url_empty(self):
        card = build_agent_card(
            name="x",
            description="x",
            version="1.0.0",
            public_url=None,
            skill_id="x",
            skill_name="X",
            skill_description="x",
            input_modes=["application/json"],
            output_modes=["application/json"],
            tags=[],
            streaming=False,
            bearer_auth=False,
        )
        # Per design: when MCP_MESH_PUBLIC_URL_PREFIX is unset and registry
        # hasn't stamped a public URL, omit the field rather than emit ''.
        assert "url" not in card

    def test_card_includes_underlying_input_schema_in_metadata(self):
        schema = {"type": "object", "properties": {"user_id": {"type": "string"}}}
        card = build_agent_card(
            name="x",
            description="x",
            version="1.0.0",
            public_url="https://x/y",
            skill_id="s",
            skill_name="S",
            skill_description=None,
            input_modes=["application/json"],
            output_modes=["application/json"],
            tags=[],
            streaming=False,
            bearer_auth=False,
            underlying_tool_input_schema=schema,
        )
        # The A2A v1.0 spec doesn't reserve a slot for tool input schema on
        # Skill — we expose it under skill.metadata so the card stays
        # spec-clean while still carrying the shape downstream.
        assert card["skills"][0]["metadata"]["input_schema"] == schema


class TestHeartbeatPreparationWithSurfaces:
    """HeartbeatPreparationStep flips agent_type and emits surfaces."""

    @pytest.fixture
    def agent_config(self):
        return {
            "agent_id": "report-agent-1",
            "name": "report-agent",
            "version": "1.0.0",
            "http_host": "0.0.0.0",
            "http_port": 9100,
            "namespace": "default",
        }

    @pytest.mark.asyncio
    async def test_no_a2a_keeps_mcp_agent_type(self, agent_config):
        step = HeartbeatPreparationStep()
        # _build_a2a_surfaces now delegates to engine.a2a_surfaces; patch
        # both the local DecoratorRegistry symbol (used for tools/config)
        # and the engine-level one (used by collect_a2a_surfaces).
        with patch(
            "_mcp_mesh.pipeline.mcp_startup.heartbeat_preparation.DecoratorRegistry"
        ) as mock_registry, patch(
            "_mcp_mesh.engine.a2a_surfaces.DecoratorRegistry"
        ) as mock_surfaces_registry:
            mock_registry.get_mesh_tools.return_value = {}
            mock_registry.get_mesh_llm_agents.return_value = {}
            mock_registry.get_resolved_agent_config.return_value = agent_config
            mock_registry.get_all_by_type.return_value = {}
            mock_surfaces_registry.get_all_by_type.return_value = {}

            result = await step.execute({})
            assert result.status == PipelineStatus.SUCCESS
            payload = result.context["registration_data"]
            assert payload["agent_type"] == "mcp_agent"
            assert "surfaces" not in payload

    @pytest.mark.asyncio
    async def test_a2a_decorator_flips_agent_type_and_emits_surfaces(
        self, agent_config
    ):
        # Build a fake mesh_a2a registration directly on the registry so the
        # heartbeat-prep step picks it up. We deliberately don't go through
        # the @mesh.a2a decorator here to keep the test surface minimal —
        # the decorator path is exercised in TestA2ADecoratorValidation.
        fake_func = MagicMock()
        fake_func.__name__ = "report_a2a"
        decorated = DecoratedFunction(
            decorator_type="mesh_a2a",
            function=fake_func,
            metadata={
                "path": "/agents/report-generator",
                "skill_id": "generate-report",
                "skill_name": "Generate Report",
                "description": "Long-form report",
                "input_modes": ["application/json"],
                "output_modes": ["application/json"],
                "tags": ["reports"],
                "auth": "bearer",
                "dependencies": [{"capability": "generate_report", "tags": []}],
            },
            registered_at=datetime.now(),
        )

        step = HeartbeatPreparationStep()
        # See note in test_no_a2a_keeps_mcp_agent_type: surfaces collection
        # now lives in engine.a2a_surfaces, so patch both registries.
        with patch(
            "_mcp_mesh.pipeline.mcp_startup.heartbeat_preparation.DecoratorRegistry"
        ) as mock_registry, patch(
            "_mcp_mesh.engine.a2a_surfaces.DecoratorRegistry"
        ) as mock_surfaces_registry:
            mock_registry.get_mesh_tools.return_value = {}
            mock_registry.get_mesh_llm_agents.return_value = {}
            mock_registry.get_resolved_agent_config.return_value = agent_config
            mock_registry.get_all_by_type.return_value = {"report_a2a": decorated}
            mock_surfaces_registry.get_all_by_type.return_value = {
                "report_a2a": decorated
            }

            result = await step.execute({})
            assert result.status == PipelineStatus.SUCCESS

            payload = result.context["registration_data"]
            assert payload["agent_type"] == "a2a"
            assert "surfaces" in payload
            surfaces = payload["surfaces"]
            assert len(surfaces) == 1
            entry = surfaces[0]
            assert entry["path"] == "/agents/report-generator"
            assert entry["skill_id"] == "generate-report"
            assert entry["name"] == "Generate Report"
            assert entry["description"] == "Long-form report"
            assert entry["input_modes"] == ["application/json"]
            assert entry["output_modes"] == ["application/json"]
            assert entry["tags"] == ["reports"]


class TestA2APublicUrlCache:
    """Public URL cache contract for the agent-card endpoint."""

    def test_update_and_get_cache(self):
        from mesh.a2a import (
            get_cached_public_url,
            update_public_url_cache,
        )

        path = "/agents/cache-test"
        skill = "cache-test"
        try:
            assert get_cached_public_url(path, skill) is None
            update_public_url_cache(path, skill, "https://agents.acme.com" + path)
            assert (
                get_cached_public_url(path, skill)
                == "https://agents.acme.com" + path
            )
            # Empty/None clears the entry.
            update_public_url_cache(path, skill, None)
            assert get_cached_public_url(path, skill) is None
        finally:
            update_public_url_cache(path, skill, None)


class TestA2ATasksSendDispatch:
    """Phase 2: sync tasks/send dispatches into the @mesh.a2a handler
    and wraps the result in an A2A v1.0 Task envelope.

    Long-running (task=True underlying), tasks/get, tasks/cancel, and
    tasks/sendSubscribe still return JSON-RPC -32601 (Phase 3 territory).
    """

    def _client(self, mount_kwargs: dict, handler):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        app = FastAPI()
        mesh.a2a.mount(app, **mount_kwargs)(handler)
        return TestClient(app)

    def test_tasks_send_returns_completed_task_for_sync_handler(self):
        async def handler(payload: dict):
            return {"date": "2026-05-09T12:34:56Z"}

        with self._client({"path": "/agents/date"}, handler) as client:
            req = {
                "jsonrpc": "2.0",
                "id": "req-42",
                "method": "tasks/send",
                "params": {
                    "id": "task-abc",
                    "sessionId": "sess-xyz",
                    "message": {"role": "user", "parts": []},
                },
            }
            r = client.post("/agents/date", json=req)
            assert r.status_code == 200
            envelope = r.json()
            assert envelope["jsonrpc"] == "2.0"
            assert envelope["id"] == "req-42"
            assert "error" not in envelope

            task = envelope["result"]
            assert task["id"] == "task-abc"
            assert task["sessionId"] == "sess-xyz"
            assert task["status"]["state"] == "completed"
            assert task["status"]["timestamp"].endswith("Z")
            assert len(task["artifacts"]) == 1
            artifact = task["artifacts"][0]
            assert artifact["name"] == "result"
            assert artifact["index"] == 0
            assert len(artifact["parts"]) == 1
            part = artifact["parts"][0]
            assert part["type"] == "text"
            # Non-string handler results are JSON-stringified.
            import json as _json

            assert _json.loads(part["text"]) == {"date": "2026-05-09T12:34:56Z"}
            # History echoes the request message.
            assert task["history"] == [{"role": "user", "parts": []}]

    def test_tasks_send_string_result_used_verbatim(self):
        async def handler(payload: dict):
            return "hello world"

        with self._client({"path": "/agents/echo"}, handler) as client:
            r = client.post(
                "/agents/echo",
                json={
                    "jsonrpc": "2.0",
                    "id": 7,
                    "method": "tasks/send",
                    "params": {
                        "id": "t1",
                        "message": {"role": "user", "parts": []},
                    },
                },
            )
            envelope = r.json()
            text = envelope["result"]["artifacts"][0]["parts"][0]["text"]
            # String results are NOT JSON-encoded (no surrounding quotes).
            assert text == "hello world"

    def test_tasks_send_handler_exception_yields_failed_task(self):
        async def handler(payload: dict):
            raise RuntimeError("boom: dependency timed out")

        with self._client({"path": "/agents/fail"}, handler) as client:
            r = client.post(
                "/agents/fail",
                json={
                    "jsonrpc": "2.0",
                    "id": "req-99",
                    "method": "tasks/send",
                    "params": {
                        "id": "task-fail",
                        "message": {"role": "user", "parts": []},
                    },
                },
            )
            assert r.status_code == 200
            envelope = r.json()
            # Per A2A v1.0: handler failure is a failed Task, NOT a
            # JSON-RPC error.
            assert "error" not in envelope
            task = envelope["result"]
            assert task["id"] == "task-fail"
            assert task["status"]["state"] == "failed"
            assert task["artifacts"] == []
            err_text = task["status"]["message"]["parts"][0]["text"]
            assert "boom" in err_text

    def test_tasks_send_session_id_defaults_to_task_id(self):
        async def handler(payload: dict):
            return {"ok": True}

        with self._client({"path": "/agents/sess"}, handler) as client:
            r = client.post(
                "/agents/sess",
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tasks/send",
                    "params": {
                        "id": "only-task-id",
                        # sessionId omitted on purpose.
                        "message": {"role": "user", "parts": []},
                    },
                },
            )
            task = r.json()["result"]
            assert task["id"] == "only-task-id"
            assert task["sessionId"] == "only-task-id"

    def test_tasks_send_missing_task_id_gets_uuid(self):
        async def handler(payload: dict):
            return {"ok": True}

        with self._client({"path": "/agents/auto"}, handler) as client:
            r = client.post(
                "/agents/auto",
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tasks/send",
                    "params": {"message": {"role": "user", "parts": []}},
                },
            )
            task = r.json()["result"]
            # Real UUID4 (not just 36-char string — guards against any
            # future "use a deterministic placeholder" regression).
            import uuid

            parsed = uuid.UUID(task["id"])
            assert parsed.version == 4
            assert task["sessionId"] == task["id"]

    def test_tasks_send_handler_receives_message_dict(self):
        captured: dict = {}

        async def handler(payload: dict):
            captured["payload"] = payload
            return {"got_role": payload.get("role")}

        with self._client({"path": "/agents/cap"}, handler) as client:
            r = client.post(
                "/agents/cap",
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tasks/send",
                    "params": {
                        "id": "t1",
                        "message": {
                            "role": "user",
                            "parts": [{"type": "text", "text": "hi"}],
                        },
                    },
                },
            )
            assert r.status_code == 200
            assert captured["payload"]["role"] == "user"
            assert captured["payload"]["parts"][0]["text"] == "hi"
            import json as _json

            artifact_text = r.json()["result"]["artifacts"][0]["parts"][0]["text"]
            assert _json.loads(artifact_text) == {"got_role": "user"}

    def test_other_tasks_methods_still_method_not_implemented(self):
        async def handler(payload: dict):
            return {}

        with self._client({"path": "/agents/x"}, handler) as client:
            for method in ("tasks/get", "tasks/cancel", "tasks/sendSubscribe"):
                r = client.post(
                    "/agents/x",
                    json={
                        "jsonrpc": "2.0",
                        "id": method,
                        "method": method,
                        "params": {},
                    },
                )
                assert r.status_code == 200
                envelope = r.json()
                assert envelope["id"] == method
                assert envelope["error"]["code"] == -32601
                assert "Method not implemented" in envelope["error"]["message"]

    def test_tasks_send_falls_back_when_underlying_is_task_true(self):
        # Mock _underlying_tool_is_task to simulate a task=True dep.
        from mesh import a2a as a2a_mod

        async def handler(payload: dict):
            # Should NOT be invoked — Phase 3 territory.
            raise AssertionError("handler should not run for task=True deps")

        with patch.object(a2a_mod, "_underlying_tool_is_task", return_value=True):
            with self._client(
                {"path": "/agents/long", "dependencies": ["long_tool"]},
                handler,
            ) as client:
                r = client.post(
                    "/agents/long",
                    json={
                        "jsonrpc": "2.0",
                        "id": "req-1",
                        "method": "tasks/send",
                        "params": {
                            "id": "t-long",
                            "message": {"role": "user", "parts": []},
                        },
                    },
                )
                envelope = r.json()
                assert envelope["error"]["code"] == -32601
                assert "Phase 3" in envelope["error"]["message"]
