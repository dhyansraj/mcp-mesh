# health-block-test-agent (TypeScript)

Regression-test scratch agent for the TypeScript-runtime equivalent of the
Python `/health` blocking bug. The Node event loop is single-threaded; the
mesh Express server (which serves `/health` and `/ready`) and the FastMCP
tool dispatcher share that loop. A tool that performs sync blocking work
inside an `async` function will stall the loop and freeze health probes.

## Why

The `/health` and `/ready` handlers in `src/runtime/typescript/src/express.ts`
(search for `setupHealthEndpoints`) are registered on the same Express app
that handles MCP tool calls. Node has
a single event loop. A tool whose `execute` blocks (e.g. `execSync`,
busy CPU loop, sync file I/O) prevents the loop from servicing any other
request — including the health endpoints.

Notes about the actual TS runtime:

- Unlike the Python runtime, the TS runtime does **not** expose a
  `/livez` endpoint — `/livez` returns 404. Only `/health` and `/ready`
  exist.
- In practice the responses come from FastMCP's mount, not from the
  Express handlers shown in `express.ts`: `/health` returns the plain
  text body `✓ Ok`, and `/ready` returns
  `{"mode":"stateless","ready":1,"status":"ready","total":1}`. Either
  way, both share Node's single event loop with the tool executor, so
  the blocking hypothesis still applies.

In Kubernetes this would manifest as readiness/liveness probe failures and
pod restarts during legitimate long-running tool calls.

## What it does

Two tools:

- `busyTool(seconds: number = 35)` — `async` function that calls
  `execSync('sleep N')` (the cleanest way to park the whole Node process
  with no CPU burn — the JS analogue of Python's blocking `time.sleep`).
- `quickTool()` — `async` function that returns immediately. Sanity check.

Listens on port `9098` (Python reproducer uses `9099`).

## Reproducing the bug manually

From the repo root:

```bash
# One-time setup
cd examples/typescript/health-block-test-agent
npm install
cd -

# Start the agent
meshctl start examples/typescript/health-block-test-agent/src/index.ts -d
sleep 8

# Confirm it registered and /health and /ready respond normally
meshctl list
curl -sS http://127.0.0.1:9098/health
curl -sS http://127.0.0.1:9098/ready

# Kick off the blocking tool in the background
meshctl call health-block-test-agent busyTool --args '{"seconds": 35}' &

# While it's running, /health and /ready should hang or time out (the bug)
sleep 2
time curl -sS --max-time 5 http://127.0.0.1:9098/health
time curl -sS --max-time 5 http://127.0.0.1:9098/ready

# Cleanup
wait
meshctl stop
```

## Status

This agent only exists to reproduce and later regression-test the issue.
It is intentionally minimal (no Dockerfile, no helm values, no tsuite case)
and is not part of any tutorial or shipped example flow.
