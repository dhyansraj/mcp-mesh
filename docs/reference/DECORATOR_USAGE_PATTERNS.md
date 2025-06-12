# MCP Mesh Decorator Usage Patterns

This document outlines tested patterns for using `@mesh_agent` decorator with `@server.tool()`, including scenarios that work reliably and those with mixed results.

## ✅ Tested & Recommended Patterns

### 1. Factory Function Pattern (RECOMMENDED)

```python
def create_server():
    server = FastMCP(name="my-server")

    @server.tool()
    @mesh_agent(
        capability="data_processor",
        dependencies=["SystemAgent"]
    )
    def process_data(data: str, SystemAgent=None):
        return {"processed": data}

    return server

# Usage
if __name__ == "__main__":
    server = create_server()
    server.run()
```

**Why it works**: Guarantees decorators execute after runtime initialization.

### 2. Nested Functions

```python
def register_tools(server):
    @server.tool()
    @mesh_agent(dependencies=["DatabaseService"])
    def query_data(query: str, DatabaseService=None):
        return DatabaseService.execute(query) if DatabaseService else None
```

**Why it works**: Decorators execute when the outer function is called, ensuring proper timing.

### 3. Class Method Registration

```python
class ToolRegistry:
    def __init__(self, server):
        self.server = server
        self.register_tools()

    def register_tools(self):
        @self.server.tool()
        @mesh_agent(dependencies=["Logger"])
        def log_message(msg: str, Logger=None):
            if Logger:
                Logger.info(msg)
            return {"logged": True}
```

**Why it works**: Controlled initialization order through class instantiation.

### 4. Conditional Registration

```python
def create_server(config):
    server = FastMCP(name="configurable-server")

    if config.enable_advanced_features:
        @server.tool()
        @mesh_agent(dependencies=["AdvancedProcessor"])
        def advanced_process(data: str, AdvancedProcessor=None):
            return AdvancedProcessor.process(data) if AdvancedProcessor else data

    return server
```

**Why it works**: Decorators only execute if condition is met, maintaining control.

## ⚠️ Patterns with Mixed Results

### 1. Module-Level Decorators

```python
# my_tools.py
server = FastMCP(name="module-server")

@server.tool()
@mesh_agent(dependencies=["SystemAgent"])
def module_level_tool(data: str, SystemAgent=None):
    return data

# This might work if imported correctly, but timing is fragile
```

**Issues**:

- Decorators execute at module parse time
- Runtime processor might not be initialized
- Import order becomes critical
- Hard to test in isolation

### 2. Dynamic Function Names in Loops

```python
for i in range(3):
    @server.tool()
    @mesh_agent(dependencies=["SystemAgent"])
    def dynamic_tool(data: str, SystemAgent=None):
        return f"Tool {i}: {data}"  # Closure issue!
```

**Issues**:

- All functions share the same closure variable
- Registry might have key collisions
- Not specific to our DI, but problematic

### 3. Lambda Functions

```python
# Don't do this
process = lambda data, SystemAgent=None: SystemAgent.process(data)
server.tool()(mesh_agent(dependencies=["SystemAgent"])(process))
```

**Issues**:

- Lambda functions lack proper `__name__` attribute
- Harder to debug and trace
- May not work with all decorator features

## ❌ Known Limitations

### 1. Wrong Decorator Order

```python
# WRONG - FastMCP will unwrap our injection wrapper
@mesh_agent(dependencies=["SystemAgent"])  # First
@server.tool()                              # Second
def broken_tool(data: str, SystemAgent=None):
    return data
```

**Why it fails**: FastMCP unwraps the function, losing our injection wrapper.

### 2. Post-Registration Modification

```python
@server.tool()
@mesh_agent(dependencies=["SystemAgent"])
def original_tool(data: str, SystemAgent=None):
    return data

# Later in code - breaks DI
server._tool_manager._tools["original_tool"].fn = some_other_function
```

**Why it fails**: Replaces our wrapped function with unwrapped version.

## Best Practices

1. **Always use correct decorator order**: `@server.tool()` before `@mesh_agent()`
2. **Prefer factory functions** over module-level decorators
3. **Initialize server before running** to ensure processor is ready
4. **Test your patterns** using the integration tests as examples
5. **Avoid dynamic function creation** in loops without proper closure handling

## Testing Your Pattern

To verify your pattern works:

```python
# After decoration, check:
func = server._tool_manager._tools["your_tool"].fn
assert hasattr(func, '_injected_deps')  # Should be True
assert hasattr(func, '_mesh_agent_dependencies')  # Should be True
```

## Migration Guide

If you have existing module-level decorators:

```python
# OLD (risky)
server = FastMCP()
@server.tool()
def my_tool(): pass

# NEW (reliable)
def create_server():
    server = FastMCP()
    @server.tool()
    def my_tool(): pass
    return server
```
