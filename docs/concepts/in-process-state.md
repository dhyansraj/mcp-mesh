# In-Process State (Escape Hatch)

> When MeshJob can't fit your shape: in-process state with documented
> caveats.

The two patterns covered in [Stateful Agents](stateful-agents.md) cover
the overwhelming majority of stateful workloads in mesh:

- **Externalized state via a state agent + MeshJob orchestrator** —
  durable, horizontally scalable, restart-tolerant.
- **Single-worker mode** ([`MCP_MESH_TOOL_WORKERS=1`](../python/dependency-injection.md#single-worker-mode-for-shared-loop-bound-resources))
  — collapse to one worker loop, share a loop-bound resource at module
  level, give up parallel execution.

This page is for the **narrow class** of agents where neither of those
fits — typically because the state cannot tolerate the ~10ms HTTP
round-trip per mutation, or because the stateful resource genuinely
cannot cross processes, or because the work is not request-driven at
all. The pattern documented here works, but it imposes constraints
mesh otherwise hides from you. The default answer should still be
MeshJob.

## Gate: should you actually be here?

Before reaching for the in-process runtime pattern, can you answer **no** to all of these?

1. **Is your work driven by tool calls (request-driven)?** → if yes, try `MCP_MESH_TOOL_WORKERS=1` (see [single-worker mode](../python/dependency-injection.md#single-worker-mode-for-shared-loop-bound-resources)).
2. **Can your state mutations tolerate ~10ms HTTP round-trip overhead per mutation?** → if yes, use MeshJob with a state agent (see [stateful agents](stateful-agents.md)).
3. **Is your stateful resource portable across processes (DB pool, Redis connection, message-broker client)?** → if yes, you don't need in-process binding.

Only if all three are **no** is the in-process runtime pattern likely the right answer.

If you answered "yes" to any of them, close this page and go back to
the linked alternative. The pattern below is more code, more failure
modes, and more discipline than either of those — only worth it when
the constraints actually demand it.

## What the narrow cases look like

The shapes that genuinely need in-process state:

- **Real-time aggregators with sub-10ms state-mutation latency
  budgets.** Market-data tick consolidators that update a moving
  window on every tick. Sensor stream processors that fuse 1kHz inputs
  into a single observable. Anything where adding an HTTP hop to the
  state agent dominates the work being done.
- **Long-lived loop-bound resources that can't cross processes.** A
  GPU context bound to a CUDA stream. A WebSocket connection to a
  hardware controller. An LLM KV-cache that's expensive enough to
  rebuild that you genuinely want it to outlive a single tool call.
  Anything where the resource's lifetime is "the lifetime of the
  process" and serializing it to another process is either impossible
  or prohibitively expensive.
- **True background work that runs constantly between tool calls.**
  Driver loops that poll an upstream every N milliseconds regardless
  of whether a user is asking. Reconciliation loops that watch a
  feed. The work is not request-driven — it's a daemon embedded in
  the agent.

If your workload doesn't look like one of those, you're in the wrong
place.

## The pattern: dedicated engine thread + bridge

The shape is consistent across all three of those cases:

- The agent spawns a **dedicated background thread** at startup.
- That thread owns its own `asyncio.new_event_loop()` and runs
  `loop.run_forever()` for the lifetime of the process.
- All long-lived state — asyncpg pools, asyncio queues, the GPU
  context, background tasks — lives on that engine loop.
- `@mesh.tool` handlers run on mesh's worker loops (a different
  thread). They bridge into the engine loop with
  `asyncio.run_coroutine_threadsafe(coro, engine_loop)`, get a
  `concurrent.futures.Future` back, and wrap it with
  `asyncio.wrap_future(...)` so the handler can `await` the result
  on its own worker loop.

A minimal skeleton:

=== "Python"

    ```python
    import asyncio
    import threading
    from typing import Any

    import mesh
    from fastmcp import FastMCP

    app = FastMCP("In-Process Engine Agent")


    class Engine:
        """Owns a dedicated thread + its own asyncio loop."""

        def __init__(self) -> None:
            self.loop: asyncio.AbstractEventLoop | None = None
            self._thread: threading.Thread | None = None
            self._ready = threading.Event()
            self._state: dict[str, Any] = {}  # the in-process state

        def start(self) -> None:
            def runner() -> None:
                self.loop = asyncio.new_event_loop()
                asyncio.set_event_loop(self.loop)
                # Schedule any always-on background tasks here.
                self.loop.create_task(self._driver_loop())
                self._ready.set()
                self.loop.run_forever()

            self._thread = threading.Thread(
                target=runner, name="engine-loop", daemon=True,
            )
            self._thread.start()
            self._ready.wait()  # block until loop is up

        async def stop(self) -> None:
            assert self.loop is not None
            self.loop.call_soon_threadsafe(self.loop.stop)
            # Optionally join the thread with a timeout in lifespan finally.

        async def _driver_loop(self) -> None:
            """Always-on background work runs HERE, not in a tool."""
            while True:
                # ... poll upstream / update state / etc ...
                await asyncio.sleep(0.01)

        def dispatch(self, coro):
            """Call this from a worker-loop tool handler."""
            assert self.loop is not None
            fut = asyncio.run_coroutine_threadsafe(coro, self.loop)
            return asyncio.wrap_future(fut)


    engine = Engine()
    engine.start()


    @app.tool()
    @mesh.tool(capability="get_aggregate")
    async def get_aggregate(key: str) -> dict:
        # Worker-loop side: bridge into engine loop, await the result.
        async def on_engine() -> dict:
            return dict(engine._state.get(key, {}))
        return await engine.dispatch(on_engine())


    @mesh.agent(name="engine-agent", http_port=9210, auto_run=True)
    class EngineAgent: pass
    ```

That's the substrate. Everything below is the cookbook of gotchas this
pattern imposes that mesh otherwise handles for you.

## The cookbook

### Boundary-crossing DI

A `@mesh.tool` function's DI parameters (`McpMeshTool`, `MeshLlmAgent`,
`MeshJob`) are injected by a wrapper mesh installs at module load time.
The wrapper is what subsitutes the proxy for the parameter — the raw
function underneath has `None` defaults that never get filled in unless
you call the wrapper.

That matters here because your engine code may want to call other
`@mesh.tool` functions from the engine loop. Two pitfalls:

- **The raw function vs. the wrapper.** If you write
  `from some_module import some_tool` and then `await some_tool(...)`
  on the engine loop, you're calling the wrapper — DI works fine.
  Don't reach into the function's `__wrapped__` attribute trying to
  "skip the wrapper"; you'll silently lose injection.
- **`__main__` vs. import-name dual-import.** If `main.py` is started
  as `python main.py`, Python loads it as the module `__main__`. If
  any other code in the process then does `from main import some_tool`,
  Python loads it again as the module `main` — two separate module
  instances, each with its own copy of the wrapped function. The mesh
  decorator installed the proxy on the `__main__` instance; the code
  that imported `main.some_tool` is calling the `main` instance, which
  has no proxy. Resolution silently fails to `None`. This is a real
  footgun severe enough that the runtime now detects it explicitly —
  see issue #1031 for the detection mechanism.

  **Recommendation:** lay your agent out as a package and start it as
  `python -m pkg.main` (or via the scaffold's entrypoint). Sibling
  imports then all resolve to the same module instance and DI works
  uniformly.

### Restart recovery is your problem

In-process state is lost on every restart. Mesh's MeshJob substrate
handles this for orchestrator agents (orphan reroute + state-agent
snapshot); the engine pattern bypasses that substrate by design.

The discipline:

- Every state mutation that must survive restart goes to durable
  storage **before** acknowledging the change to the caller.
- On agent startup, the engine reads the durable store and
  reconstructs in-memory state before serving any tool calls (or
  serves degraded responses until reconstruction completes).
- This is app-side code mesh cannot enforce. If you skip it, restarts
  silently lose state.

### Long-poll tool timeouts

If a consumer calls a tool on this agent that long-polls on engine
state (e.g., "wait until the aggregator has at least N samples"), the
consumer's mesh proxy enforces a default timeout (~30s). Calls that
exceed it abort.

To allow longer polls, the **consumer** declares it explicitly:

=== "Python"

    ```python
    @mesh.tool(
        capability="my_tool",
        dependencies=["wait_for_threshold"],
        dependency_kwargs={
            "wait_for_threshold": {"timeout": 300},  # 5 minutes
        },
    )
    async def my_tool(wait_for_threshold: mesh.McpMeshTool = None):
        return await wait_for_threshold(min_samples=1000)
    ```

The kwarg lives on the caller side because it's the caller's HTTP
proxy that's enforcing the timeout. The engine agent has no way to
override it from its own side.

### Horizontal scaling is broken

This is the central trade-off and it deserves a callout.

State pins the agent to a single replica. If you deploy two replicas
of this agent, tool calls from any given consumer will round-robin
across them — and each replica has its own independent in-memory
state. Reads against the wrong replica silently return stale or empty
data; writes silently land in the wrong bucket.

Mitigations are all imperfect:

- Run with `replicas: 1` and accept the loss of redundancy.
- Use session-affinity routing (`session_required: True` in
  `dependency_kwargs`) to pin a consumer to a replica for the
  duration of a logical session. This shifts the problem rather
  than solving it: cross-session reads still hit the wrong replica.
- Externalize the state to a state agent — at which point you're
  back to the [MeshJob pattern](stateful-agents.md) and don't need
  this page.

If horizontal scaling matters and the state genuinely can't be
externalized, you have an architectural problem mesh can't paper over
for you.

### Graceful shutdown

SIGTERM (pod eviction, deployment rollout, `Ctrl-C` in dev) needs to
reach the engine thread cleanly. The runtime's lifespan exit phase
fires on SIGTERM (fix shipped in #1029 — the exit phase is now honored
rather than skipped), so wire the engine's `stop()` into the lifespan:

=== "Python"

    ```python
    from contextlib import asynccontextmanager
    from fastapi import FastAPI

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Engine was started at module load; nothing to do here on entry.
        try:
            yield
        finally:
            await engine.stop()

    app = FastAPI(lifespan=lifespan)
    ```

The `finally` block runs on both clean shutdown and SIGTERM. Persist
final state from the engine into durable storage there if you haven't
been persisting incrementally; the engine thread will be torn down
immediately after.

## Closing

This pattern is an escape hatch, not a recommendation. If you're
reading it because you hit a cross-loop Future error or a "where do I
put my asyncpg pool" question, the answer is almost always
[single-worker mode](../python/dependency-injection.md#single-worker-mode-for-shared-loop-bound-resources)
or the [MeshJob state-agent decomposition](stateful-agents.md) — not
this page. Use MeshJob unless you can answer the three gate questions
with "no, no, and no."

## See Also

- [Stateful Agents](stateful-agents.md) — the canonical MeshJob +
  state-agent decomposition that covers the common case
- [Single-Worker Mode](../python/dependency-injection.md#single-worker-mode-for-shared-loop-bound-resources)
  — when you have one shared loop-bound resource and request-driven
  tools
- [Long-Running Jobs](jobs.md) — MeshJob substrate: lifecycle,
  retries, cancel, orphan reroute
- `meshctl man dependency-injection` — DDDI, worker-loop topology,
  and dependency proxy configuration
