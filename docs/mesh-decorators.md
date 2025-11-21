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

### Enhanced Tag Matching with +/- Operators

> **New in v0.4+**: Smart tag matching with preference and exclusion operators

MCP Mesh supports enhanced tag matching with `+` (preferred) and `-` (excluded) operators for intelligent service selection:

#### Tag Operators

- **No prefix**: Required tag (must be present) - `"claude"`
- **`+` prefix**: Preferred tag (bonus if present, no penalty if missing) - `"+opus"`
- **`-` prefix**: Excluded tag (must NOT be present, hard failure if found) - `"-experimental"`

#### Smart LLM Provider Selection

```python
# Register multiple LLM providers with different capabilities
@app.tool()
@mesh.tool(capability="llm_service", tags=["claude", "haiku", "fast"])
def claude_haiku(): return "Fast Claude Haiku response"

@app.tool()
@mesh.tool(capability="llm_service", tags=["claude", "sonnet", "balanced"])
def claude_sonnet(): return "Balanced Claude Sonnet response"

@app.tool()
@mesh.tool(capability="llm_service", tags=["claude", "opus", "premium"])
def claude_opus(): return "Premium Claude Opus response"

@app.tool()
@mesh.tool(capability="llm_service", tags=["claude", "experimental", "beta"])
def claude_experimental(): return "Experimental Claude features"

# Smart consumer with preferences and exclusions
@app.tool()
@mesh.tool(
    capability="smart_chat",
    dependencies=[{
        "capability": "llm_service",
        "tags": [
            "claude",           # Required: must have claude
            "+opus",            # Preferred: prefer opus if available
            "-experimental"     # Excluded: never use experimental services
        ]
    }]
)
def intelligent_chat(llm_service: mesh.McpMeshAgent = None) -> str:
    """
    Smart chat that:
    - Requires Claude models
    - Prefers Opus quality when available
    - Never uses experimental/unstable services
    - Gracefully falls back to Sonnet if Opus unavailable
    """
    if not llm_service:
        return "No suitable LLM service available"

    return f"Response from: {llm_service()}"
```

#### Enhanced Matching Behavior

```python
# Available providers:
# - claude-haiku: ["claude", "haiku", "fast"]
# - claude-sonnet: ["claude", "sonnet", "balanced"]
# - claude-opus: ["claude", "opus", "premium"]
# - claude-experimental: ["claude", "experimental", "beta"]

# Consumer preferences and results:
"tags": ["claude", "+opus"]                    # → Selects opus (preferred)
"tags": ["claude", "+balanced"]                # → Selects sonnet (balanced)
"tags": ["claude", "+fast", "+haiku"]          # → Selects haiku (both preferred)
"tags": ["claude", "-experimental"]            # → Excludes experimental, selects any other
"tags": ["claude", "+opus", "-experimental"]   # → Prefers opus, excludes experimental
```

#### Cost Control and Safety

```python
@app.tool()
@mesh.tool(
    capability="budget_analysis",
    dependencies=[{
        "capability": "llm_service",
        "tags": [
            "claude",
            "+balanced",     # Prefer cost-effective options
            "-premium",      # Exclude expensive premium services
            "-experimental"  # Exclude potentially unstable services
        ]
    }]
)
def cost_conscious_analysis(llm_service: mesh.McpMeshAgent = None):
    """Cost-conscious analysis that avoids premium pricing."""
    return llm_service() if llm_service else "Budget service unavailable"

@app.tool()
@mesh.tool(
    capability="production_service",
    dependencies=[{
        "capability": "database_service",
        "tags": [
            "postgres",
            "+primary",      # Prefer primary database
            "+ssd",          # Prefer SSD storage
            "-beta",         # Never use beta versions
            "-experimental"  # Never use experimental features
        ]
    }]
)
def production_workflow(database_service: mesh.McpMeshAgent = None):
    """Production workflow with strict service requirements."""
    return database_service({"query": "SELECT * FROM users"}) if database_service else None
```

#### Priority Scoring System

Enhanced tag matching uses priority scoring for automatic provider ranking:

- **Required tags**: 5 points each (must be present)
- **Preferred tags**: 10 bonus points each (bonus if present)
- **Excluded tags**: Immediate failure (provider eliminated)
- **Highest scoring provider selected automatically**

```python
# Example scoring:
# Provider A: ["claude", "opus", "premium"]
# Consumer needs: ["claude", "+opus", "-experimental"]
# Score: claude(5) + opus(10) = 15 points → HIGH PRIORITY

# Provider B: ["claude", "sonnet", "balanced"]
# Consumer needs: ["claude", "+opus", "-experimental"]
# Score: claude(5) = 5 points → LOWER PRIORITY

# Provider C: ["claude", "experimental"]
# Consumer needs: ["claude", "+opus", "-experimental"]
# Score: ELIMINATED (experimental is excluded)

# Result: Provider A selected (highest score)
```

### Multi-Tag Matching (Legacy)

Traditional exact tag matching is still supported:

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

# Consumer uses exact tags for specific info
@app.tool()
@mesh.tool(
    capability="reporter",
    dependencies=[
        {
            "capability": "info",
            "tags": ["system", "general"]  # Exact match: gets health info
        },
        {
            "capability": "info",
            "tags": ["system", "disk"]     # Exact match: gets disk info
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

## @mesh.llm - LLM Agent Injection

> **New in v0.7**: Inject LLM agents as dependencies with automatic tool discovery and type-safe prompt templates

The `@mesh.llm` decorator enables LLM integration as first-class mesh capabilities, treating LLMs as injectable dependencies like any other agent.

### Parameters

| Parameter        | Type   | Default    | Description                                        |
| ---------------- | ------ | ---------- | -------------------------------------------------- |
| `system_prompt`  | `str`  | `None`     | Literal prompt or `file://path/to/template.jinja2` |
| `filter`         | `dict` | `None`     | Tool discovery filter (capability, tags, version)  |
| `provider`       | `str`  | `"claude"` | LLM provider (claude, openai, etc.)                |
| `model`          | `str`  | Required   | Model identifier                                   |
| `context_param`  | `str`  | `None`     | Parameter name containing template context         |
| `max_iterations` | `int`  | `5`        | Max agentic loop iterations                        |

### Decorator Order with LLM

**⚠️ IMPORTANT**: LLM decorator order follows the same pattern - mesh decorators come after MCP decorators:

```python
# ✅ CORRECT ORDER
@app.tool()           # ← FastMCP decorator FIRST
@mesh.llm(            # ← LLM decorator SECOND
    provider="claude",
    model="anthropic/claude-sonnet-4-5"
)
@mesh.tool(           # ← Mesh tool decorator THIRD
    capability="chat"
)
def chat_function(message: str, llm: mesh.MeshLlmAgent = None):
    return llm(message)

# ❌ WRONG ORDER
@mesh.llm(provider="claude", model="anthropic/claude-sonnet-4-5")  # Wrong
@app.tool()                                                        # Wrong
@mesh.tool(capability="chat")                                      # Wrong
def broken_function(message: str, llm=None):
    pass
```

### Simple LLM Injection

```python
import mesh
from fastmcp import FastMCP

app = FastMCP("Chat Service")

@app.tool()
@mesh.llm(
    system_prompt="You are a helpful assistant.",
    provider="claude",
    model="anthropic/claude-sonnet-4-5"
)
@mesh.tool(capability="chat")
async def chat(message: str, llm: mesh.MeshLlmAgent = None) -> str:
    """LLM agent auto-injected with configured system prompt."""
    if llm is None:
        return "LLM service unavailable"
    return await llm(message)
```

### LLM with Tool Discovery Filter

```python
@app.tool()
@mesh.llm(
    system_prompt="You are a system administrator with monitoring tools.",
    filter={"tags": ["system", "monitoring"]},  # Auto-discover tools
    provider="claude",
    model="anthropic/claude-sonnet-4-5"
)
@mesh.tool(capability="system_admin")
async def admin_assistant(task: str, llm: mesh.MeshLlmAgent = None):
    """LLM automatically gets access to all system monitoring tools."""
    return await llm(task)
```

### Type-Safe Prompt Templates

Use `file://` prefix to load Jinja2 templates with type-safe context models:

```python
from mesh import MeshContextModel
from pydantic import BaseModel, Field

class AnalysisContext(MeshContextModel):
    """Type-safe context for analysis prompts."""
    domain: str = Field(
        ...,
        description="Analysis domain: infrastructure, security, or performance"
    )
    user_level: str = Field(
        default="beginner",
        description="User expertise: beginner, intermediate, expert"
    )
    focus_areas: list[str] = Field(
        default_factory=list,
        description="Specific areas to analyze"
    )

@app.tool()
@mesh.llm(
    system_prompt="file://prompts/analyst.jinja2",  # Load from file
    context_param="ctx",  # Which parameter contains context
    provider="claude",
    model="anthropic/claude-sonnet-4-5"
)
@mesh.tool(capability="analysis")
async def analyze_system(
    query: str,
    ctx: AnalysisContext,  # Type-safe, validated context
    llm: mesh.MeshLlmAgent = None
) -> dict:
    """Template auto-rendered with ctx before LLM call."""
    if llm is None:
        return {"error": "LLM unavailable"}
    return await llm(query)
```

**Template file** (`prompts/analyst.jinja2`):

```jinja2
You are a {{ domain }} analysis expert.
User expertise level: {{ user_level }}

{% if focus_areas %}
Focus your analysis on: {{ focus_areas | join(", ") }}
{% endif %}

Provide detailed analysis appropriate for {{ user_level }}-level users.
Use your monitoring tools when needed.
```

### Dual Injection: LLM + MCP Agent

**Breakthrough feature**: Inject both LLM agents AND MCP agents into the same function:

```python
from pydantic import BaseModel

class EnrichedResult(BaseModel):
    """LLM result enriched with MCP agent data."""
    analysis: str
    recommendations: list[str]
    timestamp: str
    system_info: str

@app.tool()
@mesh.llm(
    system_prompt="file://prompts/dual_injection.jinja2",
    filter={"tags": ["system"]},  # LLM gets system tools via filter
    provider="claude",
    model="anthropic/claude-sonnet-4-5"
)
@mesh.tool(
    capability="enriched_analysis",
    dependencies=[{
        "capability": "date_service",
        "tags": ["system", "time"]
    }]  # Direct MCP agent dependency
)
async def analyze_with_enrichment(
    query: str,
    llm: mesh.MeshLlmAgent = None,        # ← Injected LLM agent
    date_service: mesh.McpMeshAgent = None  # ← Injected MCP agent
) -> EnrichedResult:
    """
    Demonstrates dual injection pattern.

    - LLM: Intelligent analysis with filtered tool access
    - MCP agent: Direct capability calls for enrichment
    - Both orchestrated in one function, zero boilerplate
    """
    if llm is None:
        return EnrichedResult(
            analysis="LLM unavailable",
            recommendations=[],
            timestamp="N/A",
            system_info="N/A"
        )

    # Step 1: Get LLM analysis (LLM has access to system tools)
    llm_result = await llm(query)

    # Step 2: Call MCP agent directly for enrichment data
    timestamp = await date_service() if date_service else "N/A"

    # Step 3: Combine both results
    return EnrichedResult(
        analysis=llm_result.analysis,
        recommendations=llm_result.recommendations,
        timestamp=timestamp,
        system_info="Analysis enriched with real-time data"
    )
```

### MeshContextModel for Validation

`MeshContextModel` provides Pydantic-based validation with IDE support:

```python
from mesh import MeshContextModel

class ChatContext(MeshContextModel):
    """Type-safe context with validation."""
    user_name: str = Field(..., description="User's display name")
    domain: str = Field(..., description="Conversation domain")
    expertise_level: str = Field(default="beginner")

@app.tool()
@mesh.llm(
    system_prompt="file://prompts/chat.jinja2",
    context_param="ctx",
    provider="claude",
    model="anthropic/claude-sonnet-4-5"
)
@mesh.tool(capability="personalized_chat")
async def chat(
    message: str,
    ctx: ChatContext,  # Validated at runtime
    llm: mesh.MeshLlmAgent = None
):
    # ctx guaranteed to have user_name, domain, expertise_level
    return await llm(message)

# Usage with validation
chat(
    "Hello!",
    ctx=ChatContext(
        user_name="Alice",
        domain="technical",
        expertise_level="expert"
    )
)
```

### Enhanced Schemas for LLM Chains

When orchestrator LLMs call specialist LLMs, Field descriptions are automatically extracted into tool schemas:

```python
# Specialist LLM with enhanced schema
class SpecialistContext(MeshContextModel):
    domain: str = Field(
        ...,
        description="Analysis domain: infrastructure, security, or performance"
    )
    user_level: str = Field(
        default="beginner",
        description="User expertise: beginner, intermediate, expert"
    )

@app.tool()
@mesh.llm(
    system_prompt="file://prompts/specialist.jinja2",
    context_param="ctx",
    provider="claude",
    model="anthropic/claude-sonnet-4-5"
)
@mesh.tool(capability="specialist_analysis", tags=["llm", "specialist"])
async def specialist_analyze(
    request: str,
    ctx: SpecialistContext,
    llm: mesh.MeshLlmAgent = None
):
    return await llm(request)

# Orchestrator LLM discovers specialist with enhanced schema
@app.tool()
@mesh.llm(
    system_prompt="You coordinate analysis tasks across specialists.",
    filter={"capability": "specialist_analysis"},  # Discovers specialist
    provider="claude",
    model="anthropic/claude-sonnet-4-5"
)
@mesh.tool(capability="orchestrator")
async def orchestrate_analysis(task: str, llm: mesh.MeshLlmAgent = None):
    """
    Orchestrator LLM receives enhanced schema with Field descriptions.

    Knows that domain is "infrastructure|security|performance"
    Knows that user_level is "beginner|intermediate|expert"

    This dramatically improves success rate when constructing contexts!
    """
    return await llm(task)
```

The orchestrator receives:

```json
{
  "name": "specialist_analyze",
  "inputSchema": {
    "properties": {
      "ctx": {
        "properties": {
          "domain": {
            "type": "string",
            "description": "Analysis domain: infrastructure, security, or performance"
          },
          "user_level": {
            "type": "string",
            "default": "beginner",
            "description": "User expertise: beginner, intermediate, expert"
          }
        }
      }
    }
  }
}
```

### LLM Filter Patterns

Common filter patterns for tool discovery:

```python
# 1. Filter by tags (most common)
@mesh.llm(filter={"tags": ["system", "monitoring"]})

# 2. Filter by capability
@mesh.llm(filter={"capability": "weather_service"})

# 3. Combine capability + tags
@mesh.llm(filter={
    "capability": "database",
    "tags": ["production", "primary"]
})

# 4. Filter with version constraints
@mesh.llm(filter={
    "capability": "api_service",
    "version": ">=2.0.0",
    "tags": ["rest", "v2"]
})

# 5. No filter - LLM has no tools
@mesh.llm()  # Pure chat, no tool access
```

### Template Context Detection

MCP Mesh auto-detects context parameters in three ways:

```python
# 1. Explicit (recommended)
@mesh.llm(
    system_prompt="file://prompts/chat.jinja2",
    context_param="my_context"  # Explicitly named
)
def chat(msg: str, my_context: dict, llm=None): ...

# 2. Convention (auto-detected)
@mesh.llm(system_prompt="file://prompts/chat.jinja2")
def chat(msg: str, ctx: dict, llm=None): ...  # "ctx" detected

@mesh.llm(system_prompt="file://prompts/chat.jinja2")
def chat(msg: str, prompt_context: dict, llm=None): ...  # "prompt_context" detected

# 3. Type hint (auto-detected)
@mesh.llm(system_prompt="file://prompts/chat.jinja2")
def chat(msg: str, analysis_ctx: AnalysisContext, llm=None): ...
# ↑ MeshContextModel subclass detected
```

### Template Features

Full Jinja2 support:

```jinja2
{# Variables #}
Hello {{ user_name }}!

{# Conditionals #}
{% if expertise_level == "expert" %}
  Technical mode enabled.
{% else %}
  Beginner-friendly mode.
{% endif %}

{# Loops #}
Focus areas:
{% for area in focus_areas %}
  - {{ area }}
{% endfor %}

{# Filters #}
{{ capabilities | join(", ") }}
{{ task_type | upper }}

{# Defaults #}
{{ optional_field | default("N/A") }}
```

### LLM Best Practices

#### ✅ DO:

```python
# Use type-safe contexts
class AnalysisContext(MeshContextModel):
    domain: str = Field(..., description="Clear description for LLMs")

# Add Field descriptions for LLM chains
Field(..., description="infrastructure|security|performance")

# Check for None
if llm is None:
    return default_response

# Use filters for dynamic tool discovery
@mesh.llm(filter={"tags": ["system"]})

# Version templates separately
system_prompt="file://prompts/analyst_v2.jinja2"
```

#### ❌ DON'T:

```python
# Don't hardcode prompts in code
system_prompt="You are an assistant. Do this. Do that. Do everything..."

# Don't skip Field descriptions
domain: str  # No description for LLMs

# Don't forget None checks
return llm(message)  # Crashes if llm is None

# Don't manually list tools in prompts
system_prompt="You have get_cpu, get_memory, get_disk..."  # Use filters!

# Don't use dict contexts without validation
ctx: dict  # Use MeshContextModel instead
```

### Environment Variables

LLM configuration via environment variables:

```bash
# Provider API keys
export ANTHROPIC_API_KEY="your-claude-key"
export OPENAI_API_KEY="your-openai-key"

# Override provider/model at runtime
export MCP_MESH_LLM_PROVIDER="openai"
export MCP_MESH_LLM_MODEL="gpt-4"

# Template settings
export MCP_MESH_TEMPLATE_DIR="/custom/prompts"
export MCP_MESH_TEMPLATE_CACHE_ENABLED="true"
```

### Complete LLM Example

```python
import mesh
from fastmcp import FastMCP
from mesh import MeshContextModel
from pydantic import BaseModel, Field

app = FastMCP("LLM Service")

# 1. Define contexts
class DocumentContext(MeshContextModel):
    doc_type: str = Field(..., description="Document type: technical, business, legal")
    audience: str = Field(..., description="Target audience: engineer, executive, lawyer")

# 2. Specialist LLM
@app.tool()
@mesh.llm(
    system_prompt="file://prompts/doc_analyzer.jinja2",
    context_param="ctx",
    filter={"tags": ["document"]},
    provider="claude",
    model="anthropic/claude-sonnet-4-5"
)
@mesh.tool(capability="doc_analysis", tags=["llm", "specialist"])
async def analyze_doc(doc: str, ctx: DocumentContext, llm: mesh.MeshLlmAgent = None):
    if llm is None:
        return {"error": "LLM unavailable"}
    return await llm(doc)

# 3. Orchestrator LLM
@app.tool()
@mesh.llm(
    system_prompt="You orchestrate document workflows.",
    filter={"capability": "doc_analysis"},
    provider="claude",
    model="anthropic/claude-sonnet-4-5"
)
@mesh.tool(capability="doc_orchestrator")
async def orchestrate(task: str, llm: mesh.MeshLlmAgent = None):
    if llm is None:
        return {"error": "LLM unavailable"}
    return await llm(task)

# 4. Dual injection (LLM + MCP)
@app.tool()
@mesh.llm(
    system_prompt="file://prompts/enriched.jinja2",
    filter={"tags": ["system"]},
    provider="claude",
    model="anthropic/claude-sonnet-4-5"
)
@mesh.tool(
    capability="enriched_analysis",
    dependencies=[{"capability": "date_service"}]
)
async def enriched_analyze(
    query: str,
    llm: mesh.MeshLlmAgent = None,
    date_service: mesh.McpMeshAgent = None
):
    if llm is None:
        return {"error": "LLM unavailable"}

    llm_result = await llm(query)
    timestamp = await date_service() if date_service else "N/A"

    return {
        **llm_result,
        "timestamp": timestamp,
        "enriched": True
    }

# 5. Agent configuration
@mesh.agent(
    name="llm-service",
    version="1.0.0",
    http_port=8080,
    enable_http=True,
    auto_run=True
)
class LlmServiceAgent:
    pass
```

For complete LLM integration guide, see **[LLM Integration Tutorial](01-getting-started/06-llm-integration.md)**.

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
curl -s -X POST http://localhost:9091/mcp \
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
