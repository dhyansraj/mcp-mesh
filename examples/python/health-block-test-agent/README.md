# health-block-test-agent

Regression-coverage agent for the Python-runtime fix that prevents long
blocking tool calls from stalling `/health`, `/ready`, and `/livez`.

## Why

`mesh/decorators.py::_start_uvicorn_immediately()` registers the health
endpoints on the same FastAPI app that the FastMCP HTTP transport mounts on,
sharing one event loop on one thread. A tool whose body performs sync
blocking work (`time.sleep`, CPU loop, blocking I/O) used to stall that loop
for the duration of the call — including liveness probes, which would cause
Kubernetes to restart the pod.

The fix isolates each tool call onto a dedicated worker event loop in
`src/runtime/python/_mcp_mesh/shared/tool_executor.py`, controlled by
`MCP_MESH_TOOL_ISOLATION` (default: **true**).

## What it does

Two tools:

- `busy_tool(seconds: int = 35)` — `async def` that calls `time.sleep(seconds)`
  (deliberately the sync version). With isolation on, blocks only one worker
  thread; without isolation, blocks the main event loop.
- `quick_tool()` — `async def` that returns immediately. Sanity check.

Listens on port `9099`.

## Verifying the fix (default behavior)

```bash
meshctl start examples/python/health-block-test-agent/main.py -d
sleep 8

meshctl call busy_tool '{"seconds":35}' --timeout 60 &
sleep 3
time curl -sS --max-time 5 http://127.0.0.1:9099/livez   # expect ~ms

wait
meshctl stop
```

`/livez` stays responsive (a few milliseconds) while `busy_tool` runs.

## Reproducing the original bug

Disable isolation to observe the unfixed behavior:

```bash
MCP_MESH_TOOL_ISOLATION=false meshctl start examples/python/health-block-test-agent/main.py -d
sleep 8

meshctl call busy_tool '{"seconds":35}' --timeout 60 &
sleep 3
time curl -sS --max-time 5 http://127.0.0.1:9099/livez   # expect timeout

wait
meshctl stop
```

`/livez` hangs until `busy_tool` finishes, confirming what the default
isolation protects against.

---

Automated coverage:
[`tests/integration/suites/uc02_tools/tc25_health_endpoint_responsiveness_py/`](../../../tests/integration/suites/uc02_tools/tc25_health_endpoint_responsiveness_py/).
