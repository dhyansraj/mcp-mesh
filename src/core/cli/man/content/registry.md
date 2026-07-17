# Registry Operations

> Central coordination service for agent discovery and dependency resolution

## Overview

The registry is the central coordination service in MCP Mesh. It facilitates agent discovery and dependency resolution; agent-to-agent communication is always direct. The registry can OPTIONALLY proxy client→agent calls (`--use-proxy=true`, the default for `meshctl call`) for environments without direct network reachability — e.g., Kubernetes services without ingress.

## Registry Role

The registry is a **facilitator, not a controller**:

- Accepts agent registrations via heartbeat
- Stores capability metadata in database
- Resolves dependencies on request
- Monitors health and marks unhealthy agents
- Never INITIATES outbound calls to agents on its own; agent-to-agent communication is always direct. The registry can OPTIONALLY proxy client→agent calls (`--use-proxy=true`, the default for `meshctl call`) for environments without direct network reachability — e.g., Kubernetes services without ingress.

## Starting the Registry

### With meshctl (Recommended)

```bash
# Start registry only
meshctl start --registry-only

# Start registry on custom port
meshctl start --registry-only --registry-port 9000

# Start registry with debug logging
meshctl start --registry-only --debug
```

### With npm (Standalone Registry)

```bash
# Install registry via npm
npm install -g @mcpmesh/cli

# Start registry directly
mcp-mesh-registry --host 0.0.0.0 --port 8000
```

## Configuration

### Environment Variables

```bash
# Server binding
export HOST=0.0.0.0
export PORT=8000

# Database
export DATABASE_URL=mcp_mesh_registry.db  # SQLite
export DATABASE_URL=postgresql://user:pass@host:5432/db  # PostgreSQL

# Health monitoring
export DEFAULT_TIMEOUT_THRESHOLD=20  # Mark unhealthy after (seconds)
export HEALTH_CHECK_INTERVAL=10      # Scan frequency (seconds)
export DEFAULT_EVICTION_THRESHOLD=60 # Remove stale agents (seconds)

# Logging
export MCP_MESH_LOG_LEVEL=INFO
export MCP_MESH_DEBUG_MODE=false
```

## API Endpoints

| Endpoint       | Method    | Description                                |
| -------------- | --------- | ------------------------------------------ |
| `/health`      | GET       | Registry health check                      |
| `/agents`      | GET       | List registered agents (capabilities embedded per agent) |
| `/agents/{id}` | GET       | Get agent details                          |
| `/schemas`     | GET       | List canonical schemas (issue #547)        |
| `/register`    | POST      | Register/update agent                      |
| `/heartbeat`   | HEAD/POST | Agent heartbeat                            |

> Capability data is surfaced per-agent inside `/agents` responses; there is no dedicated `/capabilities` endpoint.

## Dependency Resolution

When an agent requests dependencies, the registry:

1. **Finds providers**: Agents with matching capability
2. **Applies filters**: Tag and version constraints (the `version` field is a semver constraint; bare `4.6.0` = exact match)
3. **Scores matches**: Preferred tags add points
4. **Selects winner**: Among matches, highest tag-match score first, then **highest version**, then agent ID for determinism — the newest satisfying version wins
5. **Returns topology**: Selected providers for each dependency

### Resolution Request

```json
{
  "agent_id": "hello-world",
  "dependencies": [
    { "capability": "date_service" },
    { "capability": "weather", "tags": ["+fast"] }
  ]
}
```

### Resolution Response

```json
{
  "dependencies": {
    "date_service": {
      "agent_id": "system-agent",
      "endpoint": "http://localhost:8081",
      "capability": "date_service"
    },
    "weather": {
      "agent_id": "weather-premium",
      "endpoint": "http://localhost:8082",
      "capability": "weather"
    }
  }
}
```

## Database Storage

### SQLite (Development)

```bash
export DATABASE_URL=mcp_mesh_registry.db
```

Simple, no setup, good for development and single-node.

### PostgreSQL (Production)

```bash
export DATABASE_URL=postgresql://user:password@localhost:5432/mcp_mesh
```

Better for production: concurrent access, persistence, replication.

## Monitoring

```bash
# Check registry health
curl http://localhost:8000/health

# List all agents
curl http://localhost:8000/agents | jq .

# Get specific agent
curl http://localhost:8000/agents/hello-world | jq .

# Using meshctl
meshctl status
meshctl list
```

## Drain Mode (Maintenance)

Before a registry upgrade or restart, drain mode turns the informal "quiet window" into a supported operation. While draining, the registry stops handing out new job claims (queued jobs stay queued — no attempt is burned), but running jobs keep renewing their leases and complete normally, and new job submissions are still accepted.

```bash
# Enter drain mode and block until every running job has released its owner
meshctl registry drain --wait

# Enter drain mode without waiting (poll separately)
meshctl registry drain

# Show drain state and how many live claims remain
meshctl registry status

# Resume normal dispatch (queued jobs become claimable again, FIFO)
meshctl registry resume
```

`live_claims` counts non-terminal jobs that still have an owner — the number to watch drop to zero before restarting. Drain state is held in memory only: **restarting the registry clears drain**, so a restarted process comes back dispatching normally. `--wait` aborts with an error if the registry stops draining mid-wait (a concurrent `resume` or restart), rather than falsely reporting "safe to restart".

### Separate admin port

If the registry is hardened with a dedicated admin port (`MCP_MESH_ADMIN_PORT`), the `/admin/drain` endpoints live **only** on that port — the public port returns 404. Point `--registry-url` at the admin address:

```bash
meshctl registry status --registry-url http://localhost:<admin-port>
```

### Multi-replica (HA) caveat

Drain state is **per-replica** (in-memory, not shared). In a multi-replica deployment a load balancer may route each `meshctl registry` command to a different replica, so `registry status` can flap between replicas and a single `registry drain` pauses only the replica that served the request — not the whole fleet. Before an HA upgrade, **drain every replica** by targeting each replica's address directly (`--registry-url`), and remember that restarting any replica clears its own drain.

## High Availability

The registry supports multiple replicas for high availability. All replicas share the same PostgreSQL database — no additional configuration is needed.

### How It Works

- All agent state (registrations, heartbeats, capabilities) is stored in PostgreSQL
- No in-memory state affects cross-replica consistency
- Heartbeat updates use optimistic locking to prevent concurrent update conflicts
- Each replica runs an independent health monitor against the shared database
- Startup cleanup only evicts agents that haven't heartbeated to any replica within the threshold

### Kubernetes Deployment

```bash
# Scale registry replicas
helm install mcp-core oci://ghcr.io/dhyansraj/mcp-mesh/mcp-mesh-core \
  --version 3.2.1 \
  -n mcp-mesh --create-namespace \
  --set registry.replicas=3
```

### Roadmap

- Multi-registry federation across clusters
- Cross-cluster agent discovery

## See Also

- `meshctl man health` - Health monitoring details
- `meshctl man capabilities` - Capability registration
- `meshctl man environment` - All configuration options
