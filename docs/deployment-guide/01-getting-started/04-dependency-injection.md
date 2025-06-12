# Understanding Dependency Injection in MCP Mesh

> How agents discover and use each other's capabilities automatically

## What is Dependency Injection?

Dependency Injection (DI) in MCP Mesh allows agents to:

- 🔗 Declare dependencies on other agents' capabilities
- 🔍 Automatically discover and connect to required services
- 📞 Call remote functions as if they were local
- 🔄 Handle failover and load balancing transparently
- 🎯 Focus on business logic, not service discovery

## Core Concepts

### 1. Capabilities

Each agent exposes **capabilities** - named functionalities that other agents can use:

```python
@mesh_agent(
    capability="weather",  # This agent provides "weather" capability
    version="1.0.0"
)
def get_weather(city: str) -> dict:
    return {"city": city, "temp": 22, "condition": "sunny"}
```

### 2. Dependencies

Agents declare what capabilities they need:

```python
@mesh_agent(
    capability="travel_advisor",
    dependencies=["weather_get_weather", "SystemAgent_getDate"]  # Needs these
)
def plan_trip(destination: str, weather_get_weather=None, SystemAgent_getDate=None):
    weather = weather_get_weather(destination)
    date = SystemAgent_getDate()
    return f"On {date}, {destination} will be {weather['condition']}"
```

### 3. Automatic Injection

MCP Mesh automatically:

1. Finds agents providing required capabilities
2. Creates proxy functions for remote calls
3. Injects them as function parameters

## How It Works

### Step 1: Registration

When an agent starts:

```python
# Agent registers its capabilities
registry.register({
    "name": "weather-service-001",
    "capabilities": ["weather"],
    "functions": ["weather_get_weather", "weather_get_forecast"],
    "endpoint": "http://localhost:8082",
    "metadata": {"version": "1.0.0"}
})
```

### Step 2: Discovery

When an agent needs dependencies:

```python
# MCP Mesh queries registry
for dep in dependencies:
    agents = registry.find_agents_with_capability(dep)
    if agents:
        selected = load_balancer.select(agents)
        create_proxy_function(dep, selected.endpoint)
```

### Step 3: Injection

The proxy function is injected:

```python
# Original function
def plan_trip(destination: str, weather_get_weather=None):
    # weather_get_weather is now a callable that makes HTTP requests
    result = weather_get_weather(destination)  # Remote call happens here
    return result
```

## Dependency Declaration Patterns

### 1. Simple Dependencies

```python
@mesh_agent(
    capability="analyzer",
    dependencies=["calculator_add", "calculator_multiply"]
)
def analyze_data(data: list, calculator_add=None, calculator_multiply=None):
    total = calculator_add(data[0], data[1])
    product = calculator_multiply(data[0], data[1])
    return {"sum": total, "product": product}
```

### 2. Optional Dependencies

```python
@mesh_agent(
    capability="reporter",
    dependencies=["formatter_pretty_print"],  # Required
    optional_dependencies=["logger_log"]      # Optional
)
def generate_report(data: dict, formatter_pretty_print=None, logger_log=None):
    report = formatter_pretty_print(data)

    if logger_log:  # Use if available
        logger_log(f"Report generated: {len(report)} bytes")

    return report
```

### 3. Version-Specific Dependencies

```python
@mesh_agent(
    capability="processor",
    dependencies=[
        {"capability": "parser", "version": ">=2.0.0"},
        {"capability": "validator", "version": "~1.5.0"}
    ]
)
def process_document(doc: str, parser_parse=None, validator_validate=None):
    parsed = parser_parse(doc)
    validated = validator_validate(parsed)
    return validated
```

## Real-World Example

Let's build a multi-agent system:

### 1. Database Agent

```python
# database_agent.py
from mcp_mesh import mesh_agent, create_server

server = create_server("database-agent")
db = {}  # Simple in-memory store

@server.tool()
@mesh_agent(
    capability="database",
    version="1.0.0",
    enable_http=True,
    http_port=8090
)
def database_save(key: str, value: str) -> bool:
    """Save data to database"""
    db[key] = value
    return True

@server.tool()
@mesh_agent(
    capability="database",
    version="1.0.0",
    enable_http=True,
    http_port=8090
)
def database_load(key: str) -> str | None:
    """Load data from database"""
    return db.get(key)
```

### 2. Cache Agent

```python
# cache_agent.py
from mcp_mesh import mesh_agent, create_server
from datetime import datetime, timedelta

server = create_server("cache-agent")
cache = {}

@server.tool()
@mesh_agent(
    capability="cache",
    dependencies=["database_load", "database_save"],
    version="1.0.0",
    enable_http=True,
    http_port=8091
)
def cache_get(key: str, database_load=None) -> str | None:
    """Get from cache or database"""
    if key in cache:
        entry = cache[key]
        if datetime.now() < entry["expires"]:
            return entry["value"]

    # Cache miss - load from database
    value = database_load(key)
    if value:
        cache[key] = {
            "value": value,
            "expires": datetime.now() + timedelta(minutes=5)
        }
    return value

@server.tool()
@mesh_agent(
    capability="cache",
    dependencies=["database_save"],
    version="1.0.0",
    enable_http=True,
    http_port=8091
)
def cache_set(key: str, value: str, database_save=None) -> bool:
    """Set in cache and database"""
    # Write through to database
    database_save(key, value)

    # Update cache
    cache[key] = {
        "value": value,
        "expires": datetime.now() + timedelta(minutes=5)
    }
    return True
```

### 3. API Agent

```python
# api_agent.py
from mcp_mesh import mesh_agent, create_server

server = create_server("api-agent")

@server.tool()
@mesh_agent(
    capability="api",
    dependencies=["cache_get", "cache_set"],
    version="1.0.0",
    enable_http=True,
    http_port=8092
)
def api_store_user(user_id: str, name: str, cache_set=None) -> dict:
    """Store user data"""
    key = f"user:{user_id}"
    value = f'{{"id":"{user_id}","name":"{name}"}}'

    cache_set(key, value)
    return {"status": "stored", "user_id": user_id}

@server.tool()
@mesh_agent(
    capability="api",
    dependencies=["cache_get"],
    version="1.0.0",
    enable_http=True,
    http_port=8092
)
def api_get_user(user_id: str, cache_get=None) -> dict:
    """Get user data"""
    key = f"user:{user_id}"
    value = cache_get(key)

    if value:
        import json
        return json.loads(value)
    return {"error": "User not found"}
```

### 4. Running the System

```bash
# Terminal 1: Registry
python -m mcp_mesh.registry.server

# Terminal 2: Database Agent
python database_agent.py

# Terminal 3: Cache Agent
python cache_agent.py

# Terminal 4: API Agent
python api_agent.py

# Test the system
curl -X POST http://localhost:8092/api_store_user \
  -d '{"user_id": "123", "name": "Alice"}'

curl -X POST http://localhost:8092/api_get_user \
  -d '{"user_id": "123"}'
# Returns: {"id": "123", "name": "Alice"}
```

## Advanced DI Features

### 1. Circular Dependencies

MCP Mesh detects and prevents circular dependencies:

```python
# This will raise an error during registration
@mesh_agent(capability="A", dependencies=["B_func"])
def a_func(B_func=None): pass

@mesh_agent(capability="B", dependencies=["A_func"])
def b_func(A_func=None): pass  # Error: Circular dependency
```

### 2. Dependency Health Checks

```python
@mesh_agent(
    capability="critical_service",
    dependencies=["data_source"],
    health_check_dependencies=True  # Monitor dependency health
)
def process_critical_data(data_source=None):
    # MCP Mesh ensures data_source is healthy before injection
    return data_source()
```

### 3. Fallback Strategies

```python
@mesh_agent(
    capability="resilient_service",
    dependencies=["primary_db"],
    fallback_mode=True,
    fallback_strategy="retry"  # retry, circuit_breaker, or custom
)
def get_data(key: str, primary_db=None):
    if primary_db:
        return primary_db(key)
    else:
        # Fallback logic when dependency unavailable
        return {"error": "Service degraded", "fallback": True}
```

## Best Practices

### 1. Naming Conventions

```python
# Good: capability_function
"database_save"
"weather_get_forecast"
"auth_validate_token"

# Bad: ambiguous names
"save"  # Which service?
"get"   # Get what?
```

### 2. Granular Capabilities

```python
# Good: Specific capabilities
@mesh_agent(capability="user_management")
@mesh_agent(capability="user_authentication")
@mesh_agent(capability="user_profile")

# Bad: Monolithic capability
@mesh_agent(capability="user")  # Too broad
```

### 3. Version Management

```python
# Specify compatible versions
dependencies=[
    "payment_v2_process",  # Specific version
    {"capability": "email", "version": ">=1.0.0"},
    {"capability": "sms", "version": "~2.1.0"}
]
```

## Debugging Dependency Injection

### 1. Enable Debug Logging

```bash
export MCP_MESH_LOG_LEVEL=DEBUG
python your_agent.py
```

### 2. Check Dependency Resolution

```python
# In your agent code
import logging
logger = logging.getLogger(__name__)

@mesh_agent(
    capability="debug_example",
    dependencies=["some_service"]
)
def my_function(some_service=None):
    logger.debug(f"Injected function: {some_service}")
    logger.debug(f"Function type: {type(some_service)}")
    logger.debug(f"Is callable: {callable(some_service)}")
```

### 3. Registry Inspection

```bash
# List all capabilities
curl http://localhost:8000/capabilities

# Find agents for a capability
curl http://localhost:8000/agents?capability=weather

# Check dependency graph
curl http://localhost:8000/dependencies
```

## Common Issues and Solutions

### 1. Dependency Not Found

```
ERROR: Failed to resolve dependency: weather_get_forecast
```

**Solutions:**

- Ensure the provider agent is running
- Check capability name matches exactly
- Verify provider registered successfully

### 2. Type Mismatch

```
ERROR: Dependency injection type mismatch
```

**Solutions:**

- Ensure parameter name matches dependency
- Add type hints for clarity
- Check function signature compatibility

### 3. Performance Issues

**Solutions:**

- Enable connection pooling
- Use caching for frequently called dependencies
- Consider colocating dependent services

## Next Steps

Now that you understand dependency injection, let's create your own agent:

[Creating Your First Agent](./05-first-agent.md) →

---

💡 **Pro Tip**: Use the registry UI (if available) to visualize dependency graphs.

📚 **Exercise**: Modify the cache agent to use TTL from configuration instead of hardcoded 5 minutes.

## 🔧 Troubleshooting

### DI-Specific Issues

1. **Circular dependencies** - Refactor to break the cycle or use lazy loading
2. **Version conflicts** - Specify exact versions or use version ranges carefully
3. **Injection not working** - Ensure parameter names match dependency names exactly
4. **Performance degradation** - Enable connection pooling and caching
5. **Intermittent failures** - Implement retry logic with exponential backoff

For detailed solutions, see our [Troubleshooting Guide](./troubleshooting.md).

## ⚠️ Known Limitations

- **No compile-time checking**: Dependencies resolved at runtime
- **Naming conventions**: Must follow capability_function pattern
- **Type safety**: Limited type checking for injected functions
- **Circular dependencies**: Not supported, will fail at registration
- **Dynamic dependencies**: Cannot change dependencies after registration
- **Cross-language**: Limited support for non-Python agents

## 📝 TODO

- [ ] Add dependency graph visualization UI
- [ ] Implement compile-time dependency checking
- [ ] Add support for optional dependencies with defaults
- [ ] Create dependency mocking for testing
- [ ] Add metrics for dependency call patterns
- [ ] Support for GraphQL-style selective field resolution
- [ ] Implement dependency versioning strategies
