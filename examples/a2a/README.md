# A2A Surface Example — `date-a2a-agent`

A minimal agent that exposes the existing `examples/simple/system_agent`
`date_service` capability via the A2A v1.0 protocol surface using the new
user-controlled mounting pattern:

```python
from fastapi import FastAPI
import mesh
from mesh.types import McpMeshTool

app = FastAPI()  # ← user owns the app

@mesh.a2a.mount(
    app,
    path="/agents/date",
    dependencies=["date_service"],
    skill_id="get-date",
    skill_name="Get Date",
    tags=["system", "date"],
)
async def date_a2a(payload: dict, date_service: McpMeshTool = None):
    return {"date": await date_service()}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=9090)
```

`mesh.a2a.mount()` mirrors the `@mesh.route` UX — the user owns both the
FastAPI app AND the uvicorn lifecycle, and the mesh runtime drives
dependency injection + registry registration on top:

| Concern | Handled by |
|---|---|
| Owning the FastAPI app | **You** (`app = FastAPI()`) |
| Running the HTTP server | **You** (`uvicorn.run(app, ...)` in `__main__`) |
| DI dependency resolution | `mesh.a2a.mount(...)` (same machinery as `@mesh.route`) |
| `GET /…/.well-known/agent.json` (agent card) | `mesh.a2a.mount(...)` (auto-mounted) |
| `POST /…` (JSON-RPC tasks/* entry) | `mesh.a2a.mount(...)` (auto-mounted) |
| Heartbeat → registry registration (`agent_type=a2a` + surfaces) | mesh runtime |

There is no `@mesh.agent` here — the `a2a_startup` pipeline (NOT
`api_startup`) detects `@mesh.a2a` markers in the `DecoratorRegistry`
and emits an `agent_type=a2a` heartbeat to the registry. The
`api_startup` pipeline is exclusively for `@mesh.route`-decorated
services. See `_mcp_mesh/pipeline/a2a_startup/` and
`_mcp_mesh/pipeline/api_startup/` for the two independent pipeline
modules.

## Prereqs

You'll want three terminals:

```bash
# Terminal 1: Registry
meshctl start registry

# Terminal 2: Provider — exposes date_service
python examples/simple/system_agent.py

# Terminal 3: This A2A agent (user-driven uvicorn)
python examples/a2a/date_a2a_agent.py
```

## Test the A2A surface

### Agent card

```bash
curl http://localhost:9090/agents/date/.well-known/agent.json | jq
```

Expected (abbreviated):

```json
{
  "name": "date-a2a-agent",
  "description": "date-a2a-agent",
  "version": "1.0.0",
  "capabilities": {
    "streaming": false,
    "pushNotifications": false,
    "stateTransitionHistory": false
  },
  "defaultInputModes": ["application/json"],
  "defaultOutputModes": ["application/json"],
  "skills": [
    {
      "id": "get-date",
      "name": "Get Date",
      "description": "Get current date/time via A2A protocol",
      "tags": ["system", "date"],
      "inputModes": ["application/json"],
      "outputModes": ["application/json"]
    }
  ],
  "url": "http://localhost:9090/agents/date",
  "authentication": { "schemes": [] }
}
```

### JSON-RPC `tasks/send` (Phase 2: dispatches into handler)

```bash
curl -X POST http://localhost:9090/agents/date \
     -H 'Content-Type: application/json' \
     -d '{"jsonrpc":"2.0","id":1,"method":"tasks/send","params":{"id":"t1","message":{"role":"user","parts":[]}}}'
```

Expected (sync handler dispatch — A2A v1.0 `Task` envelope):

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "id": "t1",
    "sessionId": "t1",
    "status": {
      "state": "completed",
      "timestamp": "2026-05-09T12:34:56.789Z"
    },
    "artifacts": [
      {
        "name": "result",
        "parts": [
          {"type": "text", "text": "{\"date\": \"2026-05-09T12:34:56Z\"}"}
        ],
        "index": 0
      }
    ],
    "history": [
      {"role": "user", "parts": []}
    ]
  }
}
```

The handler return value (e.g. `{"date": "..."}`) is JSON-stringified into
the single artifact's `text` part. String returns are used verbatim. If the
handler raises, the response is still a JSON-RPC `result` but with
`status.state = "failed"` and the exception text under
`status.message.parts[0].text` — per A2A v1.0, handler failures are Task
failures, not JSON-RPC errors.

### Other `tasks/*` methods (Phase 3 territory)

`tasks/get`, `tasks/cancel`, `tasks/sendSubscribe`, and `tasks/send` for
underlying tools decorated with `@mesh.tool(task=True)` still return
`-32601 Method not implemented`. Those land in Phase 3 once the MeshJob
lifecycle is wired into the long-running task envelope.

## Public URL stamping

The agent card's `url` field reflects how external clients reach the
JSON-RPC entry point. There are two paths:

1. **Registry-stamped (production):** Set
   `MCP_MESH_PUBLIC_URL_PREFIX=https://agents.acme.com` on the registry.
   On each heartbeat, the registry returns
   `surfaces[].public_url = https://agents.acme.com/agents/date`, which
   is cached in the agent process and surfaced on the card.
2. **Local fallback (dev/CI):** When the cache is empty (first request
   before the first heartbeat round-trip, or the env var is unset), the
   card falls back to `http://{http_host}:{http_port}{path}` — e.g.
   `http://localhost:9090/agents/date`.

## Authentication (`auth="bearer"`)

Add `auth="bearer"` to `mesh.a2a.mount(...)` to enforce header-presence
checks on the JSON-RPC entry. Phase 1 only verifies the
`Authorization: Bearer <token>` header is present and well-formed — token
validation (signature/issuer/audience) is Phase-2+ scope. Requests
missing the header receive a `401` with a JSON-RPC-shaped error envelope
(`code: -32001`).

## Where to read the design

- `A2A_SURFACE_DESIGN.org` — full design doc with phasing rationale
- `mesh/a2a.py` — Python helper module (`mount`, public-URL cache,
  card/RPC endpoint builders)
- `mesh/decorators.py` — bare `@mesh.a2a` decorator (DI + metadata only)
- `_mcp_mesh/engine/a2a_surfaces.py` — shared registry-shape collector
  used by all three heartbeat paths (mcp_startup Python, mcp_startup
  Rust, api_startup Rust)
