#!/usr/bin/env python3
"""Test agent for the lifespan-ready gate on the health_check refresh
loop (issue #1072 follow-up).

Scenario:
  - ``health_check_ttl=1`` (aggressive — refresh fires every second).
  - The lifespan body sleeps ~3 seconds before flipping a
    ``_lifespan_complete`` sentinel to ``True``.
  - The user ``health_check_fn`` records every call where
    ``_lifespan_complete is False`` into ``_premature_calls``.

If the refresh loop is properly gated on the lifespan-ready signal,
``_premature_calls`` MUST stay at 0 — the refresh loop should not
fire its first iteration until ``__aenter__`` has returned. The seed
call from the framework loop runs before lifespan startup by design
and is counted via ``_seed_calls`` (not premature) so the test can
distinguish a refresh-side leak from the known framework-loop seed.

A failure mode this catches: removing the
``await asyncio.wrap_future(ready_future)`` gate causes the refresh
loop to fire at T+1s while the lifespan body is still sleeping, so
``_premature_calls`` increments and the assertion fails.
"""
import asyncio
from contextlib import asynccontextmanager

import mesh
from fastmcp import FastMCP

# Sentinel flipped by the lifespan body; observed by the health check.
_lifespan_complete = False

# Calls observed BEFORE lifespan signaled complete. Should stay 0
# under correct gating. The seed call (which runs on the framework
# loop before lifespan startup by design) is counted separately so
# the test can prove refresh-side gating works.
_premature_calls = 0
_seed_calls = 0
_post_ready_calls = 0


@asynccontextmanager
async def _lifespan(server):
    global _lifespan_complete
    # Hold up the lifespan body for ~3s so the refresh loop's
    # TTL=1s schedule would have fired 2-3 times if it weren't
    # properly gated.
    await asyncio.sleep(3)
    _lifespan_complete = True
    yield
    _lifespan_complete = False


app = FastMCP("health-gate-agent", lifespan=_lifespan)


async def my_health_check() -> dict:
    """Records whether the call landed before or after the lifespan
    completed its startup body. The seed (first) call runs on the
    framework loop before lifespan startup and is counted separately.
    """
    global _premature_calls, _seed_calls, _post_ready_calls
    if _seed_calls == 0:
        _seed_calls += 1
        return {
            "status": "healthy",
            "checks": {"seed_call": True},
            "errors": [f"seed-call premature={_premature_calls}"],
        }

    if not _lifespan_complete:
        _premature_calls += 1
        return {
            "status": "unhealthy",
            "errors": [f"premature-call-{_premature_calls}"],
        }

    _post_ready_calls += 1
    return {
        "status": "healthy",
        "checks": {"post_ready": True},
        "errors": [
            f"post-ready-call-{_post_ready_calls} "
            f"premature={_premature_calls}"
        ],
    }


@app.tool()
@mesh.tool(capability="gate.status")
async def gate_status() -> dict:
    return {
        "lifespan_complete": _lifespan_complete,
        "premature_calls": _premature_calls,
        "seed_calls": _seed_calls,
        "post_ready_calls": _post_ready_calls,
    }


@mesh.agent(
    name="health-gate-agent",
    auto_run=True,
    health_check=my_health_check,
    health_check_ttl=1,
)
class HealthGateAgent:
    pass
