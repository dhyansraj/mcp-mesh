# MCP Mesh Registration & Dependency Injection Redesign (Complete)

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

### 2. Complete Decorator Pattern (ORDER CRITICAL)

```python
@server.tool()  # MUST BE FIRST - caches function pointer
@mesh_agent(    # MUST BE SECOND - wraps for DI
    # Core capability
    capability="greeting",
    version="1.0.0",
    description="Greeting service with date injection",

    # Dependencies with enhanced resolution
    dependencies=[
        {
            "capability": "date_service",
            "version": ">=1.0.0",
            "tags": ["production", "US_EAST"]
        }
    ],

    # Service configuration
    health_interval=30,
    timeout=30,
    retry_attempts=3,
    enable_caching=True,
    fallback_mode=True,

    # Discovery metadata
    tags=["demo", "v1"],
    endpoint=None,  # Auto-detected

    # Security
    security_context=None,

    # Performance & Resources
    performance_profile={"latency": "low", "throughput": "medium"},
    resource_requirements={"cpu": "100m", "memory": "128Mi"},

    # HTTP wrapper configuration
    enable_http=True,
    http_host="0.0.0.0",
    http_port=8889,

    # Additional metadata
    **{"custom_field": "value"}
)
def greet(name: str, date_service=None) -> str:
    # date_service proxy can be injected/removed anytime
    if date_service:
        return f"Hello {name}, date is {date_service()}"
    return f"Hello {name}"
```

### 3. Batched Registration Payload (All Parameters Preserved)

```python
{
    "agent_id": "myservice-abc12345",
    "metadata": {
        "name": "myservice-abc12345",
        "endpoint": "http://localhost:8889",  # HTTP endpoint if enabled
        "agent_type": "mesh_agent",
        "namespace": "default",
        "tools": [
            {
                # Function identification
                "function_name": "greet",
                "capability": "greeting",
                "version": "1.0.0",
                "description": "Greeting service with date injection",

                # Dependencies
                "dependencies": [
                    {
                        "capability": "date_service",
                        "version": ">=1.0.0",
                        "tags": ["production", "US_EAST"]
                    }
                ],

                # Service configuration
                "health_interval": 30,
                "timeout": 30,
                "retry_attempts": 3,
                "enable_caching": true,
                "fallback_mode": true,

                # Discovery metadata
                "tags": ["demo", "v1"],
                "endpoint": "http://localhost:8889",  # Per-function endpoint

                # Security
                "security_context": null,

                # Performance & Resources
                "performance_profile": {"latency": "low", "throughput": "medium"},
                "resource_requirements": {"cpu": "100m", "memory": "128Mi"},

                # HTTP configuration
                "enable_http": true,
                "http_host": "0.0.0.0",
                "http_port": 8889,
                "transport": ["stdio", "http"],

                # Custom metadata
                "custom_field": "value",

                # MCP parameters
                "parameters": {
                    "name": {"type": "string", "required": true}
                }
            },
            {
                "function_name": "farewell",
                "capability": "goodbye",
                "version": "1.0.0",
                "enable_http": false,  # This function is stdio-only
                "transport": ["stdio"],
                ...
            }
        ]
    }
}
```

### 4. Simple Heartbeat (Preserves Endpoint Updates)

```python
{
    "agent_id": "myservice-abc12345",
    "metadata": {
        # Updated endpoint if HTTP wrapper started
        "endpoint": "http://localhost:8889",
        # Any other metadata updates
        "transport": ["stdio", "http"]
    }
}
```

### 5. Dependency Resolution Response (Per Tool)

```python
{
    "status": "success",
    "dependencies_resolved": {
        "greet": {  # Per function resolution
            "date_service": {
                "agent_id": "dateservice-xyz789",
                "endpoint": "http://date:8080",
                "tool_name": "get_current_date",
                "version": "1.2.0",
                "transport": ["http"]
            }
        },
        "farewell": {
            # Different function might have different deps
        }
    }
}
```

## Registry Side Design

### 1. Database Schema Updates

```sql
-- capabilities table enhanced
CREATE TABLE capabilities (
    id INTEGER PRIMARY KEY,
    agent_id TEXT NOT NULL,
    tool_name TEXT NOT NULL,          -- NEW: Function name
    capability TEXT NOT NULL,
    version TEXT DEFAULT '1.0.0',
    description TEXT,
    tags TEXT DEFAULT '[]',           -- JSON array
    dependencies TEXT DEFAULT '[]',    -- JSON array with constraints

    -- Service configuration
    health_interval INTEGER DEFAULT 30,
    timeout INTEGER DEFAULT 30,
    retry_attempts INTEGER DEFAULT 3,
    enable_caching BOOLEAN DEFAULT TRUE,
    fallback_mode BOOLEAN DEFAULT TRUE,

    -- HTTP configuration
    enable_http BOOLEAN DEFAULT FALSE,
    http_host TEXT DEFAULT '0.0.0.0',
    http_port INTEGER DEFAULT 0,
    endpoint TEXT,                    -- Tool-specific endpoint
    transport TEXT DEFAULT '["stdio"]', -- JSON array

    -- Performance & Security
    security_context TEXT,
    performance_profile TEXT DEFAULT '{}',
    resource_requirements TEXT DEFAULT '{}',

    -- MCP metadata
    parameters_schema TEXT,

    -- Custom metadata
    metadata TEXT DEFAULT '{}',

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE
);
```

### 2. Registration Handling (Preserves All Fields)

```go
// Process each tool in registration
for _, tool := range metadata["tools"].([]interface{}) {
    toolMap := tool.(map[string]interface{})

    capability := database.Capability{
        AgentID:       req.AgentID,
        ToolName:      toolMap["function_name"],
        Capability:    toolMap["capability"],
        Version:       toolMap["version"],
        Description:   toolMap["description"],
        Tags:          toolMap["tags"],
        Dependencies:  toolMap["dependencies"],

        // Service configuration
        HealthInterval: toolMap["health_interval"],
        Timeout:        toolMap["timeout"],
        RetryAttempts:  toolMap["retry_attempts"],
        EnableCaching:  toolMap["enable_caching"],
        FallbackMode:   toolMap["fallback_mode"],

        // HTTP configuration
        EnableHTTP: toolMap["enable_http"],
        HTTPHost:   toolMap["http_host"],
        HTTPPort:   toolMap["http_port"],
        Endpoint:   toolMap["endpoint"],
        Transport:  toolMap["transport"],

        // Additional fields
        SecurityContext:       toolMap["security_context"],
        PerformanceProfile:   toolMap["performance_profile"],
        ResourceRequirements: toolMap["resource_requirements"],
        Metadata:            toolMap,  // Store all fields
    }

    // Insert or update capability
}
```

### 3. Backward Compatibility

- If `tools` array is not present, fall back to old `capabilities` array format
- Old format: One capability per agent
- New format: Multiple tools per agent

## Key Benefits

1. **All Parameters Preserved**: Every decorator parameter is maintained
2. **Per-Tool Configuration**: Each function can have different HTTP settings
3. **Network Efficient**: Still one registration/heartbeat for all tools
4. **Flexible Transport**: Tools can independently use stdio/http
5. **Rich Metadata**: All custom fields preserved for future use

## Migration Strategy

### Phase 1: Update Python Decorator

- [x] Generate new agent IDs with UUID suffix
- [ ] Collect all decorator parameters in metadata
- [ ] Keep backward compatibility

### Phase 2: Batch Registration

- [ ] Collect all functions before registering
- [ ] Build tools array with all parameters
- [ ] Send as single registration

### Phase 3: Registry Updates

- [ ] Update schema to store all tool fields
- [ ] Handle tools array in registration
- [ ] Implement backward compatibility

### Phase 4: Enhanced Dependencies

- [ ] Add version constraint parsing
- [ ] Add tag-based filtering
- [ ] Implement selection strategies

### Phase 5: Update HTTP Wrapper

- [ ] Support per-tool HTTP configuration
- [ ] Update endpoint reporting per tool
- [ ] Handle mixed stdio/http agents
