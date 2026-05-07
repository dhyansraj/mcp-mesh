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

## What's NOT in Phase B

- Idempotency keys for retries (Phase 3).
- Resumable checkpoints (Phase 3).
- Webhook/SSE notifications (Phase 3).
- SEP-1686 wire surfacing (Phase 2 — strictly additive on top).

See `MESHJOB_DESIGN.org` at the repo root for the full roadmap.
