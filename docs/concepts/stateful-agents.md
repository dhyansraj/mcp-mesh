# Stateful Agents

> Building agents that hold per-tenant state across multiple tool calls —
> without reinventing the runtime.

A single `@mesh.tool` call is stateless from the mesh's perspective: a
request arrives, a handler runs on a worker loop, a response goes out.
That's the right shape for most tools. But some agents are not a
function — they're a **session**: a debate that runs over many turns, a
multi-stage workflow with checkpoints, an aggregator that accumulates
inputs across calls. State has to survive between calls, survive a
replica restart, and (for long-running work) keep advancing even when no
client is actively waiting.

This page walks through the mesh-idiomatic decomposition for that
class of agent: a **state agent** that owns durable storage, an
**orchestrator agent** that runs the long-lived unit of work, and a
**client surface** (browser via `mesh.route`, MCP-aware clients via the
MCP transport) that talks to both. The pattern is small, but it pulls in
several primitives — MeshJob, DDDI, the worker-pool topology — so the
"why" matters as much as the "how."

## The problem

"Stateful" in mesh has a specific meaning:

- **Multiple tool calls touch shared state.** A debate agent has turns:
  turn N reads the transcript through turn N-1, appends, and writes
  back. A multi-tenant aggregator has one logical bucket per tenant
  that tool calls from many clients land into.
- **State outlives a single MCP request-response.** The client closes
  the connection, comes back five minutes later, picks up where they
  left off.
- **State survives replica restart.** Pods get evicted, deployments
  roll, OOMKills happen. The in-flight unit of work has to resume on a
  peer (or on the same pod after restart) without rewinding to zero.
- **Background work runs between user-driven calls.** A driver loop
  polls an upstream every 10 seconds; a workflow stage waits on an
  external signal; a timer fires at a deadline. None of this is gated
  on a user tool call landing.

The temptation when you hit this for the first time is to cache state
in process memory at the module level. The shape feels
natural — it's how FastAPI services without mesh usually look:

```python
# DON'T DO THIS in a multi-worker mesh agent.
import asyncpg
import mesh
from fastmcp import FastMCP

app = FastMCP("Bad State Agent")
_pool: asyncpg.Pool | None = None  # module-level cache

async def _get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool("postgres://...")
    return _pool

@app.tool()
@mesh.tool(capability="read_state")
async def read_state(tenant_id: str) -> dict:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchrow("SELECT * FROM state WHERE tenant=$1", tenant_id)
```

The first `read_state` call lands on worker loop A, lazily builds the
pool on loop A, returns. The second `read_state` call round-robins to
worker loop B. The pool's internal Futures were created on loop A; when
loop B tries to await them, asyncio throws:

```
RuntimeError: Task <Task pending name='Task-N'> got Future <Future pending>
attached to a different loop
```

Why does this happen? The Python runtime dispatches `async def`
`@mesh.tool` functions across a small pool of worker loops — default
`min(8, max(2, cpu_count()))`, always ≥ 2. The pool keeps `/health`,
`/livez`, registry heartbeats, and other concurrent tool calls
responsive even when one tool blocks. The trade-off: module-level
loop-bound resources (asyncpg pools, `redis.asyncio.Redis`,
`motor.motor_asyncio.AsyncIOMotorClient`, `aiohttp.ClientSession`) bind
to whatever loop created them and fail on every subsequent call that
lands on a different worker. The full topology is documented in
[the dependency-injection reference](../python/dependency-injection.md#single-worker-mode-for-shared-loop-bound-resources).

There are two clean answers to this problem in mesh. The simple one is
to collapse to a single worker loop with `MCP_MESH_TOOL_WORKERS=1`
(covered in [single-worker mode](../python/dependency-injection.md#single-worker-mode-for-shared-loop-bound-resources)).
The structural one — the one that survives replica restart, scales
horizontally, and composes with the rest of the mesh — is the
three-agent decomposition that follows.

## The mesh-idiomatic decomposition

Three agents. One owns durable state. One owns the long-running unit
of work. One (or more) is the user-facing surface. Each is independently
deployable, independently scalable, and binds to the rest of the mesh
via plain DDDI.

### State agent — stateless CRUD over durable storage

The state agent exposes `@mesh.tool` functions that read and write a
Postgres (or Redis) database. It does no business logic. It does no
long-running work. From mesh's perspective it's an ordinary CRUD
agent — every tool call is short, idempotent where possible, and
returns. The pool lives inside the agent process and (because the agent
is shaped for a single shared resource) runs with
`MCP_MESH_TOOL_WORKERS=1` so it can cache the pool at module level
without the cross-loop footgun.

Schema:

- An **event log** table — append-only record of every state mutation.
  Cheap to scan, replayable for audit / debugging.
- A **state snapshot** table — current state per logical key (tenant,
  session, workflow id). Read-optimized; reconstructed from the event
  log if it gets out of sync.
- A **pending_inputs** table — inbox for events that target a
  running workflow (covered in
  [Handling external events](#handling-external-events-during-a-run) below).

=== "Python"

    ```python
    import os
    import asyncpg
    import mesh
    from fastmcp import FastMCP

    app = FastMCP("State Agent")
    _pool: asyncpg.Pool | None = None  # safe: MCP_MESH_TOOL_WORKERS=1

    async def _pool_handle() -> asyncpg.Pool:
        global _pool
        if _pool is None:
            _pool = await asyncpg.create_pool(os.environ["DATABASE_URL"])
        return _pool

    @app.tool()
    @mesh.tool(capability="read_state")
    async def read_state(tenant_id: str) -> dict:
        pool = await _pool_handle()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT state FROM tenant_state WHERE tenant_id=$1",
                tenant_id,
            )
            return dict(row["state"]) if row else {}

    @app.tool()
    @mesh.tool(capability="append_event")
    async def append_event(tenant_id: str, event_type: str, payload: dict) -> dict:
        pool = await _pool_handle()
        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    "INSERT INTO event_log (tenant_id, event_type, payload) "
                    "VALUES ($1, $2, $3)",
                    tenant_id, event_type, payload,
                )
                await conn.execute(
                    "INSERT INTO tenant_state (tenant_id, state) "
                    "VALUES ($1, $2) "
                    "ON CONFLICT (tenant_id) DO UPDATE "
                    "SET state = tenant_state.state || EXCLUDED.state",
                    tenant_id, payload,
                )
        return {"ok": True}

    @mesh.agent(name="state-agent", http_port=9200, auto_run=True)
    class StateAgent: pass
    ```

Deployment env:

```yaml
env:
  MCP_MESH_TOOL_WORKERS: "1"      # collapse to one worker loop
  DATABASE_URL: "postgres://..."
```

This agent scales horizontally if you front it with Postgres-side
locking on the rows that need serialization — but for most state-agent
shapes the bottleneck is the database, not the agent.

### Orchestrator agent — `@mesh.tool(task=True)` MeshJob bodies

The orchestrator hosts the long-running unit of work. Each unit is one
`@mesh.tool(capability=..., task=True)` body. Inside the body:

- Call into the state agent for every mutation (no in-process state).
- Drive an LLM via `mesh.MeshLlmAgent`.
- Emit progress with `await job.update_progress(fraction, message)`.
- Persist after every meaningful step. If the pod dies, the next claim
  cycle reroutes the job (orphan reroute is mesh-managed — see
  [Long-Running Jobs](jobs.md)) and the new owner reads the latest snapshot
  from the state agent to know where to resume.

=== "Python"

    ```python
    import mesh
    from fastmcp import FastMCP
    from mesh import MeshJob

    app = FastMCP("Orchestrator")

    @app.tool()
    @mesh.tool(
        capability="run_workflow",
        task=True,
        dependencies=["read_state", "append_event"],
    )
    async def run_workflow(
        tenant_id: str,
        plan: list[str],
        job: MeshJob = None,
        read_state: mesh.McpMeshTool = None,
        append_event: mesh.McpMeshTool = None,
        llm: mesh.MeshLlmAgent = None,
    ) -> dict:
        if job is not None:
            await job.update_progress(0.0, "loading state")

        state = await read_state(tenant_id=tenant_id)
        completed = set(state.get("completed_stages", []))

        total = max(len(plan), 1)
        for i, stage in enumerate(plan):
            if stage in completed:
                continue  # resumed run skips finished stages

            # Real work for this stage.
            answer = await llm(f"Execute stage {stage} for tenant {tenant_id}")

            # Persist BEFORE acknowledging progress — on crash the state
            # agent is source of truth.
            await append_event(
                tenant_id=tenant_id,
                event_type="stage_completed",
                payload={"stage": stage, "result": answer,
                         "completed_stages": list(completed | {stage})},
            )
            completed.add(stage)

            if job is not None:
                await job.update_progress((i + 1) / total, f"{stage} done")

        result = {"tenant_id": tenant_id, "completed": list(completed)}
        if job is not None:
            await job.complete(result)
        return result

    @mesh.agent(name="orchestrator", http_port=9201, auto_run=True)
    class Orchestrator: pass
    ```

This body runs on mesh's default worker pool (no `WORKERS=1` here — the
agent is stateless from a resource-binding standpoint; all loop-bound
resources live across the boundary in the state agent's process).

### Client surface — `mesh.route` for web, MCP for tools

Both the browser and MCP-aware clients (over the MCP transport) hit the
same backend capabilities. A FastAPI route translates HTTP into a
MeshJob submit + wait:

=== "Python"

    ```python
    import mesh
    from fastapi import FastAPI
    from mesh import MeshJob
    from pydantic import BaseModel

    app = FastAPI()

    class StartRequest(BaseModel):
        tenant_id: str
        plan: list[str]

    @app.post("/api/workflows")
    @mesh.route(dependencies=["run_workflow"])
    async def start_workflow(
        body: StartRequest,
        run_workflow: MeshJob = None,
    ) -> dict:
        proxy = await run_workflow.submit(
            tenant_id=body.tenant_id, plan=body.plan, max_duration=3600,
        )
        return {"job_id": proxy.job_id}
    ```

The browser polls `__mesh_job_status` (or subscribes via SSE — see
[Streaming](streaming.md) for the progress-notification path) for
updates. An MCP client calls `run_workflow` directly through the
mesh as a normal tool that returns the `job_id`.

## Why this shape

Each piece of the decomposition pays for itself:

- **In-memory state is a cache; Postgres is authoritative.** When the
  orchestrator pod dies mid-stage, the next claim cycle hands the job
  to a peer. The peer reads the state-agent snapshot, sees which stages
  completed, and resumes. Lost in-flight CPU is bounded by the time
  between the last `append_event` and the crash — typically seconds.
- **MeshJob owns the long-running task lifecycle.** Orphan reroute on
  replica death, cancel propagation, progress streaming, per-attempt
  deadlines, retry-on-transient — all of that is the substrate's job,
  not yours. You write the body. See [Long-Running Jobs](jobs.md) for
  the full lifecycle.
- **Tool calls are stateless from mesh's perspective.** The orchestrator
  scales horizontally without coordination; the state agent scales
  horizontally with Postgres as the coordination point; the route agent
  scales horizontally trivially.
- **Loop-bound resources stay inside one process.** The asyncpg pool
  lives in the state agent (which runs `WORKERS=1`). No cross-loop
  sharing. No cross-process sharing. The pool is invisible to the
  orchestrator and to the route agent.

## Handling external events during a run

A common real-world wrinkle: while the workflow is running, the user
wants to interact with it — submit input mid-stage, change a parameter,
extend a deadline. The workflow body is sitting on an `await` inside an
LLM call or a state-agent write. It needs a channel to receive these
mid-flight signals.

### Today's pattern: inbox-via-state-agent

The state agent grows a `pending_inputs` table. The route agent writes
to it. The orchestrator polls it at iteration boundaries:

=== "Python"

    ```python
    # State agent — inbox writer (called by the route agent on user input)
    @app.tool()
    @mesh.tool(capability="enqueue_input")
    async def enqueue_input(tenant_id: str, input_type: str, payload: dict) -> dict:
        pool = await _pool_handle()
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO pending_inputs (tenant_id, input_type, payload, claimed) "
                "VALUES ($1, $2, $3, FALSE)",
                tenant_id, input_type, payload,
            )
        return {"ok": True}

    # State agent — inbox reader (called by the orchestrator each iteration)
    @app.tool()
    @mesh.tool(capability="claim_inputs")
    async def claim_inputs(tenant_id: str) -> list[dict]:
        pool = await _pool_handle()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "UPDATE pending_inputs SET claimed=TRUE "
                "WHERE tenant_id=$1 AND NOT claimed RETURNING input_type, payload",
                tenant_id,
            )
            return [{"input_type": r["input_type"], "payload": r["payload"]} for r in rows]
    ```

The orchestrator polls inside the loop:

=== "Python"

    ```python
    for i, stage in enumerate(plan):
        # Drain inbox at the iteration boundary
        inputs = await claim_inputs(tenant_id=tenant_id)
        for inp in inputs:
            # Apply mid-flight input — e.g., update parameters, abort stage
            ...

        # ... run the stage as before ...
    ```

The latency cost is one HTTP round-trip per poll. Against the cost of
the LLM call or the work itself, that's noise.

### Limitations of polling

Polling works when the workflow naturally cycles through iteration
boundaries. It does **not** work for sub-iteration events: if your body
is parked on a long `asyncio.sleep_until(deadline)` or inside a single
streaming LLM call that runs for two minutes, the user clicking "extend
my deadline" lands in `pending_inputs` and sits there until the next
boundary — which may be after the event was useful.

### Sub-iteration events: mesh-managed event channel (shipped in v2.2)

The sub-iteration gap above closes with **MeshJob event injection** —
a per-job, ordered, append-only event log every running job carries.
Anyone holding the `job_id` posts into the log; the running handler
drains it inline. Producer-side `proxy.send_event(payload)` (or
`mesh.jobs.post_event(job_id, ...)` from a caller that doesn't already
have a proxy), consumer-side `await job.recv_event(types=[...],
timeout_secs=...)` inside the handler body. Cross-runtime parity
(Python / TypeScript / Java).

For long-lived observers that want to mirror events without consuming
them, the **stream subscription** counterpart opens a non-destructive
iterator with per-call cursor — multiple subscribers can mirror the
same job's events independently. See
[Event injection](jobs.md#event-injection) and
[Stream subscription](jobs.md#stream-subscription) on the Jobs page
for the canonical surface, cross-runtime examples, and the synthetic
cancel-event pattern that gives handlers a graceful shutdown path.

The inbox-via-state-agent pattern above still has its place — it's the
right tool when the workflow naturally syncs at iteration boundaries
and the state agent's storage is also where you want the inbox to
live. Reach for the event channel when sub-iteration latency matters:
a handler parked on a long `recv_event` wakes the moment the event is
posted, not on the next boundary.

## Cancel and graceful shutdown

A long-running job needs a clean termination story. There are two cases:

- **Consumer cancels** via `JobProxy.cancel(reason)`. The owner replica
  receives the cancel signal and (today) raises `CancelledError` into
  the running handler. Once #1032 lands, handlers that subscribe to
  events will see a synthetic `{"type":"cancelled","reason":...}`
  event instead, which they can handle inline rather than via
  exception. Either way: persist final state to the state agent in a
  `finally` block before the handler exits.
- **Replica shutdown** (SIGTERM during pod eviction / deployment
  rollout). The runtime's lifespan exit phase fires (fix shipped in
  #1029 — the exit phase is now honored on SIGTERM rather than skipped),
  any registered cleanup runs, and the registry sees the agent
  disappear. In-flight jobs become orphans and reroute to a peer
  within ~5 seconds.

The contract for the handler body:

=== "Python"

    ```python
    @app.tool()
    @mesh.tool(capability="run_workflow", task=True, ...)
    async def run_workflow(...):
        try:
            ...  # main loop
        except asyncio.CancelledError:
            # Persist what we've done so far so the next attempt can resume.
            await append_event(
                tenant_id=tenant_id, event_type="cancelled",
                payload={"completed_stages": list(completed)},
            )
            raise
        finally:
            # Anything that must run regardless of outcome — flush
            # metrics, close per-tenant resources, etc.
            ...
    ```

## What NOT to do

A handful of anti-patterns this decomposition exists to prevent:

- **Dedicated background-thread engine with `loop.run_forever()`.** The
  pattern looks like: spawn a thread at agent startup, give it its own
  `asyncio.new_event_loop()`, run an engine on that loop, and bridge
  `@mesh.tool` handlers into it via `asyncio.run_coroutine_threadsafe`.
  This re-invents MeshJob — orphan reroute, cancel propagation,
  per-attempt deadlines — in application code, and breaks horizontal
  scaling because state pins the agent to one replica. It also drags
  in hand-rolled cross-thread plumbing (`sys.modules['__main__']`
  lookups for DI-wired functions, `dependency_kwargs.timeout` knobs
  for long-poll). There IS a narrow class of agents where this
  pattern is the right answer (GPU contexts, real-time aggregators
  with sub-10ms latency budgets) — see
  [In-Process State](in-process-state.md) — but it should never be
  the default reach.
- **Module-level state without `MCP_MESH_TOOL_WORKERS=1`.** Don't
  cache asyncpg pools, redis clients, or any other loop-bound resource
  at module level on default workers. It will work the first call.
  It will fail the second. The fix is either single-worker mode
  ([details](../python/dependency-injection.md#single-worker-mode-for-shared-loop-bound-resources))
  or moving the resource into a dedicated state agent (the pattern
  above).
- **Putting orchestration state on the orchestrator process.** The
  orchestrator's job body should be a pure transformer: read state in,
  drive work, write state out. The moment it caches anything across
  tool calls, restart recovery breaks.

## See Also

- [Long-Running Jobs](jobs.md) — MeshJob substrate: lifecycle, retries,
  cancel, orphan reroute, `task=True` opt-in
- [Streaming](streaming.md) — progress notifications and chunked text
  responses; pairs with MeshJob for live updates
- [In-Process State (Escape Hatch)](in-process-state.md) — when even
  MeshJob can't fit your shape, with documented caveats
- [Single-Worker Mode](../python/dependency-injection.md#single-worker-mode-for-shared-loop-bound-resources)
  — the `MCP_MESH_TOOL_WORKERS=1` flag and when to use it
- `meshctl man dependency-injection` — DDDI and worker-loop topology
