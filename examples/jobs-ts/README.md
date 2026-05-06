# MeshJob Phase 1 — TypeScript Examples

TypeScript port of `examples/jobs/`. Two minimal agents demonstrating
the producer + consumer pattern for long-running tasks with `MeshJob`.

## Layout

- `long-task-provider-ts/index.ts` — registers `generate_report` as a
  `task: true` tool. Hosts the producer-side `JobController` flow:
  progress updates and structured terminal results.
- `long-task-consumer-ts/index.ts` — registers `commission_report`
  which depends on `generate_report` (with `meshJobDepIndex: 0` so the
  dep slot holds a `MeshJobSubmitter` instead of a regular proxy).
  Demonstrates the consumer-side `submit(...)` + `proxy.wait(...)`
  pattern.

## Quick start

```bash
# Install (once per example)
cd examples/jobs-ts/long-task-provider-ts && npm install
cd ../long-task-consumer-ts && npm install
```

In three terminals:

```bash
# Terminal 1 — registry
go run ./cmd/mcp-mesh-registry

# Terminal 2 — provider (port 9110)
MCP_MESH_REGISTRY_URL=http://localhost:8000 \
  npx tsx examples/jobs-ts/long-task-provider-ts/index.ts

# Terminal 3 — consumer (port 9111)
MCP_MESH_REGISTRY_URL=http://localhost:8000 \
  npx tsx examples/jobs-ts/long-task-consumer-ts/index.ts
```

Then commission a report by calling the consumer's `commission_report`
tool:

```bash
meshctl call long-task-consumer-ts:commission_report \
  '{"user_id": "demo", "sections": ["intro", "analysis", "summary"]}'
```

Expected flow:

1. Consumer's `submit(...)` posts to `POST /jobs` on the registry.
2. Provider's claim worker picks up the job and dispatches it to
   `generate_report` with a `JobController` injected at `meshJobParamIndex`.
3. Provider emits progress updates (~6s total for the three sections).
4. Consumer's `wait(...)` returns the structured `report` payload.

## Inspecting in flight

While a job is running, hit any agent for status — the helper tools
auto-register on every TS mesh agent:

```bash
meshctl call long-task-provider-ts:__mesh_job_status \
  '{"jobId": "<uuid-from-submit>"}'
```

The three framework helpers (`__mesh_job_status` / `__mesh_job_result`
/ `__mesh_job_cancel`) read directly from the registry, so any replica
can serve the request.
