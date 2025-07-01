# MCP Mesh Decorators Reference

> Complete guide to @mesh.tool and @mesh.agent decorators - order matters!

## Critical: Decorator Order

**⚠️ IMPORTANT**: Mesh decorators must come **AFTER** MCP decorators:

```python
# ✅ CORRECT ORDER
@app.tool()        # ← FastMCP decorator FIRST
@mesh.tool(        # ← Mesh decorator SECOND
    capability="greeting"
)
def hello_world():
    return "Hello!"

# ❌ WRONG ORDER - This will not work!
@mesh.tool(capability="greeting")  # ← Wrong: mesh first
@app.tool()                        # ← Wrong: FastMCP second
def broken_function():
    return "This won't work"
```

**Why order matters**: Mesh decorators need to wrap and enhance MCP decorators to provide dependency injection and orchestration.

## @mesh.tool - Function-Level Capabilities

The `@mesh.tool` decorator registers individual functions as mesh capabilities with dependency injection.

### Parameters

| Parameter      | Type                        | Default            | Description                               |
| -------------- | --------------------------- | ------------------ | ----------------------------------------- |
| `capability`   | `str \| None`               | `None`             | Capability name others can depend on      |
| `tags`         | `list[str] \| None`         | `[]`               | Tags for smart service discovery          |
| `version`      | `str`                       | `"1.0.0"`          | Semantic version for this capability      |
| `dependencies` | `list[str \| dict] \| None` | `None`             | Required capabilities (simple or complex) |
| `description`  | `str \| None`               | Function docstring | Human-readable description                |
| `**kwargs`     | `Any`                       | -                  | Additional metadata                       |

### Simple Example

```python
import mesh
from fastmcp import FastMCP

app = FastMCP("My Service")

@app.tool()  # FastMCP decorator first
@mesh.tool(  # Mesh decorator second
    capability="greeting",
    tags=["social", "basic"],
    version="1.0.0",
    description="Simple greeting function"
)
def say_hello(name: str = "World") -> str:
    """Say hello to someone."""
    return f"Hello, {name}!"
```

### Dependencies: Simple vs Complex

#### Simple String Dependencies

```python
@app.tool()
@mesh.tool(
    capability="weather_report",
    dependencies=["date_service", "location_service"]  # Simple string array
)
def get_weather(
    date_service: mesh.McpMeshAgent = None,
    location_service: mesh.McpMeshAgent = None
) -> str:
    date = date_service() if date_service else "unknown"
    location = location_service() if location_service else "unknown"
    return f"Weather for {location} on {date}: Sunny"
```

#### Complex Object Dependencies

```python
@app.tool()
@mesh.tool(
    capability="advanced_weather",
    dependencies=[
        "date_service",  # Simple dependency
        {
            "capability": "location_service",
            "tags": ["geo", "precise"],           # Smart tag matching
            "version": ">=2.0.0",               # Version constraint
            "namespace": "production"            # Specific namespace
        },
        {
            "capability": "info",
            "tags": ["system", "weather"]        # Gets weather-specific info
        }
    ],
    tags=["weather", "advanced"],
    version="2.1.0"
)
def get_advanced_weather(
    date_service: mesh.McpMeshAgent = None,
    location_service: mesh.McpMeshAgent = None,
    info: mesh.McpMeshAgent = None
) -> dict:
    """Advanced weather with multiple tagged dependencies."""
    return {
        "date": date_service() if date_service else "unknown",
        "location": location_service() if location_service else "unknown",
        "system_info": info() if info else {}
    }
```

### Dependency Object Structure

For complex dependencies, use this structure:

```python
{
    "capability": "required_capability_name",  # Required: capability to find
    "tags": ["tag1", "tag2"],                 # Optional: tags for smart matching
    "version": ">=1.5.0,<2.0.0",             # Optional: semantic version constraint
    "namespace": "production"                  # Optional: specific namespace
}
```

### Version Constraints

Full semantic versioning support:

```python
@mesh.tool(
    capability="data_processor",
    version="2.1.3",  # This tool's version
    dependencies=[
        {
            "capability": "database",
            "version": ">=3.0.0"      # Minimum version
        },
        {
            "capability": "cache",
            "version": "~2.1.0"       # Compatible with 2.1.x
        },
        {
            "capability": "api",
            "version": ">=1.0.0,<2.0.0"  # Range constraint
        }
    ]
)
def process_data():
    # Implementation
    pass
```

### Multi-Tag Matching

Use multiple tags for intelligent service selection:

```python
# Service provider offers multiple info types
@app.tool()
@mesh.tool(
    capability="info",
    tags=["system", "general", "health"]
)
def get_system_health():
    return {"status": "healthy", "uptime": "5 days"}

@app.tool()
@mesh.tool(
    capability="info",
    tags=["system", "disk", "storage"]
)
def get_disk_info():
    return {"usage": "75%", "free": "250GB"}

# Consumer uses tags to get specific info
@app.tool()
@mesh.tool(
    capability="reporter",
    dependencies=[
        {
            "capability": "info",
            "tags": ["system", "general"]  # Gets health info
        },
        {
            "capability": "info",
            "tags": ["system", "disk"]     # Gets disk info
        }
    ]
)
def create_report(
    health_info: mesh.McpMeshAgent = None,
    disk_info: mesh.McpMeshAgent = None
):
    return {
        "health": health_info() if health_info else {},
        "storage": disk_info() if disk_info else {}
    }
```

## @mesh.agent - Agent-Level Configuration

The `@mesh.agent` decorator configures the entire agent with server settings and lifecycle management.

### Parameters

| Parameter           | Type          | Default      | Description                        |
| ------------------- | ------------- | ------------ | ---------------------------------- |
| `name`              | `str`         | **Required** | Agent name (mandatory!)            |
| `version`           | `str`         | `"1.0.0"`    | Agent version                      |
| `description`       | `str \| None` | `None`       | Agent description                  |
| `http_host`         | `str \| None` | `None`       | HTTP server host (auto-resolved)   |
| `http_port`         | `int`         | `0`          | HTTP server port (0 = auto-assign) |
| `enable_http`       | `bool`        | `True`       | Enable HTTP endpoints              |
| `namespace`         | `str`         | `"default"`  | Agent namespace                    |
| `health_interval`   | `int`         | `30`         | Health check interval (seconds)    |
| `auto_run`          | `bool`        | `True`       | Auto-start and keep alive          |
| `auto_run_interval` | `int`         | `10`         | Keep-alive heartbeat (seconds)     |
| `**kwargs`          | `Any`         | -            | Additional agent metadata          |

### Complete Agent Example

```python
import mesh
from fastmcp import FastMCP

app = FastMCP("Weather Service")

# Tools with mesh decorators
@app.tool()
@mesh.tool(
    capability="current_weather",
    tags=["weather", "current"],
    version="1.2.0",
    dependencies=["location_service"]
)
def get_current_weather(location_service: mesh.McpMeshAgent = None):
    location = location_service() if location_service else "Unknown"
    return f"Current weather in {location}: 22°C, Sunny"

@app.prompt()
@mesh.tool(
    capability="weather_prompt",
    tags=["weather", "ai"],
    dependencies=["current_weather"]
)
def weather_analysis_prompt(current_weather: mesh.McpMeshAgent = None):
    weather = current_weather() if current_weather else "No data"
    return f"Analyze this weather: {weather}"

@app.resource("weather://config/{city}")
@mesh.tool(
    capability="weather_config",
    tags=["weather", "config"]
)
async def weather_config(city: str):
    return f"Weather config for {city}: API enabled"

# Agent configuration
@mesh.agent(
    name="weather-service",              # Required!
    version="2.0.0",
    description="Advanced weather service with mesh integration",
    http_host="0.0.0.0",                # Listen on all interfaces
    http_port=9091,                     # Specific port
    enable_http=True,
    namespace="production",
    health_interval=60,                 # Health check every minute
    auto_run=True,                      # Zero boilerplate!
    auto_run_interval=15                # Heartbeat every 15 seconds
)
class WeatherServiceAgent:
    """
    Weather service agent demonstrating all mesh features.

    Mesh automatically:
    - Discovers the 'app' FastMCP instance
    - Registers all @mesh.tool capabilities
    - Starts HTTP server on configured port
    - Manages health checks and keep-alive
    - Handles dependency injection
    """
    pass

# No main method needed! Mesh handles everything.
```

## Environment Variable Overrides

All agent parameters can be overridden with environment variables:

```bash
# Override agent configuration
export MCP_MESH_HTTP_HOST="127.0.0.1"
export MCP_MESH_HTTP_PORT="8080"
export MCP_MESH_HTTP_ENABLED="true"
export MCP_MESH_NAMESPACE="development"
export MCP_MESH_HEALTH_INTERVAL="30"
export MCP_MESH_AUTO_RUN="true"
export MCP_MESH_AUTO_RUN_INTERVAL="10"
export MCP_MESH_AGENT_NAME="custom-agent-name"

# Start agent (uses environment overrides)
python my_agent.py
```

## Advanced Patterns

### Self-Dependencies

Agents can depend on their own capabilities:

```python
@app.tool()
@mesh.tool(
    capability="timestamp",
    tags=["time", "internal"]
)
def get_timestamp():
    return datetime.now().isoformat()

@app.tool()
@mesh.tool(
    capability="logged_greeting",
    dependencies=["timestamp"],  # Self-dependency!
    tags=["greeting", "logged"]
)
def hello_with_log(
    name: str,
    timestamp: mesh.McpMeshAgent = None
) -> str:
    time = timestamp() if timestamp else "unknown"
    greeting = f"Hello {name}!"
    print(f"[{time}] Generated greeting: {greeting}")
    return greeting
```

### Namespace Isolation

Use namespaces to isolate environments:

```python
@mesh.agent(
    name="api-service",
    namespace="development",  # Development namespace
    http_port=8080
)
class DevApiService:
    pass

@mesh.agent(
    name="api-service",
    namespace="production",   # Production namespace
    http_port=9080
)
class ProdApiService:
    pass
```

### Complex Dependency Chains

```python
# Base service
@app.tool()
@mesh.tool(capability="database", tags=["storage", "primary"])
def connect_database():
    return "database_connection"

# Middle layer
@app.tool()
@mesh.tool(
    capability="data_access",
    dependencies=["database"],
    tags=["data", "layer"]
)
def access_data(database: mesh.McpMeshAgent = None):
    db = database() if database else None
    return f"data_from_{db}"

# Top layer
@app.tool()
@mesh.tool(
    capability="business_logic",
    dependencies=[
        "data_access",
        {
            "capability": "cache",
            "tags": ["performance", "redis"]
        }
    ],
    tags=["business", "api"]
)
def process_business_logic(
    data_access: mesh.McpMeshAgent = None,
    cache: mesh.McpMeshAgent = None
):
    data = data_access() if data_access else "no_data"
    cached = cache() if cache else "no_cache"
    return f"processed_{data}_with_{cached}"
```

## Dependency Injection Types

### Option 1: McpMeshAgent (Recommended)

```python
@app.tool()
@mesh.tool(
    capability="processor",
    dependencies=["service1", "service2"]
)
def process_data(
    service1: mesh.McpMeshAgent = None,  # Type-safe
    service2: mesh.McpMeshAgent = None   # IDE support
):
    # Direct function call
    result1 = service1() if service1 else {}

    # Explicit invoke with parameters
    result2 = service2.invoke({"param": "value"}) if service2 else {}

    return {"result1": result1, "result2": result2}
```

### Option 2: Any Type (Flexible)

```python
from typing import Any

@app.tool()
@mesh.tool(
    capability="flexible_processor",
    dependencies=["any_service"]
)
def process_flexible(any_service: Any = None):
    # Maximum flexibility
    return any_service() if any_service else "no_service"
```

## Testing Your Decorators

### Check Service Registration

```bash
# Verify capabilities are registered
curl -s http://localhost:8000/agents | \
  jq '.agents[] | {name: .name, capabilities: (.capabilities | keys)}'
```

### Test Individual Capabilities

```bash
# Test a specific tool
curl -s -X POST http://localhost:9091/mcp/ \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
      "name": "get_current_weather",
      "arguments": {}
    }
  }' | jq '.result'
```

### Verify Dependency Injection

```bash
# Check if dependencies are resolved
curl -s http://localhost:8000/agents | \
  jq '.agents[] | select(.name=="weather-service") | .capabilities'
```

## Common Patterns and Best Practices

### 1. Always Check Dependencies

```python
@app.tool()
@mesh.tool(
    capability="safe_processor",
    dependencies=["external_service"]
)
def process_safely(external_service: mesh.McpMeshAgent = None):
    if external_service is None:
        return {"status": "degraded", "reason": "external_service_unavailable"}

    try:
        result = external_service()
        return {"status": "success", "data": result}
    except Exception as e:
        return {"status": "error", "error": str(e)}
```

### 2. Use Descriptive Tags

```python
@mesh.tool(
    capability="user_service",
    tags=["users", "authentication", "api", "v2"],  # Descriptive tags
    version="2.1.0"
)
```

### 3. Version Your Capabilities

```python
@mesh.tool(
    capability="data_processor",
    version="3.2.1",  # Semantic versioning
    dependencies=[
        {
            "capability": "database",
            "version": ">=4.0.0"  # Ensure compatibility
        }
    ]
)
```

### 4. Organize by Namespace

```python
# Different environments
@mesh.agent(name="service", namespace="development")
@mesh.agent(name="service", namespace="staging")
@mesh.agent(name="service", namespace="production")
```

## Troubleshooting

### Decorator Order Issues

```bash
# Error: Mesh decorator applied before MCP decorator
TypeError: mesh.tool() can only be applied to functions already decorated with MCP decorators
```

**Solution**: Always put `@mesh.tool` after `@app.tool`.

### Dependency Not Found

```bash
# Check what capabilities are available
curl -s http://localhost:8000/agents | jq '.agents[].capabilities | keys'

# Check specific capability tags
curl -s http://localhost:8000/agents | jq '.agents[] | select(.capabilities.your_capability)'
```

### Version Constraint Errors

Make sure version strings are valid semantic versions:

- ✅ `"1.0.0"`, `">=2.1.0"`, `"~1.5.0"`
- ❌ `"v1.0"`, `"latest"`, `"1"`

### Agent Name Required

```python
# ❌ This will fail
@mesh.agent()  # Missing required 'name' parameter

# ✅ This works
@mesh.agent(name="my-service")
```

## Next Steps

Now that you understand mesh decorators, you can:

1. **[Build Complex Agents](./07-advanced-patterns.md)** - Multi-service architectures
2. **[Local Development](../02-local-development.md)** - Professional development setup
3. **[Production Deployment](../03-docker-deployment.md)** - Containerized deployments

---

💡 **Key Insight**: The decorator order requirement ensures mesh can properly wrap and enhance MCP functionality with dependency injection.

🏷️ **Pro Tip**: Use specific tag combinations to enable precise service selection in complex environments.

🎯 **Best Practice**: Always version your capabilities and use semantic version constraints for dependencies.
