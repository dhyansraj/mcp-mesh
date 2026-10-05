# Observability

> Distributed tracing and monitoring for MCP Mesh agents

## Overview

MCP Mesh provides built-in observability through:

- **CLI tracing**: Quick debugging with `meshctl call --trace`
- **Grafana dashboards**: Production monitoring with Tempo backend

## CLI Tracing

### Get trace IDs

```bash
# Add --trace flag to any call
meshctl call my-agent:my_tool --trace
# Output includes: Trace ID: abc123def456...
```

### View trace tree

```bash
# View the full call tree
meshctl trace abc123def456

# Output as JSON
meshctl trace abc123def456 --json

# Show internal spans (usually hidden)
meshctl trace abc123def456 --show-internal
```

### Example output

```
Call Tree for trace abc123def456
════════════════════════════════════════════════════════════

└─ process_request (orchestrator) [45ms] ✓
   ├─ validate_input (validator) [5ms] ✓
   └─ execute_task (worker) [38ms] ✓
      └─ fetch_data (data-service) [30ms] ✓

────────────────────────────────────────────────────────────
Summary: 4 spans across 4 agents | 45ms | ✓
Agents: orchestrator, validator, worker, data-service
```

## Production Monitoring (Grafana)

### Setup with Docker Compose

```bash
# Generate docker-compose with observability stack
meshctl scaffold --compose --observability

# Starts: Redis, Tempo, Grafana
docker compose up -d
```

### Setup with Kubernetes

```bash
# Install core with observability enabled (default)
helm install mcp-core oci://ghcr.io/dhyansraj/mcp-mesh/mcp-mesh-core \
  --version 3.7.1 \
  -n mcp-mesh --create-namespace

# Or disable observability
helm install mcp-core oci://ghcr.io/dhyansraj/mcp-mesh/mcp-mesh-core \
  --version 3.7.1 \
  -n mcp-mesh --create-namespace \
  --set tempo.enabled=false \
  --set grafana.enabled=false
```

### Access Grafana

| Deployment     | URL                                                      |
| -------------- | -------------------------------------------------------- |
| Docker Compose | http://localhost:3000                                    |
| Kubernetes     | `kubectl port-forward svc/mcp-core-mcp-mesh-grafana 3000:3000 -n mcp-mesh` |

The Kubernetes Service is named `<release>-mcp-mesh-grafana`, so the command above matches the `mcp-core` release installed earlier.

Credentials:

- **Docker Compose**: `admin` / `admin`. The generated compose file also enables anonymous access with the Admin role and publishes port 3000 on every host interface, so anyone who can reach the host gets Grafana Admin without a password. Run it on a trusted machine, or change the mapping to `127.0.0.1:3000:3000`.
- **Kubernetes**: user `admin`. Unless you set `mcp-mesh-grafana.grafana.config.adminPassword` or `mcp-mesh-grafana.grafana.config.existingSecret` in the `mcp-mesh-core` values, the password is generated into a Secret; read it with:

```bash
kubectl get secret mcp-core-mcp-mesh-grafana-secret -n mcp-mesh \
  -o jsonpath='{.data.admin-password}' | base64 -d
```

### Pre-built Dashboard

Both deployments provision one dashboard, **MCP Mesh Distributed Tracing**: service activity, recent traces and per-span timing from Tempo.

### Where Traces Are Stored

- Agents publish spans to the Redis stream `mesh:trace`. The registry and meshui read it; `MCP_MESH_TRACE_RETENTION` (default `24h`) trims that stream and nothing else.
- With the default `otlp` exporter, the registry forwards spans to Tempo. `meshctl trace` asks the registry (`GET /trace/<id>`), which queries Tempo, so a trace is found only while Tempo still holds it. Both shipped Tempo configurations (compose and the `mcp-mesh-tempo` chart) keep traces for 1 hour.

## Environment Variables

| Variable                               | Description     | Default                 |
| -------------------------------------- | --------------- | ----------------------- |
| `MCP_MESH_DISTRIBUTED_TRACING_ENABLED` | Enable tracing  | `false` for agents and the registry, `true` for meshui; the Helm charts set it to `true` |
| `TRACE_EXPORTER_TYPE`                  | Exporter type   | `otlp`                  |
| `TELEMETRY_ENDPOINT`                   | OTLP endpoint   | `localhost:4317`        |
| `TELEMETRY_PROTOCOL`                   | Protocol        | `grpc`                  |
| `TEMPO_URL`                            | Tempo query URL | `http://localhost:3200` |
| `MCP_MESH_TRACE_RETENTION`             | Redis trace stream retention (`0` = no trimming) | `24h` |
| `MCP_MESH_TRACE_STREAM_MAXLEN`         | Producer-side `XADD MAXLEN ~` ceiling on `mesh:trace` (`0` = no cap) | `100000` |
| `MCP_MESH_TELEMETRY_AGGREGATE_RETENTION` | Age-out window for in-memory dashboard aggregates (`0` = no age pruning) | `24h` |
| `MCP_MESH_TELEMETRY_AGGREGATE_MAX_ENTRIES` | Key ceiling per aggregate map, LRU eviction (`0` = no ceiling). An edge key costs ~2.1 KB, so the default admits ~20 MB of edge aggregates | `10000` |
| `MCP_MESH_UI_TRACE_CONSUMER_GROUP`      | Redis consumer group meshui reads `mesh:trace` with. One consumer per group gets each entry, so a second meshui needs its own group or it takes traces from the first | `mcp-mesh-ui-dashboard` |
| `MCP_MESH_TRACE_CONSUMER_GROUP`         | The same knob for the registry. A second registry pointed at a live mesh needs its own group or it takes span events from the running one | `mcp-mesh-registry-processors` |

## Troubleshooting

### "Trace not found"

Possible reasons:

- Trace ID incorrect or expired (Tempo keeps traces for 1 hour in both shipped configurations)
- Distributed tracing not enabled (`MCP_MESH_DISTRIBUTED_TRACING_ENABLED=true`)
- Observability stack not deployed

### Traces not appearing in Grafana

1. Check Tempo is running: `docker compose ps tempo`
2. Check agent has tracing enabled in environment
3. Verify network connectivity between agents and Tempo

## See Also

- `meshctl man deployment` - Setup Docker/Kubernetes
- `meshctl man scaffold` - Generate observability stack
- `meshctl man cli` - meshctl command surface (including the trace command)
