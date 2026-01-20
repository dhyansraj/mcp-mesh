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
  --version 0.8.0-beta.9 \
  -n mcp-mesh --create-namespace

# Or disable observability
helm install mcp-core oci://ghcr.io/dhyansraj/mcp-mesh/mcp-mesh-core \
  --version 0.8.0-beta.9 \
  -n mcp-mesh --create-namespace \
  --set tempo.enabled=false \
  --set grafana.enabled=false
```

### Access Grafana

| Deployment     | URL                                                      |
| -------------- | -------------------------------------------------------- |
| Docker Compose | http://localhost:3000                                    |
| Kubernetes     | `kubectl port-forward svc/grafana 3000:3000 -n mcp-mesh` |

Default credentials: `admin` / `admin`

### Pre-built Dashboards

- **MCP Mesh Overview**: Agent health, request rates, error rates
- **Trace Explorer**: Search and visualize distributed traces
- **Agent Details**: Per-agent metrics and traces

## Environment Variables

| Variable                               | Description     | Default             |
| -------------------------------------- | --------------- | ------------------- |
| `MCP_MESH_DISTRIBUTED_TRACING_ENABLED` | Enable tracing  | `false`             |
| `TRACE_EXPORTER_TYPE`                  | Exporter type   | `otlp`              |
| `TELEMETRY_ENDPOINT`                   | Tempo endpoint  | `tempo:4317`        |
| `TELEMETRY_PROTOCOL`                   | Protocol        | `grpc`              |
| `TEMPO_URL`                            | Tempo query URL | `http://tempo:3200` |

## Troubleshooting

### "Trace not found"

Possible reasons:

- Trace ID incorrect or expired (traces expire after ~1 hour by default)
- Distributed tracing not enabled (`MCP_MESH_DISTRIBUTED_TRACING_ENABLED=true`)
- Observability stack not deployed

### Traces not appearing in Grafana

1. Check Tempo is running: `docker compose ps tempo`
2. Check agent has tracing enabled in environment
3. Verify network connectivity between agents and Tempo

## See Also

- `meshctl man deployment` - Setup Docker/Kubernetes
- `meshctl man scaffold` - Generate observability stack
- `meshctl trace --help` - Trace command options
