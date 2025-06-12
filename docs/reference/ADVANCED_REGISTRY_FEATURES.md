# Advanced Registry Features Documentation

## Overview

The MCP Mesh Registry provides advanced features that enhance service discovery, agent management, and system reliability. These features complement the MCP SDK while providing powerful capabilities for distributed agent systems.

## Core Registry Features

### 1. Agent Registration and Discovery

The registry supports comprehensive agent registration with rich metadata:

```python
from mcp_mesh_types.service_discovery import (
    ServiceInfo, ServiceDiscoveryInterface,
    DiscoveryMetadata, DiscoveryOptions
)

# Agent registration with metadata
service_info = ServiceInfo(
    name="file-agent",
    version="1.0.0",
    host="localhost",
    port=8080,
    capabilities=["file_read", "file_write", "file_list"],
    health_endpoint="/health",
    metadata={
        "description": "File operations agent",
        "supported_formats": ["txt", "json", "yaml"],
        "max_file_size": "10MB"
    }
)
```

### 2. Advanced Service Discovery

#### Capability-Based Discovery

Find agents based on specific capabilities:

```python
from mcp_mesh_types.agent_selection import (
    AgentSelectionCriteria, CapabilityRequirement,
    AgentSelector, SelectionStrategy
)

# Find agents with specific capabilities
criteria = AgentSelectionCriteria(
    required_capabilities=["file_read", "json_parse"],
    preferred_capabilities=["file_write"],
    version_constraints={"min": "1.0.0", "max": "2.0.0"},
    performance_requirements={
        "max_response_time": 1000,  # milliseconds
        "min_availability": 0.99
    }
)

selector = AgentSelector()
agents = await selector.select_agents(criteria)
```

#### Intelligent Agent Selection

Multiple selection strategies for different use cases:

```python
# Round-robin selection
strategy = SelectionStrategy.ROUND_ROBIN
selected = await selector.select_agent(criteria, strategy)

# Performance-based selection
strategy = SelectionStrategy.PERFORMANCE_BASED
selected = await selector.select_agent(criteria, strategy)

# Load-aware selection
strategy = SelectionStrategy.LOAD_AWARE
selected = await selector.select_agent(criteria, strategy)
```

### 3. Health Monitoring and Management

#### Continuous Health Monitoring

```python
from mcp_mesh_types.lifecycle import (
    HealthStatus, LifecycleManager,
    HealthCheckConfig, AgentHealth
)

# Configure health monitoring
health_config = HealthCheckConfig(
    interval=30,  # seconds
    timeout=5,    # seconds
    retries=3,
    failure_threshold=3
)

lifecycle_manager = LifecycleManager(health_config)
await lifecycle_manager.start_monitoring("agent-id")
```

#### Health Status Tracking

```python
# Get agent health status
health = await lifecycle_manager.get_health_status("agent-id")
print(f"Status: {health.status}")
print(f"Last check: {health.last_check}")
print(f"Response time: {health.response_time}ms")
```

### 4. Version Management

#### Semantic Versioning Support

```python
from mcp_mesh_types.versioning import (
    Version, VersionManager, VersionConstraint,
    CompatibilityCheck
)

# Version management
version_manager = VersionManager()

# Register agent with version
await version_manager.register_version(
    agent_id="file-agent",
    version="1.2.0",
    compatibility_info={
        "backward_compatible": ["1.0.0", "1.1.0"],
        "breaking_changes": ["0.9.0"]
    }
)

# Find compatible versions
compatible = await version_manager.find_compatible_versions(
    agent_type="file-agent",
    constraint=">=1.0.0,<2.0.0"
)
```

### 5. Configuration Management

#### Dynamic Configuration

```python
from mcp_mesh_types.configuration import (
    ConfigurationManager, ConfigurationSchema,
    ConfigurationUpdate, ValidationRule
)

# Configuration schema definition
schema = ConfigurationSchema(
    properties={
        "max_connections": {"type": "integer", "minimum": 1, "maximum": 1000},
        "timeout": {"type": "integer", "minimum": 1000, "maximum": 30000},
        "retry_policy": {
            "type": "object",
            "properties": {
                "max_retries": {"type": "integer", "minimum": 0},
                "backoff_factor": {"type": "number", "minimum": 1.0}
            }
        }
    },
    required=["max_connections", "timeout"]
)

config_manager = ConfigurationManager(schema)

# Update configuration
update = ConfigurationUpdate(
    agent_id="file-agent",
    configuration={
        "max_connections": 100,
        "timeout": 5000,
        "retry_policy": {
            "max_retries": 3,
            "backoff_factor": 2.0
        }
    }
)

await config_manager.update_configuration(update)
```

## API Reference

### Registry Server API

#### Agent Management Endpoints

- `POST /agents/register` - Register a new agent
- `PUT /agents/{agent_id}` - Update agent information
- `DELETE /agents/{agent_id}` - Unregister agent
- `GET /agents` - List all agents
- `GET /agents/{agent_id}` - Get specific agent details

#### Discovery Endpoints

- `POST /discovery/find` - Find agents by criteria
- `POST /discovery/select` - Select agent using strategy
- `GET /discovery/capabilities` - List available capabilities

#### Health Monitoring Endpoints

- `GET /health/{agent_id}` - Get agent health status
- `POST /health/{agent_id}/check` - Trigger health check
- `GET /health/summary` - Get system health summary

### Client Library API

#### Registry Client

```python
from mcp_mesh.shared.registry_client import RegistryClient

client = RegistryClient("http://localhost:8000")

# Register agent
await client.register_agent(service_info)

# Discover agents
agents = await client.discover_agents(criteria)

# Monitor health
health = await client.get_agent_health(agent_id)
```

## Integration Patterns

### 1. MCP SDK Enhancement Pattern

The registry enhances MCP SDK capabilities without replacing core functionality:

```python
# Standard MCP SDK usage
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# Enhanced with registry discovery
from mcp_mesh_types.service_discovery import ServiceDiscoveryInterface

# Discover MCP server
discovery = ServiceDiscoveryInterface()
server_info = await discovery.discover_service("file-operations")

# Connect using standard MCP SDK
server_params = StdioServerParameters(
    command="python",
    args=["-m", "file_agent"],
    env={"PORT": str(server_info.port)}
)

async with stdio_client(server_params) as (read, write):
    async with ClientSession(read, write) as session:
        # Standard MCP operations
        result = await session.call_tool("read_file", {"path": "/tmp/test.txt"})
```

### 2. Decorator Integration Pattern

Seamless integration with existing MCP servers:

```python
from mcp_mesh.decorators.mesh_agent import mesh_agent
from mcp import Server

@mesh_agent(
    capabilities=["file_read", "file_write"],
    registry_url="http://localhost:8000",
    health_check_path="/health"
)
class FileAgent:
    def __init__(self):
        self.server = Server("file-agent")

    @self.server.tool()
    async def read_file(self, path: str) -> str:
        # Implementation
        pass
```

### 3. Graceful Degradation Pattern

System continues operating even when registry is unavailable:

```python
# Automatic fallback when registry is unavailable
try:
    agents = await discovery.discover_agents(criteria)
except RegistryUnavailableError:
    # Fall back to local configuration
    agents = load_fallback_agents()
    logger.warning("Registry unavailable, using fallback configuration")
```

## Performance Considerations

### 1. Caching Strategy

- Service discovery results are cached for 5 minutes by default
- Health status is cached for 30 seconds
- Configuration changes invalidate relevant caches

### 2. Connection Pooling

- HTTP client uses connection pooling for registry API calls
- WebSocket connections for real-time health monitoring
- Configurable connection limits and timeouts

### 3. Async Operations

All registry operations are fully asynchronous:

```python
# Concurrent operations
import asyncio

tasks = [
    discovery.discover_agents(criteria1),
    discovery.discover_agents(criteria2),
    health_monitor.check_agent("agent1"),
    health_monitor.check_agent("agent2")
]

results = await asyncio.gather(*tasks)
```

## Security Features

### 1. Authentication

- API key authentication for registry access
- JWT tokens for session management
- Role-based access control (RBAC)

### 2. Validation

- Input validation for all API endpoints
- Schema validation for configuration updates
- Capability verification for agent registration

### 3. Rate Limiting

- Per-client rate limiting for API calls
- Burst protection for discovery requests
- Health check frequency limits

## Monitoring and Observability

### 1. Metrics

Key metrics exposed:

- Agent registration/deregistration rates
- Discovery request latency
- Health check success/failure rates
- System resource utilization

### 2. Logging

Structured logging with:

- Request/response logging
- Health check results
- Configuration changes
- Error tracking

### 3. Tracing

Distributed tracing support for:

- Service discovery flows
- Agent selection processes
- Health monitoring operations

## Best Practices

### 1. Agent Design

- Implement proper health check endpoints
- Use semantic versioning consistently
- Provide comprehensive capability metadata
- Handle graceful shutdown procedures

### 2. Discovery Optimization

- Cache discovery results appropriately
- Use specific capability requirements
- Implement circuit breaker patterns
- Monitor discovery performance

### 3. Health Monitoring

- Set appropriate health check intervals
- Implement meaningful health indicators
- Use exponential backoff for failed checks
- Provide detailed health status information

## Troubleshooting

### Common Issues

1. **Agent Registration Failures**

   - Check network connectivity to registry
   - Verify agent metadata format
   - Ensure unique agent identifiers

2. **Discovery Not Finding Agents**

   - Verify capability requirements
   - Check version constraints
   - Review agent health status

3. **Health Check Failures**
   - Validate health endpoint implementation
   - Check network timeouts
   - Review health check configuration

### Debug Tools

```python
# Enable debug logging
import logging
logging.getLogger("mcp_mesh").setLevel(logging.DEBUG)

# Registry diagnostics
diagnostics = await client.get_diagnostics()
print(f"Registered agents: {diagnostics.agent_count}")
print(f"Active connections: {diagnostics.connection_count}")
```

## Migration Guide

### From Manual Configuration

1. Replace static agent lists with dynamic discovery
2. Add health monitoring for existing agents
3. Implement version management
4. Enable configuration management

### From Basic MCP Setup

1. Add registry client to existing MCP applications
2. Enhance with capability-based discovery
3. Implement health monitoring
4. Add version compatibility checks

This documentation provides a comprehensive guide to the advanced registry features available in MCP Mesh, enabling you to build robust, scalable, and maintainable distributed agent systems.
