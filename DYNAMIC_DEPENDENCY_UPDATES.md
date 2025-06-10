# Dynamic Dependency Updates in MCP Mesh

## Overview

MCP Mesh provides revolutionary dynamic dependency injection that allows services to adapt to changing environments without restarts. Dependencies are automatically re-evaluated during heartbeats, and functions receive updated dependency instances seamlessly.

## Key Features

### 1. Automatic Dependency Change Detection

Dependencies are checked for changes during each heartbeat interval (default: 30 seconds):

- New services becoming available are automatically discovered
- Failed services are removed from injection
- Better providers replace existing ones based on health/performance

### 2. Configurable Update Strategies

Control how dependency updates are applied using the `MCP_MESH_UPDATE_STRATEGY` environment variable:

```bash
# Immediate updates (default)
export MCP_MESH_UPDATE_STRATEGY=immediate

# Delayed updates with grace period
export MCP_MESH_UPDATE_STRATEGY=delayed
export MCP_MESH_UPDATE_GRACE_PERIOD=60  # 60 second delay

# Manual updates (changes logged but not applied)
export MCP_MESH_UPDATE_STRATEGY=manual
```

### 3. Zero-Downtime Transitions

Functions continue working during dependency transitions:

- Existing dependency instances remain valid until replaced
- No request failures during updates
- Graceful fallback if new dependency fails

## Implementation Details

### Dependency Tracking

The MeshAgentDecorator maintains detailed dependency state:

```python
# Internal tracking structure
self._resolved_dependencies = {
    "cache_service": {
        "instance": <service_instance>,
        "agent_id": "agent-abc123",
        "timestamp": datetime.now(),
        "needs_update": False,
        "new_agent_id": None
    }
}
```

### Update Process

1. **Detection Phase** (during heartbeat):

   - Query registry for current best agents
   - Compare with cached resolutions
   - Mark changed dependencies for update

2. **Scheduling Phase**:

   - Immediate: Apply updates right away
   - Delayed: Schedule update after grace period
   - Manual: Log changes only

3. **Application Phase**:
   - Clear dependency from cache
   - Update resolution metadata
   - Notify registered callbacks
   - Next function call gets new instance

### Callback Support

Register callbacks to be notified of dependency updates:

```python
def dependency_updated(dep_name: str, new_agent_id: str):
    print(f"Dependency {dep_name} updated to {new_agent_id}")

decorator = get_mesh_decorator_instance(my_function)
decorator.add_dependency_update_callback(dependency_updated)
```

## Example Usage

### Basic Configuration

```python
@mesh_agent(
    capability="data_processor",
    dependencies=["cache_service", "database_service"],
    version="1.0.0"
)
async def process_data(
    data: str,
    cache_service: Any | None = None,
    database_service: Any | None = None
) -> dict:
    # Function automatically receives updated dependencies
    # when better providers become available
    pass
```

### Monitoring Dependency Changes

```python
@mesh_agent(
    capability="dependency_monitor",
    dependencies=["registry_service"]
)
async def monitor_dependencies(registry_service: Any | None = None):
    if registry_service:
        services = await registry_service.list_services()
        # Track which services are available
```

## Environment Variables

| Variable                       | Default     | Description                                |
| ------------------------------ | ----------- | ------------------------------------------ |
| `MCP_MESH_DYNAMIC_UPDATES`     | `true`      | Enable/disable dynamic updates             |
| `MCP_MESH_UPDATE_STRATEGY`     | `immediate` | Update strategy (immediate/delayed/manual) |
| `MCP_MESH_UPDATE_GRACE_PERIOD` | `30`        | Seconds to wait for delayed updates        |

## Best Practices

### 1. Design for Change

Write functions that gracefully handle missing dependencies:

```python
if cache_service:
    # Use cache if available
    cached = await cache_service.get(key)
else:
    # Work without cache
    cached = None
```

### 2. Use Appropriate Strategies

- **Immediate**: For stateless services that can switch instantly
- **Delayed**: For stateful services needing graceful transitions
- **Manual**: For critical services requiring controlled updates

### 3. Monitor Updates

Use the monitoring tools to track dependency changes:

```python
status = await monitor_dependencies()
print(f"Available services: {status['dependencies']}")
```

## Demonstration

Run the dynamic dependency updates example:

```bash
# Terminal 1: Start the demo server
mcp-mesh-dev start examples/dynamic_dependency_updates.py

# Terminal 2: Start a cache service
mcp-mesh-dev start examples/cache_service.py

# Terminal 3: Test the behavior
# Dependencies are automatically injected after next heartbeat
```

## Technical Benefits

1. **High Availability**: Services continue operating during dependency changes
2. **Automatic Failover**: Failed dependencies are replaced automatically
3. **Performance Optimization**: Switch to better providers dynamically
4. **Zero Configuration**: Works out of the box with sensible defaults
5. **Kubernetes Ready**: Perfect for dynamic pod environments

## Integration with Service Mesh

Dynamic updates integrate seamlessly with:

- Health monitoring for dependency selection
- Service discovery for finding new providers
- Fallback chains for graceful degradation
- Registry capability trees for efficient lookups

This feature transforms MCP Mesh into a truly adaptive service mesh that responds to changing environments in real-time.
