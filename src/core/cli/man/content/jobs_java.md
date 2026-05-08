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
    Integer maxDuration,          // per-attempt soft timeout (seconds)
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

- Thread interrupt is signaled at the next `Thread.sleep` /
  `Object.wait` / blocking I/O — the handler should propagate
  `InterruptedException` rather than swallow it.
- Outbound `McpMeshTool` proxy calls abort their underlying HTTP
  request (cancel propagates through `X-Mesh-Job-Id` header binding).

The registry treats cancel as terminal (idempotent — already-terminal
jobs return ok without re-firing).

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
