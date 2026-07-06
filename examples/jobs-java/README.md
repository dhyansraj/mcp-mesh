# MeshJob Phase B Examples (Java)

Two minimal Spring Boot agents demonstrating the producer + consumer
pattern for long-running tasks with `MeshJob` on the Java SDK. Mirrors:

- `examples/jobs/` — Python equivalents
- `examples/jobs-ts/` — TypeScript equivalents

## Layout

- `long-task-provider-java/` — registers `generate_report` as a
  `task=true` tool. Hosts the producer-side `JobController` flow:
  progress updates, structured terminal results.
- `long-task-consumer-java/` — registers `commission_report` which
  depends on `generate_report`. Demonstrates the consumer-side
  `MeshJobSubmitter.submit(...)` + `JobProxy.await(...)` pattern.

## Quick start

In three terminals:

```bash
# Terminal 1 — registry
cd cmd/mcp-mesh-registry && go run .

# Terminal 2 — Java provider (port 9120)
cd examples/jobs-java/long-task-provider-java
MCP_MESH_REGISTRY_URL=http://localhost:8000 mvn spring-boot:run

# Terminal 3 — Java consumer (port 9121)
cd examples/jobs-java/long-task-consumer-java
MCP_MESH_REGISTRY_URL=http://localhost:8000 mvn spring-boot:run
```

Then commission a report by calling the consumer's `commission_report`
tool — for example via `meshctl`:

```bash
meshctl call --timeout 60 long-task-consumer-java:commission_report \
  '{"user_id":"demo","sections":["intro","analysis","summary"]}'
```

You should see:

1. Consumer logs the `MeshJob consumer wired` startup line.
2. Consumer's `submit(...)` posts to `POST /jobs` on the registry.
3. Provider's claim worker (or the registry's owner-pinning if push-mode)
   picks up the job and dispatches to `generate_report`.
4. Provider emits progress updates (~6s total for the three sections).
5. Consumer's `await(...)` returns the structured `report` payload.

## Inspecting in flight

While a job is running, hit any agent for status:

```bash
meshctl call long-task-provider-java:__mesh_job_status \
  '{"job_id":"<uuid-from-submit>"}'
```

The three framework helper tools (`__mesh_job_status`,
`__mesh_job_result`, `__mesh_job_cancel`) are auto-registered on every
mesh agent — they read the registry directly, so any replica can serve
reads even if the job is "owned" by a different one.

## Cancelling

```bash
meshctl call long-task-provider-java:__mesh_job_cancel \
  '{"job_id":"<uuid>","reason":"user requested abort"}'
```

The registry forwards the cancel to the owner replica via
`POST /jobs/{id}/cancel` (registered on every Java mesh agent's MVC
controller stack), which fires the in-process cancel token and aborts
the in-flight job.

## Phase 2: Event injection (v2.2)

The event-channel extension added in v2.2 lets a running `task=true`
handler drain a per-job event log inline, and lets any caller
holding the `jobId` post events into that same log. Two more agents
demonstrate the pattern end-to-end:

- `event-aware-provider-java/` — registers `event_aware_long_task`
  as `task=true`. Loops on
  `controller.recvEvent(List.of("work", "stop"), Duration.ofSeconds(30))`,
  processing `work` events and exiting cleanly on `stop`. The same class
  also registers `resumable_event_task`, a durable variant that adds
  `resumeCursor = true` (issue #1277) — see below.
- `event-aware-consumer-java/` — registers `drive_event_aware_task`
  which depends on `event_aware_long_task`. Submits the job, walks an
  `EventSubscription` on a daemon thread, posts 3 `work` events + 1
  `stop` via `MeshJobs.postEvent`, then awaits the terminal result.

Java has no async/await, so the subscriber runs on a separate daemon
thread joined back on the main thread with a bounded timeout. The
`EventSubscription` iterator is wrapped in try-with-resources so its
"keep polling" flag flips deterministically on exit.

### Quick start (Phase 2)

Build the binary first if you haven't already: `make build` from the repo root.

```bash
# Terminal 1 — registry (same as Phase 1)
./bin/mcp-mesh-registry > /tmp/registry.log 2>&1 &

# Terminal 2 — event-aware provider (port 9122)
cd examples/jobs-java/event-aware-provider-java
MCP_MESH_REGISTRY_URL=http://localhost:8000 mvn spring-boot:run

# Terminal 3 — event-aware consumer (port 9123)
cd examples/jobs-java/event-aware-consumer-java
MCP_MESH_REGISTRY_URL=http://localhost:8000 mvn spring-boot:run
```

Drive the demo from a fourth terminal:

```bash
meshctl call --timeout 60 event-aware-consumer-java:drive_event_aware_task '{}'
```

Expected output shape:

```json
{
  "job_id": "01HXY...",
  "posted_seqs": [1, 2, 3],
  "subscriber_status": "ok",
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
`EventSubscription` observer mirrored the same 3 `work` events with
its own independent cursor (`observed_count: 3`).

For the full conceptual treatment of the event-channel surfaces, see
[`docs/concepts/jobs.md#event-injection`](../../docs/concepts/jobs.md#event-injection)
and [`#stream-subscription`](../../docs/concepts/jobs.md#stream-subscription).

### Durable cursor resume (`resumeCursor`, issue #1277)

By default a re-claimed task handler replays its event log from seq 0 —
correct for idempotent handlers, but wrong for one that accumulates
non-idempotent per-event state. The provider's second tool,
`resumable_event_task`, opts in:

```java
@MeshTool(capability = "resumable_event_task", task = true, resumeCursor = true)
public Map<String, Object> resumableEventTask(MeshJob job) {
    // ...
}
```

With `resumeCursor = true`, a handler re-claimed after a crash or reclaim
resumes `recvEvent` from the persisted per-filter cursor — it does not
replay already-consumed events, so its `total += amount` accumulation is
not double-applied. Two rules the handler must honor to opt in safely:

- **Still design for at-least-once.** A bounded tail of already-processed
  events may replay on resume; keep per-event effects tolerant of a rare
  repeat (or fence on `event.get("seq")`).
- **Consume strictly sequential-per-filter.** Process each event fully
  before the next `recvEvent`; never prefetch a batch or fan events out
  to concurrent workers — the persisted cursor only advances correctly
  for in-order, one-at-a-time draining.

Drive it exactly like the base task, targeting the `resumable_event_task`
capability instead.

## Typed supersession signal (`MeshSupersededException`, issue #1278)

`superseded-provider-java/` + `superseded-consumer-java/` port the calling-job
fencing pattern to Java. A `task = true` writer job makes mutating downstream
calls; when it is superseded, the provider fences its writes and the consumer
unwinds with ONE `catch (MeshSupersededException)`.

Three moving parts:

1. **Calling-job identity is the decision input (#1263).** A `task = true`
   handler runs *as* a job, so every outbound mesh call carries its identity on
   the `x-mesh-calling-*` headers. The provider reads it with
   `MeshCallContext.callingJob()` → `CallingJob(jobId, claimEpoch)`.
2. **The app decides supersession; the framework does not.** `applyWrite`
   remembers the highest `claimEpoch` accepted per `jobId` and rejects any call
   whose epoch is lower.
3. **The typed error is the one-catch unwind (#1278).** The provider rejects
   with `throw new MeshSupersededException(detail)` — on the wire the reserved
   `{"error":"claim_superseded","detail":...}` envelope. The caller's injected
   proxy re-throws `MeshSupersededException`, so the consumer wraps its whole
   write batch in ONE `catch (MeshSupersededException e)` instead of
   string-matching the marker after every call.

Distinct from `dependency_unavailable` (#1273): that means "capability
unreachable"; supersession means "you personally are stale". Both are typed so
the contract (the reserved envelope), not the error string, drives
classification.

```bash
# Build the SDK first if you haven't: (cd src/runtime/java && mvn install -DskipTests)

# Terminal 2 — provider (port 9124)
cd examples/jobs-java/superseded-provider-java
MCP_MESH_REGISTRY_URL=http://localhost:8000 mvn spring-boot:run

# Terminal 3 — consumer (port 9125)
cd examples/jobs-java/superseded-consumer-java
MCP_MESH_REGISTRY_URL=http://localhost:8000 mvn spring-boot:run
```

Then `meshctl call superseded-consumer-java run_writer --arg count=3`. See the
Python tree's README (`../jobs/README.md#typed-supersession-signal-supersedederror-issue-1278`)
for the full conceptual treatment.

## What's NOT in v2.2 yet

- Idempotency keys for retries (future).
- Resumable checkpoints (future).
- Webhook/SSE notifications (future).
- SPIRE-based caller-identity verification on `job_id` (future).

See `MESHJOB_DESIGN.org` at the repo root for the full roadmap.
