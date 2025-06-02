# MCP Mesh Registry Service

The Registry Service is the central coordination component of the MCP Mesh, implementing a **PASSIVE pull-based architecture** following Kubernetes API server patterns.

## Architecture Overview

- **PASSIVE Design**: Registry only responds to agent requests; never initiates calls to agents
- **Pull-based**: Agents register themselves and send periodic heartbeats
- **FastMCP Integration**: Built on FastMCP server architecture for high performance
- **Kubernetes Patterns**: Resource versioning, watches, and API server conventions
- **Vanilla MCP Compatibility**: Agents only import from `mcp-mesh-types` package

## Key Components

### 1. Registry Service (`registry.py`)

- Central FastMCP server providing registration and discovery APIs
- ETCD-style storage with resource versioning
- Health monitoring through agent heartbeats
- Capability-based service discovery

### 2. Registry Server (`registry_server.py`)

- Command-line interface for starting the registry
- Uvicorn integration for production deployment
- Signal handling for graceful shutdown

### 3. Client Integration

- `@mesh_agent` decorator handles all registry communication
- Automatic registration, heartbeats, and service discovery
- No boilerplate code required in agent implementations

## API Endpoints

The registry provides these MCP tools:

- `register_agent`: Register or update agent in the mesh
- `unregister_agent`: Remove agent from the mesh
- `discover_services`: Find services by capabilities/labels
- `heartbeat`: Send agent health status
- `get_agent_status`: Get detailed agent information

## Usage

### Starting the Registry

```bash
# Default configuration
python -m mcp_mesh.server.registry_server

# Custom host/port
python -m mcp_mesh.server.registry_server --host 0.0.0.0 --port 9000

# Using pip-installed script
mcp-mesh-registry --host localhost --port 8000
```

### Agent Integration

```python
from mcp_mesh_types import mesh_agent

@mesh_agent(
    capabilities=["file_read", "file_write"],
    dependencies=["auth_service"],
    health_interval=30,
    registry_endpoint="http://localhost:8000"
)
async def my_tool(path: str) -> str:
    # Tool implementation
    # Registry integration is automatic
    pass
```

## Service Discovery

Agents can discover services using:

```python
# Find services by capability
query = {
    "capabilities": ["file_read"],
    "status": "healthy"
}

# Find services by labels
query = {
    "labels": {"type": "database", "version": "1.0"},
    "namespace": "production"
}
```

## Health Monitoring

- Agents send periodic heartbeats based on `health_interval`
- Registry marks agents as unhealthy if heartbeat is overdue
- Background health check process runs every 30 seconds
- Status values: `pending`, `healthy`, `unhealthy`, `offline`

## Security Features

- Security context validation for agent registration
- Capability-based access control
- Resource versioning prevents conflicts
- Audit trail through timestamps and metadata

## Production Deployment

The registry is designed for production use with:

- Uvicorn ASGI server for high performance
- Structured logging and monitoring
- Graceful shutdown handling
- Resource versioning for consistency
- Watch streams for real-time updates

## Example Workflow

1. **Agent Startup**: Agent decorated with `@mesh_agent` automatically registers
2. **Health Monitoring**: Agent sends periodic heartbeats to maintain health status
3. **Service Discovery**: Other agents discover this agent through capability queries
4. **Dependency Injection**: Registry provides dependency services to agents
5. **Graceful Shutdown**: Agent unregisters when stopping

## Kubernetes API Server Patterns

The registry implements several Kubernetes patterns:

- **Resource Metadata**: Each agent has labels, annotations, and timestamps
- **Resource Versioning**: Optimistic concurrency control
- **Watch Streams**: Real-time event notifications
- **Namespaces**: Logical grouping of services
- **Label Selectors**: Flexible query mechanisms
- **Status Subresources**: Separate status from spec data
