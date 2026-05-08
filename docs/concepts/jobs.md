# Long-Running Jobs

> Submit-and-wait task execution that survives `tools/call` timeouts, replica
> restarts, and consumer disconnects.

A regular `tools/call` is a request-response pair on a single open HTTP/SSE
connection. If the work takes minutes — generating a multi-section report,
transcoding a video, running a long agentic loop — the client and server
spend that whole time holding a socket open and gambling that nothing in
between (load balancers, proxies, k8s pod restarts) drops the connection.
**MeshJob** is a different primitive for that class of work: producers
declare a tool as `task=true`, consumers `submit` and later `wait`, and the
registry holds the durable state in between.

## The problem

`tools/call` is fine for sub-second to ~30s tools. For anything longer:

- **Connection fragility.** Any hop (browser, ingress, mesh) drops idle
  HTTP after 60–120s. The producer keeps computing; the consumer sees a
  generic timeout and has no handle to recover.
- **No backpressure.** The producer can't tell the consumer "I'm 60% done,
  ETA 90 seconds." The consumer waits blind.
- **No cancel.** A consumer that gives up has no way to tell the producer
  to stop burning CPU.
- **No retry semantics.** A transient upstream error (rate-limit, network
  blip) on attempt 1 of a 5-minute job means restarting from scratch on the
  consumer's clock.

**Streaming** ([`streaming.md`](streaming.md)) solves the responsiveness
problem when the work is a single text stream — chunks flow back over the
already-open connection. **Jobs** solve the durability problem when the
work is a discrete unit that needs to outlive the request: the connection
closes, the producer keeps going, the consumer reconnects (or polls) for
the result.

## Solution: `task=true` opt-in

Authors annotate the tool with `task=true` and accept an injected
controller (`MeshJob`) that exposes `update_progress`, `complete`, and
`fail`. Consumers declare a dependency on the producer's capability and
type the parameter as `MeshJob` — the framework injects a
`MeshJobSubmitter` (instead of the usual `McpMeshTool` proxy) at that
slot. `submitter.submit(...)` returns a `JobProxy`; `proxy.wait(...)`
polls the registry until the row is terminal.

There's no global config knob. Whether a tool is a job is opt-in per
tool by virtue of `task=true`. Plain `task=false` tools continue to be
buffered request-response exactly as before.

## Getting started

A producer that emits progress updates and a consumer that submits-and-
waits — the canonical end-to-end pattern. The full files live under
[`examples/jobs/`](https://github.com/dhyansraj/mcp-mesh/tree/main/examples/jobs),
[`examples/jobs-ts/`](https://github.com/dhyansraj/mcp-mesh/tree/main/examples/jobs-ts),
and [`examples/jobs-java/`](https://github.com/dhyansraj/mcp-mesh/tree/main/examples/jobs-java).

<!-- markdownlint-disable MD046 -->
**Producer — declares a `task=true` capability:**

=== "Python"

    ```python
    import asyncio
    import mesh
    from fastmcp import FastMCP
    from mesh import MeshJob

    app = FastMCP("Long Task Provider")

    @app.tool()
    @mesh.tool(capability="generate_report", task=True)
    async def generate_report(
        user_id: str,
        sections: list[str],
        job: MeshJob = None,
    ) -> dict:
        if job is not None:
            await job.update_progress(0.0, "starting")
        results = []
        total = max(len(sections), 1)
        for i, section in enumerate(sections):
            await asyncio.sleep(2)
            results.append({"section": section, "content": f"...{section}"})
            if job is not None:
                await job.update_progress((i + 1) / total, f"section {i+1}/{total}")
        payload = {"user_id": user_id, "report": results}
        if job is not None:
            await job.complete(payload)
        return payload

    @mesh.agent(name="long-task-provider", http_port=9100, auto_run=True)
    class LongTaskProvider: pass
    ```

=== "TypeScript"

    ```typescript
    import { FastMCP } from "fastmcp";
    import { mesh, type MeshJob } from "@mcpmesh/sdk";
    import { z } from "zod";

    const server = new FastMCP({ name: "Long Task Provider (TS)", version: "1.0.0" });
    const agent = mesh(server, { name: "long-task-provider-ts", httpPort: 9110 });

    agent.addTool({
      name: "generate_report",
      capability: "generate_report",
      task: true,
      meshJobParamIndex: 1,         // job lands at sig pos 1 (after `args`)
      parameters: z.object({
        user_id: z.string(),
        sections: z.array(z.string()),
      }),
      execute: async ({ user_id, sections }, job: MeshJob | null = null) => {
        await job?.updateProgress?.(0.0, "starting");
        const results: { section: string; content: string }[] = [];
        const total = Math.max(sections.length, 1);
        for (let i = 0; i < sections.length; i++) {
          await new Promise((r) => setTimeout(r, 2000));
          results.push({ section: sections[i], content: `...${sections[i]}` });
          await job?.updateProgress?.((i + 1) / total, `section ${i+1}/${total}`);
        }
        const payload = { user_id, report: results };
        await job?.complete?.(payload);
        return payload;
      },
    });
    ```

=== "Java"

    ```java
    @MeshAgent(name = "long-task-provider-java", port = 9120)
    @SpringBootApplication
    public class LongTaskProviderApplication {

      public static void main(String[] args) {
        SpringApplication.run(LongTaskProviderApplication.class, args);
      }

      @MeshTool(capability = "generate_report", task = true)
      public Map<String, Object> generateReport(
          @Param("user_id") String userId,
          @Param("sections") List<String> sections,
          MeshJob job) throws InterruptedException {
        JobController controller = job instanceof JobController c ? c : null;
        if (controller != null) controller.updateProgress(0.0, "starting");
        List<Map<String, String>> results = new ArrayList<>();
        int total = Math.max(sections.size(), 1);
        for (int i = 0; i < sections.size(); i++) {
          Thread.sleep(2000);
          results.add(Map.of("section", sections.get(i), "content", "..."));
          if (controller != null) {
            controller.updateProgress((i + 1.0) / total, "section " + (i+1) + "/" + total);
          }
        }
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("user_id", userId);
        payload.put("report", results);
        if (controller != null) controller.complete(payload);
        return payload;
      }
    }
    ```

**Consumer — submits and waits:**

=== "Python"

    ```python
    import mesh
    from fastmcp import FastMCP
    from mesh import MeshJob

    app = FastMCP("Long Task Consumer")

    @app.tool()
    @mesh.tool(capability="commission_report", dependencies=["generate_report"])
    async def commission_report(
        user_id: str,
        sections: list[str],
        # Param name MUST match the dependency capability — that pairing
        # is what makes the slot a MeshJobSubmitter (not a McpMeshTool proxy).
        generate_report: MeshJob = None,
    ) -> dict:
        proxy = await generate_report.submit(
            user_id=user_id, sections=sections, max_duration=60,
        )
        return await proxy.wait(timeout_secs=60)
    ```

=== "TypeScript"

    ```typescript
    agent.addTool({
      name: "commission_report",
      capability: "commission_report",
      dependencies: [{ capability: "generate_report" }],
      meshJobDepIndex: 0,            // dep[0] is task=true → MeshJobSubmitter
      parameters: z.object({
        user_id: z.string(),
        sections: z.array(z.string()),
      }),
      execute: async (
        { user_id, sections },
        generateReport: MeshJob | null = null,
      ) => {
        const proxy = await generateReport!.submit!(
          { user_id, sections },
          { maxDuration: 60 },
        );
        return await proxy.wait!(60);
      },
    });
    ```

=== "Java"

    ```java
    @MeshTool(
        capability = "commission_report",
        dependencies = @Selector(capability = "generate_report"))
    public Map<String, Object> commissionReport(
        @Param("user_id") String userId,
        @Param("sections") List<String> sections,
        MeshJob generateReport) throws Exception {
      MeshJobSubmitter submitter = (MeshJobSubmitter) generateReport;
      Map<String, Object> payload = new LinkedHashMap<>();
      payload.put("user_id", userId);
      payload.put("sections", sections);
      var opts = new MeshJobSubmitter.SubmitOptions(payload, null, 60, null, null);
      try (JobProxy proxy = submitter.submit(opts).get()) {
        return (Map<String, Object>) proxy.await(60.0);
      }
    }
    ```
<!-- markdownlint-enable MD046 -->

`submit(...)` posts to the registry's `POST /jobs` and returns a
`JobProxy` bound to the new `job_id`. `wait(...)` polls
`GET /jobs/{id}` until the status is terminal (`completed`, `failed`,
or `cancelled`) and returns the producer's `complete()` payload (or
raises on failure / cancel / timeout).

## Retry semantics

A failed attempt does not mean a failed job. The mesh distinguishes
**explicit failure** (the handler decided this is unrecoverable) from
**transient failure** (the handler hit a retryable error class), and
re-runs only the latter on a peer replica.

### `max_retries` (Sidekiq/Celery convention)

`max_retries` counts retries **beyond** the initial attempt. So
`max_retries=3` means up to 4 total attempts. The default is conservative
— check your runtime's per-tool default and set explicitly when in doubt.

!!! warning "Retries restart from scratch"

    There are no idempotency keys in v2.x. Every retry runs the handler
    body from the top. If the work has external side effects (sending
    email, charging a card, mutating a remote DB), make the handler
    **idempotent** or design for at-least-once semantics — e.g.,
    deterministic IDs the downstream can dedupe on, or a "claim → check →
    execute → mark done" pattern keyed off the `job_id`.

### `retry_on` (per-tool exception whitelist)

`retry_on` is a per-tool list of exception classes that should be treated
as transient. When the handler raises a matching exception, the SDK calls
`releaseLease(reason)` instead of `fail(reason)`: the registry resets the
owner, and a peer replica (or the same replica on the next claim cycle)
re-runs the handler within ~5 seconds. Anything **not** in `retry_on`
still goes through `fail()` and surfaces to the consumer immediately.

The canonical pattern: a tool that calls a flakey upstream raises
`OSError` / `IOException` / `TransientUpstreamError` on the first N
attempts, succeeds on attempt N+1.

<!-- markdownlint-disable MD046 -->
=== "Python"

    ```python
    @app.tool()
    @mesh.tool(
        capability="report_with_transient_failures",
        task=True,
        retry_on=(OSError,),
    )
    async def report_with_transient_failures(
        user_id: str,
        transient_failures: int = 2,
        job: MeshJob = None,
    ) -> dict:
        n = _bump_retry_counter()
        if n <= transient_failures:
            # SDK matches retry_on=(OSError,) → calls release_lease(),
            # NOT fail() — the registry hands the job to a peer within ~5s.
            raise OSError(f"simulated transient failure {n}/{transient_failures}")
        payload = {"user_id": user_id, "succeeded_on_attempt": n}
        if job is not None:
            await job.complete(payload)
        return payload
    ```

=== "TypeScript"

    ```typescript
    class TransientUpstreamError extends Error {}

    agent.addTool({
      name: "report_with_transient_failures",
      capability: "report_with_transient_failures",
      task: true,
      meshJobParamIndex: 1,
      retryOn: [TransientUpstreamError],
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
          throw new TransientUpstreamError(`transient ${n}/${transient_failures}`);
        }
        const payload = { user_id, succeeded_on_attempt: n };
        await job?.complete?.(payload);
        return payload;
      },
    });
    ```

=== "Java"

    ```java
    @MeshTool(
        capability = "report_with_transient_failures",
        task = true,
        retryOn = IOException.class)
    public Map<String, Object> reportWithTransientFailures(
        @Param("user_id") String userId,
        @Param(value = "transient_failures", required = false) Integer transientFailures,
        MeshJob job) throws IOException {
      int target = transientFailures == null ? 2 : transientFailures;
      int n = bumpRetryCounter();
      if (n <= target) {
        // retryOn=IOException matches → dispatch wrapper calls
        // releaseLease(reason) instead of fail(reason).
        throw new IOException("simulated transient failure " + n + "/" + target);
      }
      JobController controller = job instanceof JobController c ? c : null;
      Map<String, Object> payload = new LinkedHashMap<>();
      payload.put("user_id", userId);
      payload.put("succeeded_on_attempt", n);
      if (controller != null) controller.complete(payload);
      return payload;
    }
    ```
<!-- markdownlint-enable MD046 -->

**Validation is loud.** `retry_on` requires `task=true`; misuse (string
entries, non-`Error` classes) fails at registration so it surfaces at
agent boot, not at retry time. Both `report_with_transient_failures`
fixtures (Python `tests/integration/suites/uc21_meshjob/fixtures/long-task-provider/main.py`
and Java `tests/integration/suites/uc23_meshjob_java/fixtures/long-task-provider-java/`)
exercise this end-to-end with a file-based attempt counter that lets
the test assert "succeeded on attempt 3" deterministically.

## Timeout propagation

Jobs use the existing `X-Mesh-Timeout` header (#656) to carry a
**per-attempt deadline** — relative seconds remaining for the current
attempt, not an absolute timestamp. The provider runtime parses the
header on inbound, stashes the deadline in an async-local primitive,
and outbound proxies (any `McpMeshTool` call the handler makes) read
the same primitive and attach `X-Mesh-Timeout: <remaining>` to their
own downstream requests.

| Runtime    | Async-local primitive                          |
|------------|------------------------------------------------|
| Python     | `contextvars.ContextVar("mesh_job_deadline")`  |
| TypeScript | `AsyncLocalStorage`                            |
| Java       | `ThreadLocal` (or `ScopedValue` for Loom)      |

**Nested job cap.** When a parent job calls a child job, the child's
deadline is `min(parent_remaining, child_requested)`. If the parent
has 5 seconds left on its attempt and the child's `submit(...)`
requests `max_duration=30`, the child gets 5 seconds. This is enforced
at submission time so the child's runtime sees a single coherent
deadline regardless of how deep the chain runs.

The header is on the default `MCP_MESH_PROPAGATE_HEADERS` allowlist
alongside `X-Mesh-Job-Id`, `X-Mesh-Trace-Id`, etc. — no per-agent
configuration is needed for propagation to work. Tracing this in
[Audit Trail](audit.md) shows the deadline shrinking as it walks the
chain.

## meshctl

Three SDK-managed helper tools are exposed on every mesh agent for
out-of-band job inspection. They are not separate `meshctl` subcommands
— they are regular MCP tools, prefixed with `__mesh_job_` to mark them
framework-internal, that you reach via `meshctl call`:

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
`commission_report` in the example above), which is the wrapper that
calls `submitter.submit(...)` internally. There is no
`__mesh_job_submit` helper — kicking off a job always goes through a
consumer tool, because the submitter needs to know which capability
to route to and which retry / deadline policy to apply.

The Dashboard also lists active jobs and exposes the same status /
cancel actions over the registry HTTP API directly, useful when
debugging from a browser instead of a shell.

## Auth model

`job_id` is a **presigned-URL-style capability**. Possession of a valid
`job_id` (~122 bits of entropy from a UUID) grants full status / result
/ cancel rights on that job, with no additional caller-identity check.
Reads and writes against the registry's `/jobs/{id}` endpoints are not
authenticated by design: the secret IS the URL fragment.

!!! warning "Leak the id, leak the job"

    Treat `job_id` like a presigned S3 URL. Anyone who learns it can
    cancel the work or read the result, including any error payload it
    surfaced. Don't log job ids to a system that has a wider audience
    than the consumer that issued them. Don't return them to a
    third-party browser unless you intend that party to control the
    job. If a job carries sensitive payloads, scrub them out of the
    `complete()` body too — the result lives in the registry until the
    sweep cron expires it.

In v2.x there is **no opt-in caller-identity verification**. Future
work (tracked in `MESHJOB_DESIGN.org`) will add an optional SPIRE-
based mode that matches the calling SVID against the job's submitter
on cancel / status, for environments that need stricter isolation.

## Architecture overview

The **registry** is the durable substrate. It's a Go service backed by
PostgreSQL (or SQLite for `--singlepass` dev mode); jobs live in a
`jobs` table with `status`, `owner_instance_id`, `lease_expires_at`,
`attempt_count`, `progress`, and `result` columns. A periodic sweep
loop reaps orphaned jobs (owner crashed, lease expired) and enforces
`total_deadline` as a separate safety net beyond the per-attempt
`max_duration`. All status transitions land in the same Postgres row,
so any consumer that holds the `job_id` sees the latest state on the
next poll regardless of which replica owns the job.

The **agent runtime** is a thin client. On the producer side, it
maintains a claim queue per `task=true` capability (`UPDATE jobs SET
owner_instance_id = $self WHERE capability = $cap AND status =
'pending'` is the atomic claim), runs the handler with an injected
`JobController`, and batches progress / terminal POSTs back to the
registry on a tick interval (terminal calls flush immediately). Cancel
signals bind a registry watcher to the in-flight handler's cancel
token, so `proxy.cancel(...)` from any consumer fires the token on the
owner replica and outbound HTTP proxies abort their requests too.

**DDDI is the injection layer.** The producer's `MeshJob` parameter
lands at `meshJobParamIndex` (Python and Java auto-detect it from the
type annotation; TS declares it explicitly in `addTool`). The
consumer's `MeshJob` parameter — typed identically, but on a slot
named after a dependency capability — gets a `MeshJobSubmitter`
instead of an `McpMeshTool` proxy: same DDDI lookup, different
injection target based on the dep's `task=true` flag. Resolution,
trust, and tag matching are unchanged from the regular tool path; the
only difference is the runtime swaps the proxy class at the dep slot.
For the full design rationale and lifecycle diagrams, see
[`MESHJOB_DESIGN.org`](https://github.com/dhyansraj/mcp-mesh/blob/main/MESHJOB_DESIGN.org)
and [`MESHJOB_DDDI_CONTRACT.md`](https://github.com/dhyansraj/mcp-mesh/blob/main/MESHJOB_DDDI_CONTRACT.md).

## What it does NOT do (v2 limitations)

- **No idempotency keys.** Retries restart the handler from scratch;
  the SDK does not dedupe partial side effects. Make handlers
  idempotent if at-least-once semantics are not acceptable.
- **No caller-identity check on `job_id`.** Possession of the id is
  the only auth. SPIRE-based opt-in is future work.
- **No streaming-style chunked progress.** `update_progress(fraction,
  message)` flushes through the registry on a batching tick. For
  token-by-token feedback, use [streaming](streaming.md) instead — or
  combine: a job that calls a streaming tool internally and reports
  coarse progress via `update_progress`.
- **No cross-runtime retry-on whitelist coercion.** Each runtime
  matches its own native exception classes (Python `Exception`
  subclasses, TS `Error` subclasses, Java `Throwable` subclasses).
  A Python provider's `retry_on=(OSError,)` does not propagate to a
  Java peer claiming the same capability — declare the whitelist
  separately on each runtime that hosts the capability.

## See Also

- [Streaming](streaming.md) — token-by-token progress for the request-
  response case where the work fits in a single SSE
- [Audit Trail](audit.md) — `progressToken`, `X-Mesh-Job-Id`, and
  `X-Mesh-Timeout` propagation through the audit pipeline
- [DDDI](dddi.md) — Distributed Dynamic Dependency Injection overview;
  explains how `MeshJob` slots are resolved
- [`MESHJOB_DESIGN.org`](https://github.com/dhyansraj/mcp-mesh/blob/main/MESHJOB_DESIGN.org)
  — full design doc with state machine, lifecycle, and SQL schema
- [`MESHJOB_DDDI_CONTRACT.md`](https://github.com/dhyansraj/mcp-mesh/blob/main/MESHJOB_DDDI_CONTRACT.md)
  — the cross-runtime injection contract every SDK implements
- [`examples/jobs/`](https://github.com/dhyansraj/mcp-mesh/tree/main/examples/jobs),
  [`examples/jobs-ts/`](https://github.com/dhyansraj/mcp-mesh/tree/main/examples/jobs-ts),
  [`examples/jobs-java/`](https://github.com/dhyansraj/mcp-mesh/tree/main/examples/jobs-java)
  — runnable producer + consumer pairs in all three runtimes
