"""Kubernetes probe endpoints for gateway pipelines (issue #1491).

``@mesh.agent`` agents get ``/livez``, ``/ready`` and ``/health`` from
``_start_uvicorn_immediately`` because mesh owns the server it starts. A
``@mesh.route`` (api) or ``@mesh.a2a`` (a2a) gateway owns its own FastAPI app
and its own uvicorn, so nothing registered those paths — and the agent Helm
chart points ``startupProbe``/``livenessProbe`` at ``/livez`` and
``readinessProbe`` at ``/ready`` (#1468). A Python gateway therefore 404'd
every probe and the kubelet restart-looped a perfectly working process.

Semantics (matching TypeScript's ``express.ts`` ``setupHealthEndpoints``):

``/livez``
    Unconditional 200 while the process serves. Consults nothing. Liveness
    must not share a verdict with readiness, or a dependency outage that
    should only make the service unready restarts the pod instead.

``/startupz``
    The user's ``startup_check`` (RFC #1502). Unlike ``health_check`` this one
    IS honoured on a gateway: it does not withdraw anything at runtime, it
    decides whether a misconfigured gateway is allowed to come up at all, and
    a gateway with a broken config should never come up.

``/ready``
    Whether the **mesh runtime** is up — a live Rust core handle exists and
    shutdown has not been requested — and nothing else. Since RFC #1502 that
    is the rule on every agent type, not a gateway carve-out —
    ``health_check_manager.runtime_state``, imported below, is what a
    provider's ``build_ready_response`` answers from too.

``/health``
    The diagnostic view. Always 200; no probe points at it.

The user's ``health_check`` is deliberately NOT consulted by any of the three.
A gateway is an entry point: mesh injects dependencies *into* it, but nothing
resolves *to* it, so an unhealthy verdict could only subtract — withdrawing a
fan-out point takes down every path that enters through it (#1473, #1488).
For the same reason there is no health-refresh loop on these pipelines.

The app is the user's, so each path is registered only if the application has
not already defined it (``examples/python/mesh-api/main.py`` hand-rolls
``/health`` precisely because mesh never did). Each is registered
independently: an app that defines only ``/health`` still gets ``/livez`` and
``/ready``. The check is an explicit route walk rather than a reliance on
Starlette's first-match-wins ordering — behaviour that depends on registration
order is behaviour nobody can predict from reading the code.
"""

import logging
from datetime import UTC, datetime
from typing import Any, Optional

from ...shared.config_resolver import ValidationRule, get_config_value
from ...shared.fastapi_routes import iter_app_routes
from ...shared.health_check_manager import NOT_READY_REASON, runtime_state
from ...shared.startup_check_manager import STARTUPZ_PATH
from .base_step import PipelineStep
from .pipeline_types import PipelineResult, PipelineStatus

logger = logging.getLogger(__name__)

LIVEZ_PATH = "/livez"
READY_PATH = "/ready"
HEALTH_PATH = "/health"
# STARTUPZ_PATH is imported, not redeclared: the hook module owns the path it
# is served on, and two spellings of "/startupz" is one rename away from a
# gateway serving the endpoint on a path nothing probes.

# Stamped on the handlers mesh registers so a second pipeline pass (or a
# second discovered app object that shares a router) can tell its own
# endpoints apart from a path the application defined. Without it, a re-run
# would log "the application already defines /livez" about mesh's own route.
MESH_PROBE_ATTR = "_mcp_mesh_probe_endpoint"

# Outcome values reported per path.
OUTCOME_REGISTERED = "registered"
OUTCOME_USER_DEFINED = "user_defined"
OUTCOME_ALREADY_MESH = "already_registered"


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _agent_name(default: str = "mcp-mesh-gateway") -> str:
    """Best-effort display name, resolved per request.

    Late-bound on purpose: the pipeline registers these endpoints before the
    server-setup step writes the resolved service name/id into the decorator
    registry, so reading it at request time reports the real name instead of
    a placeholder captured too early.
    """
    try:
        from ...engine.decorator_registry import DecoratorRegistry

        config = DecoratorRegistry.get_resolved_agent_config() or {}
        return config.get("name") or config.get("agent_id") or default
    except Exception:  # pragma: no cover - defensive, name is cosmetic
        return default


def _find_route(app: Any, path: str) -> Optional[Any]:
    """Return the first route ``app`` serves at ``path``, or None.

    Path-level, not method-level: an application that owns ``/health`` owns
    it for every method, and mesh adding a second handler for the verbs the
    application left free would make the response depend on the verb.
    """
    for ref in iter_app_routes(app):
        if ref.path == path:
            return ref
    return None


def register_health_endpoints(
    app: Any,
    *,
    service_type: str,
    standalone: bool = False,
) -> dict[str, str]:
    """Register ``/livez``, ``/startupz``, ``/ready`` and ``/health`` on a user-owned app.

    Args:
        app: the user's FastAPI application
        service_type: ``"api"`` or ``"a2a"``, reported in the bodies
        standalone: MCP_MESH_STANDALONE — no registry, hence no Rust handle

    Returns:
        ``{path: outcome}`` for every path, where outcome is one of
        ``registered`` / ``user_defined`` / ``already_registered``.

    Raises:
        Whatever the route walk raises. Registering without knowing what the
        app already serves would put mesh back on first-match-wins ordering,
        so an undeterminable app is left untouched and the caller reports it.
    """
    from fastapi.responses import JSONResponse

    async def livez():
        # Consults NOTHING — see module docstring.
        from ...shared.health_check_manager import build_livez_response

        return JSONResponse(
            status_code=200,
            content=build_livez_response(agent_name=_agent_name()),
        )

    async def startupz():
        # RFC #1502. The one hook a gateway DOES honour: it never withdraws a
        # running fan-out point, it only stops a misconfigured one from coming
        # up. Runs per hit — startupProbe stops polling on first success.
        from ...shared.startup_check_manager import build_startupz_response

        body, status_code = await build_startupz_response(
            agent_name=_agent_name(),
            service_type=service_type,
        )
        return JSONResponse(status_code=status_code, content=body)

    async def ready():
        is_ready, state = runtime_state(standalone)
        body: dict[str, Any] = {
            "ready": is_ready,
            "agent": _agent_name(),
            "service_type": service_type,
            "runtime": state,
            "timestamp": _now(),
        }
        if not is_ready:
            body["reason"] = NOT_READY_REASON.get(state, f"Mesh runtime is {state}")
        return JSONResponse(status_code=200 if is_ready else 503, content=body)

    async def health():
        # Diagnostic only. A gateway's own health never withdraws it, so this
        # is a fixed "healthy" plus the runtime detail — no health_check, no
        # stored health-check result, no 503.
        is_ready, state = runtime_state(standalone)
        return JSONResponse(
            status_code=200,
            content={
                "status": "healthy",
                "agent": _agent_name(),
                "service_type": service_type,
                "runtime": state,
                "mesh_ready": is_ready,
                "timestamp": _now(),
            },
        )

    handlers = (
        (LIVEZ_PATH, livez),
        (STARTUPZ_PATH, startupz),
        (READY_PATH, ready),
        (HEALTH_PATH, health),
    )

    outcomes: dict[str, str] = {}
    for path, handler in handlers:
        existing = _find_route(app, path)
        if existing is not None:
            if getattr(existing.endpoint, MESH_PROBE_ATTR, False):
                outcomes[path] = OUTCOME_ALREADY_MESH
                logger.debug("🩺 %s already registered by mesh - skipping", path)
            else:
                outcomes[path] = OUTCOME_USER_DEFINED
                logger.info(
                    "🩺 %s is defined by the application - mesh is not registering "
                    "its own (the application's handler answers the probe)",
                    path,
                )
            continue

        setattr(handler, MESH_PROBE_ATTR, True)
        app.get(path, include_in_schema=False)(handler)
        app.head(path, include_in_schema=False)(handler)
        outcomes[path] = OUTCOME_REGISTERED

    return outcomes


class HealthEndpointsStep(PipelineStep):
    """Add the K8s probe endpoints to every discovered FastAPI app.

    Shared by the api (``@mesh.route``) and a2a (``@mesh.a2a``) pipelines —
    both hand mesh an app they do not own, and both are deployed with the
    agent Helm chart that probes ``/livez`` and ``/ready`` (and, once the
    chart is repointed, ``/startupz``).

    Optional (``required=False``): a failure here must not stop the gateway
    from starting. It is loud instead — the alternative, aborting startup,
    trades a missing probe for no service at all.
    """

    def __init__(self, service_type: str):
        super().__init__(
            name="health-endpoints",
            required=False,
            description="Register /livez, /startupz, /ready and /health on the user's FastAPI app",
        )
        self.service_type = service_type

    async def execute(self, context: dict[str, Any]) -> PipelineResult:
        result = PipelineResult(message="Health endpoints registered")

        fastapi_apps = context.get("fastapi_apps", {})
        if not fastapi_apps:
            result.status = PipelineStatus.SKIPPED
            result.message = "No FastAPI applications found for health endpoints"
            self.logger.debug("🩺 No FastAPI apps to add health endpoints to")
            return result

        standalone = get_config_value(
            "MCP_MESH_STANDALONE",
            default=False,
            rule=ValidationRule.TRUTHY_RULE,
        )

        registered = 0
        skipped: list[str] = []
        try:
            for app_id, app_info in fastapi_apps.items():
                app_title = app_info.get("title", "Unknown App")
                outcomes = register_health_endpoints(
                    app_info["instance"],
                    service_type=self.service_type,
                    standalone=bool(standalone),
                )
                for path, outcome in outcomes.items():
                    if outcome == OUTCOME_REGISTERED:
                        registered += 1
                    elif outcome == OUTCOME_USER_DEFINED:
                        skipped.append(path)

                self.logger.info(
                    "🩺 Health endpoints on '%s': %s",
                    app_title,
                    ", ".join(f"{p}={o}" for p, o in outcomes.items()),
                )
                result.add_context(f"health_endpoints_{app_id}", outcomes)

        except Exception as e:
            result.status = PipelineStatus.FAILED
            result.message = f"Health endpoint registration failed: {e}"
            result.add_error(str(e))
            self.logger.error(
                "🩺 Could not register health endpoints - Kubernetes probes on "
                "/livez and /ready will 404: %s",
                e,
            )
            return result

        result.add_context("health_endpoints_registered", registered)
        result.message = f"Registered {registered} health endpoint(s)" + (
            f"; application already defines {', '.join(skipped)}" if skipped else ""
        )
        return result
