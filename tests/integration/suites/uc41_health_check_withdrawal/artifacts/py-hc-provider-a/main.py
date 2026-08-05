#!/usr/bin/env python3
"""py-hc-provider-a — the provider whose health check the test drives (issue #1480).

Provides ``hc_probe_py`` alongside py-hc-provider-b. Its ``probe_a`` tool
reports its own agent name, so the consumer's answer says WHICH provider
served the call — that string is the whole failover signal.

## The health check is FILE-TOGGLED, not invocation-counting

uc02/tc20 counts invocations because what it asks is "does the refresh loop
fire at all". Here the test needs to control WHEN the transition happens —
withdrawal has to be gated on a fault the test injects at a known moment, so
polling can bound it. So the check reads ``/workspace/health-flag`` on every
invocation:

  ok (or file absent) -> healthy    heartbeats, stays resolvable
  fail                -> unhealthy  heartbeat suppressed -> registry withdraws
  throw               -> raises     must map to DEGRADED, must NOT withdraw

## Every invocation is traced to a file

``/workspace/hc-invocations.log`` gets one line per invocation, written
BEFORE the ``throw`` branch raises. Without it the negative test
(tc02_python_throwing_check_degrades) would pass vacuously: a health check
that stopped running entirely also fails to withdraw the agent, and "the
agent is still resolvable" cannot tell the two apart. The trace is what
proves the loop kept running and kept seeing ``throw``.
"""

import os
from datetime import UTC, datetime

import mesh
from fastmcp import FastMCP

AGENT_NAME = "hc-provider-a-py"
FLAG_FILE = os.environ.get("HC_FLAG_FILE", "/workspace/health-flag")
TRACE_FILE = os.environ.get("HC_TRACE_FILE", "/workspace/hc-invocations.log")

app = FastMCP("HC Provider A (python)")


def _read_flag() -> str:
    """Current fault state. A missing file means healthy, so the agent boots
    green without the test having to seed anything."""
    try:
        with open(FLAG_FILE) as handle:
            return handle.read().strip().lower() or "ok"
    except OSError:
        return "ok"


def _trace(flag: str, verdict: str) -> None:
    """Append one line per invocation. Best-effort: a trace write that fails
    must never be the reason the health check reports something different."""
    try:
        with open(TRACE_FILE, "a") as handle:
            handle.write(
                f"{datetime.now(UTC).isoformat()} agent={AGENT_NAME} "
                f"flag={flag} verdict={verdict}\n"
            )
    except OSError:
        pass


async def vendor_health() -> dict:
    """Simulated upstream-vendor probe, driven by the flag file."""
    flag = _read_flag()

    if flag == "fail":
        _trace(flag, "unhealthy")
        return {
            "status": "unhealthy",
            "checks": {"vendor_api_reachable": False},
            "errors": ["simulated vendor outage (health-flag=fail)"],
        }

    if flag == "throw":
        # Traced BEFORE raising — see the module docstring.
        _trace(flag, "raised")
        raise RuntimeError("simulated broken health check (health-flag=throw)")

    _trace(flag, "healthy")
    return {
        "status": "healthy",
        "checks": {"vendor_api_reachable": True},
    }


@app.tool()
@mesh.tool(
    capability="hc_probe_py",
    description="Report which provider instance served this call",
    tags=["hc-withdrawal"],
)
async def probe_a() -> dict:
    # pid is self-reported from inside the process, so it cannot go stale the
    # way a pid FILE can. Baseline and post-recovery answers carrying the same
    # pid is the proof that recovery did not restart anything.
    return {"served_by": AGENT_NAME, "pid": os.getpid()}


@mesh.agent(
    name=AGENT_NAME,
    version="1.0.0",
    description="Provider whose health check withdraws it from resolution (#1480)",
    http_port=0,  # actual port comes from MCP_MESH_HTTP_PORT
    enable_http=True,
    auto_run=True,
    health_check=vendor_health,
    # 2s so a withdrawal costs ~1 TTL + the registry staleness window rather
    # than the 15s default; the test's registry runs at a matching 5s/2s.
    health_check_ttl=2,
)
class HcProviderA:
    pass
