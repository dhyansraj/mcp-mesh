# Dependency Injection Guide

> **Important**: For decorator usage patterns and what works vs. what doesn't, see [DECORATOR_USAGE_PATTERNS.md](./DECORATOR_USAGE_PATTERNS.md)

This guide explains how MCP Mesh's dependency injection system works, including decorator order flexibility, dynamic updates, and best practices.

## Overview

MCP Mesh provides automatic dependency injection for MCP tools, allowing functions to receive service dependencies without manual wiring. The system supports:

- **Automatic injection** of registered dependencies
- **Dynamic updates** when services change
- **Graceful degradation** when dependencies are unavailable
- **Both decorator orders** (@mesh_agent first OR @server.tool() first)

## How It Works

### 1. Decorator Enhancement

When you use `@mesh_agent` with dependencies, it creates an injection wrapper:

```python
@mesh_agent(capability="processor", dependencies=["Database"])
@server.tool()
def process_data(query: str, Database=None):
    if Database:
        return Database.query(query)
    return "No database available"
```

### 2. FastMCP Integration

We enhance FastMCP's `call_tool` method to check for dependency metadata and inject current values before calling your function.

### 3. Dynamic Updates

When services come online, go offline, or update, all functions automatically receive the latest dependencies.

## Decorator Order Flexibility

**Both decorator orders work correctly:**

### Recommended Order (Best Practice)

```python
@mesh_agent(capability="data", dependencies=["Database"])
@server.tool()
def get_data(query: str, Database=None):
    # This is the recommended order
    pass
```

### Alternative Order (Also Works)

```python
@server.tool()
@mesh_agent(capability="data", dependencies=["Database"])
def get_data(query: str, Database=None):
    # This order also works correctly!
    pass
```

**Why both work:** When dependencies are specified, `@mesh_agent` creates a wrapper function with injection capability. FastMCP's `@server.tool()` decorator preserves whatever it decorates, so both orders result in FastMCP having access to our injection-enabled wrapper.

## Managing Dependencies

### Registering Services

```python
from mcp_mesh.runtime.dependency_injector import get_global_injector

injector = get_global_injector()

# Register a service
await injector.register_dependency("Database", database_instance)

# Update a service (e.g., failover)
await injector.register_dependency("Database", backup_database)

# Remove a service
await injector.unregister_dependency("Database")
```

### Multiple Dependencies

```python
@mesh_agent(
    capability="api",
    dependencies=["Database", "Cache", "Logger"]
)
@server.tool()
async def api_endpoint(
    request: dict,
    Database=None,
    Cache=None,
    Logger=None
):
    if Logger:
        Logger.info(f"Processing request: {request}")

    # Check cache first
    if Cache:
        cached = Cache.get(request["key"])
        if cached:
            return cached

    # Query database
    if Database:
        result = await Database.query(request["query"])
        if Cache:
            Cache.set(request["key"], result)
        return result

    return {"error": "No data sources available"}
```

## Graceful Degradation

Functions should handle missing dependencies gracefully:

```python
@mesh_agent(capability="weather", dependencies=["WeatherAPI"])
@server.tool()
def get_weather(city: str, WeatherAPI=None):
    if WeatherAPI:
        return WeatherAPI.get_forecast(city)

    # Fallback behavior
    return {
        "city": city,
        "status": "unavailable",
        "message": "Weather service is currently offline"
    }
```

## Integration with Registry

In production, the Registry service manages dependencies:

```python
# The Registry automatically injects based on:
# 1. Service discovery
# 2. Health checks
# 3. Load balancing
# 4. Version compatibility

# Your function just declares what it needs:
@mesh_agent(
    capability="processor",
    dependencies=["Database:v2", "Cache:redis"]  # Version constraints
)
```

## Testing with Mock Dependencies

```python
# Test file
async def test_my_function():
    from mcp_mesh.runtime.dependency_injector import get_global_injector

    injector = get_global_injector()

    # Register mock dependencies
    mock_db = Mock()
    mock_db.query.return_value = {"id": 1, "name": "Test"}

    await injector.register_dependency("Database", mock_db)

    # Test your function
    result = await server.call_tool("get_data", {"query": "SELECT 1"})
    assert "Test" in result[0].text
```

## Common Patterns

### 1. Service Versioning

```python
@mesh_agent(
    capability="api",
    dependencies=["Database:v2"]  # Request specific version
)
```

### 2. Optional vs Required Dependencies

```python
@mesh_agent(capability="processor", dependencies=["Database", "Cache"])
@server.tool()
def process(data: str, Database=None, Cache=None):
    if not Database:
        raise ValueError("Database is required")  # Required

    if Cache:
        # Cache is optional
        Cache.store(data)
```

### 3. Dependency Groups

```python
@mesh_agent(
    capability="analytics",
    dependencies=["Database", "DataWarehouse", "MLModel"]
)
```

## Performance Considerations

1. **Injection is lazy** - Dependencies are only resolved when the function is called
2. **Caching** - Dependency lookups are cached for performance
3. **Weak references** - Prevents memory leaks with automatic cleanup
4. **Thread-safe** - Safe for concurrent use

## Troubleshooting

### Dependencies Not Injecting

1. Check decorator order (though both work, try recommended order)
2. Ensure parameter names match exactly (case-sensitive)
3. Verify dependencies are registered before calling
4. Check logs for injection errors

### Type Hints

Always use `Any` or `None` for injected parameters:

```python
from typing import Any

def my_function(
    regular_param: str,
    Database: Any = None,  # Correct
    Cache = None          # Also correct
):
    pass
```

## Best Practices

1. **Always provide defaults** for injected parameters (`=None`)
2. **Check if dependencies exist** before using them
3. **Handle graceful degradation** when services are unavailable
4. **Use descriptive dependency names** (e.g., "UserDatabase" not just "DB")
5. **Document required vs optional** dependencies in docstrings
6. **Test with and without** dependencies available

## Example: Complete Service

```python
from mcp.server.fastmcp import FastMCP
from mcp_mesh import mesh_agent

server = FastMCP(name="user-service")

@mesh_agent(
    capability="user_management",
    dependencies=["Database", "Cache", "EmailService", "Logger"],
    version="2.0.0"
)
@server.tool()
async def create_user(
    username: str,
    email: str,
    Database=None,
    Cache=None,
    EmailService=None,
    Logger=None
) -> dict:
    """
    Create a new user account.

    Required dependencies: Database
    Optional dependencies: Cache, EmailService, Logger
    """
    if not Database:
        return {"error": "Database service unavailable"}

    if Logger:
        Logger.info(f"Creating user: {username}")

    # Check if user exists (try cache first)
    if Cache:
        if Cache.exists(f"user:{username}"):
            return {"error": "User already exists"}

    # Create user in database
    try:
        user = await Database.create_user({
            "username": username,
            "email": email
        })

        # Update cache
        if Cache:
            Cache.set(f"user:{username}", user)

        # Send welcome email
        if EmailService:
            await EmailService.send_welcome(email, username)

        return {"status": "success", "user": user}

    except Exception as e:
        if Logger:
            Logger.error(f"Failed to create user: {e}")
        return {"error": str(e)}

if __name__ == "__main__":
    server.run(transport="stdio")
```

This system enables true service-oriented architecture with MCP, allowing services to discover and use each other dynamically!
