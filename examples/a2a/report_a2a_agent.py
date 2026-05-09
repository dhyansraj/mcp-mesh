#!/usr/bin/env python3
"""
A2A example agent for LONG-RUNNING tasks (Phase 3 — SSE streaming).

Exposes ``examples/jobs/long-task-provider``'s ``generate_report``
``task=True`` capability via the A2A v1.0 protocol surface, demonstrating:

- ``tasks/send`` returns immediately with ``state=working`` and a task id
- ``tasks/get`` polls the task and returns the current state + progress
- ``tasks/cancel`` cancels the underlying mesh job mid-flight
- ``tasks/sendSubscribe`` opens an SSE stream of TaskStatusUpdateEvent /
  TaskArtifactUpdateEvent envelopes per A2A v1.0
- ``tasks/resubscribe`` re-attaches an SSE stream to an in-flight task

The framework introspects the user handler's return value: when it's a
``mcp_mesh_core.JobProxy``, the surface routes the task lifecycle through
``MeshJob.{status, cancel, wait}``. When it's a plain dict/string, the
surface treats the task as sync (state=completed inline).

Prereqs (in three terminals)
============================

  # 1) Registry
  /tmp/mcp-mesh-registry  # or `meshctl start registry`

  # 2) Long-running provider — exposes generate_report (task=True)
  python examples/jobs/long-task-provider/main.py

  # 3) This A2A surface — exposes generate_report via A2A
  python examples/a2a/report_a2a_agent.py

Test
====

  # Submit and poll
  TASK_ID=$(curl -s -X POST http://localhost:9091/agents/report \\
    -H 'Content-Type: application/json' \\
    -d '{"jsonrpc":"2.0","id":1,"method":"tasks/send","params":{"id":"r1","message":{"role":"user","parts":[{"type":"text","text":"{\\"user_id\\":\\"alice\\",\\"sections\\":[\\"intro\\",\\"body\\",\\"summary\\"]}"}]}}}' \\
    | jq -r '.result.id')
  curl -s -X POST http://localhost:9091/agents/report \\
    -H 'Content-Type: application/json' \\
    -d "{\\"jsonrpc\\":\\"2.0\\",\\"id\\":2,\\"method\\":\\"tasks/get\\",\\"params\\":{\\"id\\":\\"$TASK_ID\\"}}"

  # Stream via SSE
  curl -N -X POST http://localhost:9091/agents/report \\
    -H 'Content-Type: application/json' \\
    -d '{"jsonrpc":"2.0","id":3,"method":"tasks/sendSubscribe","params":{"id":"s1","message":{"role":"user","parts":[{"type":"text","text":"{\\"user_id\\":\\"alice\\",\\"sections\\":[\\"intro\\",\\"body\\"]}"}]}}}'
"""

import json
import os

# Set MCP_MESH_HTTP_PORT BEFORE importing mesh so display_config picks
# up the same port we'll bind uvicorn to.
HTTP_PORT = int(os.environ.setdefault("MCP_MESH_HTTP_PORT", "9091"))

import mesh
from fastapi import FastAPI
from mesh import MeshJob

app = FastAPI(title="Report A2A Agent")


@mesh.a2a.mount(
    app,
    path="/agents/report",
    dependencies=["generate_report"],
    description="Generate a long-form report via A2A (task=True streaming)",
    skill_id="generate-report",
    skill_name="Generate Report",
    tags=["reports", "long-running"],
)
async def report_a2a(payload: dict, generate_report: MeshJob = None):
    """A2A handler that submits a long-running mesh job and returns the
    JobProxy. The framework wraps the proxy as A2A state=working with a
    fresh task_id; tasks/get/cancel/sendSubscribe/resubscribe operate on
    the parked proxy via the underlying MeshJob lifecycle.
    """
    if generate_report is None:
        # Raising surfaces as A2A state=failed. Returning a dict here would
        # incorrectly wrap the unresolved-dependency case as state=completed
        # with an error payload — misleading per the protocol.
        raise RuntimeError(
            "generate_report dependency not yet resolved by mesh DI"
        )

    # The A2A request `message` carries the user payload as a text part
    # with JSON-encoded args. Real-world clients can use any parts shape;
    # for this example we parse `parts[0].text` as JSON.
    args = {}
    parts = payload.get("parts") or []
    if parts and parts[0].get("type") == "text":
        try:
            args = json.loads(parts[0].get("text") or "{}")
        except json.JSONDecodeError:
            args = {}

    user_id = args.get("user_id", "anon")
    sections = args.get("sections") or ["overview"]

    proxy = await generate_report.submit(
        user_id=user_id,
        sections=sections,
    )
    # Returning the JobProxy switches the framework into long-running mode:
    # state=working response, task parked in _A2A_TASK_STORE for tasks/get,
    # tasks/cancel, tasks/sendSubscribe, tasks/resubscribe.
    return proxy


if __name__ == "__main__":
    import uvicorn

    print(f"📊 Report A2A Agent on http://localhost:{HTTP_PORT}")
    print(f"    Card:        GET  http://localhost:{HTTP_PORT}/agents/report/.well-known/agent.json")
    print(f"    JSON-RPC:    POST http://localhost:{HTTP_PORT}/agents/report")
    print(f"    SSE stream:  POST http://localhost:{HTTP_PORT}/agents/report  (method: tasks/sendSubscribe)")
    print()
    uvicorn.run(app, host="0.0.0.0", port=HTTP_PORT, log_level="info")
