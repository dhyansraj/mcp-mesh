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
| `max_duration`     | `int` (seconds)  | Per-attempt soft timeout (provider runtime + cron sweep)|
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

## Out-of-band inspection

Three SDK-managed helper tools are auto-registered on every mesh
agent. They are regular MCP tools (prefixed `__mesh_job_` to mark them
framework-internal) — no separate `meshctl` subcommand:

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
