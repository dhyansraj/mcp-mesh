"""
Health check manager with TTL caching and K8s response helpers.

Consolidates health check storage, caching, and Kubernetes endpoint response
generation into a single module.
"""

import asyncio
import inspect
import logging
import os
import re
import threading
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from .support_types import HealthStatus, HealthStatusType

logger = logging.getLogger(__name__)

# =============================================================================
# TTL Resolution (issue #1492)
# =============================================================================

# TypeScript's DEFAULT_HEALTH_CHECK_TTL_SECONDS and Java's DEFAULT_TTL_SECONDS.
DEFAULT_HEALTH_CHECK_TTL_SECONDS = 15

# Overrides the ``health_check_ttl`` decorator argument when set.
HEALTH_CHECK_TTL_ENV = "MCP_MESH_HEALTH_CHECK_TTL"

# Integers only — "15s", "1.5" and "0x10" are all rejected. Mirrors
# TypeScript's INTEGER_RE and Java's Integer.parseInt, both of which take a
# leading sign and nothing else. Bare `int()` would additionally accept
# "1_0" and non-ASCII digits, neither of which TypeScript honours.
#
# re.ASCII is deliberate: Python's `\d` and `int()` both accept non-ASCII
# digits ("١٥" -> 15), as does Java's Integer.parseInt, but TypeScript
# rejects them. Following TypeScript — an env var carrying an Arabic-Indic
# numeral is far likelier an encoding accident than an intent, and a loud
# fallback beats silently running a TTL the operator cannot read back.
_INTEGER_RE = re.compile(r"^[+-]?\d+$", re.ASCII)


# Long enough to recognize the value that was rejected, short enough that a
# warning stays one readable line.
_WARNING_VALUE_LIMIT = 32


def _for_warning(value: Any, *, quote: bool = False) -> str:
    """Render a value for a rejection message without raising or flooding the log.

    Interpolating a value is not safe by default here. Python 3.11 caps
    int<->str conversion at 4300 digits, so ``f"{value}"`` raises ValueError on
    a large enough int — inside the one function whose contract is that it
    never raises, on the very path that exists to keep a malformed TTL from
    stopping an agent from booting. Length is the second hazard: an env var is
    an unbounded paste, and a 300,000-character warning is not a warning.

    Every rejection message below goes through this, so a message added later
    cannot reintroduce either hazard by being written the obvious way.
    """
    try:
        text = repr(value) if quote or not isinstance(value, str) else value
    except Exception:
        # Broad: this only formats a log line, and no failure to describe a
        # bad value is worth turning into a raise here. Ints report their
        # magnitude, which str() is exactly what cannot do for them.
        if isinstance(value, int):
            digits = int(value.bit_length() * 0.30103) + 1
            return f"<{type(value).__name__} with ~{digits} digits>"
        return f"<unprintable {type(value).__name__}>"

    if len(text) > _WARNING_VALUE_LIMIT:
        return f"{text[:_WARNING_VALUE_LIMIT]}… ({len(text)} chars)"
    return text


def resolve_health_check_ttl(
    configured: Any = None, override: str | None = None
) -> int:
    """Resolve the health-check refresh period, in seconds.

    Priority: ``MCP_MESH_HEALTH_CHECK_TTL`` > ``health_check_ttl`` > 15s.
    Every rejected value warns and falls through to the next source rather
    than raising — a malformed TTL must not stop an agent from booting, but
    it must not be silently rounded into something else either.

    ``override`` is a parameter rather than an ambient ``os.environ`` read so
    the resolution rules are testable without mutating the environment (same
    shape as TypeScript's ``resolveHealthCheckTtl`` and Java's
    ``MeshHealthCheckRegistry.ttlSeconds(String)``).

    Args:
        configured: value from ``agent_config["health_check_ttl"]``
        override: raw ``MCP_MESH_HEALTH_CHECK_TTL`` value, or None if unset
    """
    ttl = DEFAULT_HEALTH_CHECK_TTL_SECONDS
    # Collected, not logged inline: a warning names the value that is
    # actually used, and that is not known until every source has been
    # considered. Warning "using 15s" while a valid env override goes on to
    # win would print a number the agent never runs with.
    rejected: list[str] = []

    if configured is not None:
        # bool is an int subclass in Python; True is not 1 second.
        if isinstance(configured, bool) or not isinstance(configured, int):
            rejected.append(
                f"health_check_ttl={_for_warning(configured, quote=True)} "
                f"is not a whole number of seconds >= 1"
            )
        elif configured < 1:
            rejected.append(
                f"health_check_ttl={_for_warning(configured)} "
                f"is not a whole number of seconds >= 1"
            )
        else:
            ttl = configured

    if isinstance(override, str) and override.strip():
        text = override.strip()
        if not _INTEGER_RE.match(text):
            rejected.append(
                f"{HEALTH_CHECK_TTL_ENV}={_for_warning(override)} "
                f"is not an integer number of seconds"
            )
        else:
            try:
                parsed = int(text)
            except ValueError:
                # Matching the regex is not enough: Python 3.11 caps
                # string->int conversion at 4300 digits, so an all-digit paste
                # reaches here and raises. Left unguarded it is the one
                # malformed TTL that stops an agent from booting, which is
                # exactly the case where falling back matters most.
                rejected.append(
                    f"{HEALTH_CHECK_TTL_ENV}={_for_warning(text)} "
                    f"is too large to parse as a number of seconds"
                )
            else:
                if parsed < 1:
                    rejected.append(
                        f"{HEALTH_CHECK_TTL_ENV}={_for_warning(override)} "
                        f"is below the 1s minimum"
                    )
                else:
                    ttl = parsed

    for reason in rejected:
        logger.warning("%s — using %ss", reason, ttl)

    return ttl


def resolve_health_check_ttl_from_env(configured: Any = None) -> int:
    """Read ``MCP_MESH_HEALTH_CHECK_TTL`` and resolve against it."""
    return resolve_health_check_ttl(configured, os.environ.get(HEALTH_CHECK_TTL_ENV))


# =============================================================================
# Health Result Storage (moved from DecoratorRegistry)
# =============================================================================

# Simple storage for the latest health check result dict
# Format: {"status": "healthy/degraded/unhealthy", "agent": "...", ...}
_health_check_result: dict | None = None


def store_health_check_result(result: dict) -> None:
    """Store health check result for K8s endpoints."""
    global _health_check_result
    _health_check_result = result
    logger.debug(f"Stored health check result: {result.get('status', 'unknown')}")


def get_health_check_result() -> dict | None:
    """Get stored health check result."""
    return _health_check_result


def clear_health_check_result() -> None:
    """Clear stored health check result."""
    global _health_check_result
    _health_check_result = None
    logger.debug("Cleared health check result")


# =============================================================================
# `degraded` as a RETURN VALUE is deprecated (issue #1515)
# =============================================================================
#
# The contract a health check answers is binary: stay in dependency
# resolution, or withdraw. `degraded` and `healthy` are the same answer to
# it — both keep the heartbeat alive and both keep consumers routing here —
# so the third word buys a 503 on an endpoint nothing probes, and costs the
# failure rate of a name that reads like withdrawal to everyone who picks it
# when their upstream is down. The reference templates themselves picked it
# wrong in all three runtimes.
#
# The BEHAVIOUR is unchanged, deliberately. Remapping `degraded` to
# `unhealthy` would fix the common intent and silently withdraw every agent
# whose author used the word correctly, so this warns and waits.
#
# The internal HealthStatusType.DEGRADED survives: a check that raises and a
# check that returns an unusable type both need a verdict that is neither
# trusted-healthy nor withdraw. Those paths do NOT warn — nothing the author
# can act on happened. Only a verdict the author SELECTED reaches here.
_degraded_return_deprecation_logged = False
_degraded_return_lock = threading.Lock()


def _warn_degraded_return_once() -> None:
    """Warn that a selected ``degraded`` no longer differs from ``healthy``.

    Once per process, not once per refresh. The check re-runs every TTL (15s
    by default), so a per-call warning would be several thousand identical
    lines a day from an agent that is doing exactly what its author intended
    — which trains operators to filter the line rather than read it.
    """
    global _degraded_return_deprecation_logged
    with _degraded_return_lock:
        if _degraded_return_deprecation_logged:
            return
        _degraded_return_deprecation_logged = True
    logger.warning(
        "health_check returned `degraded` — this agent stays in dependency "
        "resolution and consumers will keep routing to it. Return `False` to "
        "withdraw."
    )


def _reset_degraded_return_warning() -> None:
    """Re-arm the once-per-process warning. Tests only."""
    global _degraded_return_deprecation_logged
    with _degraded_return_lock:
        _degraded_return_deprecation_logged = False


# A null status is a defect in the same shape as a selected `degraded`: it
# recurs identically on every refresh, so it gets the same treatment. At the
# 15s default a per-tick line is ~5,760 identical warnings a day.
_null_status_warning_logged = False
_null_status_lock = threading.Lock()


def _warn_null_status_once() -> None:
    """Warn that a present-but-null status was read as healthy. Once."""
    global _null_status_warning_logged
    with _null_status_lock:
        if _null_status_warning_logged:
            return
        _null_status_warning_logged = True
    logger.warning(
        "Health check returned a null status — treating it as healthy "
        "(an absent status already means healthy). Return 'healthy' or "
        "'unhealthy' if a verdict was intended."
    )


def _reset_null_status_warning() -> None:
    """Re-arm the once-per-process warning. Tests only."""
    global _null_status_warning_logged
    with _null_status_lock:
        _null_status_warning_logged = False


# =============================================================================
# TTL-Based Health Cache
# =============================================================================

# Global cache for HealthStatus objects with per-key TTL
# Format: {"health:agent_id": (HealthStatus, expiry_timestamp)}
_health_cache: dict[str, tuple[HealthStatus, float]] = {}
_max_cache_size = 100


async def get_health_status_with_cache(
    agent_id: str,
    health_check_fn: Callable[[], Any] | Callable[[], Awaitable[Any]] | None,
    agent_config: dict[str, Any],
    startup_context: dict[str, Any],
    ttl: int = 15,
) -> HealthStatus:
    """
    Get health status with TTL caching.

    User health check can return:
    - bool: True = HEALTHY, False = UNHEALTHY
    - dict: {"status": "healthy/unhealthy", "checks": {...}, "errors": [...]}
    - HealthStatus: Full object

    Args:
        agent_id: Unique identifier for the agent
        health_check_fn: Optional sync or async function for health check
        agent_config: Agent configuration dict
        startup_context: Full startup context with capabilities
        ttl: Cache TTL in seconds (default: 15)

    Returns:
        HealthStatus from cache or fresh check
    """
    cache_key = f"health:{agent_id}"
    current_time = time.monotonic()

    # Check cache
    if cache_key in _health_cache:
        cached_status, expiry_time = _health_cache[cache_key]
        if current_time < expiry_time:
            logger.debug(f"Health check cache HIT for agent '{agent_id}'")
            return cached_status
        else:
            logger.debug(f"Health check cache EXPIRED for agent '{agent_id}'")
            del _health_cache[cache_key]

    logger.debug(f"Health check cache MISS for agent '{agent_id}'")

    # Execute health check
    health_status = await _execute_health_check(
        agent_id, health_check_fn, agent_config, startup_context
    )

    # Store in cache
    expiry_time = current_time + ttl
    _health_cache[cache_key] = (health_status, expiry_time)
    logger.debug(f"Cached health status for '{agent_id}' with TTL={ttl}s")

    # Enforce max cache size
    if len(_health_cache) > _max_cache_size:
        oldest_key = min(_health_cache.keys(), key=lambda k: _health_cache[k][1])
        del _health_cache[oldest_key]
        logger.debug("Evicted oldest cache entry to maintain max size")

    return health_status


async def _execute_health_check(
    agent_id: str,
    health_check_fn: Callable[[], Any] | Callable[[], Awaitable[Any]] | None,
    agent_config: dict[str, Any],
    startup_context: dict[str, Any],
) -> HealthStatus:
    """Execute health check function and build HealthStatus.

    Sync and async checks are both accepted, matching ``run_startup_check``.
    A bare ``await health_check_fn()`` raised ``TypeError`` on a ``def``
    check, which the handler below recorded as DEGRADED — so an author who
    forgot ``async`` got a check that appeared to run, never reported a real
    verdict, and could never withdraw the agent (issue #1517).

    A sync check runs on a worker thread, not inline. ``run_startup_check``
    can call one inline because it runs once, at boot; this runs every TTL for
    the life of the process, and the natural sync probe is a blocking
    ``requests.get(vendor, timeout=5)``. Inline, that stalls whichever loop the
    refresh was scheduled on — and for ``api``/``a2a`` gateways
    (``health_refresh.py``) that is the HEARTBEAT thread's loop, so a slow
    probe would delay the very heartbeats whose absence withdraws the agent.
    Accepting sync checks without offloading them would have invited exactly
    that.
    """
    capabilities = _get_capabilities(startup_context, agent_config)

    if health_check_fn:
        try:
            logger.debug(f"Executing health check for agent '{agent_id}'")
            if inspect.iscoroutinefunction(health_check_fn):
                user_result = await health_check_fn()
            else:
                user_result = await asyncio.to_thread(health_check_fn)
                if inspect.isawaitable(user_result):
                    # A `def` that returns an awaitable: a lambda wrapping an
                    # async call, an object with an async __call__. Building
                    # the coroutine off-loop is harmless; awaiting it here runs
                    # it on this loop, which is where it belongs.
                    user_result = await user_result
            status_type, checks, errors = _parse_health_result(user_result)

            logger.info(f"Health check for '{agent_id}': {status_type.value}")

        except Exception as e:
            logger.warning(f"Health check failed for agent '{agent_id}': {e}")
            status_type = HealthStatusType.DEGRADED
            checks = {"health_check_execution": False}
            errors = [f"Health check failed: {str(e)}"]
    else:
        # No health check provided - default to HEALTHY
        logger.debug(f"No health check for '{agent_id}', using default HEALTHY")
        status_type = HealthStatusType.HEALTHY
        checks = {}
        errors = []

    return HealthStatus(
        agent_name=agent_id,
        status=status_type,
        capabilities=capabilities,
        checks=checks,
        errors=errors,
        timestamp=datetime.now(UTC),
        version=agent_config.get("version", "1.0.0"),
        metadata=agent_config,
        uptime_seconds=0,
    )


def _get_capabilities(
    startup_context: dict[str, Any],
    agent_config: dict[str, Any],
) -> list[str]:
    """Get capabilities from context with fallbacks."""
    capabilities = startup_context.get("capabilities", [])
    if not capabilities:
        capabilities = agent_config.get("capabilities", [])
    if not capabilities:
        capabilities = ["default"]
    return capabilities


def _parse_health_result(
    user_result: Any,
) -> tuple[HealthStatusType, dict, list]:
    """Parse user health check result into status, checks, errors."""
    if isinstance(user_result, bool):
        status_type = (
            HealthStatusType.HEALTHY if user_result else HealthStatusType.UNHEALTHY
        )
        checks = {"health_check": user_result}
        errors = [] if user_result else ["Health check returned False"]

    elif isinstance(user_result, dict):
        raw_status = user_result.get("status", "healthy")
        if raw_status is None:
            # An explicit None is treated exactly like an absent key, which
            # already defaults to healthy here and in TypeScript — a result
            # carrying only `checks` is reporting success. It still warns:
            # `"status": None` is far likelier to be an unset variable than an
            # intent, and the warning is what separates the two cases without
            # changing routing. Left unhandled it called None.lower(), raised,
            # and landed on DEGRADED (issue #1517).
            _warn_null_status_once()
            raw_status = "healthy"
        # Stripped, matching TypeScript's `toStatus` and Java's
        # `MeshHealthStatus.fromWire`, which have always trimmed. This one is a
        # ROUTING change, not just a parsing tidy-up: `{"status": " unhealthy "}`
        # used to fall through to UNKNOWN, which keeps heartbeating, so an agent
        # that had declared itself unable to serve stayed in resolution. It now
        # withdraws, which is what it asked for.
        status_str = raw_status.strip().lower()
        status_map = {
            "healthy": HealthStatusType.HEALTHY,
            "degraded": HealthStatusType.DEGRADED,
            "unhealthy": HealthStatusType.UNHEALTHY,
        }
        status_type = status_map.get(status_str, HealthStatusType.UNKNOWN)
        if status_type is HealthStatusType.DEGRADED:
            _warn_degraded_return_once()
        checks = user_result.get("checks", {})
        errors = user_result.get("errors", [])

    elif isinstance(user_result, HealthStatus):
        status_type = user_result.status
        if status_type is HealthStatusType.DEGRADED:
            _warn_degraded_return_once()
        checks = user_result.checks
        errors = user_result.errors

    else:
        # Issue #1477: a wrong return TYPE degrades, it does not withdraw. It
        # is deterministic — it recurs identically on every refresh — so
        # UNHEALTHY would withdraw the agent permanently on a coding defect in
        # the check, from an agent whose upstream is very likely fine. Java
        # (#1475) and TypeScript (#1481) make the same call. Returning False,
        # or a dict with "status": "unhealthy", still withdraws.
        type_name = type(user_result).__name__
        logger.warning(
            "Unexpected health check return type '%s' — reporting degraded "
            "(the agent keeps heartbeating). Return a bool, a "
            "{status, checks, errors} dict, or a HealthStatus.",
            type_name,
        )
        status_type = HealthStatusType.DEGRADED
        checks = {"health_check_return_type": False}
        errors = [
            f"Invalid return type: {type_name}. A health check returns a bool, "
            f"a {{status, checks, errors}} dict, or a HealthStatus."
        ]

    return status_type, checks, errors


# =============================================================================
# Health Status → Rust Core (issue #1472)
# =============================================================================


def publish_health_status_to_core(status: str) -> bool:
    """Push the latest health-check verdict down to the Rust core.

    A failing ``health_check`` used to affect nothing but the ``/health`` and
    ``/ready`` responses: the heartbeat hardcoded HEALTHY, so the registry kept
    routing to the agent. The core now suppresses heartbeats while the reported
    status is ``unhealthy``; the registry's staleness sweep then marks the agent
    unhealthy and resolution stops selecting it. Reporting ``healthy`` again
    resumes heartbeats and the registry restores the agent — no restart.

    Called on every refresh tick, so it is idempotent by design: the core only
    acts on transitions.

    Args:
        status: The status string from the health-check result
            (``healthy`` / ``degraded`` / ``unhealthy`` / ``unknown``).

    Returns:
        True if the status was handed to at least one live core handle.
        False when there is no handle yet (startup — see below), when the Rust
        core is unavailable, or when the push failed.

    Startup ordering (deliberate): the seed health check runs during pipeline
    setup, BEFORE the lifespan task calls ``start_agent()``, so no handle
    exists and this is a no-op. That is the behaviour we want — the agent
    registers and becomes visible first, then goes silent if the check is
    genuinely failing on the next refresh. It also means the known-unreliable
    seed result (it runs on the framework loop, where loop-affine resources
    created in the user's lifespan are not yet usable) can never withdraw an
    agent that is actually fine.
    """
    try:
        import mcp_mesh_core
    except ImportError:
        # Pure-Python/test environments without the native core: nothing to
        # tell. The /health and /ready endpoints still reflect the result.
        logger.debug("Rust core unavailable — not publishing health status")
        return False

    from .simple_shutdown import get_active_rust_agent_handles

    handles = get_active_rust_agent_handles()
    if not handles:
        logger.debug(
            "No live Rust core handle yet — health status '%s' not published "
            "(expected during startup, before the heartbeat task starts)",
            status,
        )
        return False

    # Anything we cannot parse maps to Degraded, NOT Unhealthy: an
    # unrecognized status is a reporting defect, and withdrawing an agent
    # from the mesh on one is a far worse failure than keeping it.
    core_status = {
        "healthy": mcp_mesh_core.HealthStatus.Healthy,
        "degraded": mcp_mesh_core.HealthStatus.Degraded,
        "unhealthy": mcp_mesh_core.HealthStatus.Unhealthy,
    }.get(str(status).lower())
    if core_status is None:
        logger.warning(
            "Unrecognized health status '%s' — reporting Degraded to the core "
            "(the agent keeps heartbeating)",
            status,
        )
        core_status = mcp_mesh_core.HealthStatus.Degraded

    published = False
    for handle in handles:
        try:
            if handle.update_health(core_status):
                published = True
        except Exception as e:
            # Never let health reporting break the refresh loop.
            logger.warning("Failed to publish health status to Rust core: %s", e)
    if published:
        logger.debug("Published health status '%s' to Rust core", status)
    return published


def clear_health_cache(agent_id: str | None = None) -> None:
    """Clear health cache for a specific agent or all agents."""
    if agent_id:
        cache_key = f"health:{agent_id}"
        if cache_key in _health_cache:
            del _health_cache[cache_key]
            logger.debug(f"Cleared health cache for agent '{agent_id}'")
    else:
        _health_cache.clear()
        logger.debug("Cleared entire health cache")


def get_cache_stats() -> dict[str, Any]:
    """Get cache statistics for monitoring."""
    return {
        "size": len(_health_cache),
        "maxsize": _max_cache_size,
        "ttl": 15,
        "cached_agents": [key.replace("health:", "") for key in _health_cache.keys()],
    }


# =============================================================================
# K8s Response Helpers
# =============================================================================


def _standalone_from_env() -> bool:
    """Whether MCP_MESH_STANDALONE switches registry communication off.

    Never raises: this feeds a probe response, and a config-resolution error
    must not turn ``/ready`` into a 500. An unreadable value is treated as
    "not standalone", which is the mode every deployed agent runs in.
    """
    try:
        from .config_resolver import ValidationRule, get_config_value

        return bool(
            get_config_value(
                "MCP_MESH_STANDALONE",
                default=False,
                rule=ValidationRule.TRUTHY_RULE,
            )
        )
    except Exception:  # pragma: no cover - defensive
        return False


def runtime_state(standalone: bool | None = None) -> tuple[bool, str]:
    """Report whether the mesh runtime is up, and in what state.

    This is the ONE definition of "the runtime is up" for every Python probe
    — the provider endpoints in ``mesh/decorators.py`` and the gateway
    endpoints in ``pipeline/shared/health_endpoints.py`` both answer
    ``/ready`` from it. Two copies of the rule is how a gateway and a
    provider end up disagreeing about what readiness means.

    ``standalone`` mode never starts a Rust core (registry communication is
    switched off by configuration), so the agent is ready as soon as it
    serves — the absence of a handle is the configured outcome, not a
    startup that has not finished. ``None`` reads the environment; the
    gateway pipeline passes the value it already resolved.
    """
    if standalone is None:
        standalone = _standalone_from_env()
    if standalone:
        return True, "standalone"

    from .simple_shutdown import (
        get_active_rust_agent_handles,
        should_stop_heartbeat,
    )

    if should_stop_heartbeat():
        return False, "shutting_down"
    if get_active_rust_agent_handles():
        return True, "up"
    return False, "starting"


NOT_READY_REASON = {
    "starting": "Mesh runtime has not started yet",
    "shutting_down": "Mesh runtime is shutting down",
}


def build_health_response(
    agent_name: str,
    health_status: HealthStatus | None = None,
) -> tuple[dict, int]:
    """
    Build /health endpoint response with appropriate HTTP status code.

    Returns:
        Tuple of (response_dict, http_status_code)
    """
    if health_status:
        status = health_status.status.value
        response = {
            "status": status,
            "agent": agent_name,
            "checks": health_status.checks,
            "errors": health_status.errors,
            "timestamp": health_status.timestamp.isoformat(),
        }
    else:
        # Use stored result if available
        stored = get_health_check_result()
        if stored:
            status = stored.get("status", "starting")
            response = stored
        else:
            status = "starting"
            response = {"status": "starting", "message": "Agent is starting"}

    # K8s expects 200 for healthy, 503 for everything else
    http_status = 200 if status == "healthy" else 503
    return response, http_status


def build_ready_response(
    agent_name: str,
    mcp_wrappers_count: int = 0,
) -> tuple[dict, int]:
    """
    Build /ready endpoint response with appropriate HTTP status code.

    Reports whether the **mesh runtime** is up, and nothing else (RFC #1502).
    The user's ``health_check`` is deliberately NOT consulted here — this is
    the same rule the gateway pipelines have always applied, now applied to
    every agent type.

    A failing check pauses the heartbeat, the registry ages the agent out and
    resolution stops selecting it; that is the whole withdrawal mechanism and
    it needs no help from the readiness probe. Adding readiness on top is
    strictly worse: ``agent.advertisedHost`` defaults to the per-agent
    Service DNS name, so mesh traffic traverses the Service. A 503 here drops
    the pod from its Service endpoints while the registry may still be
    selecting it, and a consumer gets a connection error instead of failing
    over. The verdict still shows on ``/health``, which nothing probes.

    Returns:
        Tuple of (response_dict, http_status_code)
    """
    is_ready, state = runtime_state()

    response: dict[str, Any] = {
        "ready": is_ready,
        "agent": agent_name,
        "runtime": state,
        "mcp_wrappers": mcp_wrappers_count,
        "timestamp": datetime.now(UTC).isoformat(),
    }
    if not is_ready:
        response["reason"] = NOT_READY_REASON.get(state, f"Mesh runtime is {state}")
    return response, 200 if is_ready else 503


def build_livez_response(agent_name: str) -> dict:
    """Build /livez endpoint response (always returns 200)."""
    return {
        "alive": True,
        "agent": agent_name,
        "timestamp": datetime.now(UTC).isoformat(),
    }
