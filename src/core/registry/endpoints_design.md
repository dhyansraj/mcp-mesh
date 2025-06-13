# Registry API Endpoints Design

## Core Endpoints (Used by Python Runtime)

### 1. POST /agents/register

**Purpose**: Register agent with all its tools
**Used by**: Python runtime during startup
**Request**:

```json
{
  "agent_id": "myservice-abc123",
  "metadata": {
    "name": "myservice-abc123",
    "endpoint": "http://localhost:8889",
    "tools": [
      {
        "function_name": "greet",
        "capability": "greeting",
        "version": "1.0.0",
        "dependencies": [
          {
            "capability": "date_service",
            "version": ">=1.0.0",
            "tags": ["production"]
          }
        ]
      }
    ]
  }
}
```

**Response**:

```json
{
  "status": "success",
  "agent_id": "myservice-abc123",
  "dependencies_resolved": {
    "greet": {
      "date_service": {
        "agent_id": "dateservice-xyz",
        "endpoint": "http://date:8080",
        "tool_name": "get_date"
      }
    }
  }
}
```

### 2. POST /heartbeat

**Purpose**: Keep agent alive, get current dependency resolution
**Used by**: Python runtime every 30 seconds
**Request**:

```json
{
  "agent_id": "myservice-abc123",
  "metadata": {
    "endpoint": "http://localhost:8889" // Optional, if changed
  }
}
```

**Response** (always returns full dependency resolution):

```json
{
  "status": "success",
  "dependencies_resolved": {
    "greet": {
      "date_service": {
        "agent_id": "dateservice-xyz",
        "endpoint": "http://date:8080",
        "tool_name": "get_date"
      }
    },
    "farewell": {} // No dependencies or none resolved
  }
}
```

**Note**: Registry always returns full state. Python compares and updates only if changed.

### 3. GET /agents/{agent_id}

**Purpose**: Get agent details with dependencies
**Used by**: Python runtime on reconnect/recovery
**Response**:

```json
{
  "agent_id": "myservice-abc123",
  "name": "myservice-abc123",
  "status": "healthy",
  "endpoint": "http://localhost:8889",
  "tools": [
    {
      "name": "greet",
      "capability": "greeting",
      "version": "1.0.0",
      "dependencies_resolved": {
        "date_service": {
          "agent_id": "dateservice-xyz",
          "endpoint": "http://date:8080",
          "tool_name": "get_date"
        }
      }
    }
  ]
}
```

## Discovery Endpoints (Used by Dashboard/CLI)

### 4. GET /capabilities

**Purpose**: Find tools by capability
**Used by**: Dashboard, CLI, service discovery
**Query params**:

- `name`: Capability name (fuzzy match supported)
- `version`: Version constraint
- `tags`: Comma-separated tags
- `status`: Agent status filter

**Response**:

```json
{
  "capabilities": [
    {
      "capability": "greeting",
      "tool_name": "greet",
      "version": "1.0.0",
      "agent_id": "service1-abc",
      "agent_name": "service1",
      "agent_status": "healthy",
      "endpoint": "http://service1:8080",
      "tags": ["demo", "v1"]
    },
    {
      "capability": "greeting",
      "tool_name": "hello",
      "version": "2.0.0",
      "agent_id": "service2-def",
      "agent_name": "service2",
      "agent_status": "healthy",
      "endpoint": "http://service2:8090",
      "tags": ["production"]
    }
  ],
  "count": 2
}
```

### 5. GET /agents

**Purpose**: List all agents
**Used by**: Dashboard, monitoring
**Query params**:

- `status`: Filter by status
- `namespace`: Filter by namespace
- `labels`: Filter by labels

**Response**:

```json
{
  "agents": [
    {
      "agent_id": "service1-abc",
      "name": "service1",
      "status": "healthy",
      "endpoint": "http://service1:8080",
      "tool_count": 3,
      "last_heartbeat": "2024-01-01T12:00:00Z"
    }
  ],
  "count": 1
}
```

### 6. GET /health

**Purpose**: Registry health check
**Used by**: Kubernetes, monitoring
**Response**:

```json
{
  "status": "healthy",
  "version": "1.0.0",
  "uptime_seconds": 3600,
  "agent_count": 42,
  "capability_count": 150
}
```

## Key Design Decisions

1. **Dependency Resolution**:

   - Returned in registration response (initial setup)
   - Returned in heartbeat response (updates)
   - Returned in agent GET (recovery)

2. **Separation of Concerns**:

   - Core endpoints: Minimal, focused on runtime needs
   - Discovery endpoints: Rich querying for dashboards

3. **Efficiency**:

   - Heartbeat is lightweight (only returns deps if changed)
   - Registration returns all deps immediately
   - No unnecessary data transfer

4. **Use Cases**:
   - Python runtime: Uses /register, /heartbeat, /agents/{id}
   - Dashboard: Uses /capabilities, /agents
   - CLI: Uses /capabilities for discovery
   - Monitoring: Uses /health, /agents
