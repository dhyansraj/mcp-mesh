# Automatic Session Management with Enhanced Proxies

## Overview

The enhanced proxy system now supports **automatic session management** for stateful capabilities. This eliminates the need for manual session creation, management, and cleanup when using `@mesh.tool` decorators with `session_required=True`.

## Before: Manual Session Management (Phase 6)

In the previous implementation, developers had to manually manage sessions:

```python
@app.tool()
@mesh.tool(capability="session_test", dependencies=["session_counter"])
async def test_session_affinity(
    test_rounds: int = 3,
    session_counter: McpAgent = None,
) -> dict:
    """Test session affinity using explicit session management (Phase 6)."""
    if not session_counter:
        return {"error": "No session_counter service available"}

    try:
        # Phase 6: Create session explicitly
        session_id = await session_counter.create_session()

        results = []
        for round_num in range(1, test_rounds + 1):
            try:
                # Call with explicit session ID for session affinity
                result = await session_counter.call_with_session(
                    session_id=session_id, increment=round_num
                )
                results.append({"round": round_num, "response": result})
            except Exception as e:
                results.append({"round": round_num, "error": str(e)})

        # Clean up session
        await session_counter.close_session(session_id)

        return {
            "session_id": session_id,
            "test_rounds": test_rounds,
            "results": results,
        }

    except Exception as e:
        return {"error": f"Session affinity test failed: {str(e)}"}
```

**Issues with Manual Approach:**

- ❌ **Boilerplate Code**: Manual session creation and cleanup
- ❌ **Error-Prone**: Easy to forget session cleanup on errors
- ❌ **Complex**: Developers need to understand session lifecycle
- ❌ **Repetitive**: Same pattern needed for every session-aware function

## After: Automatic Session Management (Enhanced)

With enhanced proxies, session management is **completely automatic**:

```python
@app.tool()
@mesh.tool(
    capability="auto_session_test",
    dependencies=["session_counter"],
    session_required=True,          # ✅ Auto-session management
    stateful=True,                  # ✅ Indicates stateful behavior
    auto_session_management=True    # ✅ Enable automatic session handling
)
async def test_auto_session_affinity(
    test_rounds: int = 3,
    session_counter: McpAgent = None,  # ✅ Enhanced proxy with auto-sessions
) -> dict:
    """Test session affinity using automatic session management."""
    if not session_counter:
        return {"error": "No session_counter service available"}

    results = []
    for round_num in range(1, test_rounds + 1):
        try:
            # ✅ No manual session management needed!
            # Enhanced proxy automatically:
            # 1. Creates session on first call
            # 2. Reuses same session for subsequent calls
            # 3. Adds session headers to requests
            # 4. Handles session cleanup on errors
            result = await session_counter(increment=round_num)
            results.append({"round": round_num, "response": result})
        except Exception as e:
            results.append({"round": round_num, "error": str(e)})

    # ✅ Session cleanup happens automatically!
    return {
        "test_rounds": test_rounds,
        "results": results,
        "auto_session": True,
    }
```

**Benefits of Automatic Approach:**

- ✅ **Zero Boilerplate**: No manual session management code
- ✅ **Automatic Cleanup**: Sessions cleaned up on errors and completion
- ✅ **Declarative**: Configuration via `@mesh.tool` decorator kwargs
- ✅ **Transparent**: Works exactly like regular function calls
- ✅ **Consistent**: Same session used across multiple calls automatically

## How Automatic Session Management Works

### 1. Configuration via Kwargs

```python
@mesh.tool(
    capability="stateful_service",
    dependencies=["session_counter"],
    session_required=True,          # Enable session requirement
    stateful=True,                  # Mark as stateful capability
    auto_session_management=True,   # Enable automatic session handling (default)
    timeout=60,                     # Also supports other enhancements
    retry_count=3,
    streaming=True
)
def my_stateful_function(session_counter: McpAgent = None):
    # Enhanced proxy automatically handles sessions
    return session_counter(operation="increment")
```

### 2. Enhanced Proxy Auto-Configuration

The dependency resolution system detects `session_required=True` and creates an `EnhancedFullMCPProxy`:

```python
# Dependency resolution automatically creates enhanced proxy
enhanced_proxy = EnhancedFullMCPProxy(
    endpoint="http://session-service:8080",
    function_name="session_counter",
    kwargs_config={
        "session_required": True,
        "stateful": True,
        "auto_session_management": True,
        "timeout": 60,
        "retry_count": 3
    }
)

# Enhanced proxy configuration
assert enhanced_proxy.session_required == True
assert enhanced_proxy.auto_session_management == True
assert enhanced_proxy._current_session_id == None  # No session yet
```

### 3. Automatic Session Lifecycle

```python
# First call: Enhanced proxy automatically creates session
result1 = await enhanced_proxy("increment", {"amount": 1})
# ✅ Session created: "session:abc123"
# ✅ Call made with session headers
# ✅ Session ID stored for reuse

# Subsequent calls: Enhanced proxy reuses same session
result2 = await enhanced_proxy("increment", {"amount": 2})
# ✅ Same session reused: "session:abc123"
# ✅ Consistent stateful behavior

# On completion or error: Enhanced proxy cleans up session
await enhanced_proxy.cleanup_auto_session()
# ✅ Session closed and cleaned up
```

### 4. Streaming with Sessions

Enhanced proxies also support automatic session management for streaming:

```python
@mesh.tool(
    capability="streaming_session_service",
    dependencies=["stream_counter"],
    session_required=True,
    streaming=True,                 # Enable streaming
    auto_session_management=True
)
async def stream_with_sessions(stream_counter: McpAgent = None):
    # Enhanced proxy automatically handles sessions for streaming
    async for chunk in stream_counter.call_tool_auto("stream_count", {"start": 1}):
        yield chunk
    # ✅ Session automatically managed for entire stream
```

## Comparison: Manual vs Automatic

| Aspect                   | Manual Session Management      | Automatic Session Management |
| ------------------------ | ------------------------------ | ---------------------------- |
| **Code Lines**           | ~15-20 lines of session code   | ~0 lines (declarative)       |
| **Error Handling**       | Manual cleanup in try/catch    | Automatic cleanup on errors  |
| **Session Creation**     | `await proxy.create_session()` | Automatic on first call      |
| **Session Reuse**        | Manual tracking of session_id  | Automatic reuse              |
| **Session Cleanup**      | `await proxy.close_session()`  | Automatic cleanup            |
| **Configuration**        | Hardcoded in function logic    | Declarative in `@mesh.tool`  |
| **Streaming Support**    | Manual header management       | Automatic session headers    |
| **Developer Experience** | Complex, error-prone           | Simple, transparent          |

## Migration Guide

### From Manual to Automatic

**Step 1**: Update your `@mesh.tool` decorator:

```python
# Before
@mesh.tool(capability="my_service", dependencies=["session_counter"])

# After
@mesh.tool(
    capability="my_service",
    dependencies=["session_counter"],
    session_required=True,          # Add session requirement
    auto_session_management=True    # Enable automatic management
)
```

**Step 2**: Remove manual session management code:

```python
# Before: Manual session management
async def my_function(session_counter: McpAgent = None):
    session_id = await session_counter.create_session()
    try:
        result = await session_counter.call_with_session(
            session_id=session_id, operation="increment"
        )
        return result
    finally:
        await session_counter.close_session(session_id)

# After: Automatic session management
async def my_function(session_counter: McpAgent = None):
    result = await session_counter(operation="increment")
    return result
```

**Step 3**: Test and verify behavior:

```python
# Enhanced proxy will automatically:
# 1. Create session on first call
# 2. Include session headers in requests
# 3. Maintain session affinity
# 4. Clean up session on completion/errors
```

## Real-World Examples

### Session Counter with Retry Logic

```python
@mesh.tool(
    capability="reliable_counter",
    dependencies=["session_counter"],
    session_required=True,
    retry_count=3,                  # Retry failed calls
    retry_delay=1.0,               # 1 second between retries
    timeout=30,                    # 30 second timeout
    auto_session_management=True
)
async def reliable_increment(
    amount: int = 1,
    session_counter: McpAgent = None
) -> dict:
    """Reliable counter with automatic session management and retries."""
    # Enhanced proxy handles sessions, retries, and timeouts automatically
    return await session_counter(increment=amount)
```

### Streaming Analytics with Sessions

```python
@mesh.tool(
    capability="stream_analytics",
    dependencies=["analytics_engine"],
    session_required=True,
    streaming=True,                 # Enable streaming
    stream_timeout=300,            # 5 minute stream timeout
    buffer_size=8192,              # 8KB stream buffer
    auto_session_management=True
)
async def stream_analytics(
    dataset: str,
    analytics_engine: McpAgent = None
) -> AsyncIterator[dict]:
    """Stream analytics results with automatic session management."""
    # Enhanced proxy automatically manages session for entire stream
    async for result in analytics_engine.call_tool_auto("analyze", {"dataset": dataset}):
        yield result
    # Session automatically cleaned up when stream completes
```

## Benefits Summary

1. **🚀 Developer Productivity**: Eliminates 90% of session management code
2. **🛡️ Error Safety**: Automatic cleanup prevents session leaks
3. **🔧 Declarative Configuration**: All configuration in decorator kwargs
4. **🔄 Consistent Behavior**: Same patterns across all session-aware functions
5. **📊 Better Debugging**: Enhanced logging shows session lifecycle
6. **⚡ Performance**: Session reuse reduces overhead
7. **🌊 Streaming Support**: Works seamlessly with streaming capabilities

The enhanced proxy system with automatic session management represents a major improvement in developer experience while maintaining full compatibility with existing manual session management approaches.
