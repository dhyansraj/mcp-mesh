# MeshJob Phase 1 — TypeScript Examples

TypeScript port of `examples/jobs/`. Two minimal agents demonstrating
the producer + consumer pattern for long-running tasks with `MeshJob`.

## Layout

- `long-task-provider-ts/index.ts` — registers `generate_report` as a
  `task: true` tool. Hosts the producer-side `JobController` flow:
  progress updates and structured terminal results.
- `long-task-consumer-ts/index.ts` — registers `commission_report`
  which depends on `generate_report` (with `meshJobDepIndex: 0` so the
  dep slot holds a `MeshJobSubmitter` instead of a regular proxy).
  Demonstrates the consumer-side `submit(...)` + `proxy.wait(...)`
  pattern.

## Quick start

```bash
# Install (once per example)
cd examples/jobs-ts/long-task-provider-ts && npm install
cd ../long-task-consumer-ts && npm install
```

In three terminals:

```bash
# Terminal 1 — registry
go run ./cmd/mcp-mesh-registry

# Terminal 2 — provider (port 9110)
MCP_MESH_REGISTRY_URL=http://localhost:8000 \
  npx tsx examples/jobs-ts/long-task-provider-ts/index.ts

# Terminal 3 — consumer (port 9111)
MCP_MESH_REGISTRY_URL=http://localhost:8000 \
  npx tsx examples/jobs-ts/long-task-consumer-ts/index.ts
```

Then commission a report by calling the consumer's `commission_report`
tool:

```bash
meshctl call long-task-consumer-ts:commission_report \
  '{"user_id": "demo", "sections": ["intro", "analysis", "summary"]}'
```

Expected flow:

1. Consumer's `submit(...)` posts to `POST /jobs` on the registry.
2. Provider's claim worker picks up the job and dispatches it to
   `generate_report` with a `JobController` injected at `meshJobParamIndex`.
3. Provider emits progress updates (~6s total for the three sections).
4. Consumer's `wait(...)` returns the structured `report` payload.

## Inspecting in flight

While a job is running, hit any agent for status — the helper tools
auto-register on every TS mesh agent:

```bash
meshctl call long-task-provider-ts:__mesh_job_status \
  '{"jobId": "<uuid-from-submit>"}'
```

The three framework helpers (`__mesh_job_status` / `__mesh_job_result`
/ `__mesh_job_cancel`) read directly from the registry, so any replica
can serve the request.

## Phase 2: Event injection (v2.2)

The event-channel extension added in v2.2 lets a running `task: true`
handler drain a per-job event log inline, and lets any caller
holding the `jobId` post events into that same log. Two more agents
demonstrate the pattern end-to-end:

- `event-aware-provider-ts/src/index.ts` — registers
  `event_aware_long_task` as `task: true`. Loops on
  `controller.recvEvent(["work", "stop"], 30)`, processing `work`
  events and exiting cleanly on `stop`.
- `event-aware-consumer-ts/src/index.ts` — registers
  `drive_event_aware_task` which depends on `event_aware_long_task`.
  Submits the job, runs a `for await` subscriber via
  `mesh.jobs.subscribeEvents`, posts 3 `work` events + 1 `stop` via
  `mesh.jobs.postEvent`, then awaits the terminal result.

### Quick start (Phase 2)

```bash
# Install (once per example)
cd examples/jobs-ts/event-aware-provider-ts && npm install
cd ../event-aware-consumer-ts && npm install
```

Build the binary first if you haven't already: `make build` from the repo root.

```bash
# Terminal 1 — registry (same as Phase 1)
./bin/mcp-mesh-registry > /tmp/registry.log 2>&1 &

# Terminal 2 — event-aware provider (port 9112)
MCP_MESH_REGISTRY_URL=http://localhost:8000 \
  npx tsx examples/jobs-ts/event-aware-provider-ts/src/index.ts

# Terminal 3 — event-aware consumer (port 9113)
MCP_MESH_REGISTRY_URL=http://localhost:8000 \
  npx tsx examples/jobs-ts/event-aware-consumer-ts/src/index.ts
```

Drive the demo from a fourth terminal:

```bash
meshctl call event-aware-consumer-ts:drive_event_aware_task '{}'
```

Expected output shape:

```json
{
  "job_id": "01HXY...",
  "posted_seqs": [1, 2, 3],
  "observed_count": 3,
  "observed_events": [
    {"seq": 1, "payload": {"item": 1}},
    {"seq": 2, "payload": {"item": 2}},
    {"seq": 3, "payload": {"item": 3}}
  ],
  "result": {"processed": 3, "status": "stopped"}
}
```

The producer's `recvEvent` consumed all 3 `work` events plus the
`stop` event (`processed: 3, status: "stopped"`); the consumer-side
`subscribeEvents` observer mirrored the same 3 `work` events with
its own independent cursor (`observed_count: 3`).

For the full conceptual treatment of the event-channel surfaces, see
[`docs/concepts/jobs.md#event-injection`](../../docs/concepts/jobs.md#event-injection)
and [`#stream-subscription`](../../docs/concepts/jobs.md#stream-subscription).

## What's NOT in v2.2 yet

- Idempotency keys for retries (future).
- Resumable checkpoints (future).
- Webhook/SSE notifications (future).
- SPIRE-based caller-identity verification on `job_id` (future).
