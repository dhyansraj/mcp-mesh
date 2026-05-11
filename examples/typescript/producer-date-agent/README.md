# producer-date-agent (TypeScript)

TypeScript A2A producer example (issue #933) — port of
`examples/a2a/date_a2a_agent.py` and
`examples/java/producer-date-agent`.

Exposes a `get-date` skill over the A2A v1.0 protocol surface using
`mesh.a2a.mount(app, ...)` on a user-owned Express app. The mount helper
wires both companion routes the A2A protocol requires:

| Route                                      | Purpose                                  |
| ------------------------------------------ | ---------------------------------------- |
| `GET  /agents/date/.well-known/agent.json` | Agent card (capabilities + skills)       |
| `POST /agents/date`                        | JSON-RPC `tasks/*` entry point           |

Sync handler: the user function returns a value; the framework wraps it
as an A2A v1.0 `Task` envelope with `state=completed`. Thrown exceptions
become `state=failed`.

The handler declares `date_service` as a mesh dependency — when the
registry resolves a provider (e.g.,
`examples/simple/system_agent.py`), the framework injects the
`McpMeshTool` proxy into the handler's `deps` argument keyed by
capability name (same shape as `mesh.route(...)`).

## Stack

1. Registry — `meshctl start --registry-only`
2. System agent (Python) — provides `date_service` on port 9100
3. This TS producer — exposes `get-date` via A2A on port 9090

## Run

```bash
# 1) Start the registry
meshctl start --registry-only -d

# 2) (optional) Start the system agent so the date_service dependency
#    resolves. If skipped, the handler returns a local-fallback ISO
#    timestamp — the example still runs solo.
python examples/simple/system_agent.py &

# 3) Start the producer
cd examples/typescript/producer-date-agent
npm install
npm start
```

## Test

```bash
# Card
curl -s http://localhost:9090/agents/date/.well-known/agent.json | jq

# JSON-RPC tasks/send
curl -s -X POST http://localhost:9090/agents/date \
     -H 'Content-Type: application/json' \
     -d '{"jsonrpc":"2.0","id":1,"method":"tasks/send",
          "params":{"id":"t1","message":{"role":"user",
          "parts":[{"type":"text","text":"now"}]}}}' | jq
```
