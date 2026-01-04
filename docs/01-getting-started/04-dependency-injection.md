# Understanding Dependency Injection in MCP Mesh

> How the dual decorator pattern enables smart service discovery and dependency injection

## What is Dependency Injection?

MCP Mesh's **dual decorator pattern** provides powerful dependency injection:

- 🔗 **Smart capability matching** using tags and metadata
- 🎯 **Type-safe injection** with `mesh.McpMeshAgent` or flexible `Any` types
- 🏷️ **Tag-based resolution** for intelligent service selection
- 📞 **Seamless function calls** - remote functions work like local ones
- 🔄 **Automatic discovery** - no configuration files or service URLs needed
- 🚀 **Zero boilerplate** - Mesh handles all the complexity

## Core Concepts

### 1. Capabilities vs Function Names

There's an important distinction in MCP Mesh:

- **Function names**: What you call via MCP (`hello_mesh_simple`)
- **Capability names**: What other agents depend on (`greeting`)

```python
import mesh
from fastmcp import FastMCP

app = FastMCP("Demo Service")

@app.tool()  # MCP calls use function name: "get_current_time"
@mesh.tool(
    capability="date_service",  # Others depend on: "date_service"
    tags=["system", "time"]
)
def get_current_time() -> str:  # Function name can be anything!
    return datetime.now().strftime("%B %d, %Y")
```

### 2. Simple Dependency Declaration

Declare what capabilities you need:

```python
@app.tool()
@mesh.tool(
    capability="weather_advisor",
    dependencies=["date_service"]  # ← Simple capability name
)
def get_weather_advice(date_service: mesh.McpMeshAgent = None) -> str:
    if date_service:
        current_date = date_service()  # Call remote function
        return f"Weather advice for {current_date}"
    return "Weather advice (date not available)"
```

### 3. Smart Tag-Based Dependencies

Use tags for intelligent service selection:

```python
@app.tool()
@mesh.tool(
    capability="system_reporter",
    dependencies=[
        "date_service",  # Simple dependency
        {
            "capability": "info",
            "tags": ["system", "general"]  # ← Smart tag matching!
        }
    ]
)
def create_system_report(
    date_service: mesh.McpMeshAgent = None,
    info: mesh.McpMeshAgent = None  # Gets general system info
) -> dict:
    report = {"generated_at": "unknown", "system_info": "unavailable"}

    if date_service:
        report["generated_at"] = date_service()

    if info:
        system_data = info()  # Smart matching gets general info
        report["system_info"] = system_data

    return report
```

## Smart Tag Matching in Action

### Multiple Services, Same Capability

Consider a system agent providing two different `info` services:

```python
# System agent provides TWO info services with different tags
app = FastMCP("System Agent")

@app.tool()
@mesh.tool(
    capability="info",  # Same capability name
    tags=["system", "general"]  # General system info
)
def fetch_system_overview() -> dict:
    return {
        "server_name": "system-agent",
        "uptime": "120 seconds",
        "version": "1.0.0"
    }

@app.tool()
@mesh.tool(
    capability="info",  # Same capability name
    tags=["system", "disk"]  # Disk-specific info
)
def analyze_storage_and_os() -> dict:
    return {
        "disk_usage": "75%",
        "filesystem": "ext4",
        "mount_points": ["/", "/home"]
    }
```

### Smart Resolution Based on Tags

Now other agents can request specific info types:

```python
# Gets GENERAL system info (not disk info)
@mesh.tool(
    dependencies=[{
        "capability": "info",
        "tags": ["system", "general"]  # Matches first service
    }]
)
def get_general_status(info: mesh.McpMeshAgent = None):
    return info()  # Returns server_name, uptime, version

# Gets DISK info (not general info)
@mesh.tool(
    dependencies=[{
        "capability": "info",
        "tags": ["system", "disk"]  # Matches second service
    }]
)
def get_storage_status(info: mesh.McpMeshAgent = None):
    return info()  # Returns disk_usage, filesystem, mount_points
```

## Type Safety Options

### Option 1: Type-Safe with `mesh.McpMeshAgent`

```python
@app.tool()
@mesh.tool(
    capability="analytics",
    dependencies=["time_service", "data_service"]
)
def analyze_data(
    data: list,
    time_service: mesh.McpMeshAgent = None,  # Type-safe
    data_service: mesh.McpMeshAgent = None   # IDE support
) -> dict:
    timestamp = time_service() if time_service else "unknown"
    processed = data_service(data) if data_service else data

    return {
        "analysis": "completed",
        "timestamp": timestamp,
        "processed_data": processed
    }
```

### Option 2: Flexible with `Any`

```python
from typing import Any

@app.tool()
@mesh.tool(
    capability="flexible_processor",
    dependencies=["time_service"]
)
def process_flexibly(data: Any, time_service: Any = None) -> dict:
    # Maximum flexibility - works with any proxy implementation
    result = {"data": data}
    if time_service:
        result["timestamp"] = time_service()
    return result
```

## Advanced Dependency Patterns

### Self-Dependencies

Agents can depend on their own capabilities:

```python
@app.tool()
@mesh.tool(
    capability="health_check",
    dependencies=["date_service"]  # Uses own date_service
)
def perform_health_check(date_service: mesh.McpMeshAgent = None) -> dict:
    status = {"status": "healthy", "memory": "normal"}

    if date_service:
        status["timestamp"] = date_service()  # Self-dependency!

    return status
```

### Complex Tag Combinations

```python
@app.tool()
@mesh.tool(
    capability="comprehensive_report",
    dependencies=[
        "date_service",  # Simple dependency
        {
            "capability": "info",
            "tags": ["system", "general"]  # General system info
        },
        {
            "capability": "info",
            "tags": ["system", "disk"]     # Disk info
        }
    ]
)
def create_full_report(
    date_service: mesh.McpMeshAgent = None,
    info: mesh.McpMeshAgent = None,      # Gets general info
    disk_info: mesh.McpMeshAgent = None  # Gets disk info
) -> dict:
    # This function gets THREE injected services!
    return {
        "timestamp": date_service() if date_service else "unknown",
        "system": info() if info else {},
        "storage": disk_info() if disk_info else {}
    }
```

## How It Works Behind the Scenes

### 1. Service Registration

When agents start, mesh automatically:

```python
# System agent registers:
{
    "agent_id": "system-agent-abc123",
    "capabilities": {
        "date_service": {
            "function": "get_current_time",
            "tags": ["system", "time"],
            "endpoint": "http://system-agent:8080/mcp"
        },
        "info": [
            {
                "function": "fetch_system_overview",
                "tags": ["system", "general"],
                "endpoint": "http://system-agent:8080/mcp"
            },
            {
                "function": "analyze_storage_and_os",
                "tags": ["system", "disk"],
                "endpoint": "http://system-agent:8080/mcp"
            }
        ]
    }
}
```

### 2. Dependency Resolution

When hello world agent starts:

```python
# Mesh resolves dependencies:
dependencies = [
    "date_service",  # Finds: system-agent.get_current_time
    {
        "capability": "info",
        "tags": ["system", "general"]  # Finds: system-agent.fetch_system_overview
    }
]
```

### 3. Proxy Creation

Mesh creates callable proxies:

```python
# Injected date_service becomes:
def date_service_proxy():
    response = http_post("http://system-agent:8080/mcp", {
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {
            "name": "get_current_time",  # Function name!
            "arguments": {}
        }
    })
    return response.result
```

## Testing Dependency Injection

### Check Service Registration

```bash
# See what agents are registered
meshctl list
```

### Test Individual Services

```bash
# Test date service directly
meshctl call get_current_time

# Test dependency injection (hello_mesh_simple calls date_service internally)
meshctl call hello_mesh_simple
```

<details>
<summary>Alternative: Using curl directly</summary>

```bash
# View registry
curl -s http://localhost:8000/agents | \
  jq '.agents[] | {name: .name, capabilities: (.capabilities | keys)}'

# Test date service directly
curl -s -X POST http://localhost:8080/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"get_current_time","arguments":{}}}'

# Test dependency injection
curl -s -X POST http://localhost:9090/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"hello_mesh_simple","arguments":{}}}'
```

</details>

## Benefits of the New Pattern

### For Developers

- **Familiar FastMCP** - Keep using `@app.tool()` decorators
- **Enhanced capabilities** - Add `@mesh.tool()` for orchestration
- **Type safety** - Choose between `mesh.McpMeshAgent` and `Any`
- **Smart resolution** - Tag-based service selection

### For Operations

- **Zero configuration** - No service URLs or config files
- **Automatic discovery** - Services find each other automatically
- **Graceful degradation** - Functions work without dependencies
- **Real-time updates** - Dependencies resolve dynamically

## Troubleshooting

### Dependency Not Injected

```bash
# Quick check - see if all dependencies are resolved (e.g., "4/4")
meshctl list

# Detailed view - shows capabilities, resolved dependencies, and endpoints
meshctl status
```

### Wrong Service Selected

- Check your **tags** - they determine which service is selected
- Use specific tag combinations for precise matching
- Remember: `"general"` vs `"disk"` tags select different services

### Type Errors

- Use `mesh.McpMeshAgent` for better IDE support
- Use `Any` for maximum flexibility
- Always check if dependency is `None` before calling

## Next Steps

Now that you understand dependency injection, let's create a complete agent:

**[Creating Your First Agent](./05-first-agent.md)** →

### Reference Guides

- **[Mesh Decorators](../mesh-decorators.md)** - Complete decorator parameters and patterns

---

💡 **Key Insight**: The dual decorator pattern gives you familiar FastMCP development with powerful mesh orchestration - the best of both worlds!

🏷️ **Pro Tip**: Use tags strategically to enable smart service selection - same capability name, different behaviors based on tags.
