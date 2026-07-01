# Long-Running Jobs (MeshJob — Java)

> DDDI-native primitive for tasks that outlast a `tools/call` request — submit, await, cancel, retryOn

## Why MeshJob

`tools/call` is fine for sub-second to ~30s work. For anything longer (multi-section reports, video transcoding, long agentic loops), the consumer's HTTP socket is at the mercy of every load balancer, ingress, and pod restart between the two agents.

**MeshJob** is the durable alternative:

- Producer sets `task = true` on `@MeshTool` — the SDK runs the
  method under a registry-backed claim/lease, with progress updates
  and explicit `complete()` / `fail()` terminal states.
- Consumer types a dependency parameter as `MeshJob` — DDDI swaps
  the usual `McpMeshTool` proxy for a `MeshJobSubmitter` at that slot.
- `submitter.submit(...)` posts to `POST /jobs` and returns a
  `CompletableFuture<JobProxy>` bound to the new job id.
  `proxy.await(timeoutSeconds)` polls `GET /jobs/{id}` until terminal.

Plain `task = false` (default) tools continue to be buffered
request-response — no behavior change for non-job tools.

## Cheat sheet

| Surface              | Producer                                    | Consumer                                           |
| -------------------- | ------------------------------------------- | -------------------------------------------------- |
| Annotation flag      | `@MeshTool(task = true)`                    | (regular `@MeshTool` w/ dependency)                |
| Slot detection       | Auto from `MeshJob` parameter type          | Auto from `MeshJob` parameter type                 |
| Injected type        | `MeshJob` (cast to `JobController`)         | `MeshJob` (cast to `MeshJobSubmitter`)             |
| Concrete injection   | `JobController` (or `null`)                 | `MeshJobSubmitter`                                 |
| Progress             | `controller.updateProgress(f, m)`           | (read via `__mesh_job_status`)                     |
| Request input        | `controller.requestInput(prompt)`           | (status → `input_required`; answer via `postEvent`) |
| Terminal success     | `controller.complete(payload)`              | `proxy.await(timeoutSeconds)`                      |
| Terminal failure     | `controller.fail(reason)`                   | `await()` throws                                   |
| Transient retry      | `throw new IOException(...)` w/ `retryOn`   | (registry hands to peer in ~5s)                    |
| Cancel               | (cancel token fires in handler)             | `proxy.cancel(reason)`                             |

## Producer: `@MeshTool(task = true)`

```java
package com.example.longtaskprovider;

import io.mcpmesh.JobController;
import io.mcpmesh.MeshAgent;
import io.mcpmesh.MeshJob;
import io.mcpmesh.MeshTool;
import io.mcpmesh.Param;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

@MeshAgent(
    name = "long-task-provider-java",
    version = "1.0.0",
    description = "MeshJob producer (Java)",
    port = 9120
)
@SpringBootApplication
public class LongTaskProviderApplication {

    public static void main(String[] args) {
        SpringApplication.run(LongTaskProviderApplication.class, args);
    }

    @MeshTool(
        capability = "generate_report",
        task = true,                                // opts the tool into MeshJob
        description = "Long-running report generator"
    )
    public Map<String, Object> generateReport(
            @Param("user_id") String userId,
            @Param(value = "sections", required = false) List<String> sections,
            MeshJob job) throws InterruptedException {       // injected at this slot

        if (sections == null) {
            sections = List.of("default");
        }
        // The runtime injects a JobController when X-Mesh-Job-Id is set,
        // or null when invoked via a regular tools/call (fast path).
        JobController controller = job instanceof JobController c ? c : null;
        if (controller != null) {
            controller.updateProgress(0.0, "starting");
        }

        List<Map<String, String>> results = new ArrayList<>();
        int total = Math.max(sections.size(), 1);
        for (int i = 0; i < sections.size(); i++) {
            Thread.sleep(2000);                     // simulate work
            String section = sections.get(i);
            Map<String, String> entry = new LinkedHashMap<>();
            entry.put("section", section);
            entry.put("content", "..." + section);
            results.add(entry);
            if (controller != null) {
                controller.updateProgress(
                    (i + 1.0) / total,
                    "finished section " + (i + 1) + "/" + total);
            }
        }

        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("user_id", userId);
        payload.put("report", results);

        if (controller != null) {
            controller.complete(payload);           // explicit terminal flush
        }
        return payload;
    }
}
```

**Notes:**

- The SDK auto-detects the `MeshJob` slot from the parameter type
  signature — no `meshJobParamIndex` needed (Java has reflection).
- `job` is `null` when the tool is invoked via a regular `tools/call`
  (no `X-Mesh-Job-Id` header) — the function then runs the fast path.
  Always check `job instanceof JobController` before downcasting.
- `complete()` / `fail()` flush past the batching tick immediately,
  so the consumer's `await(...)` sees the terminal state without
  latency.
- `updateProgress(fraction, message)` is batched. For token-by-token
  feedback, see `meshctl man streaming --java`.

## Consumer: `MeshJob`-typed dependency

```java
package com.example.longtaskconsumer;

import io.mcpmesh.JobProxy;
import io.mcpmesh.MeshAgent;
import io.mcpmesh.MeshJob;
import io.mcpmesh.MeshJobSubmitter;
import io.mcpmesh.MeshTool;
import io.mcpmesh.Param;
import io.mcpmesh.Selector;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

@MeshAgent(name = "long-task-consumer-java", port = 9121)
@SpringBootApplication
public class LongTaskConsumerApplication {

    public static void main(String[] args) {
        SpringApplication.run(LongTaskConsumerApplication.class, args);
    }

    @MeshTool(
        capability = "commission_report",
        description = "Commission a report and await its result",
        dependencies = @Selector(capability = "generate_report")
    )
    @SuppressWarnings("unchecked")
    public Map<String, Object> commissionReport(
            @Param("user_id") String userId,
            @Param(value = "sections", required = false) List<String> sections,
            MeshJob generateReport) throws Exception {

        // The DI layer injects a MeshJobSubmitter (NOT an McpMeshTool proxy)
        // because the dependency points at a task=true capability.
        if (!(generateReport instanceof MeshJobSubmitter submitter)) {
            Map<String, Object> err = new LinkedHashMap<>();
            err.put("error", "submitter not injected");
            return err;
        }

        if (sections == null) {
            sections = List.of("intro", "analysis", "summary");
        }

        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("user_id", userId);
        payload.put("sections", sections);

        // SubmitOptions(args, ownerInstanceId, maxDuration, maxRetries, totalDeadline)
        MeshJobSubmitter.SubmitOptions opts = new MeshJobSubmitter.SubmitOptions(
            payload,
            null,    // ownerInstanceId — let the registry route via claim
            60,      // maxDuration seconds (per-attempt soft timeout)
            null,    // maxRetries — accept default
            null     // totalDeadline — unlimited
        );

        try (JobProxy proxy = submitter.submit(opts).get()) {
            Object result = proxy.await(60.0);     // poll until terminal
            if (result instanceof Map<?, ?> m) {
                return (Map<String, Object>) m;
            }
            Map<String, Object> wrapped = new LinkedHashMap<>();
            wrapped.put("result", result);
            return wrapped;
        }
    }
}
```

**Notes:**

- `MeshJob` is the cross-runtime parameter marker; on the consumer
  side it downcasts to `MeshJobSubmitter`, on the producer side to
  `JobController`. Same DDDI lookup pipeline (resolution, trust,
  tags) — only the proxy class differs.
- `JobProxy` is `AutoCloseable` — use try-with-resources to ensure
  the underlying poller releases its registry watcher.
- `proxy.await(timeoutSeconds)` returns the producer's `complete()`
  payload on success; throws `JobFailedException`,
  `JobCancelledException`, or `JobTimeoutException` on the other
  terminal states.

## `SubmitOptions`

```java
public record SubmitOptions(
    Object args,                  // Map of args forwarded to the tool
    String ownerInstanceId,       // optional: pin to a replica
    Integer maxDuration,          // per-attempt soft timeout (sec); also sizes the lease + floors the stale ceiling
    Integer maxRetries,           // retries beyond initial attempt
    Integer totalDeadline         // hard ceiling across attempts (seconds)
) { }
```

## `retryOn` (per-tool exception whitelist)

`retryOn` is a `Class<? extends Throwable>[]` of exception classes
that should be treated as transient. When the handler throws a
matching exception, the SDK calls `releaseLease(reason)` instead of
`fail(reason)` — the registry resets the owner and a peer replica
re-runs the handler within ~5 seconds. Anything **not** in `retryOn`
still goes through `fail()` and surfaces to the consumer immediately.

```java
import java.io.IOException;

@MeshTool(
    capability = "report_with_transient_failures",
    task = true,
    retryOn = IOException.class                    // class literal (or array)
)
public Map<String, Object> reportWithTransientFailures(
        @Param("user_id") String userId,
        @Param(value = "transient_failures", required = false)
            Integer transientFailures,
        MeshJob job) throws IOException {

    int target = transientFailures == null ? 2 : transientFailures;
    int n = bumpRetryCounter();
    if (n <= target) {
        // retryOn=IOException.class matches → dispatch wrapper calls
        // releaseLease(reason) instead of fail(reason). The registry
        // hands the job to a peer (or this replica's next claim cycle)
        // within ~5 seconds.
        throw new IOException(
            "simulated transient failure " + n + "/" + target);
    }

    JobController controller = job instanceof JobController c ? c : null;
    Map<String, Object> payload = new LinkedHashMap<>();
    payload.put("user_id", userId);
    payload.put("succeeded_on_attempt", n);
    if (controller != null) {
        controller.complete(payload);
    }
    return payload;
}
```

**Multiple classes:**

```java
@MeshTool(
    capability = "...",
    task = true,
    retryOn = { IOException.class, TimeoutException.class }
)
```

**Validation:**

- `retryOn` requires `task = true` — registration fails at agent boot
  otherwise. Same for non-`Throwable` subclass entries (caught at
  compile time via the bound).
- Misuse surfaces at startup, not at retry time.

Retries restart the handler from scratch — there are no idempotency
keys in v2.x. If the handler has external side effects, design for
at-least-once: deterministic ids the downstream can dedupe on, or a
"claim → check → execute → mark done" pattern keyed off `job_id`.

## Cancellation

```java
// Consumer-side: cancel an in-flight job
proxy.cancel("user requested abort");
```

The registry forwards the cancel to the owner replica via
`POST /jobs/{id}/cancel` (auto-registered on every agent's HTTP
server). On the producer side, the cancel token fires:

- Handlers cannot rely on `Thread#sleep` being interrupted — Java's
  `Thread.interrupt()` cannot be signaled by the Tokio cancel token
  firing on the registry side. Long-running task handlers MUST poll
  `controller.isCancelled()` between work units (the cooperative
  model), OR park on `controller.recvEvent(List.of("cancelled", ...),
  ...)` to observe the synthetic cancel event (see [Event
  injection](#event-injection) below).
- Outbound `McpMeshTool` proxy calls abort their underlying HTTP
  request (cancel propagates through `X-Mesh-Job-Id` header binding).

The registry treats cancel as terminal (idempotent — already-terminal
jobs return ok without re-firing).

## Event injection

Per-job append-only event log every running job carries. Anyone with
the `jobId` writes; the running handler drains.

**Inside a `task = true` handler — receive events:**

```java
@MeshTool(capability = "run_workflow", task = true)
public Map<String, Object> runWorkflow(
    @Param("tenant_id") String tenantId,
    MeshJob job) throws Exception {
  JobController controller = (JobController) job;
  while (true) {
    Map<String, Object> event = controller.recvEvent(
        List.of("user_input", "cancelled"),
        Duration.ofSeconds(10));
    if (event == null) continue;       // clean timeout
    if ("cancelled".equals(event.get("type"))) {
      return Map.of("status", "cancelled");
    }
    // ...handle user_input...
  }
}
```

**Outside the handler, with a `jobId` in scope — fire an event:**

```java
import io.mcpmesh.MeshJobs;

@MeshTool(capability = "submit_user_input")
public Map<String, Object> submitUserInput(
    @Param("job_id") String jobId,
    @Param("text") String text) {
  Map<String, Object> receipt = MeshJobs.postEvent(
      jobId, "user_input", Map.of("text", text));
  return Map.of("seq", receipt.get("seq"));
}
```

`MeshJobs.postEvent` is the canonical fire-and-forget. It resolves
the registry from `MCP_MESH_REGISTRY_URL` and reuses a process-wide
LRU cache keyed by `(registryUrl, jobId)` (default cap 256; tune via
`MCP_MESH_JOBPROXY_CACHE_MAX`). If the calling code already holds a
`JobProxy`, use `proxy.sendEvent(eventType, payload)` directly.

**Typed exceptions** (both extend `MeshException`):

- `JobNotFoundException` — job swept or id typo
- `JobTerminalException` — job already terminal, no more events accepted

**Request input — pause for an external answer.** A `task = true`
handler that needs a human (or another agent) to supply something
mid-run calls `requestInput(prompt)` to transition the job to
`input_required`, then parks on `recvEvent` for the answer:

```java
@MeshTool(capability = "approve_spend", task = true)
public Map<String, Object> approveSpend(
    @Param("amount") double amount,
    MeshJob job) throws Exception {
  JobController controller = (JobController) job;

  // 1. Signal the consumer we're blocked on input. The prompt rides the
  //    job's progress_message field; status flips to "input_required".
  controller.requestInput("Approve $" + amount + "? Reply yes/no.");

  // 2. Park on the answer (no busy-wait — long-polls the event log).
  Map<String, Object> event = controller.recvEvent(
      List.of("answer"), Duration.ofSeconds(300));
  if (event == null) {
    controller.fail("timed out waiting for approval");
    return Map.of("status", "timeout");
  }

  // 3. Resume and finish. complete()/fail() exit input_required.
  @SuppressWarnings("unchecked")
  Map<String, Object> payload = (Map<String, Object>) event.get("payload");
  boolean approved = payload != null && Boolean.TRUE.equals(payload.get("approved"));
  return Map.of("status", approved ? "approved" : "denied");
}
```

An external party answers by posting the matching event:

```java
MeshJobs.postEvent(jobId, "answer", Map.of("approved", true));
```

`requestInput` is **status-only**: it posts the `input_required`
transition (flushing immediately, since the consumer is blocked on it)
and returns — it does not await the answer. Awaiting is composed with
the existing `recvEvent` / `postEvent` event primitives, as above. The
transition is **non-terminal**: the handler keeps running.
`complete()` / `fail()` exit `input_required` (a mid-flight
resume-to-`working` primitive is a future follow-up).

## Lifecycle facades by `jobId`

Symmetric to `MeshJobs.postEvent` / `MeshJobs.subscribeEvents`: callers
that hold a `jobId` but no `JobProxy` reference drive the rest of the
post-submit lifecycle through static facades on `MeshJobs`. Same
registry-URL resolution + cached-proxy machinery — `cancel`, `status`,
`await` and `postEvent` all reuse the same underlying `JobProxy` for a
given `(registryUrl, jobId)`.

| Operation                | Static facade                              | Returns                                   |
| ------------------------ | ------------------------------------------ | ----------------------------------------- |
| Cancel a running job     | `MeshJobs.cancel(jobId[, reason])`         | `void`                                    |
| Read latest job state    | `MeshJobs.status(jobId)`                   | `Map<String, Object>` (registry Job row)  |
| Wait for terminal state  | `MeshJobs.await(jobId[, timeoutSecs])`     | `Object` (handler's `complete()` payload) |

```java
import io.mcpmesh.MeshJobs;

@MeshTool(capability = "abort_workflow")
public Map<String, Object> abortWorkflow(
    @Param("job_id") String jobId,
    @Param("reason") String reason) {
  MeshJobs.cancel(jobId, reason);
  return Map.of("cancelled", jobId);
}

@MeshTool(capability = "check_progress")
public Map<String, Object> checkProgress(@Param("job_id") String jobId) {
  Map<String, Object> snapshot = MeshJobs.status(jobId);
  return Map.of(
      "status", snapshot.get("status"),
      "progress", snapshot.get("progress"),
      "message", snapshot.get("progress_message"));
}

@MeshTool(capability = "run_to_completion")
public Map<String, Object> runToCompletion(@Param("job_id") String jobId) {
  Object result = MeshJobs.await(jobId, 300.0);
  return Map.of("result", result);
}
```

**Notes:**

- Named `await` (not `wait`) to avoid readability confusion with the
  inherited `Object.wait()` / `Object.wait(long)` /
  `Object.wait(long, int)` overload family, and to match the existing
  `JobProxy.await(double)` instance method.
- `cancel` is idempotent per the registry's contract — calling on an
  already-terminal job returns ok without re-firing. If the registry
  surfaces a conflict for some other reason, the facade re-classifies
  it as `JobTerminalException`.
- `await(jobId, timeoutSecs)` with `timeoutSecs <= 0.0` or non-finite
  values means "no timeout" (matches `JobProxy.await(double)` and the
  no-arg `MeshJobs.await(jobId)` overload). Positive finite waits the
  given seconds before surfacing a timeout error.
- `status` returns the full registry Job row (same shape
  `JobProxy.status()` exposes); keys always present include `id`,
  `capability`, `status`, `progress`, `progress_message`, `result`,
  `error`, `submitted_payload`, plus lease-tracking fields
  (`owner_instance_id`, `lease_expires_at`, `last_heartbeat_at`).
- `JobNotFoundException` is raised from any of the three when the
  registry doesn't know the `jobId` (sweep already removed it, or id
  typo). `JobTerminalException` is the conflict surface for `cancel`
  and `await` when the registry treats the targeted terminal state as
  a conflict.
- If the calling code already holds a `JobProxy`, the same surface is
  on the proxy directly: `proxy.cancel(reason)`, `proxy.status()`,
  `proxy.await(timeoutSecs)`. Skip the facade + cache lookup when you
  already have a proxy in scope.

**Synthetic cancel event**. When a consumer calls `proxy.cancel(
reason)`, the registry writes a synthetic event into the log before
HTTP-forwarding the cancel signal. A handler parked on `recvEvent(
List.of("cancelled", ...), ...)` observes the synthetic event and can
return cleanly. This is the recommended pattern for cancel-aware Java
handlers — `Thread#sleep` cannot be interrupted by the registry's
cancel token firing, so handlers that sleep between work units must
poll `controller.isCancelled()` between intervals; `recvEvent` on the
synthetic `"cancelled"` event type sidesteps the polling requirement
by tying cancel observation to the event channel. The registry waits
a small grace window before issuing the cancel-forward (default
200ms, tunable via `MCP_MESH_CANCEL_EVENT_GRACE_MS`, capped at 10s).

**Synthetic stale event**. When the registry reaps a job for exceeding
the `MCP_MESH_JOB_STALE_TIMEOUT` default ceiling (see **Reaping and
lease recovery**), it writes a synthetic
`{ "type": "stale", "payload": { "reason": "stale", "detail": "..." } }`
event into the log as it transitions the job to `failed`. A handler
parked on `recvEvent(List.of("stale", ...), ...)` observes the reaping
and can unwind cleanly:

```java
Map<String, Object> event =
    controller.recvEvent(List.of("stale", "cancelled"), Duration.ofSeconds(30));
if (event != null && "stale".equals(event.get("type"))) {
  Map<String, Object> payload = (Map<String, Object>) event.get("payload");
  return Map.of("status", "aborted", "reason", payload.get("detail"));
}
```

No SDK change is needed — `stale` is an ordinary event type, so the
existing `recvEvent` / stream paths surface it across every runtime.

## Stream subscription

Non-destructive observer iterator. Multiple subscribers can mirror
the same job's events independently — each subscription has its own
cursor, none disturb the producer's `recvEvent` drain.

```java
import io.mcpmesh.EventSubscription;
import io.mcpmesh.MeshJobs;
import io.mcpmesh.SubscribeOptions;

void mirror(String jobId) {
  SubscribeOptions opts = SubscribeOptions.builder()
      .types(List.of("progress", "ended"))
      .after(0L)
      .longPoll(Duration.ofSeconds(30))
      .build();
  try (EventSubscription sub = MeshJobs.subscribeEvents(jobId, opts)) {
    while (sub.hasNext()) {
      Map<String, Object> event = sub.next();
      downstream.publish(event);
      if ("ended".equals(event.get("type"))) break;
    }
  }
}
```

**`EventSubscription` is `Closeable` and blocking.** `hasNext()`
parks inside the long-poll until an event arrives or the iterator is
closed. Use try-with-resources so `close()` flips the "don't issue
another long-poll" flag deterministically when control leaves the
block. `close()` does **not** interrupt an in-flight FFI long-poll —
if you need fast shutdown, configure a shorter `longPoll` budget so
the in-flight call drains quickly.

**Use it for**: fan-out to a downstream queue / UI websocket /
metrics sink; third-party observer that mirrors events without being
the running handler; reconnect-from-cursor (persist `next_after`
between sessions). For the in-handler drain — where each event is
processed once — use `recvEvent` instead.

**Semantics:**

- `after(0)` (the default) starts from the beginning of the log; pass
  a higher value to skip historical events.
- Server-side `types` filter; the `next_after` watermark advances
  even on empty pages so filtered re-scans are O(1).
- No automatic terminal-state detection. The iterator runs until the
  caller breaks out of the loop, calls `close()`, or the registry
  raises `JobNotFoundException`. Applications signal end via a
  sentinel event type (e.g. `{"type": "ended"}`).

## Timeout propagation

Jobs use the `X-Mesh-Timeout` header (#656) to carry a per-attempt
deadline as **relative seconds remaining** for the current attempt
(not an absolute timestamp). The producer runtime stashes the deadline
in a `ThreadLocal` (or `ScopedValue` under Loom); outbound proxies
read it back and attach a recomputed `X-Mesh-Timeout` to downstream
requests.

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
- **Lease recovery.** Every accepted progress/heartbeat delta extends
  the owner's lease. A job whose lease expires with no further deltas —
  a wedged or silently-crashed handler — is reset to claimable while
  retries remain, or marked `failed` once the retry budget is spent.
  This includes jobs parked in `input_required`: if the producer stops
  extending the lease while waiting for an answer that never comes, the
  job is reclaimed rather than held forever.
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
ceiling — and/or emit periodic progress to keep the lease renewed. Set
`totalDeadline` if you want a hard total-runtime bound across all
attempts, or to opt out of the registry-wide stale ceiling entirely.

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
  `meshctl man streaming --java` — or combine: a job that calls a
  streaming tool internally and reports coarse progress via
  `updateProgress`.
- **No cross-runtime `retryOn` coercion.** Each runtime matches its
  own native exception classes. A Java
  `retryOn = IOException.class` does NOT propagate to a Python or
  TypeScript peer claiming the same capability — declare the
  whitelist separately on each runtime that hosts the capability.

## See Also

- `meshctl man streaming --java` — token-by-token progress
- `meshctl man audit` — `X-Mesh-Job-Id` + `X-Mesh-Timeout` propagation
- `meshctl man dependency-injection --java` — how DDDI resolves
  `MeshJob`-typed slots
- [`docs/concepts/jobs.md`](https://github.com/dhyansraj/mcp-mesh/blob/main/docs/concepts/jobs.md) — narrative concept doc with architecture overview
- [`examples/jobs-java/`](https://github.com/dhyansraj/mcp-mesh/tree/main/examples/jobs-java) — runnable producer + consumer pair (Java)
