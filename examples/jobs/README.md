# MeshJob Phase 1 Examples

Two minimal agents demonstrating the producer + consumer pattern for
long-running tasks with `MeshJob`.

## Layout

- `long-task-provider/main.py` — registers `generate_report` as a
  `task=True` tool. Hosts the producer-side `JobController` flow:
  progress updates, structured terminal results.
- `long-task-consumer/main.py` — registers `commission_report` which
  depends on `generate_report`. Demonstrates the consumer-side
  `MeshJobSubmitter.submit(...)` + `JobProxy.wait(...)` pattern.

## Quick start

In three terminals:

```bash
# Terminal 1 — registry
cd src/core/registry
go run ./cmd/registry

# Terminal 2 — provider (port 9100)
MCP_MESH_REGISTRY_URL=http://localhost:8000 \
  python3 examples/jobs/long-task-provider/main.py

# Terminal 3 — consumer (port 9101)
MCP_MESH_REGISTRY_URL=http://localhost:8000 \
  python3 examples/jobs/long-task-consumer/main.py
```

Then commission a report by calling the consumer's `commission_report`
tool — for example via `meshctl`:

```bash
meshctl call long-task-consumer commission_report \
  --arg user_id=demo --arg sections='["intro","analysis","summary"]'
```

You should see:

1. Consumer logs `📨 MESH_JOB_INJECTION: Injected MeshJobSubmitter`.
2. Consumer's `submit(...)` posts to `POST /jobs` on the registry.
3. Provider's claim worker (or the registry's owner-pinning if push-mode)
   picks up the job and dispatches to `generate_report`.
4. Provider emits progress updates (~6s total for the three sections).
5. Consumer's `wait(...)` returns the structured `report` payload.

## Inspecting in flight

While a job is running, hit any agent (or `meshctl`) for status:

```bash
meshctl call long-task-provider __mesh_job_status \
  --arg job_id=<uuid-from-submit>
```

The three framework helper tools are auto-registered on every mesh
agent — they read the registry directly, so any replica can serve
reads even if the job is "owned" by a different one.

## Cancelling

```bash
meshctl call long-task-provider __mesh_job_cancel \
  --arg job_id=<uuid> --arg reason="user requested abort"
```

The registry forwards the cancel to the owner replica via
`POST /jobs/{id}/cancel` (registered on every agent's FastAPI app),
which fires the in-process cancel token and aborts the in-flight job.

## What's NOT in Phase 1

- Idempotency keys for retries (Phase 3).
- Resumable checkpoints (Phase 3).
- Webhook/SSE notifications (Phase 3).
- SEP-1686 wire surfacing (Phase 2 — strictly additive on top).

See `MESHJOB_DESIGN.org` at the repo root for the full roadmap.
