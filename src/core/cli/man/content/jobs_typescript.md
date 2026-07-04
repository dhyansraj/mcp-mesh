# Long-Running Jobs (MeshJob — TypeScript)

> DDDI-native primitive for tasks that outlast a `tools/call` request — submit, await, cancel, retryOn

## Why MeshJob

`tools/call` is fine for sub-second to ~30s work. For anything longer (multi-section reports, video transcoding, long agentic loops), the consumer's HTTP socket is at the mercy of every load balancer, ingress, and pod restart between the two agents.

**MeshJob** is the durable alternative:

- Producer sets `task: true` on the tool — the SDK runs it under a
  registry-backed claim/lease, with progress updates and explicit
  `complete()` / `fail()` terminal states.
- Consumer types a dependency parameter as `MeshJob | null` — DDDI
  swaps the usual `McpMeshTool` proxy for a `MeshJobSubmitter` at that
  slot.
- `submitter.submit(...)` posts to `POST /jobs` and returns a
  `JobProxy` bound to the new job id. `proxy.wait(...)` polls
  `GET /jobs/{id}` until terminal.

Plain `task: false` tools continue to be buffered request-response —
no behavior change for non-job tools.

## Cheat sheet

| Surface              | Producer                                  | Consumer                                  |
| -------------------- | ----------------------------------------- | ----------------------------------------- |
| Tool flag            | `task: true`                              | (regular `addTool` w/ dependency)         |
| Slot index           | `meshJobParamIndex: <pos>`                | `meshJobDepIndex: <dep-array-index>`      |
| Injected type        | `job: MeshJob \| null = null`             | `<dep>: MeshJob \| null = null`           |
| Concrete injection   | `JobController` (or `null`)               | `MeshJobSubmitter`                        |
| Progress             | `await job?.updateProgress(f, m)`         | (read via `__mesh_job_status`)            |
| Request input        | `await job?.requestInput(prompt)`         | (status → `input_required`; answer via `postEvent`) |
| Terminal success     | `await job?.complete(payload)`            | `await proxy.wait(timeoutSecs)`           |
| Terminal failure     | `await job?.fail(reason)`                 | `wait()` rejects                          |
| Transient retry      | `throw new TransientError(...)` w/ `retryOn` | (registry hands to peer in ~5s)        |
| Cancel               | (cancel token fires in handler)           | `await proxy.cancel(reason)`              |

## Producer: `task: true`

```typescript
import { FastMCP } from "fastmcp";
import { mesh, type MeshJob } from "@mcpmesh/sdk";
import { z } from "zod";

const server = new FastMCP({
  name: "Long Task Provider (TS)",
  version: "1.0.0",
});

const agent = mesh(server, {
  name: "long-task-provider-ts",
  httpPort: 9110,
});

agent.addTool({
  name: "generate_report",
  capability: "generate_report",
  task: true,                              // opts the tool into MeshJob
  // Position 0 is `args`, the MeshJob lands at position 1.
  meshJobParamIndex: 1,
  description: "Long-running report generator",
  parameters: z.object({
    user_id: z.string(),
    sections: z.array(z.string()),
  }),
  execute: async (
    { user_id, sections },
    job: MeshJob | null = null,            // injected JobController (or null)
  ) => {
    if (job?.updateProgress) {
      await job.updateProgress(0.0, "starting");
    }
    const results: { section: string; content: string }[] = [];
    const total = Math.max(sections.length, 1);
    for (let i = 0; i < sections.length; i++) {
      await new Promise((r) => setTimeout(r, 2000));    // simulate work
      results.push({
        section: sections[i],
        content: `...${sections[i]}`,
      });
      if (job?.updateProgress) {
        await job.updateProgress(
          (i + 1) / total,
          `finished section ${i+1}/${total}`,
        );
      }
    }
    const payload = { user_id, report: results };
    if (job?.complete) {
      await job.complete(payload);         // explicit terminal flush
    }
    return payload;
  },
});
```

**Notes:**

- Unlike Python (which auto-detects from the type annotation), TS
  declares `meshJobParamIndex` explicitly because runtime type
  reflection is not available. Position 0 is the `args` object;
  position 1 is the first slot after that.
- `job` is `null` when the tool is invoked via a regular `tools/call`
  (no `X-Mesh-Job-Id` header) — the function then runs the fast path
  and just returns its result.
- `complete()` / `fail()` flush past the batching tick immediately, so
  the consumer's `wait(...)` sees the terminal state without latency.
- `updateProgress(fraction, message)` is batched. For token-by-token
  feedback, see `meshctl man streaming --typescript`.

## Consumer: `MeshJob`-typed dependency

```typescript
import { FastMCP } from "fastmcp";
import { mesh, type MeshJob } from "@mcpmesh/sdk";
import { z } from "zod";

const server = new FastMCP({
  name: "Long Task Consumer (TS)",
  version: "1.0.0",
});

const agent = mesh(server, {
  name: "long-task-consumer-ts",
  httpPort: 9111,
});

agent.addTool({
  name: "commission_report",
  capability: "commission_report",
  dependencies: [{ capability: "generate_report" }],
  // Replace dep[0]'s slot with a MeshJobSubmitter. Without this flag,
  // the SDK injects a regular McpMeshTool proxy.
  meshJobDepIndex: 0,
  parameters: z.object({
    user_id: z.string(),
    sections: z.array(z.string()),
  }),
  execute: async (
    { user_id, sections },
    generateReport: MeshJob | null = null,
  ) => {
    if (!generateReport?.submit) {
      return { error: "submitter not injected" };
    }
    const proxy = await generateReport.submit(
      { user_id, sections },
      { maxDuration: 60 },                 // per-attempt soft timeout
    );
    return await proxy.wait!(60);
  },
});
```

**Notes:**

- `meshJobDepIndex: N` swaps `McpMeshTool` for `MeshJobSubmitter` at
  the Nth dependency slot. Same DDDI lookup pipeline (resolution,
  trust, tags) — only the proxy class differs.
- `proxy.wait(timeoutSecs)` resolves with the producer's `complete()`
  payload on success; rejects on `JobFailedError`,
  `JobCancelledError`, or `JobTimeoutError`.

## `submit(...)` options

```typescript
const proxy = await generateReport.submit(
  { user_id, sections },                    // tool args
  {
    maxDuration: 60,                        // per-attempt soft timeout (sec); also sizes the lease + floors the stale ceiling
    maxRetries: 3,                          // retries beyond initial attempt
    totalDeadline: 300,                     // hard ceiling across attempts (sec)
    ownerInstanceId: undefined,             // optional: pin to a replica
  },
);
```

## `retryOn` (per-tool exception whitelist)

`retryOn` is an array of `Error` subclass constructors that should be
treated as transient. When the handler throws an instance of a matching
class, the SDK calls `releaseLease(reason)` instead of `fail(reason)`
— the registry resets the owner and a peer replica re-runs the handler
within ~5 seconds. Anything **not** in `retryOn` still goes through
`fail()` and surfaces to the consumer immediately.

```typescript
class TransientUpstreamError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "TransientUpstreamError";
  }
}

agent.addTool({
  name: "report_with_transient_failures",
  capability: "report_with_transient_failures",
  task: true,
  meshJobParamIndex: 1,
  retryOn: [TransientUpstreamError],         // array of Error subclasses
  parameters: z.object({
    user_id: z.string(),
    transient_failures: z.number().default(2),
  }),
  execute: async (
    { user_id, transient_failures },
    job: MeshJob | null = null,
  ) => {
    const n = bumpRetryCounter();
    if (n <= transient_failures) {
      // retryOn match → SDK releases the lease; peer replica retries.
      throw new TransientUpstreamError(
        `simulated transient failure ${n}/${transient_failures}`,
      );
    }
    const payload = { user_id, succeeded_on_attempt: n };
    if (job?.complete) await job.complete(payload);
    return payload;
  },
});
```

**Validation:**

- `retryOn` requires `task: true` — registration fails at agent boot
  otherwise. Same for non-`Error`-subclass entries (strings,
  instances, plain objects, etc).
- Misuse surfaces at startup, not at retry time.

**`maxRetries` does NOT soften a real failure.** A handler exception that
is **not** matched by `retryOn` — and any explicit `fail()` — is
**terminal immediately**, no matter how much of the `maxRetries` budget is
unspent. That budget covers only crash-style recoveries the runtime
retries on your behalf: lease expiry, orphan reclaim, `maxDuration`
timeout, plus `retryOn`-matched releases. So a job that shows
`attempt_count: 1` with `maxRetries: 3` after a non-transient error has
**zero** retries left — not two — it already reached its terminal
`failed` state on that first attempt.

Retries restart the handler from scratch — there are no idempotency
keys in v2.x. If the handler has external side effects, design for
at-least-once: deterministic ids the downstream can dedupe on, or a
"claim → check → execute → mark done" pattern keyed off `job_id`.

## Cancellation

```typescript
// Consumer-side: cancel an in-flight job
await proxy.cancel("user requested abort");
```

The registry forwards the cancel to the owner replica via
`POST /jobs/{id}/cancel` (auto-registered on every agent's HTTP
server). On the producer side, the cancel token fires:

- The `AbortSignal` exposed via `job?.signal` (if the handler
  subscribed) is aborted.
- Outbound `McpMeshTool` proxy calls abort their underlying `fetch`
  (cancel propagates through `X-Mesh-Job-Id` binding).

The registry treats cancel as terminal (idempotent — already-terminal
jobs return ok without re-firing).

## Event injection

Per-job append-only event log every running job carries. Anyone with
the `jobId` writes; the running handler drains.

**Inside a `task: true` handler — receive events:**

```typescript
if (!job) throw new Error("job slot is not bound");
const event = await job.recvEvent(["user_input", "cancelled"], 10);
// event is { seq, type, payload, ... } | null
if (event === null) {
  // nothing arrived within timeout
} else if (event.type === "cancelled") {
  const payload = event.payload as Record<string, unknown> | null;
  const reason = typeof payload?.reason === "string" ? payload.reason : "";
  return { status: "cancelled", reason };
}
```

Each distinct `types` filter is an **independent event stream** with its
own cursor, so interleaving `recvEvent(["A"])` and `recvEvent(["B"])`
never lets one filter's consumption skip the other's earlier events.
Delivery is **exactly-once within a filter stream** and **at-least-once
across different filters** (an event matching two filters can surface once
per stream). The cursor is per-handler and starts at the beginning of the
log on every (re-)claim — a re-claimed handler replays from the start.
Handlers doing **non-idempotent** work per event should checkpoint (e.g.
persist their own event cursor) or design idempotent phases.

**Outside the handler, with a `jobId` in scope — fire an event:**

```typescript
import { mesh } from "@mcpmesh/sdk";

agent.addTool({
  name: "submit_user_input",
  capability: "submit_user_input",
  parameters: z.object({ jobId: z.string(), text: z.string() }),
  execute: async ({ jobId, text }) => {
    const receipt = await mesh.jobs.postEvent(
      jobId, "user_input", { text },
    );
    return { seq: receipt.seq };
  },
});
```

`mesh.jobs.postEvent` is the canonical fire-and-forget. It resolves
the registry from `MCP_MESH_REGISTRY_URL` and reuses a process-cached
`JobProxy` from a bounded LRU keyed by `(registryUrl, jobId)` (default
cap 256; tune via `MCP_MESH_JOBPROXY_CACHE_MAX`). If the calling code
already holds a `JobProxy`, use `proxy.sendEvent(eventType, payload)`
directly — same wire shape, skip the helper.

**Lifecycle facades by `jobId`.** Same DDDI-clean pattern as
`postEvent` — module-level helpers that take a `jobId` and dispatch
through the shared proxy cache, for callers that don't hold a
`JobProxy` reference:

```typescript
// Cancel a running job (idempotent — already-terminal jobs return ok)
await mesh.jobs.cancel(jobId, "user requested abort");

// Read latest job state (JobStatus — registry Job row, field-for-field)
const snapshot = await mesh.jobs.status(jobId);
// snapshot.status ∈ "working" | "input_required" | "completed" | "failed" | "cancelled"

// Wait for terminal state and return the result payload
const result = await mesh.jobs.wait(jobId, 300);
```

`wait` rejects with an `Error` whose message starts with `"timeout:"`
on `timeoutSecs` expiry; omit `timeoutSecs` (or pass `undefined`) to
wait until the job reaches a terminal state. All three reject with
`JobNotFoundError` if the registry has reaped the job; `cancel` also
re-classifies a conflict response into `JobTerminalError`.

**Typed errors** (both extend `Error`):

- `JobNotFoundError` — job swept or id typo
- `JobTerminalError` — job already terminal, no more events accepted

**Synthetic cancel event**. When a consumer calls `proxy.cancel(
reason)`, the registry writes a synthetic
`{ type: "cancelled", payload: { reason: "..." } }` event into the log
before forwarding the cancel signal. A handler parked on `recvEvent(
["cancelled", ...])` observes it and can return cleanly instead of
relying on the `AbortSignal`. The registry waits a small grace window
before issuing the cancel-forward (default 200ms, tunable via
`MCP_MESH_CANCEL_EVENT_GRACE_MS`, capped at 10s).

**Synthetic stale event**. When the registry reaps a job for exceeding
the `MCP_MESH_JOB_STALE_TIMEOUT` default ceiling (see **Reaping and
lease recovery**), it writes a synthetic
`{ type: "stale", payload: { reason: "stale", detail: "..." } }` event
into the log as it transitions the job to `failed`. A handler parked on
`recvEvent(["stale", ...])` observes the reaping and can unwind cleanly:

```typescript
const event = await job.recvEvent(["stale", "cancelled"], 30);
if (event && event.type === "stale") {
  return { status: "aborted", reason: event.payload.detail };
}
```

No SDK change is needed — `stale` is an ordinary event type, so the
existing `recvEvent` / stream paths surface it across every runtime.

**Request input — pause for an external answer.** A `task: true` handler
that needs a human (or another agent) to supply something mid-run calls
`requestInput(prompt)` to transition the job to `input_required`, then
parks on `recvEvent` for the answer:

```typescript
agent.addTool({
  name: "approve_spend",
  capability: "approve_spend",
  task: true,
  parameters: z.object({ amount: z.number() }),
  meshJobParamIndex: 1,
  execute: async ({ amount }, job: MeshJob | null = null) => {
    if (!job) throw new Error("job slot is not bound");

    // 1. Signal the consumer we're blocked on input. The prompt rides the
    //    job's progress_message field; status flips to "input_required".
    await job.requestInput?.(`Approve $${amount}? Reply yes/no.`);

    // 2. Park on the answer (no busy-wait — long-polls the event log).
    const event = await job.recvEvent?.(["answer"], 300);
    if (!event) {
      await job.fail?.("timed out waiting for approval");
      return { status: "timeout" };
    }

    // 3. Resume and finish. complete()/fail() exit input_required.
    const payload = event.payload as Record<string, unknown> | null;
    return { status: payload?.approved ? "approved" : "denied" };
  },
});
```

An external party answers by posting the matching event:

```typescript
await mesh.jobs.postEvent(jobId, "answer", { approved: true });
```

`requestInput` is **status-only**: it posts the `input_required`
transition (flushing immediately, since the consumer is blocked on it)
and resolves — it does not await the answer. Awaiting is composed with
the existing `recvEvent` / `postEvent` event primitives, as above. The
transition is **non-terminal**: the handler keeps running. `complete()`
/ `fail()` exit `input_required` (a mid-flight resume-to-`working`
primitive is a future follow-up).

## Stream subscription

Non-destructive observer iterator. Multiple subscribers can mirror
the same job's events independently — each call has its own cursor,
none of them disturb the producer's `recvEvent` drain.

```typescript
import { mesh } from "@mcpmesh/sdk";

async function mirror(jobId: string): Promise<void> {
  for await (const event of mesh.jobs.subscribeEvents(jobId, {
    types: ["progress", "ended"],
    after: 0,
    longPollSecs: 30,
  })) {
    await downstream.publish(event);
    if (event.type === "ended") break;
  }
}
```

**Use it for**: fan-out to a downstream queue / UI websocket /
metrics sink; third-party observer that mirrors events without
being the running handler; reconnect-from-cursor (persist
`next_after` between sessions). For the in-handler drain — where each
event is processed once — use `recvEvent` instead.

**Semantics:**

- `after = 0` (the default) starts from the beginning of the log; pass
  a higher value to skip historical events.
- Server-side `types` filter; the `nextAfter` watermark advances even
  on empty pages so filtered re-scans are O(1).
- No automatic terminal-state detection. The iterator runs until the
  caller breaks out of the `for await` loop or the registry raises
  `JobNotFoundError`. Applications signal end via a sentinel event
  type (e.g. `{ type: "ended" }`).

## Timeout propagation

Jobs use the `X-Mesh-Timeout` header (#656) to carry a per-attempt
deadline as **relative seconds remaining** for the current attempt
(not an absolute timestamp). The producer runtime stashes the deadline
in `AsyncLocalStorage`; outbound proxies read it back and attach a
recomputed `X-Mesh-Timeout` to downstream requests.

**Nested job cap:** when a parent job calls a child job, the child's
deadline is `min(parentRemaining, childRequested)`. Enforced at
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
- **Lease recovery.** The lease window is derived from `maxDuration`
  (the 300s claim default when undeclared) — declare `maxDuration` ≈
  the job's real per-attempt ceiling for long-running work. The lease
  renews on **any accepted non-terminal delta AND any `recvEvent` poll
  from the current claim**: a handler parked in a legitimate `recvEvent`
  gate is provably alive, so no artificial `updateProgress` keepalives
  are needed. Poll-liveness never pushes the lease past the job's
  `totalDeadline` or stale ceiling, so an actively-polling handler
  cannot outlive the point where the sweep would legitimately reap it. A
  job whose lease expires with no renewal — a genuinely wedged handler,
  neither progressing nor polling — is reset to claimable while retries
  remain, or marked `failed` once the retry budget is spent. This
  includes jobs parked in `input_required`: a handler that crashes while
  awaiting an answer stops renewing and is reclaimed rather than held
  forever (a live handler polling `recvEvent` for the answer keeps its
  lease renewed).
- **Total-deadline ceiling.** A job that set `totalDeadline` is failed
  with `deadline_exceeded` once that wall-clock deadline passes.
- **Default stale ceiling (opt-in).** Set `MCP_MESH_JOB_STALE_TIMEOUT`
  (a duration, e.g. `2h`) on the registry to apply a *default*
  total-runtime ceiling, measured from submission, to jobs that did
  **not** set their own `totalDeadline`. The effective ceiling for a
  job is `max(MCP_MESH_JOB_STALE_TIMEOUT, maxDuration)` — it never reaps
  a job before its own declared per-attempt `maxDuration` has elapsed.
  Such a job is marked `failed` with a `stale: ...` error once it
  exceeds the ceiling. Unset (the default) leaves the feature off —
  jobs without an explicit `totalDeadline` run unbounded (subject only
  to lease recovery). Jobs that set their own `totalDeadline` are fully
  exempt.

Reaping is observable in-handler via a synthetic `stale` event — see
**Event injection** above.

**Long-running (hours) jobs.** Set `maxDuration` to the job's real
per-attempt runtime — this sizes the lease window AND floors the stale
ceiling. A handler sitting in `recvEvent` gates renews the lease on
every poll; one that computes silently for long stretches should emit
periodic `updateProgress` to keep the lease renewed. Set `totalDeadline`
if you want a hard total-runtime bound across all attempts, or to opt out
of the registry-wide stale ceiling entirely.

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
the registry gate into a handler that would see `null`. As a last resort, a
**pre-invoke guard** that finds a required slot still unresolved at invoke
time **releases the claim back to the queue** (`releaseLease`, mirroring the
`retryOn` path — never a terminal `fail()`) rather than running the handler
with a missing dependency. Net effect: a handler never observes `null` for a
`required: true` dependency, including during dependency recovery.

## Multi-replica execution and fencing

Several replicas may declare the same `task: true` capability. Each job is
claimed by **exactly one** replica per attempt — the claim is a guarded
atomic update, so concurrent claimers race and only one wins. If a lease
genuinely expires (a handler wedged, neither progressing nor polling), the
sweep returns the job to the pool and a peer re-claims it.

Every claim — including a re-claim of the same job, even by the same
replica — carries a **monotonically increasing claim epoch**. The registry
fences the superseded execution: its writes are rejected
(`claim_superseded`) and it observes cancellation through the **same
surface as a user cancel** — the handler's `AbortSignal` (`job?.signal`)
aborts and a parked `recvEvent` rejects with the cancelled error. Honor
cancellation promptly (return / stop side effects) instead of running to
completion under a lost claim.

For a side effect a fenced re-execution might repeat, stamp it with the
claim epoch so downstream can dedupe. Read the epoch from the active job
context:

```typescript
import { currentJob } from "@mcpmesh/sdk";

// currentJob()?.claimEpoch is the generation this attempt runs under
// (number, or null for a push-mode inbound job / an old registry).
// Read-only and additive — supersession works without it (it rides the
// cancellation path); the epoch exists only so downstream can distinguish
// a fenced re-execution's duplicate write.
const claimEpoch = currentJob()?.claimEpoch ?? null;
await ledger.upsert({ key: orderId, claimEpoch, amount });
```

When the dedupe sink is **itself a mesh provider** (rather than a raw
DB/client as above), don't plumb the epoch as a tool argument — the provider
reads the caller's identity straight off the propagated headers via
`callingJob()`. See **Calling-job identity** below.

## Calling-job identity

The epoch stamp above lets a handler fence *its own* side effects. The dual
problem is a **downstream provider** fencing writes from a *stale executor*
it doesn't control — e.g. a state-authority agent that must reject a write
issued under a superseded claim. Rather than make every caller thread
`jobId` / `claimEpoch` through the tool payload, the mesh seeds them
automatically: any outbound mesh→mesh tool call made from within a job
handler carries the calling job's identity on two dedicated propagated
headers — `x-mesh-calling-job-id` and (when known)
`x-mesh-calling-claim-epoch`. The mesh forwards this pair by default across
every mesh→mesh hop, including the registry's proxy hop, so no per-agent
`MCP_MESH_PROPAGATE_HEADERS` configuration is needed.

The provider reads that identity with `callingJob()` (exported from the
package root), which returns `{ jobId, claimEpoch }` or `null`:

```typescript
import { callingJob } from "@mcpmesh/sdk";

agent.addTool({
  name: "record_charge",
  capability: "record_charge",
  parameters: z.object({ order_id: z.string(), amount: z.number() }),
  execute: async ({ order_id, amount }) => {
    const caller = callingJob();          // { jobId, claimEpoch } | null
    if (caller) {
      // Fence: stamp the caller's claim epoch so a superseded
      // re-execution's duplicate write is distinguishable / rejectable.
      await ledger.upsert({ key: order_id, claimEpoch: caller.claimEpoch, amount });
    }
    return { order_id };
  },
});
```

`callingJob()` returns the identity of the job that **called this tool** —
not the job this handler is itself running as. It returns `null` for a
regular (non-job) `tools/call`, for a caller on an older SDK that did not
seed the headers, and — critically — inside a handler that was **claimed
directly** (a `task: true` handler pulled off its own claim queue): that
handler's *own* identity lives on `currentJob()`, not here. The returned
`claimEpoch` is `null` for a push-mode inbound job. It is purely additive
and read-only — reading it has no effect on the call. This is the
provider-side dual of `currentJob()`: `currentJob()` answers "what job am I
executing *as*", `callingJob()` answers "what job *invoked* me".

## Out-of-band inspection

Three SDK-managed helper tools are auto-registered on every mesh
agent. They are regular MCP tools (prefixed `__mesh_job_` to mark them
framework-internal):

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
  `meshctl man streaming --typescript` — or combine: a job that calls
  a streaming tool internally and reports coarse progress via
  `updateProgress`.
- **No cross-runtime `retryOn` coercion.** Each runtime matches its
  own native exception classes. A TypeScript
  `retryOn: [TransientUpstreamError]` does NOT propagate to a Python
  or Java peer claiming the same capability — declare the whitelist
  separately on each runtime that hosts the capability.

## See Also

- `meshctl man streaming --typescript` — token-by-token progress
- `meshctl man audit` — `X-Mesh-Job-Id` + `X-Mesh-Timeout` propagation
- `meshctl man dependency-injection --typescript` — how DDDI resolves
  `MeshJob`-typed slots
- [`docs/concepts/jobs.md`](https://github.com/dhyansraj/mcp-mesh/blob/main/docs/concepts/jobs.md) — narrative concept doc with architecture overview
- [`examples/jobs-ts/`](https://github.com/dhyansraj/mcp-mesh/tree/main/examples/jobs-ts) — runnable producer + consumer pair (TypeScript)
