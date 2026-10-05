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
meshctl start --registry-only --registry-port 8000 --registry-host 0.0.0.0
```

## Registry API

### List Agents

```bash
curl http://localhost:8000/agents
```

Response:

Abridged (`AgentsListResponse` in `api/mcp-mesh-registry.openapi.yaml`):

```json
{
  "agents": [
    {
      "id": "my-agent-a1b2c3d4",
      "name": "my-agent",
      "agent_type": "mcp_agent",
      "runtime": "python",
      "status": "healthy",
      "endpoint": "http://localhost:9090",
      "capabilities": [
        {
          "name": "greeting",
          "version": "1.0.0",
          "function_name": "greet",
          "tags": ["social"]
        }
      ],
      "total_dependencies": 0,
      "dependencies_resolved": 0
    }
  ],
  "count": 1,
  "timestamp": "2026-10-04T12:00:00Z"
}
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

    A->>R: POST /heartbeat (full registration)
    Note right of R: Store agent info
    R->>A: 200 OK (resolved dependencies)
    loop Heartbeat
        A->>R: HEAD /heartbeat/{agent_id}
        R->>A: 200 OK (202 when topology changed)
    end
```

### Registration Payload

The full heartbeat body (`MeshAgentRegistration` in `api/mcp-mesh-registry.openapi.yaml`), abridged. Capabilities are declared per tool:

```json
{
  "agent_id": "my-agent-a1b2c3d4",
  "agent_type": "mcp_agent",
  "runtime": "python",
  "name": "my-agent",
  "version": "1.0.0",
  "http_host": "localhost",
  "http_port": 9090,
  "namespace": "default",
  "tools": [
    {
      "function_name": "greet",
      "capability": "greeting",
      "version": "1.0.0",
      "tags": ["social", "basic"],
      "dependencies": [{ "capability": "date_service" }]
    }
  ]
}
```

## Dependency Resolution

There is no separate resolution call; resolution rides the heartbeat:

1. Each full heartbeat carries every tool's declared `dependencies`
2. The registry finds, filters and scores the providers of each
3. The response's `dependencies_resolved` maps each consuming function to its resolved providers (`agent_id`, `function_name`, `endpoint`, `capability`, `status`)
4. The agent builds a proxy per dependency and injects it

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
# Agents: where the registry is
export MCP_MESH_REGISTRY_URL=http://localhost:8000
export MCP_MESH_HEALTH_INTERVAL=5      # Agent heartbeat cadence (seconds, default 5)

# Registry binary: listen address
export HOST=0.0.0.0
export PORT=8000

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
      - HOST=0.0.0.0
      - PORT=8000

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
