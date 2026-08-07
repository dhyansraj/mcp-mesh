"""The ``health_check`` refresh loop, shared by every agent type (RFC #1502).

One timer, one verdict, one effect: re-run the user's ``health_check`` every
TTL, store the result for ``/health``, and report it to the Rust core, which
stops heartbeating while the status is ``unhealthy`` so the registry withdraws
this agent from dependency resolution. Reporting ``healthy`` again resumes the
heartbeat and the registry restores the agent through its ``410 Gone``
re-register path — no restart.

Why this module exists
----------------------

The loop was written inside ``mcp_startup/fastapiserver_setup.py`` and so only
ever ran for ``@mesh.agent`` providers. ``@mesh.route`` (api) and ``@mesh.a2a``
(a2a) gateways had no health-refresh loop at all, which is how #1473's
exemption was implemented in Python: not as a rule, as an absence.

**RFC #1502 step 3 reverses that exemption, and step 2 is why it is safe.**
The exemption existed because withdrawing a fan-out point "takes the
application down". Heartbeat suppression stops registry traffic ONLY: the
uvicorn server keeps serving, resolved dependencies are retained (#1131), and
``/ready`` reports the mesh runtime rather than the verdict (step 2), so the
pod stays in its Service endpoints and keeps taking ingress. A gateway that
reports unavailable stops being *discovered*; it does not go dark.

The hook means the same thing on every agent type — "I am not available" — and
mesh does the same thing with it everywhere: it stops wiring that agent. What
differs is topology, not meaning. So the loop lives here, next to
``health_endpoints.py`` (#1494), and both the provider pipeline and the two
gateway pipelines drive it rather than growing a second copy that can drift.

Where each caller runs it
-------------------------

``mcp_startup/fastapiserver_setup.py`` (provider)
    On the **user loop**, gated on the lifespan-ready signal, so a
    ``health_check`` that touches loop-affine resources built in ``lifespan``
    (asyncpg pools, redis.asyncio clients) sees them on the loop that created
    them.

``api_heartbeat`` / ``a2a_heartbeat`` (gateway)
    On the **heartbeat thread's** loop, started once the Rust handle exists.
    A gateway owns its own FastAPI app and its own uvicorn: mesh never hijacks
    that loop, and the startup pipeline runs to completion inside a throwaway
    ``asyncio.run``, so there is no mesh-owned loop with the right lifetime
    anywhere else. The heartbeat loop lives exactly as long as the agent's
    registration does, which is precisely the lifetime a verdict that
    suppresses that registration should have.

    The consequence to know: a gateway's ``health_check`` runs on a different
    loop from its request handlers. Keep it self-contained (an outbound probe,
    an env read) rather than reaching into objects the user's lifespan built.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any, Optional

logger = logging.getLogger(__name__)


async def refresh_health_once(
    *,
    agent_name: str,
    health_check_fn: Callable[[], Any] | None,
    agent_config: dict[str, Any],
    startup_context: dict[str, Any],
    ttl_seconds: int,
    publish_to_core: bool,
) -> dict[str, Any]:
    """Run the check once, store the verdict, and optionally publish it.

    Args:
        agent_name: cache key and the ``agent`` field of the stored result
        health_check_fn: the user's ``health_check``, or None
        agent_config: resolved agent config (version, capabilities, ...)
        startup_context: pipeline/heartbeat context, for capability reporting
        ttl_seconds: cache TTL for this verdict
        publish_to_core: also report to the Rust core, which is what suppresses
            the heartbeat. False for the startup seed — see below.

    Returns:
        The stored result dict (``status``/``agent``/``checks``/``errors``).

    The seed call deliberately does not publish (issue #1472): it can run
    before there is a handle to publish to, and it is the unreliable one — a
    pool that is not warm yet, a lazily built client. The agent registers and
    becomes visible first; the first PUBLISHED verdict is one TTL later.
    """
    from ...engine.decorator_registry import DecoratorRegistry

    if health_check_fn:
        from ...shared.health_check_manager import get_health_status_with_cache

        health_status = await get_health_status_with_cache(
            agent_id=agent_name,
            health_check_fn=health_check_fn,
            agent_config=agent_config,
            startup_context=startup_context,
            ttl=ttl_seconds,
        )
        result: dict[str, Any] = {
            "status": health_status.status.value,
            "agent": agent_name,
            "checks": health_status.checks,
            "errors": health_status.errors,
            "timestamp": health_status.timestamp.isoformat(),
        }
    else:
        # No health check configured - default healthy status.
        result = {
            "status": "healthy",
            "agent": agent_name,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    # Store for /health to read.
    DecoratorRegistry.store_health_check_result(result)

    if publish_to_core:
        from ...shared.health_check_manager import publish_health_status_to_core

        # Best-effort and idempotent — the core only acts on transitions.
        publish_health_status_to_core(result["status"])

    return result


async def health_refresh_loop(
    *,
    agent_name: str,
    health_check_fn: Callable[[], Any],
    agent_config: dict[str, Any],
    startup_context: dict[str, Any],
    ttl_seconds: int,
    log: logging.Logger | None = None,
    wait_ready: Callable[[], Awaitable[None]] | None = None,
    seed: bool = False,
) -> None:
    """Re-run the check every ``ttl_seconds`` and publish each verdict.

    Never returns on its own and never lets a single failure end it: a loop
    that dies leaves an agent that can no longer be withdrawn, with nothing in
    the logs after the first error. Only cancellation stops it, which is how
    both callers tear it down.

    ``wait_ready`` is awaited once before the first sleep when supplied. The
    provider path passes the lifespan-ready gate so the user's check never
    observes half-initialized lifespan state; a gateway has no mesh-owned
    lifespan to gate on and passes nothing.

    ``seed`` runs one NON-PUBLISHING refresh before the first sleep, so
    ``/health`` reports something real instead of the default healthy for a
    whole TTL. The provider seeds outside this function (on the framework
    loop, during pipeline setup); a gateway has no earlier place to do it.
    """
    log = log or logger

    if wait_ready is not None:
        try:
            await wait_ready()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            # Better to refresh than to hang if the gate mechanism breaks.
            log.warning(
                "Health refresh: readiness gate failed for agent '%s' (%s). "
                "Proceeding without gating.",
                agent_name,
                e,
            )

    from ...shared.health_check_manager import clear_health_cache

    if seed:
        try:
            await refresh_health_once(
                agent_name=agent_name,
                health_check_fn=health_check_fn,
                agent_config=agent_config,
                startup_context=startup_context,
                ttl_seconds=ttl_seconds,
                # NEVER publishes: a check that fails at boot — a client built
                # lazily, a pool not warm — must not withdraw an agent that has
                # only just registered. The first PUBLISHED verdict is one TTL
                # later.
                publish_to_core=False,
            )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.warning(
                f"Health seed failed for agent '{agent_name}': {e}",
                exc_info=True,
            )

    while True:
        try:
            await asyncio.sleep(ttl_seconds)
            # Invalidate first, or a refresh landing inside the cache window
            # returns the previous result and the check never re-runs.
            clear_health_cache(agent_name)
            await refresh_health_once(
                agent_name=agent_name,
                health_check_fn=health_check_fn,
                agent_config=agent_config,
                startup_context=startup_context,
                ttl_seconds=ttl_seconds,
                publish_to_core=True,
            )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.warning(
                f"Health refresh failed for agent '{agent_name}': {e}",
                exc_info=True,
            )


def start_gateway_health_refresh(
    *,
    service_type: str,
    service_id: str,
    context: dict[str, Any],
    log: logging.Logger | None = None,
) -> Optional["asyncio.Task"]:
    """Start the refresh loop for an ``api`` or ``a2a`` gateway.

    Called from the gateway heartbeat tasks once the Rust handle exists, so a
    verdict always has somewhere to go and the gateway is registered before
    anything can withdraw it. Returns the task (cancel it on teardown), or None
    when the gateway declares no ``health_check``.

    Never raises: a gateway must start even if its health wiring cannot.
    """
    log = log or logger

    try:
        from ...engine.decorator_registry import DecoratorRegistry
        from ...shared.health_check_manager import (
            resolve_health_check_ttl_from_env,
        )

        agent_config = DecoratorRegistry.get_resolved_agent_config() or {}
        health_check_fn = agent_config.get("health_check")
        if not callable(health_check_fn):
            # Nothing declared — no timer, no task. This is what keeps a
            # gateway without a health check behaving exactly as before.
            return None

        agent_name = agent_config.get("name") or service_id
        ttl_seconds = resolve_health_check_ttl_from_env(
            agent_config.get("health_check_ttl")
        )

        log.info(
            "🩺 Health check runs every %ss for %s gateway '%s'; an unhealthy "
            "verdict stops the heartbeat and withdraws it from discovery "
            "(the HTTP server keeps serving and /ready stays 200)",
            ttl_seconds,
            service_type,
            agent_name,
        )

        return asyncio.create_task(
            health_refresh_loop(
                agent_name=agent_name,
                health_check_fn=health_check_fn,
                agent_config=agent_config,
                startup_context=context,
                ttl_seconds=ttl_seconds,
                log=log,
                seed=True,
            ),
            name=f"health-refresh:{agent_name}",
        )
    except Exception as e:  # pragma: no cover - defensive
        log.warning(
            "Could not start the health-check refresh for %s gateway '%s': %s",
            service_type,
            service_id,
            e,
        )
        return None
