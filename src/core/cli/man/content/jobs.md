# Long-Running Jobs (MeshJob)

> DDDI-native primitive for tasks that outlast a `tools/call` request — submit, await, cancel, retry_on

## Why MeshJob

`tools/call` is fine for sub-second to ~30s work. For anything longer (multi-section reports, video transcoding, long agentic loops), the consumer's HTTP socket is at the mercy of every load balancer, ingress, and pod restart between the two agents.

**MeshJob** is the durable alternative:

- Producer declares `task=True` on the tool — the SDK runs it under a
  registry-backed claim/lease, with progress updates and explicit
  `complete()` / `fail()` terminal states.
- Consumer types a dependency parameter as `MeshJob` — DDDI swaps the
  usual `McpMeshTool` proxy for a `MeshJobSubmitter` at that slot.
- `submitter.submit(...)` posts to `POST /jobs` and returns a
  `JobProxy` bound to the new job id. `proxy.wait(...)` polls
  `GET /jobs/{id}` until terminal.

Plain `task=False` tools continue to be buffered request-response — no
behavior change for non-job tools.

## Cheat sheet

| Surface                    | Producer                          | Consumer                                |
| -------------------------- | --------------------------------- | --------------------------------------- |
| Decorator flag             | `@mesh.tool(task=True, ...)`      | (regular `@mesh.tool` w/ dependency)    |
| Injected type              | `job: MeshJob = None`             | `<dep_name>: MeshJob = None`            |
| Concrete injection         | `JobController` (or `None`)       | `MeshJobSubmitter`                      |
| Progress                   | `await job.update_progress(f, m)` | (read via `__mesh_job_status`)          |
| Request input              | `await job.request_input(prompt)` | (status → `input_required`; answer via `post_event`) |
| Terminal success           | `await job.complete(payload)`     | `await proxy.wait(timeout_secs=N)`      |
| Terminal failure           | `await job.fail(reason)`          | `wait()` raises                         |
| Transient retry            | `raise OSError(...)` w/ `retry_on=(OSError,)` | (registry hands to peer in ~5s) |
| Cancel                     | (cancel token fires in handler)   | `await proxy.cancel(reason)`            |

## Producer: `@mesh.tool(task=True)`

```python
import asyncio
import mesh
from fastmcp import FastMCP
from mesh import MeshJob

app = FastMCP("Long Task Provider")


@app.tool()
@mesh.tool(
    capability="generate_report",
    task=True,                              # opts the tool into MeshJob
    description="Long-running report generator",
)
async def generate_report(
    user_id: str,
    sections: list[str],
    job: MeshJob = None,                    # auto-injected by signature scan
) -> dict:
    if job is not None:
        await job.update_progress(0.0, "starting")

    results = []
    total = max(len(sections), 1)
    for i, section in enumerate(sections):
        await asyncio.sleep(2)              # simulate work
        results.append({"section": section, "content": f"...{section}"})
        if job is not None:
            await job.update_progress(
                (i + 1) / total,
                f"finished section {i+1}/{total}",
            )

    payload = {"user_id": user_id, "report": results}
    if job is not None:
        await job.complete(payload)         # explicit terminal flush
    return payload


@mesh.agent(name="long-task-provider", http_port=9100, auto_run=True)
class LongTaskProvider:
    pass
```

**Notes:**

- `job: MeshJob = None` lands at the parameter position the SDK detects
  by type annotation. It is `None` when the tool is invoked via a
  regular `tools/call` (no `X-Mesh-Job-Id` header) — the function then
  runs the fast path and just returns its result.
- `complete()` / `fail()` flush past the batching tick immediately, so
  the consumer's `wait(...)` sees the terminal state without latency.
- `update_progress(fraction, message)` is batched to avoid hammering
  the registry. For token-by-token feedback, see `meshctl man streaming`.

## Consumer: `MeshJob`-typed dependency

```python
import mesh
from fastmcp import FastMCP
from mesh import MeshJob

app = FastMCP("Long Task Consumer")


@app.tool()
@mesh.tool(
    capability="commission_report",
    # Param NAME must match the dependency capability — that pairing is
    # what makes the slot a MeshJobSubmitter (instead of an McpMeshTool).
    dependencies=["generate_report"],
)
async def commission_report(
    user_id: str,
    sections: list[str],
    generate_report: MeshJob = None,        # injected MeshJobSubmitter
) -> dict:
    proxy = await generate_report.submit(
        user_id=user_id,
        sections=sections,
        max_duration=60,                    # per-attempt soft timeout (seconds)
    )
    return await proxy.wait(timeout_secs=60)
```

**Notes:**

- The SDK swaps `McpMeshTool` for `MeshJobSubmitter` at the slot
  whose param name matches a dependency that points at a `task=True`
  capability. Same DDDI lookup pipeline (resolution, trust, tags) —
  only the proxy class differs.
- `wait(timeout_secs=N)` returns the producer's `complete()` payload
  on success; raises `JobFailedError`, `JobCancelledError`, or
  `JobTimeoutError` on the other terminal states.

## `submit(...)` options

| Keyword            | Type             | Purpose                                                 |
| ------------------ | ---------------- | ------------------------------------------------------- |
| `**args`           | per-tool         | Forwarded as the tool's input arguments                 |
| `max_duration`     | `int` (seconds)  | Per-attempt soft timeout; also sizes the lease window and floors the stale ceiling |
| `max_retries`      | `int`            | Retries beyond initial attempt (Sidekiq convention)     |
| `total_deadline`   | `int` (seconds)  | Hard ceiling across all attempts (registry enforces)    |
| `owner_instance_id`| `str`            | Pin to a specific replica (rarely needed)               |

## `retry_on` (per-tool exception whitelist)

`retry_on` is a tuple of exception classes that should be treated as
transient. When the handler raises a matching exception, the SDK calls
`release_lease(reason)` instead of `fail(reason)` — the registry
resets the owner and a peer replica re-runs the handler within ~5
seconds. Anything **not** in `retry_on` still goes through `fail()`
and surfaces to the consumer immediately.

```python
@app.tool()
@mesh.tool(
    capability="report_with_transient_failures",
    task=True,
    retry_on=(OSError,),                    # tuple of Exception subclasses
)
async def report_with_transient_failures(
    user_id: str,
    transient_failures: int = 2,
    job: MeshJob = None,
) -> dict:
    n = _bump_retry_counter()
    if n <= transient_failures:
        # SDK matches retry_on=(OSError,) → release_lease(), NOT fail().
        # The registry hands the job to a peer (or this replica's next
        # claim cycle) within ~5 seconds.
        raise OSError(f"simulated transient failure {n}/{transient_failures}")

    payload = {"user_id": user_id, "succeeded_on_attempt": n}
    if job is not None:
        await job.complete(payload)
    return payload
```

**Validation:**

- `retry_on` requires `task=True` — registration fails at agent boot
  otherwise. Same for non-`Exception` entries (strings, instances, etc).
- Misuse surfaces at startup, not at retry time.

**Combining with `max_retries`:**

```python
# Caller-side: at most 4 total attempts (1 initial + 3 retries)
proxy = await generate_report.submit(
    user_id="alice",
    sections=["intro"],
    max_duration=30,
    max_retries=3,
)
```

**`max_retries` does NOT soften a real failure.** A handler exception
that is **not** matched by `retry_on` — and any explicit `fail()` — is
**terminal immediately**, no matter how much of the `max_retries` budget
is unspent. That budget covers only crash-style recoveries the runtime
retries on your behalf: lease expiry, orphan reclaim, `max_duration`
timeout, plus `retry_on`-matched releases. So a job that shows
`attempt_count: 1` with `max_retries: 3` after a non-transient error has
**zero** retries left — not two — it already reached its terminal
`failed` state on that first attempt.

Retries restart the handler from scratch — there are no idempotency
keys in v2.x. If the handler has external side effects, design for
at-least-once: deterministic ids the downstream can dedupe on, or a
"claim → check → execute → mark done" pattern keyed off `job_id`.

## Cancellation

```python
# Consumer-side: cancel an in-flight job
await proxy.cancel(reason="user requested abort")
```

The registry forwards the cancel to the owner replica via
`POST /jobs/{id}/cancel` (auto-registered on every agent's FastAPI
app). On the producer side, the in-process cancel token fires:

- `asyncio.CancelledError` is raised at the next `await` point in the
  handler.
- Outbound `McpMeshTool` proxy calls abort their underlying HTTP
  request (cancel propagates through `X-Mesh-Job-Id` header binding).

The registry treats cancel as terminal (idempotent — already-terminal
jobs return ok without re-firing).

## Event injection

Per-job append-only event log every running job carries. Anyone with
the `job_id` writes; the running handler drains.

**Inside a `task=True` handler — receive events:**

```python
event = await job.recv_event(
    types=["user_input", "cancelled"],
    timeout_secs=10.0,
)
# event is dict with {seq, type, payload, ...}, or None on timeout.
if event is None:
    pass  # nothing arrived within timeout
elif event["type"] == "cancelled":
    return {"status": "cancelled", "reason": event["payload"].get("reason")}
```

Each distinct `types` filter is an **independent event stream** with its
own cursor, so interleaving `recv_event(types=["A"])` and
`recv_event(types=["B"])` never lets one filter's consumption skip the
other's earlier events. Delivery is **exactly-once within a filter stream**
and **at-least-once across different filters** (an event matching two
filters can surface once per stream).

By default the per-filter cursor starts at the beginning of the log on every
(re-)claim — a re-claimed handler **replays from `seq=0`**. That is the safe
default for idempotent or cheap-to-recompute handlers.

**`resume_cursor=True` — durable resume.** A `task=True` tool can opt into a
durable cursor so a re-claimed handler resumes **after** the last processed
event instead of replaying from the start:

```python
@app.tool()
@mesh.tool(capability="run_workflow", task=True, resume_cursor=True)
async def run_workflow(job: mesh.MeshJob = None) -> dict:
    while True:
        event = await job.recv_event(types=["user_input"], timeout_secs=10.0)
        if event is None:
            continue
        # ...process event sequentially, then loop to request the next one...
```

The framework persists each per-filter cursor on the job row via the normal
epoch-fenced delta flush; on re-claim the new controller resumes past the
persisted seqs. It stays **at-least-once**: a crash replays only the
un-flushed tail — a small, bounded replay of the most recent events — never
the whole log. Design for at-least-once, not exactly-once.

**Contract — durable resume requires sequential per-filter consumption.** The
cursor advances when the handler requests the *next* event of a filter; that
`recv_event` call is treated as proof the prior event finished
(commit-on-poll, Kafka-style). A handler that **prefetches** or processes a
filter's events **concurrently** (recv → spawn async → recv again before the
first finished) must **not** set `resume_cursor=True` — resume would skip the
still-in-flight event. If you pipeline a filter, stay on the replay-from-`0`
default (or checkpoint yourself).

**Outside the handler, with a `job_id` in scope — fire an event:**

```python
import mesh

@app.tool()
@mesh.tool(capability="submit_user_input")
async def submit_user_input(job_id: str, text: str) -> dict:
    receipt = await mesh.jobs.post_event(
        job_id, "user_input", {"text": text},
    )
    return {"seq": receipt["seq"]}
```

`mesh.jobs.post_event` is the canonical fire-and-forget. It resolves
the registry from `MCP_MESH_REGISTRY_URL` and reuses a process-cached
`JobProxy` from a bounded LRU keyed by `(registry_url, job_id)`
(default cap 256; tune via `MCP_MESH_JOBPROXY_CACHE_MAX`). If the
calling code already holds a `JobProxy`, use `proxy.send_event(
event_type, payload)` directly — same wire shape, skip the helper.

**Lifecycle facades by `job_id`.** Same DDDI-clean pattern as
`post_event` — module-level helpers that take a `job_id` and dispatch
through the shared proxy cache, for callers that don't hold a
`JobProxy` reference:

```python
# Cancel a running job (idempotent — already-terminal jobs return ok)
await mesh.jobs.cancel(job_id, reason="user requested abort")

# Read latest job state (dict — registry Job row, field-for-field)
snapshot = await mesh.jobs.status(job_id)
# snapshot["status"] ∈ {"working","input_required","completed","failed","cancelled"}

# Wait for terminal state and return the result payload
result = await mesh.jobs.wait(job_id, timeout_secs=300.0)
```

`wait` raises `TimeoutError` on `timeout_secs` expiry; pass `None`
(default) to wait until the job reaches a terminal state. All three
raise `JobNotFoundError` if the registry has reaped the job.

**Typed errors** (both subclass `RuntimeError` for back-compat):

- `mesh.JobNotFoundError` — job swept or id typo
- `mesh.JobTerminalError` — job already terminal, no more events accepted

**Synthetic cancel event**. When a consumer calls `proxy.cancel(
reason)`, the registry writes a synthetic
`{"type": "cancelled", "payload": {"reason": "..."}}` event into the
log before forwarding the cancel signal. A handler parked on
`recv_event(types=["cancelled", ...])` observes it and can return
cleanly instead of being interrupted by `CancelledError`. The
registry waits a small grace window before issuing the cancel-forward
(default 200ms, tunable via `MCP_MESH_CANCEL_EVENT_GRACE_MS`, capped
at 10s) so the synthetic event lands before the cancel token fires.

**Synthetic stale event**. When the registry reaps a job for exceeding
the `MCP_MESH_JOB_STALE_TIMEOUT` default ceiling (see **Reaping and
lease recovery**), it writes a synthetic
`{"type": "stale", "payload": {"reason": "stale", "detail": "..."}}`
event into the log as it transitions the job to `failed`. A handler
parked on `recv_event(types=["stale", ...])` observes the reaping and
can unwind cleanly:

```python
event = await job.recv_event(types=["stale", "cancelled"], timeout_secs=30.0)
if event and event["type"] == "stale":
    return {"status": "aborted", "reason": event["payload"]["detail"]}
```

No SDK change is needed — `stale` is an ordinary event type, so the
existing `recv_event` / stream paths surface it across every runtime.

**Request input — pause for an external answer.** A `task=True` handler
that needs a human (or another agent) to supply something mid-run calls
`request_input(prompt)` to transition the job to `input_required`, then
parks on `recv_event` for the answer:

```python
@app.tool()
@mesh.tool(capability="approve_spend", task=True)
async def approve_spend(amount: float, job: mesh.MeshJob = None) -> dict:
    # 1. Signal the consumer we're blocked on input. The prompt rides the
    #    job's progress_message field; status flips to "input_required".
    await job.request_input(f"Approve ${amount}? Reply yes/no.")

    # 2. Park on the answer (no busy-wait — long-polls the event log).
    event = await job.recv_event(types=["answer"], timeout_secs=300.0)
    if event is None:
        return await job.fail("timed out waiting for approval")

    # 3. Resume and finish. complete()/fail() exit input_required.
    if event["payload"].get("approved"):
        return {"status": "approved"}
    return {"status": "denied"}
```

An external party answers by posting the matching event:

```python
await mesh.jobs.post_event(job_id, "answer", {"approved": True})
```

`request_input` is **status-only**: it posts the `input_required`
transition (flushing immediately, since the consumer is blocked on it)
and returns — it does not await the answer. Awaiting is composed with
the existing `recv_event` / `post_event` event primitives, as above.
The transition is **non-terminal**: the handler keeps running.
`complete()` / `fail()` exit `input_required` (a mid-flight
resume-to-`working` primitive is a future follow-up).

## Stream subscription

Non-destructive observer iterator. Multiple subscribers can mirror
the same job's events independently — each call has its own cursor,
none of them disturb the producer's `recv_event` drain.

```python
import mesh

async def mirror(job_id: str) -> None:
    async for event in mesh.jobs.subscribe_events(
        job_id,
        types=["progress", "ended"],
        after=0,
        long_poll_secs=30.0,
    ):
        await downstream.publish(event)
        if event["type"] == "ended":
            break
```

**Use it for**: fan-out to a downstream queue / UI websocket /
metrics sink; third-party observer that mirrors events without
being the running handler; reconnect-from-cursor (persist
`next_after` between sessions). For the in-handler drain — where each
event is processed once — use `recv_event` instead.

**Semantics:**

- `after=0` starts from the beginning of the log; pass a higher
  value to skip historical events.
- Server-side `types` filter; the `next_after` watermark advances
  even on empty pages so filtered re-scans are O(1).
- No automatic terminal-state detection. The iterator runs until the
  caller breaks out of the loop or the registry raises
  `JobNotFoundError`. Applications signal end via a sentinel event
  type (e.g. `{"type": "ended"}`).

## Timeout propagation

Jobs use the `X-Mesh-Timeout` header (#656) to carry a per-attempt
deadline as **relative seconds remaining** for the current attempt
(not an absolute timestamp). The producer runtime stashes the deadline
in a `contextvars.ContextVar("mesh_job_deadline")`; outbound proxies
read it back and attach a recomputed `X-Mesh-Timeout` to downstream
requests.

**Nested job cap:** when a parent job calls a child job, the child's
deadline is `min(parent_remaining, child_requested)`. Enforced at
submission time, so the child's runtime sees a single coherent
deadline regardless of depth.

The header is on the default `MCP_MESH_PROPAGATE_HEADERS` allowlist
alongside `X-Mesh-Job-Id` and `X-Mesh-Trace-Id` — no per-agent
configuration is needed.

## Reaping and lease recovery

A registry cron sweep keeps the job pool healthy without operator
intervention:

- **Orphan reroute.** A job whose owner replica is gone (deregistered
  or gone unhealthy) is returned to the claimable pool so any peer with
  the matching capability picks it up. Jobs parked in `input_required`
  are covered too — a job waiting on a consumer answer whose owner then
  dies is reclaimed, not stranded.
- **Lease recovery.** The lease window is derived from `max_duration`
  (the 300s claim default when undeclared) — declare `max_duration` ≈
  the job's real per-attempt ceiling for long-running work. The lease
  renews on **any accepted non-terminal delta AND any `recv_event` poll
  from the current claim**: a handler parked in a legitimate `recv_event`
  gate is provably alive, so no artificial `update_progress` keepalives
  are needed. Poll-liveness never pushes the lease past the job's
  `total_deadline` or stale ceiling, so an actively-polling handler
  cannot outlive the point where the sweep would legitimately reap it. A
  job whose lease expires with no renewal — a genuinely wedged handler,
  neither progressing nor polling — is reset to claimable while retries
  remain, or marked `failed` once the retry budget is spent. This
  includes jobs parked in `input_required`: a handler that crashes while
  awaiting an answer stops renewing and is reclaimed rather than held
  forever (a live handler polling `recv_event` for the answer keeps its
  lease renewed).
- **Total-deadline ceiling.** A job that set `total_deadline` is failed
  with `deadline_exceeded` once that wall-clock deadline passes.
- **Default stale ceiling (opt-in).** Set `MCP_MESH_JOB_STALE_TIMEOUT`
  (a duration, e.g. `2h`) on the registry to apply a *default*
  total-runtime ceiling, measured from submission, to jobs that did
  **not** set their own `total_deadline`. The effective ceiling for a
  job is `max(MCP_MESH_JOB_STALE_TIMEOUT, max_duration)` — it never
  reaps a job before its own declared per-attempt `max_duration` has
  elapsed. Such a job is marked `failed` with a `stale: ...` error once
  it exceeds the ceiling. Unset (the default) leaves the feature off —
  jobs without an explicit `total_deadline` run unbounded (subject only
  to lease recovery). Jobs that set their own `total_deadline` are fully
  exempt.

Reaping is observable in-handler via a synthetic `stale` event — see
**Event injection** below.

**Long-running (hours) jobs.** Set `max_duration` to the job's real
per-attempt runtime — this sizes the lease window AND floors the stale
ceiling. A handler sitting in `recv_event` gates renews the lease on
every poll; one that computes silently for long stretches should emit
periodic `update_progress` to keep the lease renewed. Set
`total_deadline` if you want a hard total-runtime bound across all
attempts, or to opt out of the registry-wide stale ceiling entirely.

## Claim gating on unavailable capabilities

A claim worker never pulls a job for a capability whose `required`
dependencies are currently unavailable (see **Required Dependencies** in
`meshctl man dependency-injection` for the availability predicate).
Claiming it would only run the handler far enough to fail on the missing
dependency and burn a retry on a purely topological outage. Instead the
registry leaves the job queued and untouched — no owner, no attempt-count
increment, no epoch bump, no lease — and the worker moves on. The gate is
evaluated lazily, only once a candidate job actually exists, so an idle
queue pays nothing. Claiming resumes automatically within one claim-poll
cycle (≤5s backoff ceiling) of the required chain recovering, so no retry
budget is spent while the capability is down.

**Enforced at both layers.** The gate is belt-and-suspenders. Registry-side,
the transitive availability predicate keeps the job out of any claim response
whose `required` chain is down (the description above). Consumer-side, the
claim worker independently **skips claiming** while a `required` dependency
slot is still unresolved *locally* — the claim gate and the handler's
injection read one clock, so a dep flapping DOWN→UP cannot slip a job past
the registry gate into a handler that would see `None`. As a last resort, a
**pre-invoke guard** that finds a required slot still unresolved at invoke
time **releases the claim back to the queue** (a lease release, mirroring the
`retry_on` path — never a terminal `fail()`) rather than running the handler
with a missing dependency. Net effect: a handler never observes `None` for a
`required=true` dependency, including during dependency recovery.

## Multi-replica execution and fencing

Several replicas may declare the same `task=True` capability. Each job is
claimed by **exactly one** replica per attempt — the claim is a guarded
atomic update, so concurrent claimers race and only one wins. If a lease
genuinely expires (a handler wedged, neither progressing nor polling), the
sweep returns the job to the pool and a peer re-claims it.

Every claim — including a re-claim of the same job, even by the same
replica — carries a **monotonically increasing claim epoch**. The registry
fences the superseded execution: its writes are rejected
(`claim_superseded`) and it observes cancellation through the **same
surface as a user cancel** — the handler's cancel token fires, so a parked
`recv_event` raises the cancelled error and the next `await` point raises
`asyncio.CancelledError`. Honor cancellation promptly (return / stop side
effects) instead of running to completion under a lost claim.

For a side effect a fenced re-execution might repeat, stamp it with the
claim epoch so downstream can dedupe:

```python
@app.tool()
@mesh.tool(capability="charge_card", task=True)
async def charge_card(order_id: str, amount: float, job: mesh.MeshJob = None) -> dict:
    # job.claim_epoch is the generation this attempt runs under (int, or
    # None for a push-mode inbound job / an old registry). Read-only and
    # additive — supersession works without it (it rides the cancellation
    # path); the epoch exists only so downstream can distinguish a fenced
    # re-execution's duplicate write.
    await ledger.upsert(key=order_id, claim_epoch=job.claim_epoch, amount=amount)
    ...
```

When the dedupe sink is **itself a mesh provider** (rather than a raw
DB/client as above), don't plumb the epoch as a tool argument — the provider
reads the caller's identity straight off the propagated headers via
`mesh.calling_job()`. See **Calling-job identity** below.

## Calling-job identity

The epoch stamp above lets a handler fence *its own* side effects. The dual
problem is a **downstream provider** fencing writes from a *stale executor*
it doesn't control — e.g. a state-authority agent that must reject a write
issued under a superseded claim. Rather than make every caller thread
`job_id` / `claim_epoch` through the tool payload, the mesh seeds them
automatically: any outbound mesh→mesh tool call made from within a job
handler carries the calling job's identity on two dedicated propagated
headers — `x-mesh-calling-job-id` and (when known)
`x-mesh-calling-claim-epoch`. The mesh forwards this pair by default across
every mesh→mesh hop, including the registry's proxy hop, so no per-agent
`MCP_MESH_PROPAGATE_HEADERS` configuration is needed.

The provider reads that identity with `mesh.calling_job()`:

```python
import mesh

@app.tool()
@mesh.tool(capability="record_charge")
async def record_charge(order_id: str, amount: float) -> dict:
    caller = mesh.calling_job()          # CallingJob(job_id, claim_epoch) | None
    if caller is not None:
        # Fence: stamp the caller's claim epoch so a superseded
        # re-execution's duplicate write is distinguishable / rejectable.
        await ledger.upsert(
            key=order_id,
            claim_epoch=caller.claim_epoch,
            amount=amount,
        )
    return {"order_id": order_id}
```

`calling_job()` returns the identity of the job that **called this tool** —
not the job this handler is itself running as. It returns `None` for a
regular (non-job) `tools/call`, for a caller on an older SDK that did not
seed the headers, and — critically — inside a handler that was **claimed
directly** (a `task=True` handler pulled off its own claim queue): that
handler's *own* identity lives on `current_job()`, not here. The returned
`CallingJob.claim_epoch` is `None` for a push-mode inbound job. It is purely
additive and read-only — reading it has no effect on the call. This is the
provider-side dual of `current_job()`: `current_job()` answers "what job am I
executing *as*", `calling_job()` answers "what job *invoked* me".

## Out-of-band inspection

Three SDK-managed helper tools are auto-registered on every mesh
agent. They are regular MCP tools (prefixed `__mesh_job_` to mark them
framework-internal) and route through a consumer agent:

```bash
# Inspect status (registry returns the full job row)
meshctl call <consumer>:__mesh_job_status \
    '{"job_id":"01HXY..."}'

# Pull just the terminal result + status (convenience over status)
meshctl call <consumer>:__mesh_job_result \
    '{"job_id":"01HXY..."}'

# Cancel mid-flight (idempotent — already-terminal jobs return ok)
meshctl call <consumer>:__mesh_job_cancel \
    '{"job_id":"01HXY...","reason":"user requested"}'
```

Submission goes through the consumer's actual capability (e.g.
`commission_report`), not a dedicated `__mesh_job_submit` helper —
the submitter needs the dependency context to know which capability
to route to and which retry / deadline policy to apply.

### Reading job state directly from the registry

`meshctl job` talks to the registry row directly (no consumer agent
in the loop) and surfaces the fencing / lease fields used for
post-incident forensics — `claim_epoch`, `owner`, `attempt_count`,
`lease_expires_at`:

```bash
# Full job state, including claim_epoch and lease
meshctl job status 01HXY...

# A claim_epoch > 1 means the job was re-claimed at least once
# (owner change / fencing event) during its lifetime.
```

### Forcing a re-claim (fencing drills)

A healthy handler renews its lease on every poll, so supersession is
otherwise almost impossible to trigger on demand. `meshctl job reclaim`
forces the lease-expiry path for one job — it clears the owner and
lease so the job is claimable again, leaving `claim_epoch` unchanged
(the next claim mints the new generation, which fences the superseded
execution as `claim_superseded`). Use it to validate epoch fencing in
staging / incident drills, or to evict a job from a replica you're
about to drain. Terminal jobs cannot be reclaimed.

```bash
meshctl job reclaim 01HXY...
```

## Auth model

`job_id` is a presigned-URL-style capability. Possession of a valid
job id (~122 bits of entropy from a UUID) grants full status / result
/ cancel rights on that job, with no additional caller-identity check.

> **Leak the id, leak the job.** Treat `job_id` like a presigned S3
> URL. Anyone who learns it can cancel the work or read the result,
> including any error payload. Don't log job ids to a system that has
> a wider audience than the consumer that issued them. If a job
> carries sensitive payloads, scrub them out of `complete()` too —
> the result lives in the registry until the sweep cron expires it.

In v2.x there is no opt-in caller-identity verification. SPIRE-based
mode is future work (tracked in `MESHJOB_DESIGN.org`).

## v2 Limitations

- **No idempotency keys.** Retries restart the handler from scratch.
- **No caller-identity check on `job_id`.** Possession is the only auth.
- **No streaming-style chunked progress.** Progress flushes on a
  batching tick. For token-by-token feedback, see
  `meshctl man streaming` — or combine: a job that calls a streaming
  tool internally and reports coarse progress via `update_progress`.
- **No cross-runtime `retry_on` coercion.** Each runtime matches its
  own native exception classes. A Python `retry_on=(OSError,)` does
  NOT propagate to a Java peer claiming the same capability — declare
  the whitelist separately on each runtime that hosts the capability.

## See Also

- `meshctl man streaming` — token-by-token progress for the
  request-response case where the work fits in a single SSE
- `meshctl man audit` — `X-Mesh-Job-Id` + `X-Mesh-Timeout` propagation
  through the audit pipeline
- `meshctl man dependency-injection` — how DDDI resolves
  `MeshJob`-typed slots
- [`docs/concepts/jobs.md`](https://github.com/dhyansraj/mcp-mesh/blob/main/docs/concepts/jobs.md) — narrative concept doc with architecture overview
- [`examples/jobs/`](https://github.com/dhyansraj/mcp-mesh/tree/main/examples/jobs) — runnable producer + consumer pair (Python)
