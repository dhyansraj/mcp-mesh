# Observability

> Metrics and distributed traces across the mesh call graph — with a dashboard stack shipped in the box.

## What the mesh emits

Every agent and the registry are instrumented out of the box. The mesh produces two kinds of telemetry:

- **Metrics** — agent health, request rates, and error rates, scraped in Prometheus format.
- **Distributed traces** — OpenTelemetry spans stitched into a single trace that follows a request across the entire mesh call graph. When agent A calls agent B which calls agent C, all three spans land under one trace ID, so you see the full call tree, per-hop latency, and where a failure occurred.

Traces are published by agents to a Redis stream, consumed and correlated by the registry, and exported over OTLP to a trace backend (Tempo). You never wire span propagation by hand — the mesh threads the trace context through every dependency call.

## The shipped stack

MCP Mesh **ships** a ready-to-run observability stack — Prometheus (metrics), Tempo (trace storage), and Grafana (pre-built dashboards) — so you get dashboards without assembling anything:

- **Kubernetes** — the `mcp-mesh-core` Helm chart deploys Redis, Tempo, and Grafana with tracing enabled by default. Disable with `--set tempo.enabled=false --set grafana.enabled=false`.
- **Docker Compose** — the observability profile generates the same stack for local use.

This page does not teach Grafana or Prometheus themselves — see the [Grafana](https://grafana.com/docs/) and [Prometheus](https://prometheus.io/docs/) docs for how to build panels and queries. The mesh's job is to emit the data and give you working dashboards on top of it.

### Generate the stack

If the `--observability` scaffold flag is available in your build:

```bash
# Emit a standalone observability compose file (Redis + Tempo + Grafana)
meshctl scaffold --observability

docker compose -f docker-compose.observability.yml up -d
```

Combine with `--compose` (`meshctl scaffold --compose --observability`) to merge the stack into your main `docker-compose.yml` instead. Grafana comes up on `http://localhost:3000` (default `admin` / `admin`).

## Enabling tracing

Tracing is off unless enabled. Set these on the registry and on each agent (they are trace publishers):

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
| `MCP_MESH_DISTRIBUTED_TRACING_ENABLED` | `false` | Master switch for trace publishing and collection |
| `REDIS_URL` | `redis://localhost:6379` | Redis stream for trace spans |
| `TELEMETRY_ENDPOINT` | `localhost:4317` | OTLP endpoint the registry exports to (Tempo) |
| `TELEMETRY_PROTOCOL` | `grpc` | OTLP protocol: `grpc` or `http` |
| `TRACE_EXPORTER_TYPE` | `otlp` | Exporter: `otlp`, `console`, or `json` |
| `TEMPO_URL` | `http://localhost:3200` | Tempo query URL for the trace API |
| `MCP_MESH_TRACE_RETENTION` | `24h` | Redis `mesh:trace` stream retention (`0` disables trimming) |

See the [environment variables reference](environment-variables.md) for the full list.

## Where traces surface

Trace and telemetry endpoints are served by the **meshui service on port `3080`** — not the registry. The registry (port `8000`) collects and exports spans, but the query surface (`/api/trace/recent`, `/api/trace/agent-stats`) lives on meshui. Hitting the registry for those paths returns `404`.

For quick debugging without a dashboard, the CLI reads the same traces:

```bash
# Attach a trace to any call and print its ID
meshctl call my-agent:my_tool --trace

# Render the full call tree for a trace ID
meshctl trace <trace-id>
```

## See also

- [Dashboard](dashboard.md) — the meshui operations dashboard
- [Environment Variables](environment-variables.md) — every tracing and telemetry knob
- `meshctl man observability` — CLI tracing and the shipped stack
