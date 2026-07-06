#!/usr/bin/env python3
"""uc38 py-signal-provider — emits the typed supersession signal (issue #1278).

This provider proves the EMIT half of the emit->wire->recognize plumbing over
the REAL HTTP transport (not the mocked converter boundary the unit tests
exercised). Three capabilities:

  * reject-superseded — UNCONDITIONALLY rejects every call by raising
    ``mesh.SupersededError``. That subclasses fastmcp's ``ToolError``, so the
    existing tool-error path emits an ``isError`` result whose text is the
    reserved envelope ``{"error":"claim_superseded","detail":...}``. This is the
    signal that must cross the wire and be RECOGNIZED by the caller's injected
    proxy. It increments an in-process counter BEFORE raising so the caller side
    can assert the provider was invoked EXACTLY ONCE (the Python real-transport
    bug double-invoked via a fallback transport).

  * reject-generic — the CONTROL. Raises a plain ``ToolError`` whose message is
    NOT the reserved envelope. The caller's recognize path must classify this as
    a GENERIC failure, never as supersession.

  * superseded-call-count — reports how many times reject-superseded actually
    ran in this process, so the caller can prove single-invoke.

The provider rejects unconditionally on purpose: this TC proves the framework
plumbing, NOT the epoch-supersession app logic (that is app-owned and covered
by the example). The real calling-job-epoch dance is deliberately absent.
"""

import json
import os

import mesh
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

app = FastMCP("SignalProvider Service")

# In-process invocation counter. Only reject_superseded increments it; a
# double-invoke on the real transport would push this to 2.
_calls = {"reject_superseded": 0}


@app.tool()
@mesh.tool(
    capability="reject-superseded",
    description="Unconditionally rejects the caller as superseded (issue #1278)",
)
async def reject_superseded() -> str:
    # Count the REAL provider-side invocation, then reject. A caller that
    # recognizes the typed signal sees this exactly once.
    _calls["reject_superseded"] += 1
    raise mesh.SupersededError("stale epoch: caller superseded")


@app.tool()
@mesh.tool(
    capability="reject-generic",
    description="Control: fails with a generic (non-superseded) error",
)
async def reject_generic() -> str:
    # A plain ToolError whose message is NOT the reserved envelope. The caller
    # must classify this as generic, proving the recognize path is envelope-
    # exact and does not misclassify arbitrary failures as supersession.
    raise ToolError("generic-provider-failure: this is NOT a supersession")


@app.tool()
@mesh.tool(
    capability="superseded-call-count",
    description="Reports how many times reject-superseded was invoked",
)
async def get_reject_count() -> str:
    return json.dumps({"count": _calls["reject_superseded"]})


@mesh.agent(
    name="py-signal-provider",
    version="1.0.0",
    description="uc38 provider that emits the typed supersession signal",
    http_port=int(os.environ.get("MCP_MESH_HTTP_PORT", "9201")),
    enable_http=True,
    auto_run=True,
)
class SignalProvider:
    pass
