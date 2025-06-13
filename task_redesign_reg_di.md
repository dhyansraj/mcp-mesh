# MCP Mesh Registration & Dependency Injection Redesign

## Critical Implementation Notes

1. **Decorator Order Matters**: `@server.tool()` must be FIRST, `@mesh_agent()` second
2. **Python stays lightweight**: Just sending heartbeat = healthy (no health checks)
3. **Proxy injection timing**: Can be done anytime after server.tool caches the function

## Core Architecture

**One Agent = One Process** with multiple tools (functions)

## Python Side Design

### 1. Agent ID (Per Process)

```python
_SHARED_AGENT_ID = f"{os.environ.get('MCP_MESH_AGENT_NAME', 'agent')}-{uuid4().hex[:8]}"
```

### 2. Decorator Pattern (ORDER CRITICAL)

```python
@server.tool()  # MUST BE FIRST - caches function pointer
@mesh_agent(    # MUST BE SECOND - wraps for DI
    capability="greeting",
    version="1.0.0",
    tags=["demo", "v1"],
    dependencies=[
        {
            "capability": "date_service",
            "version": ">=1.0.0",
            "tags": ["production", "US_EAST"]
        }
    ]
)
def greet(name: str, date_service=None) -> str:
    # date_service proxy can be injected/removed anytime
    if date_service:
        return f"Hello {name}, date is {date_service()}"
    return f"Hello {name}"
```

### 3. Batched Registration (One Call)

```python
# All functions collected, then ONE registration:
{
    "agent_id": "myservice-abc12345",
    "metadata": {
        "endpoint": "http://localhost:8889",
        "tools": [
            {
                "function_name": "greet",
                "capability": "greeting",
                "version": "1.0.0",
                "tags": ["demo"],
                "dependencies": [...]
            },
            {
                "function_name": "farewell",
                "capability": "goodbye",
                ...
            }
        ]
    }
}
```

### 4. Simple Heartbeat (One Call)

```python
# Just send heartbeat - being alive = healthy
{
    "agent_id": "myservice-abc12345",
    "metadata": {
        # Any metadata updates (endpoint changes, etc)
    }
}
# No health status - registry deduces from receiving heartbeat
```

### 5. Dependency Resolution Response

```python
# Registry returns in registration & heartbeat responses:
{
    "status": "success",
    "dependencies_resolved": {
        "greet": {  # Per function resolution
            "date_service": {
                "agent_id": "dateservice-xyz789",
                "endpoint": "http://date:8080",
                "tool_name": "get_current_date"
            }
        },
        "farewell": {
            # Different function might have different deps
        }
    }
}
```

## Registry Side Design

### 1. Registration Handling

- Receive one payload with multiple tools
- Update agent record
- Update/insert each tool's capability
- Return dependencies_resolved for ALL tools

### 2. Heartbeat Processing

- Receiving heartbeat = agent is healthy
- Update last_heartbeat timestamp
- Check if any dependency resolutions changed
- Return updated dependencies_resolved if changed

### 3. Health Monitoring

- No heartbeat within timeout = degraded
- No heartbeat within eviction = expired
- Status deduced from heartbeat timing, not payload

### 4. Dependency Resolution (Per Tool)

```go
for each tool in agent.tools:
    for each dependency in tool.dependencies:
        1. Find agents with matching capability
        2. Filter by version constraint
        3. Filter by tags (ALL must match)
        4. Select best match
        5. Add to dependencies_resolved[tool_name]
```

## Key Benefits

1. **Network Efficient**: 1 registration + 1 heartbeat per interval
2. **No Function Collisions**: Scoped by agent_id
3. **Lightweight Python**: No health calculations
4. **Preserves DI Magic**: Respects server.tool caching

## What NOT to Change

- Decorator order (@server.tool first)
- Proxy injection mechanism (works as tested)
- Function pointer caching by server.tool

## Migration Strategy

### Phase 1: Update Python (Current)

- Generate new agent IDs with UUID suffix
- Keep backward compatibility

### Phase 2: Batch Registration

- Collect all functions before registering
- Send tools array in metadata

### Phase 3: Registry Updates

- Handle tools array in registration
- Update schema for tool-level capabilities
- Implement per-tool dependency resolution

### Phase 4: Enhanced Dependencies

- Add version constraint parsing
- Add tag-based filtering
- Implement selection strategies

### Phase 5: Deprecate Old Format

- Remove single-capability support
- Clean up legacy code

## Test Plan

### Unit Tests

```python
def test_agent_id_generation_with_uuid()
def test_multiple_tools_single_agent()
def test_decorator_order_preservation()
def test_batch_registration_payload()
def test_dependency_resolution_per_tool()
```

### Integration Tests

```python
def test_multi_tool_registration_no_collision()
def test_heartbeat_updates_all_tools()
def test_dependency_updates_specific_tools()
def test_version_constraint_filtering()
def test_tag_based_dependency_matching()
```

### Manual Testing

1. Start registry
2. Run agent with multiple functions
3. Verify all functions registered
4. Stop dependency service
5. Verify dependency removed
6. Start dependency service
7. Verify dependency restored
