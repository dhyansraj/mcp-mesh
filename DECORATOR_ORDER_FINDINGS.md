# Decorator Order Findings - UPDATED

## Summary

After extensive testing, we've discovered:

1. The current `@mesh_agent` decorator does NOT wrap the function - it only adds metadata and returns the original function
2. FastMCP's `@server.tool()` has UNEXPECTED behavior - it stores what it receives but applies additional wrapping
3. This creates a REVERSE pattern from what we expected

## Key Findings

1. **@server.tool() Behavior** (CORRECTED)

   - Stores whatever function it receives in its registry
   - BUT when decorators are stacked, behavior is complex:
     - If @server.tool() is FIRST: It stores the original, but subsequent decorators still wrap it
     - If @server.tool() is LAST: It stores the already-wrapped function
   - This is why our tests showed unexpected results

2. **@mesh_agent Behavior (Current)**

   - Adds metadata to the function
   - Returns the original function (no wrapper)
   - Runtime processor gets called but returns the same function

3. **Why Dependency Injection Isn't Working**
   - Neither decorator creates a wrapper
   - No actual injection code is executed at call time
   - The `process_function` method just returns the original function

## What Needs to Be Fixed

To make dependency injection work through MCP protocol:

1. **Update mesh_agent decorator** to return a wrapper function that:

   - Intercepts function calls
   - Queries the registry for dependencies
   - Injects them into kwargs
   - Calls the original function

2. **Ensure correct decorator order**:
   - `@mesh_agent` must come BEFORE `@server.tool()`
   - This ensures FastMCP stores the wrapper, not the original

## Example of What's Needed

```python
def mesh_agent(capability: str, dependencies: list[str] = None, **kwargs):
    def decorator(target):
        # Add metadata
        target._mesh_metadata = {...}

        # Create wrapper that does injection
        @functools.wraps(target)
        def wrapper(**call_kwargs):
            # Inject dependencies here
            if dependencies:
                for dep in dependencies:
                    if dep not in call_kwargs:
                        # Get from registry/runtime
                        call_kwargs[dep] = get_dependency(dep)

            # Call original
            return target(**call_kwargs)

        # Copy metadata to wrapper
        wrapper._mesh_metadata = target._mesh_metadata

        # Return wrapper, not original!
        return wrapper

    return decorator
```

## Next Steps

1. Implement proper wrapper in mesh_agent decorator
2. Add dependency resolution logic
3. Test with MCP Inspector to verify injection works
4. Update documentation about decorator order importance
