"""User-facing A2A surface helpers (issue #903 Phase 1B / Phase 2).

Two complementary entry points:

* ``@mesh.a2a(path=..., dependencies=[...])`` — decorator that stamps
  ``_mesh_a2a_metadata`` on the function and wires DDDI dependency
  injection (mirrors ``@mesh.route``). Pure metadata + DI; does NOT
  mount any FastAPI routes. Imported from ``mesh.decorators`` and
  re-exposed here under the ``mesh.a2a`` callable so users can write
  ``@mesh.a2a(...)`` for advanced cases (multi-app fan-out, custom
  mounting, library-style integrations).

* ``mesh.a2a.mount(app, *, path=..., dependencies=[...])`` — the
  recommended entry point. Mirrors the ``@mesh.route`` UX: the user
  owns the FastAPI app, the helper applies ``@mesh.a2a`` AND mounts
  the two companion routes the A2A protocol surface needs:

    GET  ``{path}/.well-known/agent.json``  → A2A AgentCard
    POST ``{path}``                         → JSON-RPC 2.0 entry point

Phase 2 (this module) dispatches sync ``tasks/send`` into the user
handler and wraps the result in an A2A v1.0 ``Task`` envelope. Other
``tasks/*`` methods (``tasks/get``, ``tasks/cancel``,
``tasks/sendSubscribe``) and ``tasks/send`` for ``task=True``
underlying tools still return JSON-RPC ``Method not implemented`` —
those land in Phase 3 once the MeshJob lifecycle is wired.

Public URL caching
==================
Each surface caches the registry-stamped public URL (delivered on the
heartbeat response under ``surfaces[].public_url``) on a module-level
dict keyed by ``(path, skill_id)``. The agent-card endpoint reads
this cache so the card's ``url`` field reflects the public FQDN. When
the cache is empty (e.g., first request before the first heartbeat
round-trip, or ``MCP_MESH_PUBLIC_URL_PREFIX`` unset), the URL falls
back to the agent's local ``http_host:http_port + path`` — sufficient
for local development and integration tests.

NOTE: we deliberately avoid ``from __future__ import annotations`` in
this module — FastAPI's Dependant builder calls ``inspect.signature``
and stringified annotations cause it to misclassify ``request: Request``
as a query parameter (yielding 422 on every POST).
"""

import json as _json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


# Module-level cache of the registry-stamped public URLs, keyed by
# (path, skill_id). Populated by :func:`update_public_url_cache` from the
# heartbeat-response handler; read by the agent-card endpoint at request
# time. Process-local — not persisted.
_PUBLIC_URL_CACHE: Dict[tuple, str] = {}


# Tracks already-mounted A2A surfaces keyed by ``(id(app), path)`` so a
# duplicate ``mount(app, path=X, ...)`` call raises instead of silently
# splitting into two DecoratorRegistry entries (heartbeat would report 2
# surfaces) plus a single reachable route. Keying by ``id(app)`` allows
# the same path on different FastAPI app instances (e.g. multiple test apps).
_MOUNTED_A2A_PATHS: set = set()


def update_public_url_cache(path: str, skill_id: str, public_url: Optional[str]) -> None:
    """Cache (or clear) a registry-stamped public URL for one A2A surface.

    Called from the heartbeat-response handler when the registry returns
    ``surfaces[].public_url``. Empty/None clears the cache entry so the
    agent-card endpoint falls back to the local host:port.
    """
    key = (path, skill_id)
    if public_url:
        _PUBLIC_URL_CACHE[key] = public_url
    else:
        _PUBLIC_URL_CACHE.pop(key, None)


def get_cached_public_url(path: str, skill_id: str) -> Optional[str]:
    """Return the registry-stamped public URL for a surface, if cached."""
    return _PUBLIC_URL_CACHE.get((path, skill_id))


def _local_fallback_url(agent_config: dict, path: str) -> str:
    """Build a host:port + path URL for local-development fallback.

    Used when the registry hasn't stamped a public URL yet (or
    ``MCP_MESH_PUBLIC_URL_PREFIX`` is unset). Not addressable from
    outside the local network — appropriate only for dev/CI.
    """
    host = agent_config.get("http_host") or "localhost"
    port = agent_config.get("http_port") or 0
    if port:
        return f"http://{host}:{port}{path}"
    return f"http://{host}{path}"


def _resolve_agent_config() -> dict:
    """Best-effort lookup of the resolved @mesh.agent config at mount time.

    Falls back to an empty dict — the agent-card endpoint then uses
    ``localhost`` for the fallback URL. Once the heartbeat round-trip
    populates the public-URL cache, the fallback path stops mattering.
    """
    try:
        from _mcp_mesh.engine.decorator_registry import DecoratorRegistry

        return DecoratorRegistry.get_resolved_agent_config() or {}
    except Exception:
        return {}


def _underlying_tool_is_task(metadata: dict) -> bool:
    """Return True iff the underlying mesh tool dep is task=True.

    Best-effort: looks up the dependency's capability in the
    DecoratorRegistry's mesh_tools and checks the producer-side
    ``task`` flag stamped by ``@mesh.tool(task=True)``. Returns
    False when the dep is missing, multi-dep, or the tool isn't
    locally registered (cross-agent dep).
    """
    try:
        from _mcp_mesh.engine.decorator_registry import DecoratorRegistry
    except Exception:
        return False

    deps = metadata.get("dependencies") or []
    if len(deps) != 1:
        return False
    cap = deps[0].get("capability")
    if not cap:
        return False
    for _, decorated in DecoratorRegistry.get_mesh_tools().items():
        tool_meta = decorated.metadata or {}
        if tool_meta.get("capability") == cap and tool_meta.get("task"):
            return True
    return False


def _underlying_tool_input_schema(metadata: dict) -> Optional[dict]:
    """Return the underlying mesh tool's input schema if available."""
    try:
        from _mcp_mesh.engine.decorator_registry import DecoratorRegistry
        from _mcp_mesh.utils.fastmcp_schema_extractor import (
            FastMCPSchemaExtractor,
        )
    except Exception:
        return None

    deps = metadata.get("dependencies") or []
    if len(deps) != 1:
        return None
    cap = deps[0].get("capability")
    if not cap:
        return None
    for _, decorated in DecoratorRegistry.get_mesh_tools().items():
        tool_meta = decorated.metadata or {}
        if tool_meta.get("capability") == cap:
            schema = tool_meta.get("input_schema")
            if schema:
                return schema
            try:
                return FastMCPSchemaExtractor.extract_input_schema(decorated.function)
            except Exception:
                return None
    return None


def _make_card_endpoint(
    *,
    metadata: dict,
    agent_config_provider: Callable[[], dict],
):
    """Build a FastAPI endpoint coroutine returning the AgentCard JSON.

    ``agent_config_provider`` is called lazily on each request so the
    card picks up agent config that may not have been resolved yet at
    mount time (mount() is typically called at module import, before
    the @mesh.agent class is processed).
    """
    from _mcp_mesh.engine.a2a_card import build_agent_card

    path = metadata["path"]
    skill_id = metadata["skill_id"]

    async def get_agent_card() -> dict:
        agent_config = agent_config_provider() or {}
        agent_name = (
            agent_config.get("name")
            or agent_config.get("agent_id")
            or "agent"
        )
        agent_version = agent_config.get("version", "1.0.0")
        agent_description = agent_config.get("description")

        cached = get_cached_public_url(path, skill_id)
        public_url = cached or _local_fallback_url(agent_config, path)

        streaming = _underlying_tool_is_task(metadata)
        input_schema = _underlying_tool_input_schema(metadata)
        bearer_auth = metadata.get("auth") == "bearer"

        return build_agent_card(
            name=agent_name,
            description=agent_description,
            version=agent_version,
            public_url=public_url,
            skill_id=skill_id,
            skill_name=metadata.get("skill_name") or skill_id,
            skill_description=metadata.get("description"),
            input_modes=metadata.get("input_modes") or ["application/json"],
            output_modes=metadata.get("output_modes") or ["application/json"],
            tags=metadata.get("tags") or [],
            streaming=streaming,
            bearer_auth=bearer_auth,
            underlying_tool_input_schema=input_schema,
        )

    return get_agent_card


def _utc_now_iso() -> str:
    """Return current UTC time in A2A v1.0 ``...Z`` ISO-8601 form."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _build_completed_task(
    task_id: str,
    session_id: str,
    request_message: Optional[dict],
    result: Any,
) -> dict:
    """Build an A2A v1.0 ``Task`` with ``state=completed``.

    The user-handler return value becomes the single ``result`` artifact's
    text part. Non-string results are JSON-stringified so the artifact's
    ``text`` field stays string-typed per the A2A v1.0 ``TextPart`` shape.
    Non-JSON-serializable types (datetime, Decimal, Path, dataclass, set,
    etc.) are coerced best-effort via ``default=str`` so a handler that
    returns one of these doesn't crash the JSON-RPC entry — the user's
    try/except is honoured by routing exceptions through ``state=failed``,
    not bubbling them up as 500s.
    """
    text = result if isinstance(result, str) else _json.dumps(result, default=str)
    return {
        "id": task_id,
        "sessionId": session_id,
        "status": {
            "state": "completed",
            "timestamp": _utc_now_iso(),
        },
        "artifacts": [
            {
                "name": "result",
                "parts": [{"type": "text", "text": text}],
                "index": 0,
            }
        ],
        "history": [request_message] if request_message else [],
    }


def _build_failed_task(
    task_id: str,
    session_id: str,
    request_message: Optional[dict],
    error_msg: str,
) -> dict:
    """Build an A2A v1.0 ``Task`` with ``state=failed``.

    Per A2A v1.0, handler exceptions become a ``failed`` task (NOT a
    JSON-RPC error). JSON-RPC errors are reserved for protocol-level
    issues like bad request shape or missing method.
    """
    return {
        "id": task_id,
        "sessionId": session_id,
        "status": {
            "state": "failed",
            "timestamp": _utc_now_iso(),
            "message": {
                "role": "agent",
                "parts": [{"type": "text", "text": error_msg}],
            },
        },
        "artifacts": [],
        "history": [request_message] if request_message else [],
    }


def _jsonrpc_success(req_id: Any, result_obj: Any) -> JSONResponse:
    return JSONResponse(
        status_code=200,
        content={"jsonrpc": "2.0", "id": req_id, "result": result_obj},
    )


def _jsonrpc_error(
    req_id: Any,
    code: int,
    message: str,
    *,
    status_code: int = 200,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": code, "message": message},
        },
    )


async def _handle_tasks_send(
    *,
    req_id: Any,
    params: dict,
    user_handler: Callable[..., Any],
    metadata: dict,
) -> JSONResponse:
    """Phase 2 sync-only ``tasks/send`` dispatch.

    Calls the user's ``@mesh.a2a`` handler with the A2A ``message`` dict
    as the positional payload. Dependency injection (e.g. ``date_service``)
    is wired by the decorator wrapper, so deps land via keyword args at
    call time.

    Long-running surfaces (underlying mesh tool was ``@mesh.tool(task=True)``)
    fall back to ``Method not implemented`` until Phase 3 wires the
    MeshJob lifecycle into ``tasks/send`` + ``tasks/sendSubscribe``.
    """
    if _underlying_tool_is_task(metadata):
        return _jsonrpc_error(
            req_id,
            -32601,
            (
                "Method not implemented: 'tasks/send' for task=True "
                "underlying tools requires Phase 3 (MeshJob lifecycle). "
                "Sync handlers are supported today."
            ),
        )

    if not isinstance(params, dict):
        params = {}

    task_id = params.get("id") or str(uuid.uuid4())
    session_id = params.get("sessionId") or task_id
    message = params.get("message") if isinstance(params.get("message"), dict) else {}

    # Pass the full A2A message dict to the user's handler so user code
    # can introspect parts/role as needed. The handler is responsible for
    # translating message → its dependency-call shape.
    try:
        import inspect

        result = user_handler(message)
        if inspect.isawaitable(result):
            result = await result
    except Exception as exc:
        # Per A2A v1.0: handler exceptions surface as Task.state=failed,
        # NOT as a JSON-RPC -3260x error.
        logger.warning(
            "A2A tasks/send handler raised on %s: %s",
            metadata.get("path"),
            exc,
        )
        return _jsonrpc_success(
            req_id,
            _build_failed_task(task_id, session_id, message or None, str(exc)),
        )

    return _jsonrpc_success(
        req_id,
        _build_completed_task(task_id, session_id, message or None, result),
    )


def _make_rpc_endpoint(*, metadata: dict, user_handler: Callable[..., Any]):
    """Build a FastAPI endpoint coroutine for the JSON-RPC entry point.

    Phase 2 dispatches sync ``tasks/send`` into ``user_handler`` and
    wraps the return value in an A2A v1.0 ``Task`` envelope. All other
    ``tasks/*`` methods still return JSON-RPC ``Method not implemented``
    (Phase 3 territory).

    Honours the decorator's ``auth="bearer"`` setting at the header-
    presence level only — token validation (signature/issuer/audience)
    is Phase-2+ scope.
    """
    bearer_auth = metadata.get("auth") == "bearer"

    async def jsonrpc_entry(request: Request) -> JSONResponse:
        if bearer_auth:
            authz = request.headers.get("authorization") or ""
            if not authz.lower().startswith("bearer "):
                return JSONResponse(
                    status_code=401,
                    content={
                        "jsonrpc": "2.0",
                        "error": {
                            "code": -32001,
                            "message": (
                                "Authentication required: missing "
                                "Authorization: Bearer <token> header"
                            ),
                        },
                        "id": None,
                    },
                )
            # Reject "Bearer " (or "Bearer ...empty/whitespace token...") —
            # accepting a prefix-only header would let any client past the
            # auth gate without supplying a real token.
            parts = authz.split(" ", 1)
            if len(parts) != 2 or not parts[1].strip():
                return JSONResponse(
                    status_code=401,
                    content={
                        "jsonrpc": "2.0",
                        "error": {
                            "code": -32001,
                            "message": (
                                "Authentication required: empty bearer token "
                                "in Authorization header"
                            ),
                        },
                        "id": None,
                    },
                )

        try:
            body = await request.json()
        except Exception:
            return JSONResponse(
                status_code=400,
                content={
                    "jsonrpc": "2.0",
                    "error": {
                        "code": -32700,
                        "message": "Parse error: request body is not valid JSON",
                    },
                    "id": None,
                },
            )

        req_id = None
        method = None
        params: dict = {}
        if isinstance(body, dict):
            req_id = body.get("id")
            method = body.get("method")
            raw_params = body.get("params")
            if isinstance(raw_params, dict):
                params = raw_params

        if method == "tasks/send":
            return await _handle_tasks_send(
                req_id=req_id,
                params=params,
                user_handler=user_handler,
                metadata=metadata,
            )

        # All other tasks/* methods land in Phase 3.
        return _jsonrpc_error(
            req_id,
            -32601,
            (
                f"Method not implemented: {method!r}. "
                "Phase 2 wires sync 'tasks/send' only — long-running "
                "and streaming methods (tasks/sendSubscribe, tasks/get, "
                "tasks/cancel) land in Phase 3 (see A2A_SURFACE_DESIGN.org)."
            ),
        )

    return jsonrpc_entry


def mount(
    app: FastAPI,
    *,
    path: str,
    dependencies: Optional[list] = None,
    description: Optional[str] = None,
    skill_id: Optional[str] = None,
    skill_name: Optional[str] = None,
    input_modes: Optional[list] = None,
    output_modes: Optional[list] = None,
    tags: Optional[list] = None,
    auth: Optional[str] = None,
    **kwargs: Any,
) -> Callable[[Callable], Callable]:
    """Mount an A2A surface on the user's FastAPI ``app``.

    Mirrors the ``@mesh.route`` UX: the user owns the FastAPI app,
    this helper applies ``@mesh.a2a`` (DI + metadata stamping) AND
    registers the two routes A2A v1.0 requires:

      * ``GET  {path}/.well-known/agent.json`` — agent card
      * ``POST {path}``                        — JSON-RPC tasks/* entry

    Phase 1 returns ``Method not implemented`` for every ``tasks/*``
    JSON-RPC method; Phase 2 wires actual task routing.

    Args:
        app: User-owned ``FastAPI`` application instance.
        path: REQUIRED URL path prefix for this surface (must start
            with ``/``), e.g. ``/agents/report-generator``. The
            registry concatenates ``MCP_MESH_PUBLIC_URL_PREFIX`` with
            this path to compute the public FQDN stamped on the card.
        dependencies: Optional list of mesh capabilities to inject
            (same shape as ``@mesh.tool`` deps). For v1, typically a
            single capability — the user's handler may declare more
            but multi-skill grouping in a single card is v2 scope.
        description: Free-form skill description shown on the agent
            card. Defaults to the function's docstring when not set.
        skill_id: A2A skill identifier (kebab-case canonical). When
            unset, derived from the path's last segment.
        skill_name: Human-readable skill name. When unset, derived
            from ``skill_id`` (TitleCase).
        input_modes: A2A inputModes (default ``["application/json"]``).
        output_modes: A2A outputModes (default ``["application/json"]``).
        tags: Skill tags surfaced on the agent card.
        auth: Authentication scheme. v1 accepts ``"bearer"`` or ``None``
            (no auth). Anything else raises ``ValueError`` —  broader
            schemes (SPIRE/mTLS/OAuth) land in v2.
        **kwargs: Additional metadata stamped onto the surface.

    Returns:
        A decorator that:
          1. Applies ``@mesh.a2a(...)`` to the user's handler function
             (DI + metadata stamping).
          2. Mounts the agent-card and JSON-RPC routes on ``app``.
          3. Returns the wrapped function so the user's variable points
             to a usable callable (e.g., for direct unit tests).

    Example:
        from fastapi import FastAPI
        import mesh
        from mesh.types import McpMeshTool

        app = FastAPI()

        @mesh.a2a.mount(
            app,
            path="/agents/date",
            dependencies=["date_service"],
        )
        async def date_a2a(payload: dict, date_service: McpMeshTool = None):
            return await date_service()
    """
    if not isinstance(app, FastAPI):
        raise ValueError(
            "mesh.a2a.mount requires a FastAPI app instance as the first argument"
        )

    # Reject duplicate mounts on the same (app, path) pair — silently
    # accepting the second call would add another `mesh_a2a` entry to the
    # DecoratorRegistry (heartbeat reports 2 surfaces) while only one
    # endpoint stays reachable, since route registration short-circuits
    # on path collision below.
    #
    # NOTE: do NOT add ``dup_key`` to ``_MOUNTED_A2A_PATHS`` here — if any
    # validation or route registration in the inner ``decorator`` raises,
    # the key would leak and block legitimate retries on the same path.
    # Add it on the success path at the end of ``decorator`` instead.
    dup_key = (id(app), (path or "").rstrip("/") or "/")
    if dup_key in _MOUNTED_A2A_PATHS:
        raise ValueError(
            f"mesh.a2a.mount: path {dup_key[1]!r} is already mounted on this "
            "FastAPI app. A2A surfaces must have unique paths per app."
        )

    # Late-bind the decorator import to avoid circular import at module load.
    from .decorators import a2a as a2a_decorator

    def decorator(target: Callable) -> Callable:
        # Apply @mesh.a2a(...) for DI + metadata stamping. The decorator
        # registers the surface in DecoratorRegistry under "mesh_a2a" so
        # heartbeat preparation picks it up and emits agent_type=a2a.
        wrapped = a2a_decorator(
            path=path,
            description=description,
            dependencies=dependencies,
            skill_id=skill_id,
            skill_name=skill_name,
            input_modes=input_modes,
            output_modes=output_modes,
            tags=tags,
            auth=auth,
            **kwargs,
        )(target)

        # The decorator stamps the (possibly-derived) final metadata on
        # the wrapper. Use that as the source of truth for the routes.
        metadata = getattr(wrapped, "_mesh_a2a_metadata", None)
        if metadata is None:
            # The DI wrapper failed and we got the raw target back;
            # pull metadata directly from the target.
            metadata = getattr(target, "_mesh_a2a_metadata", None)
        if metadata is None:
            # Nothing to mount — decorator failed catastrophically. Log
            # and return the (un)wrapped function so the caller's import
            # doesn't blow up.
            logger.error(
                "mesh.a2a.mount: @mesh.a2a metadata missing on %s; "
                "skipping route registration",
                getattr(target, "__name__", target),
            )
            return wrapped

        skill_id_resolved = metadata["skill_id"]
        path_resolved = metadata["path"]

        card_path = path_resolved.rstrip("/") + "/.well-known/agent.json"
        rpc_path = path_resolved.rstrip("/") or "/"

        # Map existing paths to their endpoint callables so we can
        # distinguish a legitimate idempotent re-mount (same endpoint
        # function — typical in test fixtures that call ``mount()``
        # multiple times against a fresh ``_MOUNTED_A2A_PATHS``) from a
        # foreign route hijacking the path. Silently skipping on path
        # collision would let a hostile/typo'd route own ``card_path`` /
        # ``rpc_path`` while heartbeat still advertises the surface for
        # this agent — clients would then call the wrong handler.
        existing_endpoints: dict = {}
        for r in app.router.routes:
            r_path = getattr(r, "path", None)
            if r_path is not None:
                existing_endpoints[r_path] = getattr(r, "endpoint", None)

        card_endpoint = _make_card_endpoint(
            metadata=metadata,
            agent_config_provider=_resolve_agent_config,
        )
        rpc_endpoint = _make_rpc_endpoint(metadata=metadata, user_handler=wrapped)

        added_paths: list = []
        if card_path not in existing_endpoints:
            app.add_api_route(
                path=card_path,
                endpoint=card_endpoint,
                methods=["GET"],
                tags=["a2a"],
                summary=f"A2A AgentCard for skill '{skill_id_resolved}'",
            )
            added_paths.append(card_path)
            logger.debug(
                "Mounted A2A card route GET %s (skill=%s)",
                card_path, skill_id_resolved,
            )
        elif existing_endpoints[card_path] is card_endpoint:
            # Identical callable already wired (e.g., test fixture re-mount
            # after wiping ``_MOUNTED_A2A_PATHS``) — safe to skip.
            logger.debug(
                "A2A card route %s already registered with identical endpoint; skipping",
                card_path,
            )
        else:
            raise RuntimeError(
                f"mesh.a2a.mount: cannot mount A2A card route at {card_path!r} — "
                "the path is already registered with a different endpoint. "
                "Refusing to silently let a foreign route own this path while "
                "the agent's heartbeat advertises it as an A2A surface."
            )

        if rpc_path not in existing_endpoints:
            app.add_api_route(
                path=rpc_path,
                endpoint=rpc_endpoint,
                methods=["POST"],
                tags=["a2a"],
                summary=f"A2A JSON-RPC entry point for skill '{skill_id_resolved}'",
            )
            added_paths.append(rpc_path)
            logger.debug(
                "Mounted A2A RPC route POST %s (skill=%s)",
                rpc_path, skill_id_resolved,
            )
        elif existing_endpoints[rpc_path] is rpc_endpoint:
            logger.debug(
                "A2A RPC route %s already registered with identical endpoint; skipping",
                rpc_path,
            )
        else:
            raise RuntimeError(
                f"mesh.a2a.mount: cannot mount A2A JSON-RPC route at {rpc_path!r} — "
                "the path is already registered with a different endpoint. "
                "Refusing to silently let a foreign route own this path while "
                "the agent's heartbeat advertises it as an A2A surface."
            )

        # Move the newly-added routes to the FRONT of the router so the
        # FastMCP catch-all (mounted at "" by FastAPIServerSetupStep)
        # doesn't shadow them. Mirrors jobs_cancel_route.py #bug 4.
        # Starlette resolves routes in registration order and Mount("")
        # matches every path — explicit routes added AFTER the mount
        # would yield 404 without this re-ordering.
        if added_paths:
            head: list = []
            rest: list = []
            for r in app.router.routes:
                if getattr(r, "path", None) in added_paths:
                    head.append(r)
                else:
                    rest.append(r)
            app.router.routes[:] = head + rest

        logger.info(
            "🌐 Mounted A2A surface: %s (skill=%s, %d route(s))",
            path_resolved, skill_id_resolved, len(added_paths),
        )

        # Validation + route registration succeeded — only NOW record the
        # (app, path) pair so a future re-mount on the same pair raises.
        # Adding before this point would leak the key on validation
        # failures and block legitimate retries.
        _MOUNTED_A2A_PATHS.add(dup_key)
        return wrapped

    return decorator
