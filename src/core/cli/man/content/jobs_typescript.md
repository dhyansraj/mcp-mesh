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
    maxDuration: 60,                        // per-attempt soft timeout (sec)
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
