#!/usr/bin/env python3
"""uc38 py-signal-consumer — RECOGNIZES the typed supersession signal (#1278).

This consumer proves the RECOGNIZE half over the REAL transport. Each probe
tool calls the provider through an INJECTED ``mesh.McpMeshTool`` proxy (the
primary HTTP transport path — the one whose recognize was found DEAD because
the unit tests mocked the converter boundary) and classifies the outcome:

  * probe_superseded calls reject-superseded. The provider's reserved envelope
    must be recognized by the injected proxy and re-raised as the typed
    ``mesh.SupersededError`` — so this handler's ``except mesh.SupersededError``
    fires and it reports ``outcome=superseded``. That marker is ONLY reachable
    if the typed error was raised; a string body or a generic error would land
    in the generic branch instead.

  * probe_generic calls reject-generic (the control). The provider's plain
    error is NOT the reserved envelope, so the proxy must NOT re-raise
    ``SupersededError`` — this handler falls through to the generic branch and
    reports ``outcome=generic``. This is the negative control that proves an
    arbitrary failure is never misclassified as supersession.

The ``except`` order matters: ``SupersededError`` IS a ``ToolError`` IS an
``Exception``, so the specific catch is listed first. Every probe returns a
JSON STRING so the caller parses it uniformly via ``content[0].text | fromjson``
(structuredContent is Python-only; the text envelope is portable).
"""

import json
import os

import mesh
from fastmcp import FastMCP

app = FastMCP("SignalConsumer Service")


@app.tool()
@mesh.tool(
    capability="probe-superseded",
    description="Calls reject-superseded via injected proxy and classifies it",
    dependencies=[{"capability": "reject-superseded"}],
)
async def probe_superseded(dep: mesh.McpMeshTool = None) -> str:
    if dep is None:
        return json.dumps({"outcome": "no_dep"})
    try:
        await dep()
        return json.dumps({"outcome": "no_error"})
    except mesh.SupersededError as e:
        # Reachable ONLY when the injected proxy recognized the reserved
        # claim_superseded envelope and re-raised the typed error.
        return json.dumps({"outcome": "superseded", "detail": e.detail})
    except Exception as e:  # noqa: BLE001 — deliberately broad control branch
        return json.dumps({"outcome": "generic", "error_type": type(e).__name__})


@app.tool()
@mesh.tool(
    capability="probe-generic",
    description="Control: calls reject-generic via injected proxy and classifies it",
    dependencies=[{"capability": "reject-generic"}],
)
async def probe_generic(dep: mesh.McpMeshTool = None) -> str:
    if dep is None:
        return json.dumps({"outcome": "no_dep"})
    try:
        await dep()
        return json.dumps({"outcome": "no_error"})
    except mesh.SupersededError as e:
        return json.dumps({"outcome": "superseded", "detail": e.detail})
    except Exception as e:  # noqa: BLE001 — a generic error MUST land here
        return json.dumps({"outcome": "generic", "error_type": type(e).__name__})


@mesh.agent(
    name="py-signal-consumer",
    version="1.0.0",
    description="uc38 consumer that recognizes the typed supersession signal",
    http_port=int(os.environ.get("MCP_MESH_HTTP_PORT", "9202")),
    enable_http=True,
    auto_run=True,
)
class SignalConsumer:
    pass
