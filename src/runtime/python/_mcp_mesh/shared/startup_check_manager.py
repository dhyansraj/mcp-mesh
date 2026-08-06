"""The ``startup_check`` hook and the ``/startupz`` response (RFC #1502).

``health_check`` answers "can I serve *right now*?" — a transient answer, and a
failing one only pauses the heartbeat so the registry stops selecting this agent
until it recovers. ``startup_check`` answers the other question: "is this agent
configured such that it can *ever* serve?" A missing API key is not going to fix
itself, and today it looks exactly like a vendor outage — the agent sits
unregistered, the pod runs, and nothing is loud.

**What ships today (RFC #1502 step 1).** ``startup_check`` is reported by
``GET``/``HEAD`` ``/startupz``, and that is the whole effect: a failing check
answers 503 there. Nothing else changes — the agent is not withdrawn, the
heartbeat is untouched, ``/livez`` and ``/ready`` answer exactly as they did.

The agent chart's ``startupProbe`` still points at ``/livez``, so nothing acts
on the verdict yet. Repointing it at ``/startupz`` is step 2, and it is what
the hook exists for: a pod whose startup check never passes then never becomes
ready, never registers, and ends up in ``CrashLoopBackOff`` — visible. Until
then, ``/startupz`` is a surface to build against and to scrape.

Three properties are deliberate, and each is the OPPOSITE of the corresponding
``health_check`` rule:

``A throw fails the check.``
    ``health_check`` degrades on a throw (a buggy probe must not withdraw a
    working provider from a mesh that may have no other one). Here the question
    is whether a possibly-misconfigured agent should be allowed to come up at
    all, and an indeterminate answer at boot is not a reason to let it through.
    The cost of being wrong is also asymmetric: a false failure crash-loops one
    pod that was never serving, a false pass silently registers a broken one.

``Anything short of a clean pass fails.``
    ``degraded``, an unrecognized return type, ``None`` — all fail. There is no
    partial credit for "am I configured".

``There is no cache.``
    A ``startupProbe`` stops polling after its first success, so the check runs
    a handful of times at most. A TTL cache would only add a way for the endpoint
    to answer with a verdict older than the probe that asked for it.

An agent that declares no ``startup_check`` passes. Default-true is what makes
this purely additive: every existing agent behaves exactly as it did.
"""

import inspect
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from .health_check_manager import _for_warning
from .support_types import HealthStatus, HealthStatusType

logger = logging.getLogger(__name__)

STARTUPZ_PATH = "/startupz"

#: Key under which ``@mesh.agent(startup_check=...)`` stores the callable.
STARTUP_CHECK_CONFIG_KEY = "startup_check"


def get_startup_check() -> Callable[[], Any] | None:
    """The agent's ``startup_check``, or None when none was declared.

    Resolved per call rather than captured once: the probe endpoints are
    registered before the pipeline has finished writing the resolved agent
    config, so reading it at request time is the only way to see a check the
    decorator declared.
    """
    try:
        from ..engine.decorator_registry import DecoratorRegistry

        config = DecoratorRegistry.get_resolved_agent_config() or {}
    except Exception as e:  # pragma: no cover - defensive
        # Never let a config-lookup failure decide that an agent is broken:
        # not finding a check is "no check declared", which passes.
        logger.debug("Could not resolve agent config for startup_check: %s", e)
        return None

    check = config.get(STARTUP_CHECK_CONFIG_KEY)
    return check if callable(check) else None


def _parse_startup_result(raw: Any) -> tuple[bool, dict, list]:
    """Reduce whatever the check returned to ``(passed, checks, errors)``.

    The accepted shapes are ``health_check``'s, so an author writing both hooks
    writes them the same way: a bool, a ``{status, checks, errors}`` dict, or a
    ``HealthStatus``. What differs is the verdict mapping — only a clean
    ``healthy``/``True`` passes (see the module docstring).
    """
    if isinstance(raw, bool):
        return (
            raw,
            {"startup_check": raw},
            [] if raw else ["Startup check returned False"],
        )

    if isinstance(raw, dict):
        status = str(raw.get("status", "healthy")).lower()
        passed = status == "healthy"
        errors = list(raw.get("errors", []))
        if not passed and not errors:
            errors = [f"Startup check reported '{_for_warning(status)}'"]
        return passed, dict(raw.get("checks", {})), errors

    if isinstance(raw, HealthStatus):
        passed = raw.status == HealthStatusType.HEALTHY
        errors = list(raw.errors)
        if not passed and not errors:
            # Not ``raw.status.value``: ``model_construct`` skips validation, so
            # ``status`` need not be the enum, and interpolating a user value is
            # the hazard ``_for_warning`` exists for (see health_check_manager).
            status = getattr(raw.status, "value", raw.status)
            errors = [f"Startup check reported '{_for_warning(status)}'"]
        return passed, dict(raw.checks), errors

    type_name = type(raw).__name__
    logger.warning(
        "startup_check returned '%s', which is not a startup verdict — failing "
        "the startup probe. Return a bool, a {status, checks, errors} dict, or "
        "a HealthStatus.",
        type_name,
    )
    return (
        False,
        {"startup_check_return_type": False},
        [
            f"Invalid return type: {type_name}. A startup check returns a bool, "
            f"a {{status, checks, errors}} dict, or a HealthStatus."
        ],
    )


async def run_startup_check(
    check: Callable[[], Any] | Callable[[], Awaitable[Any]] | None,
) -> tuple[bool, dict, list]:
    """Run ``check`` once and report ``(passed, checks, errors)``.

    Never raises. Sync and async checks are both accepted — a startup check is
    often a bare environment-variable read, and forcing ``async def`` on it
    would be ceremony with no payoff.
    """
    if check is None:
        return True, {}, []

    try:
        result = check()
        if inspect.isawaitable(result):
            result = await result
        # Parsed INSIDE the guard, not after it. Reducing the return value
        # touches user-controlled attributes — a lazily-computed ``status``, a
        # dict-like config object — and a raise there is exactly as
        # indeterminate as a raise from the check itself. Parsing outside would
        # leave the one path this hook exists for able to 500 the endpoint.
        return _parse_startup_result(result)
    except Exception as e:
        # Broad on purpose. A throwing check must not take the endpoint down
        # with it, and unlike health_check (where a throw degrades and the
        # agent keeps heartbeating) it must not pass either — see the module
        # docstring on why an indeterminate boot-time answer fails.
        logger.warning("startup_check raised — failing the startup probe: %s", e)
        return False, {"startup_check_execution": False}, [f"Startup check failed: {e}"]


async def build_startupz_response(
    agent_name: str,
    check: Callable[[], Any] | None = None,
    **extra: Any,
) -> tuple[dict, int]:
    """Build the ``/startupz`` body and status code.

    Mirrors ``build_ready_response``'s shape — a ``started`` boolean in place of
    ``ready``, and ``reason``/``errors`` on failure — so an operator reads the
    two probes the same way.

    Args:
        agent_name: name reported in the body
        check: the check to run; resolved from the agent config when omitted
        extra: additional body keys (e.g. ``service_type`` on a gateway)
    """
    if check is None:
        check = get_startup_check()

    passed, checks, errors = await run_startup_check(check)

    body: dict[str, Any] = {
        "started": passed,
        "agent": agent_name,
        **extra,
        "timestamp": datetime.now(UTC).isoformat(),
    }
    if checks:
        body["checks"] = checks
    if not passed:
        body["reason"] = "Startup check failed"
        body["errors"] = errors
    return body, (200 if passed else 503)
