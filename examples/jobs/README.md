# MeshJob Phase 1 Examples

Two minimal agents demonstrating the producer + consumer pattern for
long-running tasks with `MeshJob`.

## Layout

- `long-task-provider/main.py` — registers `generate_report` as a
  `task=True` tool. Hosts the producer-side `JobController` flow:
  progress updates, structured terminal results.
- `long-task-consumer/main.py` — registers `commission_report` which
  depends on `generate_report`. Demonstrates the consumer-side
  `MeshJobSubmitter.submit(...)` + `JobProxy.wait(...)` pattern.

## Quick start

In three terminals:

```bash
# Terminal 1 — registry
cd src/core/registry
go run ./cmd/registry

# Terminal 2 — provider (port 9100)
MCP_MESH_REGISTRY_URL=http://localhost:8000 \
  python3 examples/jobs/long-task-provider/main.py

# Terminal 3 — consumer (port 9101)
MCP_MESH_REGISTRY_URL=http://localhost:8000 \
  python3 examples/jobs/long-task-consumer/main.py
```

Then commission a report by calling the consumer's `commission_report`
tool — for example via `meshctl`:

```bash
meshctl call long-task-consumer commission_report \
  --arg user_id=demo --arg sections='["intro","analysis","summary"]'
```

You should see:

1. Consumer logs `📨 MESH_JOB_INJECTION: Injected MeshJobSubmitter`.
2. Consumer's `submit(...)` posts to `POST /jobs` on the registry.
3. Provider's claim worker (or the registry's owner-pinning if push-mode)
   picks up the job and dispatches to `generate_report`.
4. Provider emits progress updates (~6s total for the three sections).
5. Consumer's `wait(...)` returns the structured `report` payload.

## Inspecting in flight

While a job is running, hit any agent (or `meshctl`) for status:

```bash
meshctl call long-task-provider __mesh_job_status \
  --arg job_id=<uuid-from-submit>
```

The three framework helper tools are auto-registered on every mesh
agent — they read the registry directly, so any replica can serve
reads even if the job is "owned" by a different one.

## Cancelling

```bash
meshctl call long-task-provider __mesh_job_cancel \
  --arg job_id=<uuid> --arg reason="user requested abort"
```

The registry forwards the cancel to the owner replica via
`POST /jobs/{id}/cancel` (registered on every agent's FastAPI app),
which fires the in-process cancel token and aborts the in-flight job.

## Phase 2: Event injection (v2.2)

The event-channel extension added in v2.2 lets a running `task=True`
handler drain a per-job event log inline, and lets any caller
holding the `job_id` post events into that same log. Two more agents
demonstrate the pattern end-to-end:

- `event-aware-provider/main.py` — registers `event_aware_long_task`
  as `task=True`. Loops on `controller.recv_event(types=["work", "stop"])`,
  processing `work` events and exiting cleanly on `stop`.
- `event-aware-consumer/main.py` — registers `drive_event_aware_task`
  which depends on `event_aware_long_task`. Submits the job, spawns a
  background subscriber via `mesh.jobs.subscribe_events`, posts 3
  `work` events + 1 `stop` via `mesh.jobs.post_event`, then awaits
  the terminal result.

### Quick start (Phase 2)

Build the binary first if you haven't already: `make build` from the repo root.

```bash
# Terminal 1 — registry (same as Phase 1)
./bin/mcp-mesh-registry > /tmp/registry.log 2>&1 &

# Terminal 2 — event-aware provider (port 9102)
MCP_MESH_REGISTRY_URL=http://localhost:8000 \
  python3 examples/jobs/event-aware-provider/main.py

# Terminal 3 — event-aware consumer (port 9103)
MCP_MESH_REGISTRY_URL=http://localhost:8000 \
  python3 examples/jobs/event-aware-consumer/main.py
```

Drive the demo from a fourth terminal:

```bash
meshctl call event-aware-consumer drive_event_aware_task
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

The producer's `recv_event` consumed all 3 `work` events plus the
`stop` event (`processed=3, status=stopped`); the consumer-side
`subscribe_events` observer mirrored the same 3 `work` events with
its own independent cursor (`observed_count=3`).

For the full conceptual treatment of the event-channel surfaces —
the symmetry between `recv_event`/`post_event`/`send_event`, the
synthetic-cancel-event pattern, and the multi-cursor semantics — see
[`docs/concepts/jobs.md#event-injection`](../../docs/concepts/jobs.md#event-injection)
and [`#stream-subscription`](../../docs/concepts/jobs.md#stream-subscription).

## What's NOT in v2.2 yet

- Idempotency keys for retries (future).
- Resumable checkpoints (future).
- Webhook/SSE notifications (future).
- SPIRE-based caller-identity verification on `job_id` (future).

See `MESHJOB_DESIGN.org` at the repo root for the full roadmap.
