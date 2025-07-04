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

## Advanced @mesh.tool Configuration (v0.3+)

> **New in v0.3+**: Enhanced proxy auto-configuration through decorator kwargs

The `@mesh.tool` decorator now supports advanced configuration kwargs that automatically configure enhanced MCP proxies with timeouts, retries, authentication, streaming, and session management.

### Enhanced Proxy Kwargs

| Parameter                 | Type   | Default | Description                       |
| ------------------------- | ------ | ------- | --------------------------------- |
| `timeout`                 | `int`  | `30`    | Request timeout in seconds        |
| `retry_count`             | `int`  | `1`     | Number of retry attempts          |
| `custom_headers`          | `dict` | `{}`    | Custom HTTP headers to inject     |
| `streaming`               | `bool` | `False` | Enable streaming capabilities     |
| `auth_required`           | `bool` | `False` | Require authentication            |
| `session_required`        | `bool` | `False` | Enable session affinity           |
| `stateful`                | `bool` | `False` | Mark as stateful capability       |
| `auto_session_management` | `bool` | `False` | Enable automatic session handling |

### Timeout Configuration

Configure different timeouts for different types of operations:

```python
@app.tool()
@mesh.tool(
    capability="quick_lookup",
    timeout=5,  # Fast operations: 5 seconds
    retry_count=2
)
def quick_data_lookup(query: str) -> dict:
    """Fast lookup with 5s timeout, 2 retries."""
    return {"result": f"Quick result for {query}"}

@app.tool()
@mesh.tool(
    capability="heavy_computation",
    timeout=300,  # Heavy operations: 5 minutes
    retry_count=1
)
def complex_calculation(data: list) -> dict:
    """Heavy computation with 5-minute timeout."""
    return {"processed": len(data), "result": "computed"}
```

### Custom Headers for Service Identification

Add custom headers for debugging, routing, or service identification:

```python
@app.tool()
@mesh.tool(
    capability="database_service",
    timeout=60,
    custom_headers={
        "X-Service-Type": "database",
        "X-Priority": "high",
        "X-Cache-Control": "no-cache"
    }
)
def query_database(sql: str) -> dict:
    """Database query with custom headers for routing and debugging."""
    return {"rows": 42, "query": sql}

@app.tool()
@mesh.tool(
    capability="external_api",
    timeout=30,
    retry_count=3,
    custom_headers={
        "X-External-Service": "weather-api",
        "X-Rate-Limit": "100/hour"
    }
)
def fetch_weather_data(location: str) -> dict:
    """External API call with rate limiting headers."""
    return {"location": location, "temperature": "22°C"}
```

### Streaming Capabilities

Enable streaming for real-time data processing:

```python
from typing import AsyncGenerator

@app.tool()
@mesh.tool(
    capability="data_stream",
    streaming=True,          # Enables streaming proxy
    timeout=600,             # Longer timeout for streams
    custom_headers={
        "X-Stream-Type": "data",
        "X-Content-Type": "application/json"
    }
)
async def stream_processing_results(
    batch_size: int = 100
) -> AsyncGenerator[dict, None]:
    """Stream processing results with enhanced proxy configuration."""
    for i in range(0, 1000, batch_size):
        yield {
            "batch": i // batch_size,
            "processed_items": batch_size,
            "timestamp": "2025-01-01T00:00:00Z"
        }
        await asyncio.sleep(0.1)  # Simulate processing time
```

### Authentication Requirements

Mark capabilities that require authentication:

```python
@app.tool()
@mesh.tool(
    capability="secure_data",
    auth_required=True,      # Requires authentication
    timeout=60,
    custom_headers={
        "X-Security-Level": "high",
        "X-Auth-Required": "bearer"
    }
)
def get_sensitive_data(data_type: str) -> dict:
    """Access sensitive data - requires authentication."""
    return {
        "data_type": data_type,
        "classified": True,
        "access_level": "authorized"
    }
```

### Session Management & Stickiness

Enable session affinity for stateful operations:

```python
@app.tool()
@mesh.tool(
    capability="user_session",
    session_required=True,           # Enable session affinity
    stateful=True,                   # Mark as stateful
    auto_session_management=True,    # Automatic session handling
    timeout=30,
    custom_headers={
        "X-Session-Enabled": "true",
        "X-Stateful": "true"
    }
)
def manage_user_session(
    session_id: str,
    action: str,
    user_data: dict = None
) -> dict:
    """Session-aware operation with automatic session stickiness."""
    # Session data automatically routed to same pod
    if not hasattr(manage_user_session, '_sessions'):
        manage_user_session._sessions = {}

    if action == "create":
        manage_user_session._sessions[session_id] = user_data or {}
    elif action == "get":
        return manage_user_session._sessions.get(session_id, {})
    elif action == "update":
        if session_id in manage_user_session._sessions:
            manage_user_session._sessions[session_id].update(user_data or {})

    return {
        "session_id": session_id,
        "action": action,
        "data": manage_user_session._sessions.get(session_id, {})
    }
```

### Complete Enhanced Example

Here's a comprehensive example showing all advanced features:

```python
import asyncio
from datetime import datetime
from typing import AsyncGenerator
import mesh
from fastmcp import FastMCP

app = FastMCP("Enhanced Service")

@app.tool()
@mesh.tool(
    capability="enhanced_processor",
    dependencies=["auth_service", "session_manager"],
    tags=["processing", "enhanced", "production"],
    version="2.0.0",
    # Enhanced proxy configuration
    timeout=120,                     # 2-minute timeout
    retry_count=3,                   # 3 retry attempts
    streaming=True,                  # Enable streaming
    auth_required=True,              # Require authentication
    session_required=True,           # Enable session affinity
    stateful=True,                   # Mark as stateful
    auto_session_management=True,    # Automatic session handling
    custom_headers={
        "X-Service-Type": "enhanced-processor",
        "X-Processing-Level": "advanced",
        "X-Stream-Enabled": "true",
        "X-Auth-Required": "bearer",
        "X-Session-Managed": "auto"
    }
)
async def enhanced_data_processor(
    session_id: str,
    data_batch: list,
    processing_type: str = "standard",
    # Injected dependencies
    auth_service: mesh.McpMeshAgent = None,
    session_manager: mesh.McpMeshAgent = None
) -> AsyncGenerator[dict, None]:
    """
    Enhanced data processor with full advanced configuration.

    Features:
    - 120s timeout with 3 retries
    - Authentication verification
    - Session affinity for stateful processing
    - Streaming results with custom headers
    - Dependency injection for auth and session services
    """

    # Verify authentication
    if auth_service:
        auth_result = auth_service({"session_id": session_id})
        if not auth_result.get("authenticated"):
            yield {"error": "Authentication failed"}
            return

    # Initialize session data
    if session_manager:
        session_manager({
            "action": "initialize",
            "session_id": session_id,
            "processing_type": processing_type
        })

    # Stream processing results
    total_items = len(data_batch)
    for i, item in enumerate(data_batch):
        # Simulate processing time
        await asyncio.sleep(0.1)

        yield {
            "session_id": session_id,
            "item_index": i,
            "item_data": item,
            "processing_type": processing_type,
            "progress": (i + 1) / total_items,
            "timestamp": datetime.now().isoformat(),
            "enhanced": True,
            "authenticated": True,
            "session_managed": True
        }

    # Final result
    yield {
        "session_id": session_id,
        "status": "completed",
        "total_processed": total_items,
        "processing_type": processing_type,
        "timestamp": datetime.now().isoformat()
    }
```

### Automatic Proxy Selection

> **Smart Proxy Selection**: MCP Mesh automatically selects the appropriate proxy based on kwargs:

- **Basic kwargs** (`timeout`, `retry_count`) → `EnhancedMCPClientProxy`
- **Streaming enabled** (`streaming=True`) → `EnhancedFullMCPProxy`
- **No special kwargs** → Standard `MCPClientProxy` (backward compatible)

```python
# Gets EnhancedMCPClientProxy
@mesh.tool(capability="basic", timeout=60)
def basic_operation(): pass

# Gets EnhancedFullMCPProxy
@mesh.tool(capability="streaming", streaming=True)
async def streaming_operation(): pass

# Gets standard MCPClientProxy
@mesh.tool(capability="simple")
def simple_operation(): pass
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

MCP Mesh provides two different proxy types for dependency injection, each designed for specific use cases:

### McpMeshAgent - Simple Tool Calls

Use `mesh.McpMeshAgent` when you need **simple tool execution** - calling remote functions with arguments:

```python
@app.tool()
@mesh.tool(
    capability="processor",
    dependencies=["service1", "service2"]
)
def process_data(
    service1: mesh.McpMeshAgent = None,  # For simple tool calls
    service2: mesh.McpMeshAgent = None   # Type-safe, IDE support
):
    # Direct function call - proxy knows which remote function to invoke
    result1 = service1() if service1 else {}

    # With arguments
    result2 = service1({"format": "JSON"}) if service1 else {}

    # Explicit invoke (same as call)
    result3 = service2.invoke({"param": "value"}) if service2 else {}

    return {"result1": result1, "result2": result2, "result3": result3}
```

**Key Features of McpMeshAgent:**

- ✅ Function-to-function binding (no need to specify function names)
- ✅ Simple `()` and `.invoke()` methods
- ✅ Optimized for basic tool execution
- ✅ Lightweight proxy with minimal overhead

### McpAgent - Full MCP Protocol Access

Use `mesh.McpAgent` when you need **advanced MCP capabilities** like listing tools, managing resources, prompts, streaming, or session management:

```python
@app.tool()
@mesh.tool(
    capability="advanced_processor",
    dependencies=["file_service", "api_service"]
)
async def advanced_processing(
    file_service: mesh.McpAgent = None,     # Full MCP protocol access
    api_service: mesh.McpAgent = None       # Advanced capabilities
) -> dict:
    """Advanced processing with full MCP protocol support."""

    if not file_service or not api_service:
        return {"error": "Services unavailable"}

    # === VANILLA MCP PROTOCOL METHODS (100% compatible) ===

    # Discovery - List available capabilities
    tools = await file_service.list_tools()
    resources = await file_service.list_resources()
    prompts = await file_service.list_prompts()

    # Resource Management
    config = await file_service.read_resource("file://config.json")

    # Prompt Templates
    analysis_prompt = await file_service.get_prompt(
        "data_analysis",
        {"dataset": "sales", "period": "Q4"}
    )

    # === BACKWARD COMPATIBILITY ===

    # Simple calls (McpMeshAgent compatibility)
    basic_result = file_service({"action": "scan"})
    api_result = api_service.invoke({"method": "GET", "endpoint": "/status"})

    # === STREAMING CAPABILITIES (BREAKTHROUGH FEATURE) ===

    # Stream large file processing
    processed_chunks = []
    async for chunk in file_service.call_tool_streaming(
        "process_large_file",
        {"file": "massive_dataset.csv", "batch_size": 1000}
    ):
        processed_chunks.append(chunk)
        # Real-time processing progress
        if chunk.get("type") == "progress":
            print(f"Progress: {chunk['percent']}%")

    # === EXPLICIT SESSION MANAGEMENT (Phase 6) ===

    # Create persistent session for stateful operations
    session_id = await api_service.create_session()

    # All calls with same session_id route to same agent instance
    login_result = await api_service.call_with_session(
        session_id,
        tool="authenticate",
        credentials={"user": "admin"}
    )

    user_data = await api_service.call_with_session(
        session_id,
        tool="get_user_profile"
        # Session maintains authentication state
    )

    # Cleanup session when done
    await api_service.close_session(session_id)

    return {
        "discovered": {
            "tools": len(tools),
            "resources": len(resources),
            "prompts": len(prompts)
        },
        "config": config,
        "basic_results": [basic_result, api_result],
        "streaming_chunks": len(processed_chunks),
        "session_results": [login_result, user_data],
        "analysis_template": analysis_prompt
    }
```

**Key Features of McpAgent:**

- ✅ **Complete MCP Protocol**: `list_tools()`, `list_resources()`, `read_resource()`, `list_prompts()`, `get_prompt()`
- ✅ **Streaming Support**: `call_tool_streaming()` for real-time data processing
- ✅ **Session Management**: `create_session()`, `call_with_session()`, `close_session()`
- ✅ **Backward Compatibility**: Supports `()` and `.invoke()` from McpMeshAgent
- ✅ **Discovery**: Dynamic capability exploration at runtime

### When to Use Which Type?

| Use Case                | Recommended Type | Reason                                                |
| ----------------------- | ---------------- | ----------------------------------------------------- |
| Simple tool calls       | `McpMeshAgent`   | Lightweight, optimized for function-to-function calls |
| Resource management     | `McpAgent`       | Need `read_resource()`, `list_resources()`            |
| Dynamic discovery       | `McpAgent`       | Need `list_tools()`, `list_prompts()`                 |
| Streaming operations    | `McpAgent`       | Need `call_tool_streaming()`                          |
| Session-based workflows | `McpAgent`       | Need session management methods                       |
| Multi-step protocols    | `McpAgent`       | Need full MCP protocol access                         |
| Performance-critical    | `McpMeshAgent`   | Minimal overhead for simple calls                     |

### Proxy Selection Example

```python
@app.tool()
@mesh.tool(
    capability="hybrid_processor",
    dependencies=[
        "simple_math",      # For basic calculations
        "file_manager",     # For advanced file operations
        "stream_processor"  # For streaming data
    ]
)
async def hybrid_processing(
    # Simple tool calls - use McpMeshAgent
    simple_math: mesh.McpMeshAgent = None,

    # Advanced capabilities - use McpAgent
    file_manager: mesh.McpAgent = None,
    stream_processor: mesh.McpAgent = None
) -> dict:
    # Simple calculation
    result = simple_math({"a": 10, "b": 20, "op": "add"}) if simple_math else 0

    # Advanced file operations
    if file_manager:
        files = await file_manager.list_resources()
        config = await file_manager.read_resource("file://settings.json")

    # Streaming processing
    chunks = []
    if stream_processor:
        async for chunk in stream_processor.call_tool_streaming("process", {"data": result}):
            chunks.append(chunk)

    return {
        "calculation": result,
        "files_found": len(files) if file_manager else 0,
        "stream_chunks": len(chunks)
    }
```

### Mixed Type Dependencies

You can mix both types in the same function based on your specific needs:

```python
@app.tool()
@mesh.tool(
    capability="data_pipeline",
    dependencies=[
        "validator",        # Simple validation calls
        "transformer",      # Simple data transformation
        "storage_service",  # Advanced resource management
        "notification_api"  # Advanced streaming notifications
    ]
)
async def process_data_pipeline(
    data: dict,
    # Simple operations
    validator: mesh.McpMeshAgent = None,
    transformer: mesh.McpMeshAgent = None,

    # Advanced operations
    storage_service: mesh.McpAgent = None,
    notification_api: mesh.McpAgent = None
) -> dict:
    # Step 1: Simple validation
    is_valid = validator({"data": data}) if validator else True
    if not is_valid:
        return {"error": "Validation failed"}

    # Step 2: Simple transformation
    transformed = transformer({"data": data, "format": "normalized"}) if transformer else data

    # Step 3: Advanced storage with resource discovery
    if storage_service:
        # Discover available storage options
        resources = await storage_service.list_resources()

        # Use appropriate storage method
        if "database://primary" in [r["uri"] for r in resources]:
            storage_result = await storage_service.call_with_session(
                session_id="pipeline-session",
                tool="store_data",
                data=transformed
            )

    # Step 4: Stream real-time notifications
    if notification_api:
        async for notification in notification_api.call_tool_streaming(
            "send_progress",
            {"pipeline_id": "data-pipeline", "status": "completed"}
        ):
            print(f"Notification: {notification}")

    return {"status": "completed", "records_processed": len(transformed)}
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
