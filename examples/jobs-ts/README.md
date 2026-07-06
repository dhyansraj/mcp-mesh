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
  events and exiting cleanly on `stop`. The same file also registers
  `resumable_event_task`, a durable variant that adds
  `resumeCursor: true` (issue #1277) — see below.
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

### Durable cursor resume (`resumeCursor`, issue #1277)

By default a re-claimed task handler replays its event log from seq 0 —
correct for idempotent handlers, but wrong for one that accumulates
non-idempotent per-event state. The provider's second tool,
`resumable_event_task`, opts in:

```ts
agent.addTool({
  name: "resumable_event_task",
  capability: "resumable_event_task",
  task: true,
  resumeCursor: true,
  meshJobParamIndex: 1,
  execute: async (_args, controller) => { /* ... */ },
});
```

With `resumeCursor: true`, a handler re-claimed after a crash or reclaim
resumes `recvEvent` from the persisted per-filter cursor — it does not
replay already-consumed events, so its `total +=` accumulation is not
double-applied. Two rules the handler must honor to opt in safely:

- **Still design for at-least-once.** A bounded tail of already-processed
  events may replay on resume; keep per-event effects tolerant of a rare
  repeat (or fence on `event.seq`).
- **Consume strictly sequential-per-filter.** Process each event fully
  before the next `recvEvent`; never prefetch a batch or fan events out
  to concurrent workers — the persisted cursor only advances correctly
  for in-order, one-at-a-time draining.

Drive it exactly like the base task, targeting the `resumable_event_task`
capability instead.

## Typed supersession signal (`MeshSupersededError`, issue #1278)

`superseded-provider-ts/` + `superseded-consumer-ts/` port the calling-job
fencing pattern to TypeScript. A `task: true` writer job makes mutating
downstream calls; when it is superseded, the provider fences its writes and the
consumer unwinds with ONE `instanceof MeshSupersededError`.

Three moving parts:

1. **Calling-job identity is the decision input (#1263).** A `task: true`
   handler runs *as* a job, so every outbound mesh call carries its identity on
   the `x-mesh-calling-*` headers. The provider reads it with `callingJob()` →
   `CallingJob { jobId, claimEpoch }`.
2. **The app decides supersession; the framework does not.** `apply_write`
   remembers the highest `claimEpoch` accepted per `jobId` and rejects any call
   whose epoch is lower.
3. **The typed error is the one-catch unwind (#1278).** The provider rejects
   with `throw new MeshSupersededError(detail)` — on the wire the reserved
   `{"error":"claim_superseded","detail":...}` envelope. The caller's injected
   proxy re-throws `MeshSupersededError`, so the consumer wraps its whole write
   batch in ONE `catch (e) { if (e instanceof MeshSupersededError) ... }`
   instead of string-matching the marker after every call.

Distinct from `dependency_unavailable` (#1273): that means "capability
unreachable"; supersession means "you personally are stale". Both are typed
`UserError` subclasses so the contract, not the string, drives classification.

```bash
# Terminal 2 — provider (port 9114)
cd examples/jobs-ts/superseded-provider-ts && npm install
MCP_MESH_REGISTRY_URL=http://localhost:8000 npx tsx src/index.ts

# Terminal 3 — consumer (port 9115)
cd examples/jobs-ts/superseded-consumer-ts && npm install
MCP_MESH_REGISTRY_URL=http://localhost:8000 npx tsx src/index.ts
```

Then `meshctl call superseded-consumer-ts run_writer '{"count": 3}'`. See the
Python tree's README (`../jobs/README.md#typed-supersession-signal-supersedederror-issue-1278`)
for the full conceptual treatment.

## What's NOT in v2.2 yet

- Idempotency keys for retries (future).
- Resumable checkpoints (future).
- Webhook/SSE notifications (future).
- SPIRE-based caller-identity verification on `job_id` (future).
