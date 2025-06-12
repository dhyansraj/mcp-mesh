# Pull-Based Registry API Patterns and Usage

## Overview

The MCP Mesh Registry Service implements a **pull-based architecture** following the **Kubernetes API Server pattern**. This document provides comprehensive guidance on API patterns, usage examples, and best practices for integrating with the registry.

## Architecture Principles

### Pull-Based Design

- **Agents initiate all communication** with the registry
- **Registry NEVER calls agents** - it is entirely passive
- **Registry responds to queries** but doesn't push updates
- **Kubernetes API server pattern** for resource management

### Key Characteristics

- ✅ **Passive Registry**: Only responds to incoming requests
- ✅ **Agent-Driven**: Agents control registration, heartbeats, and discovery
- ✅ **Resource Versioning**: Kubernetes-style resource versioning
- ✅ **Watch Events**: Optional event streaming for real-time updates
- ✅ **Declarative State**: Registry maintains desired vs actual state
- ✅ **Health Monitoring**: Timer-based passive health checks

## API Endpoints

### MCP Protocol Endpoints

The registry provides standard MCP tools accessible via `/mcp/tools/`:

#### 1. Agent Registration

```http
POST /mcp/tools/register_agent
Content-Type: application/json

{
  "registration_data": {
    "id": "file-agent-001",
    "name": "File Operations Agent",
    "namespace": "system",
    "agent_type": "file_agent",
    "endpoint": "http://localhost:8001/mcp",
    "capabilities": [
      {
        "name": "read_file",
        "description": "Read file contents",
        "category": "file_operations",
        "version": "1.2.0",
        "stability": "stable",
        "tags": ["io", "filesystem"],
        "input_schema": {
          "type": "object",
          "properties": {
            "file_path": {"type": "string"}
          },
          "required": ["file_path"]
        }
      }
    ],
    "labels": {
      "env": "production",
      "team": "platform"
    },
    "security_context": "standard",
    "health_interval": 30.0
  }
}
```

**Response:**

```json
{
  "status": "success",
  "agent_id": "file-agent-001",
  "resource_version": "1635789123456",
  "message": "Agent File Operations Agent registered successfully"
}
```

#### 2. Service Discovery

```http
POST /mcp/tools/discover_services
Content-Type: application/json

{
  "query": {
    "namespace": "system",
    "capabilities": ["read_file"],
    "status": "healthy",
    "labels": {"env": "production"},
    "fuzzy_match": false,
    "version_constraint": ">=1.0.0"
  }
}
```

**Response:**

```json
{
  "status": "success",
  "agents": [
    {
      "id": "file-agent-001",
      "name": "File Operations Agent",
      "namespace": "system",
      "status": "healthy",
      "endpoint": "http://localhost:8001/mcp",
      "capabilities": [...],
      "last_heartbeat": "2024-01-15T10:30:00Z",
      "resource_version": "1635789123456"
    }
  ],
  "count": 1
}
```

#### 3. Heartbeat

```http
POST /mcp/tools/heartbeat
Content-Type: application/json

{
  "agent_id": "file-agent-001"
}
```

**Response:**

```json
{
  "status": "success",
  "timestamp": "2024-01-15T10:30:00Z",
  "message": "Heartbeat recorded"
}
```

#### 4. Agent Status

```http
POST /mcp/tools/get_agent_status
Content-Type: application/json

{
  "agent_id": "file-agent-001"
}
```

#### 5. Agent Unregistration

```http
POST /mcp/tools/unregister_agent
Content-Type: application/json

{
  "agent_id": "file-agent-001"
}
```

### REST API Endpoints

For convenience, the registry also provides REST endpoints:

#### Agent Discovery

```http
GET /agents?namespace=system&status=healthy&capability=read_file
GET /agents?label_selector=env=production,team=platform
GET /agents?fuzzy_match=true&capability=file
GET /agents?version_constraint=%3E%3D1.0.0  # >=1.0.0 URL encoded
```

#### Capability Search

```http
GET /capabilities?category=file_operations&stability=stable
GET /capabilities?name=read&fuzzy_match=true
GET /capabilities?tags=filesystem&agent_status=healthy
GET /capabilities?description_contains=file&include_deprecated=false
```

#### Health and Monitoring

```http
POST /heartbeat
GET /health/{agent_id}
GET /health
GET /metrics
GET /metrics/prometheus
```

## Usage Patterns

### 1. Basic Agent Registration Pattern

```python
from mcp_mesh_types.exceptions import SecurityValidationError
from mcp_mesh.shared.registry_client import RegistryClient

class MyAgent:
    def __init__(self, registry_url="http://localhost:8000"):
        self.registry_client = RegistryClient(registry_url)
        self.agent_id = "my-agent-001"
        self.heartbeat_interval = 30.0

    async def start(self):
        """Start agent with registry registration."""
        # 1. Register with registry
        registration_data = {
            "id": self.agent_id,
            "name": "My Custom Agent",
            "namespace": "custom",
            "agent_type": "custom_agent",
            "endpoint": "http://localhost:8010/mcp",
            "capabilities": [
                {
                    "name": "custom_operation",
                    "description": "My custom operation",
                    "category": "custom",
                    "version": "1.0.0",
                    "stability": "stable"
                }
            ],
            "labels": {"env": "development"},
            "security_context": "standard",
            "health_interval": self.heartbeat_interval
        }

        try:
            result = await self.registry_client.register_agent(registration_data)
            if result["status"] == "success":
                print(f"Registered with registry: {result['agent_id']}")

                # 2. Start heartbeat loop
                asyncio.create_task(self._heartbeat_loop())
            else:
                print(f"Registration failed: {result.get('message', 'Unknown error')}")
        except Exception as e:
            print(f"Registry communication failed: {e}")
            # Continue without registry (graceful degradation)

    async def _heartbeat_loop(self):
        """Send periodic heartbeats to registry."""
        while True:
            try:
                result = await self.registry_client.heartbeat(self.agent_id)
                if result["status"] != "success":
                    print(f"Heartbeat failed: {result.get('message')}")
            except Exception as e:
                print(f"Heartbeat error: {e}")
                # Continue trying with exponential backoff in real implementation

            await asyncio.sleep(self.heartbeat_interval)
```

### 2. Service Discovery Pattern

```python
async def discover_file_agents():
    """Discover all file operation agents."""
    registry_client = RegistryClient("http://localhost:8000")

    # Method 1: Using MCP tools
    discovery_query = {
        "capability_category": "file_operations",
        "status": "healthy",
        "labels": {"env": "production"}
    }

    result = await registry_client.discover_services(discovery_query)
    if result["status"] == "success":
        for agent in result["agents"]:
            print(f"Found agent: {agent['name']} at {agent['endpoint']}")

    # Method 2: Using REST API
    async with aiohttp.ClientSession() as session:
        async with session.get(
            "http://localhost:8000/agents",
            params={
                "capability_category": "file_operations",
                "status": "healthy",
                "label_selector": "env=production"
            }
        ) as resp:
            if resp.status == 200:
                data = await resp.json()
                print(f"Found {data['count']} file agents")
```

### 3. Advanced Capability Search

```python
async def find_capabilities_by_criteria():
    """Advanced capability search with multiple criteria."""

    async with aiohttp.ClientSession() as session:
        # Search for stable file operations
        async with session.get(
            "http://localhost:8000/capabilities",
            params={
                "category": "file_operations",
                "stability": "stable",
                "agent_status": "healthy"
            }
        ) as resp:
            stable_file_caps = await resp.json()

        # Fuzzy search for monitoring capabilities
        async with session.get(
            "http://localhost:8000/capabilities",
            params={
                "name": "monitor",
                "fuzzy_match": "true",
                "include_deprecated": "false"
            }
        ) as resp:
            monitor_caps = await resp.json()

        # Search by tags
        async with session.get(
            "http://localhost:8000/capabilities",
            params={
                "tags": "filesystem,io",
                "version_constraint": ">=1.0.0"
            }
        ) as resp:
            tagged_caps = await resp.json()

        return {
            "stable_file_ops": stable_file_caps["capabilities"],
            "monitoring": monitor_caps["capabilities"],
            "filesystem_io": tagged_caps["capabilities"]
        }
```

### 4. Health Monitoring Pattern

```python
async def monitor_agent_health():
    """Monitor health of registered agents."""

    async with aiohttp.ClientSession() as session:
        # Get overall registry health
        async with session.get("http://localhost:8000/health") as resp:
            registry_health = await resp.json()
            print(f"Registry status: {registry_health['status']}")

        # Get specific agent health
        agent_id = "file-agent-001"
        async with session.get(f"http://localhost:8000/health/{agent_id}") as resp:
            if resp.status == 200:
                health = await resp.json()
                print(f"Agent {agent_id}:")
                print(f"  Status: {health['status']}")
                print(f"  Last heartbeat: {health['last_heartbeat']}")
                print(f"  Time since heartbeat: {health['time_since_heartbeat']}s")
                print(f"  Is expired: {health['is_expired']}")
            else:
                print(f"Agent {agent_id} not found")

        # Get registry metrics
        async with session.get("http://localhost:8000/metrics") as resp:
            metrics = await resp.json()
            print(f"Total agents: {metrics['total_agents']}")
            print(f"Healthy agents: {metrics['healthy_agents']}")
            print(f"Total capabilities: {metrics['total_capabilities']}")
```

### 5. Watch Events Pattern (Optional)

```python
async def watch_registry_events():
    """Watch for registry events (if using storage watchers)."""
    from mcp_mesh.server.registry import RegistryService

    # This would typically be done within the registry service
    service = RegistryService()
    await service.initialize()

    try:
        # Create watcher
        watcher = service.storage.create_watcher()

        while True:
            try:
                # Wait for events
                event = await asyncio.wait_for(watcher.get(), timeout=30.0)

                print(f"Event: {event['type']}")
                print(f"Agent: {event['object']['id']}")
                print(f"Timestamp: {event['timestamp']}")

                if event['type'] == 'ADDED':
                    print(f"New agent registered: {event['object']['name']}")
                elif event['type'] == 'MODIFIED':
                    print(f"Agent updated: {event['object']['name']}")
                elif event['type'] == 'DELETED':
                    print(f"Agent unregistered: {event['object']['name']}")

            except asyncio.TimeoutError:
                print("No events in 30 seconds")
    finally:
        await service.close()
```

## Best Practices

### 1. Agent Implementation

- **Always implement graceful degradation** when registry is unavailable
- **Use exponential backoff** for failed heartbeats
- **Cache service discovery results** locally
- **Re-register after network partitions**
- **Handle partial registry failures** gracefully

### 2. Service Discovery

- **Use specific queries** to reduce network overhead
- **Cache discovery results** with appropriate TTL
- **Implement fallback mechanisms** for critical services
- **Use version constraints** for compatibility
- **Leverage labels** for environment-specific discovery

### 3. Health Management

- **Set appropriate heartbeat intervals** based on agent criticality
- **Monitor health status** regularly
- **Implement health check endpoints** in agents
- **Use different timeout thresholds** for different agent types

### 4. Security

- **Validate security contexts** during registration
- **Use appropriate security contexts** based on agent capabilities
- **Implement authentication** for production deployments
- **Secure registry endpoints** with proper access controls

### 5. Performance

- **Use REST endpoints** for simple queries
- **Batch multiple operations** when possible
- **Implement response caching** for frequently accessed data
- **Monitor registry metrics** for performance insights

## Error Handling

### Common Error Scenarios

#### Registry Unavailable

```python
async def register_with_fallback():
    """Register with graceful fallback."""
    try:
        result = await registry_client.register_agent(registration_data)
        return result
    except (ConnectionError, TimeoutError) as e:
        print(f"Registry unavailable: {e}")
        # Continue operating without registry
        return {"status": "offline", "message": "Registry unavailable"}
```

#### Invalid Registration Data

```python
async def validate_registration():
    """Validate registration data before sending."""
    required_fields = ["id", "name", "namespace", "agent_type", "endpoint"]

    for field in required_fields:
        if not registration_data.get(field):
            raise ValueError(f"Missing required field: {field}")

    # Validate capabilities
    for cap in registration_data.get("capabilities", []):
        if not cap.get("name") or not cap.get("version"):
            raise ValueError("Capabilities must have name and version")
```

#### Heartbeat Failures

```python
async def robust_heartbeat_loop():
    """Heartbeat loop with error handling."""
    consecutive_failures = 0
    max_failures = 5

    while consecutive_failures < max_failures:
        try:
            result = await registry_client.heartbeat(agent_id)
            if result["status"] == "success":
                consecutive_failures = 0
                await asyncio.sleep(heartbeat_interval)
            else:
                consecutive_failures += 1
                backoff = min(300, 2 ** consecutive_failures)
                await asyncio.sleep(backoff)
        except Exception as e:
            consecutive_failures += 1
            print(f"Heartbeat failed: {e}")
            backoff = min(300, 2 ** consecutive_failures)
            await asyncio.sleep(backoff)

    print(f"Too many heartbeat failures, stopping after {max_failures} attempts")
```

## Integration Examples

### File Agent Integration

```python
# Import only from mcp-mesh-types for compatibility
from mcp_mesh_types.exceptions import SecurityValidationError

@mesh_agent(
    name="Enhanced File Agent",
    namespace="system",
    registry_url="http://localhost:8000"
)
class FileAgent:
    def __init__(self):
        self.capabilities = [
            {
                "name": "read_file",
                "description": "Read file contents securely",
                "category": "file_operations",
                "version": "1.2.0",
                "stability": "stable",
                "tags": ["io", "filesystem", "security"]
            }
        ]

    @tool(name="read_file")
    async def read_file(self, file_path: str) -> str:
        """Read file with security validation."""
        # Implementation here
        pass
```

### Command Agent Integration

```python
@mesh_agent(
    name="Secure Command Agent",
    namespace="system",
    registry_url="http://localhost:8000",
    security_context="high_security"
)
class CommandAgent:
    def __init__(self):
        self.capabilities = [
            {
                "name": "execute_command",
                "description": "Execute system commands with audit trail",
                "category": "system_operations",
                "version": "2.1.0",
                "stability": "stable",
                "tags": ["shell", "audit", "security"]
            },
            {
                "name": "authentication",
                "description": "User authentication",
                "category": "security",
                "version": "1.0.0"
            },
            {
                "name": "authorization",
                "description": "Permission checks",
                "category": "security",
                "version": "1.0.0"
            },
            {
                "name": "audit",
                "description": "Security audit logging",
                "category": "security",
                "version": "1.0.0"
            }
        ]
```

## Monitoring and Observability

### Prometheus Metrics

The registry exposes Prometheus metrics at `/metrics/prometheus`:

```bash
# HELP mcp_registry_agents_total Total number of registered agents
# TYPE mcp_registry_agents_total gauge
mcp_registry_agents_total 5

# HELP mcp_registry_agents_by_status Number of agents by status
# TYPE mcp_registry_agents_by_status gauge
mcp_registry_agents_by_status{status="healthy"} 4
mcp_registry_agents_by_status{status="degraded"} 1
mcp_registry_agents_by_status{status="expired"} 0

# HELP mcp_registry_capabilities_total Total number of capabilities
# TYPE mcp_registry_capabilities_total gauge
mcp_registry_capabilities_total 15

# HELP mcp_registry_uptime_seconds Registry uptime in seconds
# TYPE mcp_registry_uptime_seconds counter
mcp_registry_uptime_seconds 86400
```

### Health Check Dashboard

```python
async def create_health_dashboard():
    """Create health monitoring dashboard."""
    async with aiohttp.ClientSession() as session:
        # Get registry metrics
        async with session.get("http://localhost:8000/metrics") as resp:
            metrics = await resp.json()

        # Get all agents with health status
        async with session.get("http://localhost:8000/agents") as resp:
            agents_data = await resp.json()

        dashboard = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "registry": {
                "status": "healthy",
                "uptime_seconds": metrics["uptime_seconds"],
                "total_agents": metrics["total_agents"],
                "healthy_agents": metrics["healthy_agents"],
                "degraded_agents": metrics["degraded_agents"],
                "expired_agents": metrics["expired_agents"]
            },
            "agents": []
        }

        for agent in agents_data["agents"]:
            # Get detailed health for each agent
            async with session.get(f"http://localhost:8000/health/{agent['id']}") as resp:
                if resp.status == 200:
                    health = await resp.json()
                    dashboard["agents"].append({
                        "id": agent["id"],
                        "name": agent["name"],
                        "status": health["status"],
                        "last_heartbeat": health["last_heartbeat"],
                        "time_since_heartbeat": health["time_since_heartbeat"],
                        "capabilities_count": len(agent["capabilities"])
                    })

        return dashboard
```

## Conclusion

The Pull-Based Registry API provides a robust, scalable foundation for MCP agent service discovery and management. By following these patterns and best practices, you can build resilient agent systems that handle failures gracefully and scale effectively.

Key takeaways:

- **Always implement graceful degradation**
- **Use appropriate caching strategies**
- **Monitor health and metrics continuously**
- **Follow security best practices**
- **Design for failure scenarios**

For more information, see:

- [MCP Protocol Integration Guide](MCP_PROTOCOL_INTEGRATION.md)
- [Architecture Overview](ARCHITECTURE_OVERVIEW.md)
- [Error Handling Types](ERROR_HANDLING_TYPES.md)
