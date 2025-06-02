# Registry API Usage Guide

The MCP Mesh Registry Service provides a **pull-based, Kubernetes API Server pattern** for agent registration, discovery, and health monitoring.

## Architecture Overview

- **Pattern**: Kubernetes API Server (passive/pull-based)
- **Clients**: Agents actively register and send heartbeats
- **Registry**: Passively receives updates and serves discovery queries
- **Health**: Timer-based monitoring with configurable timeouts

## Core Endpoints

### 1. Agent Registration (MCP Protocol)

**Endpoint**: `/mcp` (MCP protocol)
**Purpose**: Agents register themselves with capabilities

```python
# Agent registration via MCP client
agent_data = AgentRegistration(
    name="file-agent",
    namespace="production",
    endpoint="http://localhost:9001",
    capabilities=[
        AgentCapability(
            name="file_read",
            description="Read files from filesystem",
            version="1.0.0",
            category="file_operations"
        )
    ],
    agent_type="file-agent"
)
```

### 2. Heartbeat Updates (REST)

**Endpoint**: `POST /heartbeat`
**Purpose**: Agents send periodic health updates

```bash
curl -X POST http://localhost:8000/heartbeat \
  -H "Content-Type: application/json" \
  -d '{
    "agent_id": "agent-uuid-here",
    "status": "healthy",
    "metadata": {"load": "low"}
  }'
```

**Response**:

```json
{
  "status": "success",
  "timestamp": "2024-01-01T12:00:00Z",
  "message": "Heartbeat recorded"
}
```

### 3. Service Discovery (REST)

**Endpoint**: `GET /agents`
**Purpose**: Discover available agents with filtering

```bash
# Basic discovery
curl http://localhost:8000/agents

# Filter by capability
curl http://localhost:8000/agents?capability=file_read

# Filter by namespace
curl http://localhost:8000/agents?namespace=production

# Filter by labels (Kubernetes-style)
curl http://localhost:8000/agents?label_selector=environment=prod,role=worker

# Fuzzy matching
curl http://localhost:8000/agents?capability=file&fuzzy_match=true
```

**Response**:

```json
{
  "agents": [
    {
      "id": "uuid",
      "name": "file-agent",
      "namespace": "production",
      "endpoint": "http://localhost:9001",
      "status": "healthy",
      "capabilities": [...],
      "labels": {"environment": "prod"}
    }
  ],
  "count": 1,
  "timestamp": "2024-01-01T12:00:00Z"
}
```

### 4. Capability Discovery (REST)

**Endpoint**: `GET /capabilities`
**Purpose**: Search for specific capabilities across all agents

```bash
# Search by category
curl http://localhost:8000/capabilities?category=file_operations

# Search by name with fuzzy matching
curl http://localhost:8000/capabilities?name=file&fuzzy_match=true

# Filter by stability
curl http://localhost:8000/capabilities?stability=stable

# Complex search
curl "http://localhost:8000/capabilities?category=file_operations&agent_status=healthy&include_deprecated=false"
```

## Pull-Based Behavior

### Client Responsibilities

1. **Registration**: Agents must actively register via MCP protocol
2. **Heartbeats**: Agents must send periodic heartbeats to maintain health status
3. **Discovery**: Clients query the registry when they need to find services

### Registry Responsibilities

1. **Passive Reception**: Accepts registrations and heartbeats
2. **Health Monitoring**: Timer-based health checks with configurable timeouts
3. **Query Serving**: Responds to discovery requests with current state
4. **Automatic Cleanup**: Evicts expired agents based on timeout thresholds

### Health States

- `pending`: Newly registered, awaiting first heartbeat
- `healthy`: Receiving regular heartbeats within timeout
- `degraded`: Missed heartbeat but within eviction threshold
- `expired`: Exceeded eviction threshold, will be removed
- `offline`: Explicitly set by agent or admin

## Example Workflow

```python
import asyncio
import aiohttp
from mcp_mesh.server.models import AgentRegistration, AgentCapability

async def agent_lifecycle():
    # 1. Register agent (via MCP - simplified here)
    agent = AgentRegistration(
        name="my-agent",
        capabilities=[AgentCapability(name="process_data")]
    )

    # 2. Send periodic heartbeats
    async with aiohttp.ClientSession() as session:
        while True:
            await session.post("http://localhost:8000/heartbeat", json={
                "agent_id": agent.id,
                "status": "healthy"
            })
            await asyncio.sleep(30)  # Every 30 seconds

async def client_discovery():
    # 3. Discover services when needed
    async with aiohttp.ClientSession() as session:
        async with session.get("http://localhost:8000/agents?capability=process_data") as resp:
            agents = await resp.json()
            return agents["agents"]
```

## Health Monitoring

### Timeout Configuration

```python
# Default timeouts
default_timeout_threshold = 60    # seconds until degraded
default_eviction_threshold = 120  # seconds until expired

# Per-agent-type configuration
agent_type_configs = {
    "file-agent": {"timeout_threshold": 90, "eviction_threshold": 180},
    "worker": {"timeout_threshold": 45, "eviction_threshold": 90},
    "critical": {"timeout_threshold": 30, "eviction_threshold": 60}
}
```

### Health Check Endpoint

```bash
# Check specific agent health
curl http://localhost:8000/health/agent-uuid

# Registry health
curl http://localhost:8000/health

# Registry metrics
curl http://localhost:8000/metrics
```

## Error Handling

The registry follows graceful degradation patterns:

- **Connection Failures**: Clients should retry with exponential backoff
- **Registry Unavailable**: Agents continue operating with cached discovery
- **Timeout Exceeded**: Agents are marked degraded, then expired
- **Invalid Requests**: Returns proper HTTP status codes with error details

## Best Practices

1. **Heartbeat Frequency**: Send heartbeats at 1/2 the timeout threshold
2. **Discovery Caching**: Cache discovery results for reasonable periods
3. **Error Handling**: Implement retry logic with backoff
4. **Health Monitoring**: Monitor agent health via `/health/{agent_id}`
5. **Metrics**: Use `/metrics` endpoint for observability
