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
  processing `work` events and exiting cleanly on `stop`. The same file
  also registers `resumable_event_task`, a durable variant that adds
  `resume_cursor=True` (issue #1277) — see below.
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

### Durable cursor resume (`resume_cursor`, issue #1277)

By default a re-claimed task handler replays its event log from seq 0 —
correct for idempotent handlers, but wrong for one that accumulates
non-idempotent per-event state. The provider's second tool,
`resumable_event_task`, opts in:

```python
@mesh.tool(capability="resumable_event_task", task=True, resume_cursor=True)
async def resumable_event_task(controller: MeshJob = None) -> dict:
    ...
```

With `resume_cursor=True`, a handler re-claimed after a crash or reclaim
resumes `recv_event` from the persisted per-filter cursor — it does not
replay already-consumed events, so its `total += amount` accumulation is
not double-applied. Two rules the handler must honor to opt in safely:

- **Still design for at-least-once.** A bounded tail of already-processed
  events may replay on resume; keep per-event effects tolerant of a rare
  repeat (or fence on `event["seq"]`).
- **Consume strictly sequential-per-filter.** Process each event fully
  before the next `recv_event`; never prefetch a batch or fan events out
  to concurrent workers — the persisted cursor only advances correctly
  for in-order, one-at-a-time draining.

Drive it exactly like the base task, targeting the `resumable_event_task`
capability instead.

## Typed supersession signal (`SupersededError`, issue #1278)

`superseded-provider/` + `superseded-consumer/` demonstrate how a job
executor's mutating downstream writes are fenced when the executor has been
superseded — and how the caller unwinds cleanly with ONE `except`.

### The problem

When a job is re-claimed (crash, reclaim, drain), a NEWER executor runs under a
HIGHER `claim_epoch`. The OLD executor may still be mid-flight and try to write.
Those stale writes must be rejected so the newer executor owns the outcome.

### The pattern (three moving parts)

1. **Calling-job identity is the decision input (#1263).** A `task=True`
   handler runs *as* a job, so every outbound mesh call it makes carries its
   identity on dedicated headers (`x-mesh-calling-job-id` /
   `x-mesh-calling-claim-epoch`). The provider reads it back with
   `mesh.calling_job()` → `CallingJob(job_id, claim_epoch)` — no need to thread
   identity through each payload.

2. **The app decides supersession; the framework does not.** The provider owns
   the "is this caller stale?" rule. In `apply_write` the authority remembers
   the highest `claim_epoch` it has accepted per `job_id` and rejects any call
   whose epoch is lower — a deterministic "an older executor is writing after a
   newer one already has" test. A real authority might consult the registry, a
   lease table, or a monotonic version column instead.

3. **The typed error is the one-catch unwind (#1278).** The provider rejects
   with `raise mesh.SupersededError(detail)`. On the wire that is the reserved
   app envelope `{"error":"claim_superseded","detail":...}`. The caller's
   injected proxy recognizes that envelope and re-raises `mesh.SupersededError`
   on the calling side — so the consumer wraps its whole write batch in ONE
   `except mesh.SupersededError` instead of string-matching the marker after
   every call:

   ```python
   try:
       for entry in entries:
           await apply_write(entry=entry)   # any call may be fenced
   except mesh.SupersededError as e:
       return {"status": "superseded", "detail": e.detail}   # one unwind
   ```

   The OLD pattern this replaces re-checked `result.get("error") ==
   "claim_superseded"` at every call site — brittle and easy to forget.

### Distinct from `dependency_unavailable` (#1273)

`dependency_unavailable` means "the capability isn't reachable"; supersession
means "you personally are stale — a newer you is authoritative". Both are typed
so the CONTRACT (the reserved envelope), not the error string, drives
classification; both raise a `ToolError` subclass, so `except ToolError` still
catches either.

### Quick start

```bash
# Terminal 1 — registry
./bin/mcp-mesh-registry > /tmp/registry.log 2>&1 &

# Terminal 2 — provider (port 9104)
MCP_MESH_REGISTRY_URL=http://localhost:8000 \
  python3 examples/jobs/superseded-provider/main.py

# Terminal 3 — consumer (port 9105)
MCP_MESH_REGISTRY_URL=http://localhost:8000 \
  python3 examples/jobs/superseded-consumer/main.py
```

Kick off a writer job:

```bash
meshctl call superseded-consumer run_writer '{"count": 3}'
```

A single, uncontested run returns `{"status": "completed", ...}` — the
authority sees a monotonic epoch and accepts every write. The fence fires when
a LOWER-epoch executor writes after a higher one has been recorded for the same
`job_id` (the reclaim scenario): the provider raises `SupersededError`, the
consumer catches it once, and returns `{"status": "superseded", ...}`.

The TypeScript (`../jobs-ts/`) and Java (`../jobs-java/`) trees carry the same
pair with `MeshSupersededError` / `MeshSupersededException`.

## What's NOT in v2.2 yet

- Idempotency keys for retries (future).
- Resumable checkpoints (future).
- Webhook/SSE notifications (future).
- SPIRE-based caller-identity verification on `job_id` (future).

See `MESHJOB_DESIGN.org` at the repo root for the full roadmap.
