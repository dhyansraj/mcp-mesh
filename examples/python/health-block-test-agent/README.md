# health-block-test-agent

Regression-test scratch agent for a hypothesized bug in the mcp-mesh Python
runtime: the `/health`, `/ready`, and `/livez` HTTP endpoints get blocked
while a long-running MCP tool call is in progress.

## Why

`mesh/decorators.py::_start_uvicorn_immediately()` creates a FastAPI app,
registers the health endpoints as async coroutines, and runs `uvicorn.run(...)`
in a background thread with a single worker. The pipeline then mounts the
FastMCP HTTP app onto the same FastAPI instance. As a result, MCP tool calls
and health probes share a single event loop on a single thread.

If a tool's coroutine performs sync blocking work (`time.sleep`, CPU-bound
loop, blocking I/O), it stalls the entire event loop — including `/livez`.
In Kubernetes this would manifest as liveness probe failures and pod restarts
during legitimate long-running tool calls.

## What it does

Two tools:

- `busy_tool(seconds: int = 35)` — `async def` that calls `time.sleep(seconds)`
  (deliberately the sync version, not `asyncio.sleep`). Blocks the loop.
- `quick_tool()` — `async def` that returns immediately. Sanity check.

Listens on port `9099`.

## Reproducing the bug manually

From the repo root:

```bash
# Start the agent
meshctl start examples/python/health-block-test-agent/main.py -d
sleep 8

# Confirm it registered and /livez responds normally
meshctl list
curl -sS http://127.0.0.1:9099/livez

# Kick off the blocking tool in the background
meshctl call health-block-test-agent busy_tool --args '{"seconds": 35}' &

# While it's running, /livez should hang or time out (the bug)
sleep 2
time curl -sS --max-time 5 http://127.0.0.1:9099/livez

# Cleanup
wait
meshctl stop
```

## Status

This agent only exists to reproduce and later regression-test the issue.
It is intentionally minimal (no Dockerfile, no helm values, no tsuite case)
and is not part of any tutorial or shipped example flow.
