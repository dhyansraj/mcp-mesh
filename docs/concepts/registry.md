# Registry

> Central coordination point for agent discovery

## Overview

The registry is the brain of MCP Mesh:

- Tracks all registered agents
- Resolves capability dependencies
- Manages health status
- Provides discovery endpoints

## Automatic Startup

The registry starts automatically when you run your first agent:

```bash
meshctl start my_agent.py
# Registry starts automatically on port 8000
```

## Manual Startup

For custom configurations:

```bash
meshctl registry start --port 8000 --host 0.0.0.0
```

## Registry API

### List Agents

```bash
curl http://localhost:8000/agents
```

Response:

```json
{
  "agents": [
    {
      "name": "my-agent",
      "host": "localhost",
      "port": 9090,
      "capabilities": {
        "greeting": {
          "version": "1.0.0",
          "tags": ["social"]
        }
      },
      "status": "healthy"
    }
  ]
}
```

### Get Agent Status

```bash
curl http://localhost:8000/agents/my-agent
```

### Health Check

```bash
curl http://localhost:8000/health
```

## Agent Registration

Agents auto-register on startup:

```mermaid
sequenceDiagram
    participant A as Agent
    participant R as Registry

    A->>R: POST /register
    Note right of R: Store agent info
    R->>A: 200 OK (agent ID)
    loop Heartbeat
        A->>R: POST /heartbeat
        R->>A: 200 OK
    end
```

### Registration Payload

```json
{
  "name": "my-agent",
  "host": "localhost",
  "port": 9090,
  "namespace": "default",
  "capabilities": {
    "greeting": {
      "version": "1.0.0",
      "tags": ["social", "basic"],
      "dependencies": []
    }
  }
}
```

## Dependency Resolution

When an agent registers with dependencies:

1. Registry receives registration with `dependencies`
2. Finds agents providing those capabilities
3. Returns proxy configurations to consumer
4. Consumer uses proxies to call providers

```mermaid
graph LR
    A[Consumer] -->|depends on: database| R[Registry]
    R -->|finds| B[Provider: database]
    R -->|returns proxy config| A
    A -->|calls via proxy| B
```

## Configuration

### Environment Variables

```bash
# Registry host/port
export MCP_MESH_REGISTRY_URL=http://localhost:8000

# Custom registry host
export MCP_MESH_REGISTRY_HOST=0.0.0.0
export MCP_MESH_REGISTRY_PORT=8000

# Health check settings
export MCP_MESH_HEALTH_INTERVAL=5      # Agent heartbeat cadence (seconds, default 5)

# Registry-side: mark an agent unhealthy after N seconds of missed
# heartbeats (default 20 = 4 missed heartbeats at the 5s cadence)
export DEFAULT_TIMEOUT_THRESHOLD=20
```

### Docker Compose

```yaml
services:
  registry:
    image: ghcr.io/dhyansraj/mcp-mesh/mcp-mesh-registry:latest
    ports:
      - "8000:8000"
    environment:
      - MCP_MESH_REGISTRY_HOST=0.0.0.0
      - MCP_MESH_HEALTH_INTERVAL=5

  my-agent:
    build: ./my-agent
    environment:
      - MCP_MESH_REGISTRY_URL=http://registry:8000
    depends_on:
      - registry
```

## Namespaces

Namespaces isolate agents:

```python
# Production namespace
@mesh.agent(name="api", namespace="production")

# Development namespace
@mesh.agent(name="api", namespace="development")
```

Agents only discover others in the same namespace.

## High Availability

For production, run multiple registry instances:

```yaml
# docker-compose.yml
services:
  registry-1:
    image: ghcr.io/dhyansraj/mcp-mesh/mcp-mesh-registry:latest
    ports:
      - "8000:8000"

  registry-2:
    image: ghcr.io/dhyansraj/mcp-mesh/mcp-mesh-registry:latest
    ports:
      - "8001:8000"

  # Load balancer in front
```

> **Drain state is per-replica.** Each registry replica tracks its own
> drain state on its admin port — draining one replica does not drain the
> others, and a restart clears it. During a rolling upgrade you drain each
> replica independently before rotating it; a naive load balancer in front
> is not drain-aware on its own. See [Upgrading](../upgrading.md) for the
> rolling-restart procedure and [Long-Running Jobs](jobs.md) for how
> claims/leases survive replica rotation.

> **Correlation-mode tracing assumes one replica.** The default exporter is
> replica-safe: each replica streams the spans it consumes straight through to
> Tempo, which reassembles a trace by its ID however the spans were split on
> the way in. Under `TRACE_EXPORTER_TYPE=console` or `json` a replica instead
> assembles each trace in its own memory, and Redis hands each trace-stream
> entry to exactly one consumer in the shared consumer group — so at N
> replicas every logical trace completes as N fragments, and `meshctl trace`
> answers from whichever fragment the replica behind the load balancer holds.
> Stay at one instance in those modes, or export through Tempo. The registry
> warns at startup whenever correlation mode is active. See
> [Observability](../07-observability.md).

## Troubleshooting

### Agent Not Registering

```bash
# Check registry is running
curl http://localhost:8000/health

# Check agent logs
meshctl start my_agent.py --log-level debug
```

### Dependency Not Found

```bash
# List all agents
curl http://localhost:8000/agents | jq '.agents[] | {name, capabilities: (.capabilities | keys)}'

# Check capability exists
curl http://localhost:8000/agents | jq '.agents[] | select(.capabilities.my_capability)'
```

### Wrong Namespace

```bash
# Check agent namespace
curl http://localhost:8000/agents | jq '.agents[] | {name, namespace}'
```

## See Also

- [Architecture](architecture.md) - System overview
- [Health & Discovery](health-discovery.md) - Health system
- [Environment Variables](../environment-variables.md) - All config options
