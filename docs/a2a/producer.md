# A2A Producer (Python)

Expose mesh tools to external A2A clients via the A2A v1.0 protocol surface.

!!! info "Python only (today)"
    Producer support ships in the Python runtime only. Java and TypeScript producer support is future work — track the A2A consumer arc for the Java/TS sides ([Consumer Quick Start](consumer-quickstart.md)).

## The two-piece pattern

A producer agent has two pieces, both Python-side:

1. **Handler** — a function decorated with `@mesh.a2a` that processes the inbound A2A request body. Dependencies on other mesh capabilities are declared on the decorator the same way they would be on `@mesh.tool`.
2. **Mount** — `mesh.a2a.mount(app, path="/agents/<skill>", ...)` attaches both the JSON-RPC entry route AND the `/.well-known/agent.json` card route to a user-owned FastAPI app. The user owns the uvicorn lifecycle (no `@mesh.agent` decorator on the producer file).

This is intentionally the same shape as `@mesh.route` for HTTP routes — same FastAPI mounting, same uvicorn ownership, same DDDI for declared dependencies. The difference is that `mesh.a2a.mount` registers the agent with the registry as `agent_type=a2a` (with the surfaces array populated), so other mesh agents and external scaffolding tools can discover the agent's A2A skills.

## Sync handler

The simplest case — the upstream returns within seconds, so there is no parking. The handler returns a value; the framework wraps it as an A2A v1.0 `Task` envelope with `state=completed`, placing the JSON-stringified return as `result.artifacts[0].parts[0].text`.

```python
import mesh
from fastapi import FastAPI
from mesh.types import McpMeshTool

app = FastAPI(title="Date A2A Agent")


@mesh.a2a.mount(
    app,
    path="/agents/date",
    dependencies=["date_service"],
    description="Get current date/time via A2A protocol",
    skill_id="get-date",
    skill_name="Get Date",
    tags=["system", "date"],
)
async def date_a2a(payload: dict, date_service: McpMeshTool = None):
    if date_service is None:
        return {"error": "date_service not yet resolved"}
    result = await date_service()
    return {"date": result}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=9090, log_level="info")
```

Two routes are now live on port 9090:

| Route                                      | Purpose                                       |
| ------------------------------------------ | --------------------------------------------- |
| `GET  /agents/date/.well-known/agent.json` | Auto-generated agent card (capabilities, skills, auth schemes) |
| `POST /agents/date`                        | JSON-RPC entry — dispatches `tasks/*` methods |

The card is built at agent registration time from the `@mesh.tool` metadata of declared dependencies and the `mesh.a2a.mount(...)` parameters (`skill_id`, `skill_name`, `description`, `tags`). Source: `src/runtime/python/_mcp_mesh/engine/a2a_card.py`.

## Long-running handler (`task=True`)

When the underlying work is long-running (`task=True` in the dependency graph), the handler returns a `JobProxy` instead of a value. The framework parks the proxy in `_A2A_TASK_STORE` and responds to the inbound `tasks/send` immediately with `state=working` and a fresh task id. Subsequent `tasks/get` and `tasks/cancel` calls operate on the parked proxy via the underlying `MeshJob` lifecycle.

```python
import json
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
    if generate_report is None:
        raise RuntimeError("generate_report dependency not yet resolved by mesh DI")

    args = {}
    parts = payload.get("parts") or []
    if parts and parts[0].get("type") == "text":
        try:
            args = json.loads(parts[0].get("text") or "{}")
        except json.JSONDecodeError:
            args = {}

    proxy = await generate_report.submit(
        user_id=args.get("user_id", "anon"),
        sections=args.get("sections") or ["overview"],
    )
    return proxy
```

Returning the `JobProxy` switches the framework into long-running mode:

- The inbound `tasks/send` returns `state=working` immediately.
- The task is parked in `_A2A_TASK_STORE` keyed by a freshly-issued task id.
- Subsequent `tasks/get` polls the parked proxy via `MeshJob.status()`.
- `tasks/cancel` calls `MeshJob.cancel()`, propagating through to the underlying mesh job.

## SSE handler (`tasks/sendSubscribe`)

The same `JobProxy`-returning handler also services `tasks/sendSubscribe`. The framework opens an SSE stream and emits `TaskStatusUpdateEvent` + `TaskArtifactUpdateEvent` envelopes per A2A v1.0, sourced from the parked `JobProxy`'s status updates and final artifact.

The producer-side handler does NOT need to be SSE-aware — write it once for `tasks/send`, and the same code path handles `tasks/sendSubscribe` and `tasks/resubscribe`. The framework decides which envelope shape to emit based on the inbound method.

## Mixed-mode rejection

A single Python process may NOT host both `@mesh.tool`-style capabilities and a `mesh.a2a.mount(...)` surface. The framework raises a clear error at agent boot if both are present in the same process — they have different registration paths (`@mesh.tool` goes through the standard heartbeat; `mesh.a2a.mount` registers the agent as `agent_type=a2a`), and the agent card cannot represent both shapes coherently.

If you need both: split into two agents (one `@mesh.tool`-style provider for the underlying capability, one A2A-surface agent that depends on it via `dependencies=[...]`). The `report_a2a_agent` example above is exactly this pattern — it depends on `generate_report` (provided by a separate `task=True` agent) and exposes it via A2A.

## Authentication

The producer side enforces bearer auth at the JSON-RPC route. Configure the expected token via the `auth=` parameter on `mesh.a2a.mount(...)` (Phase 1 ships bearer only — OAuth / mTLS are future work). Card auth schemes are auto-published in `/.well-known/agent.json` so consumers can scaffold against them. See [Authentication](authentication.md).

## Working examples

- `examples/a2a/date_a2a_agent.py` — sync handler bridging the `date_service` capability
- `examples/a2a/report_a2a_agent.py` — long-running + SSE handler bridging `generate_report` (`task=True`)

## See also

- [Long-Running & SSE](long-running.md) — the consumer-side bridge for `task=True` and SSE
- [Authentication](authentication.md) — bearer setup on both producer and consumer
- [Architecture & Decisions](architecture.md) — `JobProxy` parking rationale
