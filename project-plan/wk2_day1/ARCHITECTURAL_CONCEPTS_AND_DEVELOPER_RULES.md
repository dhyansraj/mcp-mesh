# MCP Mesh - Architectural Concepts and Developer Rules

## Executive Summary

MCP Mesh is a service mesh that enhances the Model Context Protocol (MCP) with automatic dependency injection, service discovery, and graceful degradation. The architecture follows Kubernetes patterns with a passive registry that serves as the "API server" while agents operate independently like pods that can function with or without cluster connectivity.

## Core Architectural Concepts

### 1. Registry as Passive API Server (Kubernetes Pattern)

**Concept**: The registry operates like a Kubernetes API server + etcd - it's a passive data store that only responds to requests, never initiates communication.

**Key Principles**:

- **Pull-Based Architecture**: Agents initiate ALL communication with the registry
- **No Outbound Connections**: Registry never calls agents directly
- **Resource Versioning**: Conflict detection and optimistic concurrency control
- **Timer-Based Health Monitoring**: Passive monitoring based on agent heartbeat timestamps
- **Horizontal Scalability**: Registry instances can be load balanced and scaled independently

**Implementation Details**:

- FastAPI server with both REST (`/agents`, `/capabilities`, `/heartbeat`) and MCP endpoints
- SQLite/PostgreSQL storage with in-memory caching (30-second TTL)
- Kubernetes-style watch events for real-time updates
- Advanced query capabilities: fuzzy matching, version constraints, label selectors

**What Happens When**:

1. **Agent Startup**: Agent POST to `/agents/register_with_metadata` with full capability metadata
2. **Health Monitoring**: Agent POST to `/heartbeat` every 30 seconds (configurable)
3. **Service Discovery**: Agent GET from `/agents?capabilities=greeting&status=healthy`
4. **Health Assessment**: Registry background timer marks agents as `healthy → degraded → expired`

### 2. Interface-Optional Dependency Injection

**Concept**: The revolutionary feature that allows the same code to work in both mesh (remote proxies) and standalone (local instances) environments without requiring Protocol definitions.

**Key Innovation**: Three dependency patterns supported simultaneously:

```python
@mesh_agent(
    capabilities=["auth", "file_operations"],
    dependencies=[
        "legacy_auth",      # STRING: Registry lookup (legacy)
        AuthService,        # PROTOCOL: Interface matching (future)
        OAuth2AuthService,  # CONCRETE: Direct instantiation (hybrid)
    ]
)
async def flexible_function(
    legacy_auth: str = None,                    # Injected via registry
    auth_service: AuthService = None,           # Injected via fallback chain
    oauth2_auth: OAuth2AuthService = None,      # Injected via fallback chain
):
    # All three dependency types work simultaneously!
```

**Runtime Flow**:

1. **Design Time**: `@mesh_agent` decorator analyzes function signatures and dependency specifications
2. **Registration**: `DecoratorProcessor` registers enhanced metadata with mesh registry
3. **First Call**: `MeshAgentDecorator._initialize()` sets up dependency resolution chain
4. **Every Call**: `_inject_dependencies()` resolves parameters via `MeshUnifiedDependencyResolver`

**Fallback Chain Resolution** (Target: <200ms remote→local transition):

1. **Remote Proxy Resolver**: Try service discovery + proxy creation
2. **Local Instance Resolver**: Fall back to local class instantiation
3. **Circuit Breaker**: Prevent repeated failures with exponential backoff

### 3. Agent Independence and Graceful Degradation

**Concept**: Agents operate like Kubernetes pods - they function independently and can survive registry failures.

**Independence Principles**:

- **Registry is Optional**: Agents start successfully when no registry is available at startup
- **Graceful Degradation**: If registry goes down after connection, agents continue working
- **Self-Healing**: Agents keep trying to reconnect but never die due to registry failure
- **Local Capability**: If agent can process requests locally, it works without registry
- **Mesh Connectivity**: Agents that found each other via registry remain connected after registry failure

**Startup Patterns**:

```bash
# Scenario 1: No registry at startup
mcp_mesh_dev start examples/hello_world.py  # Works standalone with local dependencies

# Scenario 2: Registry dies after connection
mcp_mesh_dev start --registry-only &
mcp_mesh_dev start examples/hello_world.py  # Connects to registry
# Kill registry → hello_world continues working with cached/local dependencies

# Scenario 3: Registry reconnection
# Start new registry → hello_world auto-reconnects and re-registers
```

**Agent Lifecycle Management**:

1. **Environment Setup**: Registry connection details via environment variables
2. **Auto-Registration**: Enhanced capability metadata registration on first function call
3. **Health Monitoring**: Background heartbeat loop (30s intervals)
4. **Graceful Shutdown**: Signal handlers for SIGTERM/SIGINT with process tree cleanup

### 4. Dual-Decorator Architecture

**Concept**: Perfect compatibility between vanilla MCP SDK and MCP Mesh enhancements through dual decorators.

**Pattern**:

```python
@server.tool()  # Vanilla MCP SDK - always required
@mesh_agent(    # MCP Mesh enhancement - optional
    capabilities=["greeting", "mesh_integration"],
    dependencies=["SystemAgent"],
    fallback_mode=True
)
def enhanced_function(SystemAgent: Any | None = None) -> str:
    # Function works with vanilla MCP (SystemAgent=None)
    # Function enhanced with mesh (SystemAgent=injected instance)
```

**Compatibility Matrix**:

- **Vanilla MCP Only**: `@server.tool()` → Standard MCP functionality
- **Mesh Enhanced**: `@server.tool() + @mesh_agent()` → Enhanced with dependency injection
- **Backwards Compatible**: Mesh-decorated functions work in vanilla MCP environments

## Developer Rules and Guidelines

### 1. Import Patterns (CRITICAL)

**RULE**: All examples and user code MUST import only from `mcp_mesh`, never from `mcp_mesh_runtime`.

```python
# ✅ CORRECT - Public API
from mcp_mesh import mesh_agent
from mcp_mesh import DependencySpecification, ServiceContract

# ❌ WRONG - Internal implementation
from mcp_mesh_runtime.decorators.mesh_agent import MeshAgentDecorator
from mcp_mesh_runtime.shared.registry_client import RegistryClient
```

**Architecture**:

- `mcp_mesh/`: Types-only package with public APIs, Protocol definitions, and imports
- `mcp_mesh_runtime/`: Full implementation with FastAPI, SQLite, async operations

### 2. MCP SDK Compliance

**RULE**: All examples MUST be valid MCP SDK host/client implementations.

**Required Patterns**:

```python
# ✅ CORRECT - FastMCP Server Pattern
from mcp.server.fastmcp import FastMCP
from mcp_mesh import mesh_agent

server = FastMCP(name="example-server")

@server.tool()  # MCP SDK decorator - ALWAYS REQUIRED
@mesh_agent()   # Mesh enhancement - OPTIONAL
def my_function():
    pass

server.run(transport="stdio")  # Standard MCP transport
```

**Validation**:

- Must work with vanilla MCP clients
- Must use stdio transport (MCP standard)
- Must follow FastMCP server patterns
- Should work in MCP client environments like Claude Desktop

### 3. Dependency Injection Patterns

**RULE**: Use the three dependency patterns appropriately:

```python
@mesh_agent(
    dependencies=[
        "legacy_service",     # STRING: For existing services, simple lookup
        NewServiceProtocol,   # PROTOCOL: For interfaces, future-proof design
        ConcreteService,      # CONCRETE: For classes, direct instantiation
    ]
)
def my_function(
    legacy_service: Any = None,           # STRING pattern
    new_service: NewServiceProtocol = None,  # PROTOCOL pattern
    concrete: ConcreteService = None,     # CONCRETE pattern
):
    pass
```

**Guidelines**:

- Use STRING pattern for legacy compatibility and simple cases
- Use PROTOCOL pattern for interface-based design and future flexibility
- Use CONCRETE pattern for specific class requirements and hybrid scenarios
- Always provide default `None` values for dependency parameters

### 4. Registry Interaction Rules

**RULE**: Never poll or push to agents from registry code.

**Registry Behavior** (Passive):

- Only respond to incoming HTTP requests
- Never make outbound connections to agents
- Use timer-based health assessment, not active polling
- Provide REST and MCP endpoints for agent consumption

**Agent Behavior** (Active):

- Initiate all communication with registry
- Send periodic heartbeats
- Pull service discovery information
- Handle registry unavailability gracefully

### 5. Error Handling and Fallback Patterns

**RULE**: Always design for graceful degradation.

```python
@mesh_agent(
    dependencies=["AuthService"],
    fallback_mode=True  # ALWAYS enable fallback
)
def secure_operation(AuthService: Any = None) -> str:
    if AuthService is None:
        # Graceful degradation - reduced functionality
        return "Operating in basic mode (no auth)"

    try:
        # Enhanced functionality with dependency
        return f"Authenticated operation: {AuthService.authenticate()}"
    except Exception as e:
        # Fallback on dependency failure
        return f"Auth failed, continuing in basic mode: {e}"
```

**Patterns**:

- Always provide fallback behavior when dependencies are unavailable
- Use `fallback_mode=True` in decorator configuration
- Handle dependency injection failures gracefully
- Provide meaningful responses even in degraded mode

### 6. Health and Monitoring Rules

**RULE**: Configure appropriate health monitoring for your service type.

```python
@mesh_agent(
    capabilities=["critical_service"],
    health_interval=10,    # Frequent for critical services
    # timeout_threshold=30,   # Custom timeout if needed
    # eviction_threshold=60,  # Custom eviction if needed
)
def critical_function():
    pass

@mesh_agent(
    capabilities=["background_task"],
    health_interval=60,    # Less frequent for background tasks
)
def background_function():
    pass
```

**Guidelines**:

- Critical services: 10-30 second heartbeat intervals
- Background services: 60+ second heartbeat intervals
- Configure timeouts based on service SLA requirements
- Monitor health status transitions in registry

### 7. Capability and Metadata Design

**RULE**: Design capabilities for service discovery and operational clarity.

```python
@mesh_agent(
    capabilities=[
        "greeting",           # Functional capability
        "mesh_integration",   # Architecture pattern
        "demo"               # Environment type
    ],
    version="1.0.0",         # Semantic versioning
    description="Clear description for operators",
    tags=["demo", "greeting", "dependency_injection"],
    performance_profile={"response_time_ms": 50.0},
    security_context="public",
)
def well_documented_function():
    pass
```

**Guidelines**:

- Use hierarchical capabilities: `auth.oauth2`, `file.read`, `data.transform`
- Provide semantic version for compatibility checking
- Include performance expectations for SLA monitoring
- Tag for operational filtering and grouping

## Flow Diagrams: What Happens When

### Agent Startup with Registry Available

```
1. Agent Process Start
   ├─ Environment setup (registry URL, host, port, DB path)
   ├─ FastMCP server initialization
   └─ @mesh_agent decorator analysis

2. First Function Call
   ├─ MeshAgentDecorator._initialize()
   ├─ Create RegistryClient + ServiceDiscoveryService
   ├─ Setup MeshFallbackChain + MeshUnifiedDependencyResolver
   └─ Start background health monitoring task

3. Auto-Registration
   ├─ Extract enhanced method metadata
   ├─ Build CapabilityMetadata with signatures
   ├─ POST /agents/register_with_metadata
   └─ Emit REGISTRATION_COMPLETED event

4. Runtime Operation
   ├─ Every function call: _inject_dependencies()
   ├─ Every 30s: POST /heartbeat
   └─ Service discovery: GET /agents?capabilities=...
```

### Agent Startup without Registry

```
1. Agent Process Start
   ├─ Environment setup (no registry URLs)
   ├─ FastMCP server initialization
   └─ @mesh_agent decorator analysis

2. First Function Call
   ├─ MeshAgentDecorator._initialize()
   ├─ Registry connection fails → Enable fallback mode
   ├─ Setup local-only MeshFallbackChain
   └─ Skip background health monitoring

3. Fallback Operation
   ├─ Every function call: Local dependency resolution only
   ├─ No registry communication attempts
   └─ Full functionality with local instances
```

### Registry Health Monitoring Flow

```
1. Agent Heartbeat Loop (Every 30s)
   ├─ POST /heartbeat with agent status
   ├─ Registry updates last_heartbeat timestamp
   └─ Continue background loop

2. Registry Timer Assessment (Every 10s)
   ├─ Check all registered agents
   ├─ Compare last_heartbeat vs current time
   └─ Update status: healthy → degraded → expired

3. Service Discovery Impact
   ├─ Healthy agents: Returned in all queries
   ├─ Degraded agents: Returned with warning
   └─ Expired agents: Excluded from results
```

### Dependency Injection Resolution Flow

```
1. Function Call with Dependencies
   ├─ @mesh_agent intercepts call
   ├─ Check if initialization needed
   └─ Proceed to dependency injection

2. Multi-Pattern Resolution (Concurrent)
   ├─ STRING pattern: registry_client.get_dependency("ServiceName")
   ├─ PROTOCOL pattern: fallback_chain.resolve_dependency(ServiceProtocol)
   └─ CONCRETE pattern: fallback_chain.resolve_dependency(ConcreteClass)

3. Fallback Chain (Per Pattern)
   ├─ Remote Proxy Resolver: Try service discovery + proxy creation
   ├─ Local Instance Resolver: Fall back to local class instantiation
   └─ Circuit Breaker: Prevent repeated failures

4. Parameter Injection
   ├─ Map successful resolutions to function parameters
   ├─ Inject resolved instances as keyword arguments
   └─ Call original function with injected dependencies
```

This architecture provides a robust, scalable foundation for service mesh management while maintaining simplicity, MCP SDK compatibility, and following well-established patterns from the Kubernetes ecosystem. The passive/pull-based design ensures the registry can scale efficiently while agents maintain autonomy and resilience.
