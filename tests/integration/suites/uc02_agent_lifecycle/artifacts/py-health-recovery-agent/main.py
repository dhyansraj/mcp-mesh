#!/usr/bin/env python3
"""Test agent for issue #1072: verifies that health_check_ttl drives a
periodic refresh of the stored /health result.

The health check is invocation-counting (not wall-clock based) on
purpose. With ``health_check_ttl=3`` and a threshold of 2, the user
function MUST be invoked at least three times for /health to report
"healthy":
  - call 1 (seed at pipeline startup): unhealthy
  - call 2 (first scheduled refresh, TTL later): unhealthy
  - call 3 (second scheduled refresh, 2*TTL later): healthy

If the runtime never refreshes (the pre-v2.2.5 bug behavior),
``_invocation_count`` stays pinned at 1 and /health reports "unhealthy"
forever. Wall-clock-based detection (e.g., "after 5 seconds") doesn't
distinguish that bug from a slow agent boot.
"""
import mesh
from fastmcp import FastMCP

# Captured at module import; mutated by each health-check invocation.
# We rely on the user_loop refresh task on a single user loop, so
# concurrent invocations are not a concern here.
_invocation_count = 0
_UNHEALTHY_INVOCATIONS = 2

app = FastMCP("health-recovery-agent")


async def my_health_check() -> dict:
    """Returns unhealthy on the first ``_UNHEALTHY_INVOCATIONS`` calls,
    then healthy on every call after that.

    Each invocation increments the counter. The "unhealthy" payload
    embeds the count so the test can distinguish the seed result from
    a refresh result.
    """
    global _invocation_count
    _invocation_count += 1
    if _invocation_count <= _UNHEALTHY_INVOCATIONS:
        return {
            "status": "unhealthy",
            "errors": [f"startup-call-{_invocation_count}"],
        }
    # checks values must be bool per the SDK's HealthStatus contract;
    # leak the invocation count via errors as a stable, parseable marker.
    return {
        "status": "healthy",
        "checks": {"refreshed": True},
        "errors": [f"refresh-call-{_invocation_count}"],
    }


@app.tool()
@mesh.tool(capability="ping")
async def ping() -> dict:
    return {"ok": True, "invocation_count": _invocation_count}


@mesh.agent(
    name="health-recovery-agent",
    auto_run=True,
    health_check=my_health_check,
    health_check_ttl=3,
)
class HealthRecoveryAgent:
    pass
