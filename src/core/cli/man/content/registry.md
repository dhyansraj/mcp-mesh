# Registry Operations

> Central coordination service for agent discovery and dependency resolution

## Overview

The registry is the central coordination service in MCP Mesh. It facilitates agent discovery and dependency resolution but never proxies communication - agents communicate directly with each other.

## Registry Role

The registry is a **facilitator, not a controller**:

- Accepts agent registrations via heartbeat
- Stores capability metadata in database
- Resolves dependencies on request
- Monitors health and marks unhealthy agents
- Never calls agents - agents always initiate

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

# Caching
export CACHE_TTL=30
export ENABLE_RESPONSE_CACHE=true

# Logging
export MCP_MESH_LOG_LEVEL=INFO
export MCP_MESH_DEBUG_MODE=false
```

## API Endpoints

| Endpoint        | Method    | Description            |
| --------------- | --------- | ---------------------- |
| `/health`       | GET       | Registry health check  |
| `/agents`       | GET       | List registered agents |
| `/agents/{id}`  | GET       | Get agent details      |
| `/capabilities` | GET       | List all capabilities  |
| `/register`     | POST      | Register/update agent  |
| `/heartbeat`    | HEAD/POST | Agent heartbeat        |

## Dependency Resolution

When an agent requests dependencies, the registry:

1. **Finds providers**: Agents with matching capability
2. **Applies filters**: Tag and version constraints
3. **Scores matches**: Preferred tags add points
4. **Returns topology**: Selected providers for each dependency

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

## High Availability (Future)

Planned features:

- Multi-registry federation
- Cross-cluster discovery
- Leader election

## See Also

- `meshctl man health` - Health monitoring details
- `meshctl man capabilities` - Capability registration
- `meshctl man environment` - All configuration options
