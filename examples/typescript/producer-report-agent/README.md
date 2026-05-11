# producer-report-agent (TypeScript)

TypeScript A2A producer example (long-running, issue #933) — port of
`examples/a2a/report_a2a_agent.py` and
`examples/java/producer-report-agent`.

Exposes a `generate-report` skill over the A2A v1.0 protocol surface
using `mesh.a2a.mount(app, ...)`. The handler returns a `JobProxy` to
switch the framework into long-running mode:

- `tasks/send` returns immediately with `state=working`
- `tasks/get` polls the parked task and returns the live state +
  progress
- `tasks/cancel` propagates through to the underlying mesh job
- `tasks/sendSubscribe` opens an SSE stream of
  `TaskStatusUpdateEvent` + `TaskArtifactUpdateEvent` envelopes per
  A2A v1.0
- `tasks/resubscribe` re-attaches an SSE stream to an in-flight task

## `MeshJobSubmitter` wiring

The dispatcher auto-injects `McpMeshTool` proxies into A2A handlers but
not `MeshJobSubmitter` (`task=true` deps inside A2A handlers are
currently a framework gap — same issue documented in the Java example).

This example constructs `MeshJobSubmitter` by hand from
`getApiRuntime().getServiceId()` (agent id) +
`process.env.MCP_MESH_REGISTRY_URL` (registry URL). Cheap to construct
and stateless after construction.

## Stack

1. Registry — `meshctl start --registry-only`
2. Long-task provider (Python) — provides `generate_report`
   (`task=true`) on port 9100
3. This TS producer — exposes `generate-report` via A2A on port 9091

## Run

```bash
# 1) Start the registry
meshctl start --registry-only -d

# 2) Start the upstream provider that actually does the work
python examples/jobs/long-task-provider/main.py &

# 3) Start the producer
cd examples/typescript/producer-report-agent
npm install
npm start
```

## Test

```bash
# Submit + poll
TASK_ID=$(curl -s -X POST http://localhost:9091/agents/report \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tasks/send",
       "params":{"id":"r1","message":{"role":"user",
       "parts":[{"type":"text",
       "text":"{\"user_id\":\"alice\",\"sections\":[\"intro\",\"body\"]}"}]}}}' \
  | jq -r '.result.id')

curl -s -X POST http://localhost:9091/agents/report \
  -H 'Content-Type: application/json' \
  -d "{\"jsonrpc\":\"2.0\",\"id\":2,\"method\":\"tasks/get\",\"params\":{\"id\":\"$TASK_ID\"}}" | jq

# Stream via SSE
curl -N -X POST http://localhost:9091/agents/report \
  -H 'Accept: text/event-stream' \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":3,"method":"tasks/sendSubscribe",
       "params":{"id":"s1","message":{"role":"user",
       "parts":[{"type":"text",
       "text":"{\"user_id\":\"alice\",\"sections\":[\"intro\",\"body\"]}"}]}}}'
```
