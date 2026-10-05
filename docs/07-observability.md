# Observability

> Metrics and distributed traces across the mesh call graph — with a dashboard stack shipped in the box.

## What the mesh emits

Every agent and the registry are instrumented out of the box. The mesh produces two kinds of telemetry:

- **Metrics** — per-agent, per-model and per-edge request, error and token statistics, aggregated by meshui from the trace stream.
- **Distributed traces** — OpenTelemetry spans stitched into a single trace that follows a request across the entire mesh call graph. When agent A calls agent B which calls agent C, all three spans land under one trace ID, so you see the full call tree, per-hop latency, and where a failure occurred.

Traces are published by agents to a Redis stream, consumed and correlated by the registry, and exported over OTLP to a trace backend (Tempo). You never wire span propagation by hand — the mesh threads the trace context through every dependency call.

## The shipped stack

MCP Mesh **ships** a ready-to-run observability stack — Redis (span transport), Tempo (trace storage), and Grafana with a pre-built dashboard — so you get traces without assembling anything:

- **Kubernetes** — the `mcp-mesh-core` Helm chart deploys Redis, Tempo, and Grafana with tracing enabled by default. Disable with `--set tempo.enabled=false --set grafana.enabled=false`.
- **Docker Compose** — the observability profile generates the same stack for local use.

Both provision one Grafana dashboard, **MCP Mesh Distributed Tracing**. This page does not teach Grafana itself — see the [Grafana](https://grafana.com/docs/) docs for how to build panels and queries.

### Generate the stack

If the `--observability` scaffold flag is available in your build:

```bash
# Emit a standalone observability compose file (Redis + Tempo + Grafana)
meshctl scaffold --observability

docker compose -f docker-compose.observability.yml up -d
```

Combine with `--compose` (`meshctl scaffold --compose --observability`) to merge the stack into your main `docker-compose.yml` instead. Grafana comes up on `http://localhost:3000` with `admin` / `admin`, and the generated compose file also enables anonymous access with the Admin role. Port 3000 is published on every host interface, so anyone who can reach the host gets Grafana Admin without a password: run the stack on a trusted machine, or change the mapping to `"127.0.0.1:3000:3000"`.

### Grafana on Kubernetes

The Grafana Service is named `<release>-mcp-mesh-grafana`. For a core release named `mcp-core` in namespace `mcp-mesh`:

```bash
kubectl port-forward svc/mcp-core-mcp-mesh-grafana 3000:3000 -n mcp-mesh
```

The user is `admin`. Unless you set `mcp-mesh-grafana.grafana.config.adminPassword` or `mcp-mesh-grafana.grafana.config.existingSecret` in the `mcp-mesh-core` values, the chart generates the password into a Secret:

```bash
kubectl get secret mcp-core-mcp-mesh-grafana-secret -n mcp-mesh \
  -o jsonpath='{.data.admin-password}' | base64 -d
```

## Enabling tracing

Agents and the registry default to tracing off; meshui defaults to on. The Helm charts (`mcp-mesh-core`, `mcp-mesh-registry`, `mcp-mesh-agent`, `mcp-mesh-ui`) set it on. Outside Helm, set these on the registry and on each agent (they are trace publishers):

```bash
# Turn on distributed tracing
export MCP_MESH_DISTRIBUTED_TRACING_ENABLED=true

# Redis stream that carries trace spans from agents to the registry
export REDIS_URL=redis://localhost:6379

# Registry → Tempo OTLP export
export TELEMETRY_ENDPOINT=localhost:4317
export TELEMETRY_PROTOCOL=grpc          # grpc or http

# Tempo HTTP query URL (used by the trace query surface)
export TEMPO_URL=http://localhost:3200
```

| Variable | Default | Description |
| -------- | ------- | ----------- |
| `MCP_MESH_DISTRIBUTED_TRACING_ENABLED` | `false` (agents, registry), `true` (meshui) | Master switch for trace publishing and collection |
| `REDIS_URL` | `redis://localhost:6379` | Redis stream for trace spans |
| `TELEMETRY_ENDPOINT` | `localhost:4317` | OTLP endpoint the registry exports to (Tempo) |
| `TELEMETRY_PROTOCOL` | `grpc` | OTLP protocol: `grpc` or `http` |
| `TRACE_EXPORTER_TYPE` | `otlp` | Exporter: `otlp`, `console`, or `json` |
| `TEMPO_URL` | `http://localhost:3200` | Tempo query URL for the trace API |
| `MCP_MESH_TRACE_RETENTION` | `24h` | Redis `mesh:trace` stream retention (`0` disables trimming). Honoured by both the registry and meshui, so trimming survives either being down |
| `MCP_MESH_TRACE_STREAM_MAXLEN` | `100000` | Producer-side `XADD MAXLEN ~` ceiling on `mesh:trace`, applied by every agent runtime. Bounds the stream even with no consumer alive (`0` disables) |
| `MCP_MESH_TELEMETRY_AGGREGATE_RETENTION` | `24h` | Age-out window for the in-memory per-agent / per-model / per-edge dashboard aggregates (`0` disables age pruning) |
| `MCP_MESH_TELEMETRY_AGGREGATE_MAX_ENTRIES` | `10000` | Hard key ceiling per aggregate map, evicting least-recently-seen first (`0` disables the ceiling). An edge key costs ~2.1 KB, so the default admits ~20 MB of edge aggregates |
| `MCP_MESH_UI_TRACE_CONSUMER_GROUP` | `mcp-mesh-ui-dashboard` | Redis consumer group meshui reads `mesh:trace` with. Redis delivers each entry to one consumer per group, so a second meshui on the default group takes traces from a running dashboard — give an extra reader its own group |
| `MCP_MESH_TRACE_CONSUMER_GROUP` | `mcp-mesh-registry-processors` | The same knob for the registry. Point a second registry process at a live mesh to diagnose it and this is what keeps it from taking half the running registry's span events |

See the [environment variables reference](environment-variables.md) for the full list.

## Where traces surface

Trace and telemetry endpoints are served by the **meshui service on port `3080`** — not the registry. The registry (port `8000`) collects and exports spans, but the query surface (`/api/trace/recent`, `/api/trace/agent-stats`) lives on meshui. Hitting the registry for those paths returns `404`.

For quick debugging without a dashboard, use the CLI:

```bash
# Attach a trace to any call and print its ID
meshctl call my-agent:my_tool --trace

# Render the full call tree for a trace ID
meshctl trace <trace-id>
```

`meshctl trace` asks the registry (`GET /trace/<id>`), which with the default `otlp` exporter queries Tempo. A trace is therefore found only while Tempo holds it: both shipped Tempo configurations keep traces for 1 hour. `MCP_MESH_TRACE_RETENTION` trims the Redis `mesh:trace` stream only and does not affect what `meshctl trace` can find.

## See also

- [Dashboard](dashboard.md) — the meshui operations dashboard
- [Environment Variables](environment-variables.md) — every tracing and telemetry knob
- `meshctl man observability` — CLI tracing and the shipped stack
