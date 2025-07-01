# MCP Mesh Architecture and Design

> Understanding the core architecture, design principles, and implementation details of MCP Mesh

## Overview

MCP Mesh is a distributed service orchestration framework built on top of the Model Context Protocol (MCP) that enables seamless dependency injection, service discovery, and inter-service communication. The architecture combines familiar FastMCP development patterns with powerful mesh orchestration capabilities.

## Core Architecture

### High-Level Components

```
┌─────────────────────────────────────────────────────────────────┐
│                        MCP Mesh Ecosystem                       │
├─────────────────────────────────────────────────────────────────┤
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐              │
│  │   Agent A   │  │   Agent B   │  │   Agent C   │              │
│  │             │◄─┼─────────────┼─►│             │              │
│  │ ┌─────────┐ │  │ ┌─────────┐ │  │ ┌─────────┐ │              │
│  │ │FastMCP  │◄┼──┼►│FastMCP  │◄┼──┼►│FastMCP  │ │              │
│  │ │Server   │ │  │ │Server   │ │  │ │Server   │ │              │
│  │ └─────────┘ │  │ └─────────┘ │  │ └─────────┘ │              │
│  │ ┌─────────┐ │  │ ┌─────────┐ │  │ ┌─────────┐ │              │
│  │ │Mesh     │ │  │ │Mesh     │ │  │ │Mesh     │ │              │
│  │ │Runtime  │ │  │ │Runtime  │ │  │ │Runtime  │ │              │
│  │ │(Inject) │ │  │ │(Inject) │ │  │ │(Inject) │ │              │
│  │ └─────────┘ │  │ └─────────┘ │  │ └─────────┘ │              │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘              │
│         │                │                │                     │
│         │ Heartbeat      │ Heartbeat      │ Heartbeat           │
│         │ + Discovery    │ + Discovery    │ + Discovery         │
│         │                │                │                     │
│         └────────────────┼────────────────┘                     │
│                          ▼                                      │
│                  ┌─────────────┐                                │
│                  │   Registry  │                                │
│                  │ (Background)│                                │
│                  │ ┌─────────┐ │                                │
│                  │ │Service  │ │                                │
│                  │ │Discovery│ │                                │
│                  │ │         │ │                                │
│                  │ │SQLite DB│ │                                │
│                  │ └─────────┘ │                                │
│                  │ ┌─────────┐ │                                │
│                  │ │Health   │ │                                │
│                  │ │Monitor  │ │                                │
│                  │ └─────────┘ │                                │
│                  └─────────────┘                                │
│                                                                 │
│  Direct MCP JSON-RPC calls between FastMCP servers             │
│  ◄──────────────────────────────────────────────────────────►  │
│  Registry and Mesh Runtime work in background                  │
└─────────────────────────────────────────────────────────────────┘
```

### Component Responsibilities

#### 1. **Agents (Python Runtime)**

- **FastMCP Integration**: Native MCP protocol support for direct agent-to-agent communication
- **Mesh Runtime**: Background dependency injection and proxy creation
- **Auto-Discovery**: Automatic capability registration with registry
- **Health Monitoring**: Periodic heartbeats to registry (background process)

#### 2. **Registry (Go Service)**

- **Service Discovery**: Centralized capability and endpoint registry (background coordination)
- **Health Tracking**: Agent health monitoring and failure detection
- **Dependency Resolution**: Smart capability matching with tags at startup
- **Load Balancing**: Multiple providers for same capability selection

#### 3. **meshctl CLI (Go Binary)**

- **Lifecycle Management**: Start, stop, monitor agents
- **Development Tools**: File watching, auto-restart, debugging
- **Registry Operations**: Query services, check health, troubleshoot

### Key Insight: Background Orchestration

**MCP Mesh operates as background infrastructure:**

- **Discovery Phase**: Registry helps agents find each other during startup
- **Runtime Phase**: Direct FastMCP-to-FastMCP communication (no proxy)
- **Monitoring Phase**: Continuous health checks and capability updates in background

## Design Principles

### 1. **Dual Decorator Pattern**

MCP Mesh uses a dual decorator approach that preserves FastMCP familiarity while adding mesh orchestration:

```python
@app.tool()      # ← FastMCP: MCP protocol handling
@mesh.tool(      # ← Mesh: Dependency injection + orchestration
    capability="weather_data",
    dependencies=["time_service"]
)
def get_weather(time_service: Any = None) -> dict:
    # Business logic here
```

**Design Benefits:**

- **Familiar Development**: Developers keep using FastMCP patterns
- **Enhanced Capabilities**: Mesh adds dependency injection seamlessly
- **Zero Boilerplate**: No manual server management or configuration
- **Gradual Adoption**: Can add mesh features incrementally

### 2. **Heartbeat-Only Architecture**

Unlike traditional service meshes, MCP Mesh uses a heartbeat-only registration model:

```python
# Traditional: Register + Heartbeat
service.register(capabilities)    # Initial registration
service.heartbeat()              # Periodic updates

# MCP Mesh: Heartbeat-Only
service.heartbeat(capabilities)   # Registration + health in one call
```

**Design Benefits:**

- **Simplified Protocol**: Single operation for registration + health
- **Automatic Updates**: Capability changes propagated immediately
- **Failure Recovery**: Missing heartbeats = automatic deregistration
- **Reduced Complexity**: No separate registration lifecycle

### 3. **Smart Dependency Resolution**

MCP Mesh supports sophisticated dependency matching using tags and metadata:

```python
# Simple string dependency
dependencies=["database_service"]

# Complex tag-based dependency
dependencies=[{
    "capability": "storage",
    "tags": ["database", "postgresql"],
    "version": ">=2.0.0"
}]
```

**Resolution Algorithm:**

1. **Exact Match**: Find capability with exact name
2. **Tag Filtering**: Apply tag-based filters if specified
3. **Version Constraints**: Ensure version compatibility
4. **Load Balancing**: Select from multiple compatible providers
5. **Fallback**: Graceful degradation if dependency unavailable

### 4. **Zero Configuration Service Discovery**

Services find each other automatically without configuration files:

```python
# No configuration needed!
@mesh.tool(
    capability="user_service",
    dependencies=["auth_service", "database_service"]
)
def get_user(auth_service=None, database_service=None):
    # Dependencies automatically injected
```

**Discovery Process:**

1. **Agent Startup**: Register capabilities with registry
2. **Dependency Declaration**: Declare what capabilities are needed
3. **Automatic Resolution**: Registry finds and connects services
4. **Dynamic Updates**: New services automatically available
5. **Health Monitoring**: Unhealthy services automatically removed

## Implementation Architecture

### Registry as the Brain, Runtime as Thin Wrapper

MCP Mesh separates concerns between a smart registry and lightweight runtime:

- **Registry (Go)**: Centralized brain that handles dependency resolution, topology management, and service discovery
- **Runtime (Python)**: Thin language wrapper that integrates with FastMCP and provides dependency injection
- **No Direct Communication**: Registry never makes calls to runtime - runtime polls registry for updates

This design allows multiple language runtimes (future: Go, Rust, Node.js) while keeping the intelligence centralized.

### Two-Pipeline Architecture

#### Startup Pipeline (One-time)

```python
# Startup pipeline steps:
1. DecoratorCollectionStep    # Collect all @mesh.tool and @mesh.agent decorators
2. ConfigurationStep          # Resolve agent config from decorators/environment
3. HeartbeatPreparationStep   # Prepare heartbeat payload structure
4. FastMCPServerDiscoveryStep # Discover user's FastMCP server instances
5. HeartbeatLoopStep         # Setup background heartbeat configuration
6. FastAPIServerSetupStep    # Setup FastAPI app with background heartbeat
```

#### Heartbeat Pipeline (Continuous loop)

```python
# Heartbeat pipeline steps:
1. RegistryConnectionStep    # Establish registry connection
2. HeartbeatSendStep        # Send heartbeat to registry with capabilities
3. DependencyResolutionStep # Process registry response and update dependency injection
```

### Decorator Processing Flow

#### Debounce Coordination

```python
# Decorators trigger debounced processing
class DebounceCoordinator:
    def __init__(self, delay=1.0):  # MCP_MESH_DEBOUNCE_DELAY
        self.delay = delay
        self.timer = None

    def trigger_processing(self):
        # Cancel previous timer, schedule new processing
        if self.timer:
            self.timer.cancel()
        self.timer = Timer(self.delay, self._start_startup_pipeline)

# Each decorator calls this when processed
def _trigger_debounced_processing():
    coordinator = get_debounce_coordinator()
    coordinator.trigger_processing()
```

**Process**: Decorators notify when processed → Hold pipeline until no more decorations → Start startup pipeline

### Environment Variable Control

```python
# Key environment variables:
MCP_MESH_AUTO_RUN=true        # Controls standalone vs heartbeat mode
MCP_MESH_ENABLED=true         # Controls runtime initialization
MCP_MESH_DEBOUNCE_DELAY=1.0   # Decorator processing delay
MCP_MESH_REGISTRY_URL=http://localhost:8000  # Registry connection
```

**Flow**: Startup pipeline completes → Check `MCP_MESH_AUTO_RUN` → If true, start heartbeat pipeline

### FastMCP Integration Strategy

#### Function Caching and Wrapping

```python
# We process BEFORE FastMCP decorators
@mesh.tool(capability="greeting", dependencies=["time_service"])
@app.tool()  # FastMCP processes after us
def hello(time_service=None):
    return f"Hello at {time_service()}"

# Implementation:
def mesh_tool_decorator(func):
    # 1. Cache original function
    func._mesh_original_func = func

    # 2. Create dependency injection wrapper
    wrapped = create_injection_wrapper(func, dependencies)

    # 3. Give wrapper to FastMCP (not original)
    return wrapped

def create_injection_wrapper(func, dependencies):
    @functools.wraps(func)
    def dependency_wrapper(*args, **kwargs):
        # Inject dependencies as additional kwargs
        for dep_name, proxy in dependency_wrapper._mesh_injected_deps.items():
            if dep_name in dependencies and dep_name not in kwargs:
                kwargs[dep_name] = proxy

        # Call original cached function
        return func._mesh_original_func(*args, **kwargs)

    # Storage for dependency proxies
    dependency_wrapper._mesh_injected_deps = {}
    return dependency_wrapper
```

### Dependency Resolution and Proxy Creation

#### Registry-Driven Dependency Resolution

```python
# Registry does dependency resolution, returns topology
async def process_heartbeat_response(response):
    current_state = extract_dependency_state(response)
    current_hash = hash_dependency_state(current_state)

    # Only update if dependencies changed
    if current_hash == _last_dependency_hash:
        return  # No changes

    # Update dependency injection
    await update_dependency_injection(current_state)
```

#### Proxy Types

```python
# Two proxy types based on dependency location:

class SelfDependencyProxy:
    """For same-agent dependencies - direct local call"""
    def __init__(self, original_func, function_name):
        self.original_func = original_func
        self.function_name = function_name

    def __call__(self, *args, **kwargs):
        # Direct call to cached original function
        return self.original_func(*args, **kwargs)

class MCPClientProxy:
    """For cross-agent dependencies - direct MCP call"""
    def __init__(self, endpoint, function_name):
        self.endpoint = endpoint
        self.function_name = function_name

    def __call__(self, *args, **kwargs):
        # Direct MCP JSON-RPC call to remote FastMCP server
        payload = {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": "tools/call",
            "params": {
                "name": self.function_name,
                "arguments": kwargs
            }
        }

        response = requests.post(
            f"{self.endpoint}/mcp/",
            json=payload,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream"
            }
        )
        return response.json().get("result")
```

#### Dependency Injection Decision

```python
# Registry response determines proxy type
for dependency in heartbeat_response.dependencies:
    current_agent_id = self.agent_id
    target_agent_id = dependency.agent_id

    if current_agent_id == target_agent_id:
        # Same agent - use self dependency proxy
        proxy = SelfDependencyProxy(
            find_original_function(dependency.function_name),
            dependency.function_name
        )
    else:
        # Different agent - use MCP client proxy
        proxy = MCPClientProxy(
            dependency.endpoint,
            dependency.function_name
        )

    # Update wrapper's injected dependencies
    await injector.update_dependency(dependency.capability, proxy)
```

### Function Execution Flow

#### Runtime Execution

```python
# When FastMCP calls our wrapper:
def dependency_wrapper(*args, **kwargs):
    # 1. Check if dependency proxies are set
    for dep_name in dependencies:
        if dep_name not in kwargs:
            # 2. Inject proxy from _mesh_injected_deps
            proxy = dependency_wrapper._mesh_injected_deps.get(dep_name)
            kwargs[dep_name] = proxy

    # 3. Call original cached function with injected dependencies
    return func._mesh_original_func(*args, **kwargs)

# When user function calls dependency:
def hello(time_service=None):
    if time_service:
        current_time = time_service()  # Proxy.__call__ invoked
        return f"Hello at {current_time}"
```

#### Proxy Invocation

```python
# If self dependency proxy:
def __call__(self, *args, **kwargs):
    return self.original_func(*args, **kwargs)  # Local call

# If MCP client proxy:
def __call__(self, *args, **kwargs):
    # HTTP call to remote FastMCP server
    return self._make_mcp_call(*args, **kwargs)
```

### Hash-Based Change Detection

```python
# Efficient dependency update detection
def _hash_dependency_state(dependency_state):
    """Create hash of current dependency topology"""
    state_str = json.dumps(dependency_state, sort_keys=True)
    return hashlib.sha256(state_str.encode()).hexdigest()

# Global state tracking
_last_dependency_hash = None

async def process_heartbeat_response(response):
    current_hash = _hash_dependency_state(response.dependencies)

    if current_hash == _last_dependency_hash:
        return  # No changes - skip expensive DI update

    # Update dependency injection only when topology changes
    await update_dependency_injection(response.dependencies)
    _last_dependency_hash = current_hash
```

### Agent Lifecycle Management

```python
class AgentProcessor:
    async def startup(self):
        # 1. Wait for decorator debounce completion
        await self._wait_for_decorators()

        # 2. Run startup pipeline
        await self._run_startup_pipeline()

        # 3. Check auto-run environment variable
        if os.getenv('MCP_MESH_AUTO_RUN', 'true').lower() == 'true':
            # 4. Start heartbeat pipeline loop
            asyncio.create_task(self._heartbeat_loop())

    async def _heartbeat_loop(self):
        while True:
            try:
                # Run heartbeat pipeline
                await self._run_heartbeat_pipeline()
                await asyncio.sleep(30)  # MCP_MESH_AUTO_RUN_INTERVAL
            except Exception as e:
                logger.error(f"Heartbeat failed: {e}")
                await asyncio.sleep(5)  # Retry faster on failure
```

This architecture provides efficient, hash-based dependency updates with minimal overhead, direct MCP communication between agents, and clean separation between registry intelligence and runtime simplicity.

## Data Flow and Communication

### 1. Agent Registration Flow

```
┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│   Agent A   │    │  Registry   │    │   Agent B   │
└─────────────┘    └─────────────┘    └─────────────┘
        │                  │                  │
        │  1. Heartbeat   │                  │
        │  (capabilities) │                  │
        ├─────────────────►                  │
        │                 │                  │
        │  2. Store & Index                  │
        │                 │                  │
        │  3. Discovery   │                  │
        │  Request        │                  │
        ◄─────────────────┤                  │
        │                 │                  │
        │  4. Available   │                  │
        │  Capabilities   │                  │
        ├─────────────────►                  │
        │                 │                  │
        │                 │  5. Heartbeat   │
        │                 │  (capabilities) │
        │                 ◄─────────────────┤
        │                 │                  │
        │                 │  6. Store & Index
        │                 │                  │
```

### 2. Dependency Resolution Flow

```
┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│ Consumer    │    │  Registry   │    │  Provider   │
│ Agent       │    │(Background) │    │  Agent      │
└─────────────┘    └─────────────┘    └─────────────┘
        │                  │                  │
        │  1. Startup:     │                  │
        │  Query for deps  │                  │
        ├─────────────────►                  │
        │                 │                  │
        │  2. Find matching                  │
        │  capabilities    │                  │
        │                 │                  │
        │  3. Return       │                  │
        │  endpoint URLs   │                  │
        ◄─────────────────┤                  │
        │                 │                  │
        │  4. Mesh injects │                  │
        │  proxy functions │                  │
        │                 │                  │
        │                 │                  │
        │  5. Runtime: Direct MCP JSON-RPC   │
        │  POST /mcp/ {"method":"tools/call"} │
        ├────────────────────────────────────►
        │                 │                  │
        │  6. FastMCP response               │
        ◄────────────────────────────────────┤
        │                 │                  │
        │                 │                  │
        │  Registry works in background -    │
        │  no involvement in actual calls    │
        │                 │                  │
```

### 3. Health Monitoring Flow

```
┌─────────────┐    ┌─────────────┐
│   Agent     │    │  Registry   │
└─────────────┘    └─────────────┘
        │                  │
        │  Heartbeat       │
        │  every 30s       │
        ├─────────────────►
        │                 │
        │                 │ Mark healthy
        │                 │ Update timestamp
        │                 │
        │  (No heartbeat  │
        │   for 90s)      │
        │                 │
        │                 │ Mark unhealthy
        │                 │ Remove from discovery
        │                 │
        │  Heartbeat       │
        │  resumed         │
        ├─────────────────►
        │                 │
        │                 │ Mark healthy
        │                 │ Re-add to discovery
```

## Performance Characteristics

### Scalability Metrics

| Component                 | Metric             | Performance          |
| ------------------------- | ------------------ | -------------------- |
| **Registry**              | Agents             | 1000+ agents         |
| **Registry**              | Capabilities       | 10,000+ capabilities |
| **Registry**              | Heartbeat Rate     | 100+ heartbeats/sec  |
| **Agent**                 | Tool Calls         | 1000+ calls/sec      |
| **Agent**                 | Startup Time       | <2 seconds           |
| **Dependency Resolution** | Lookup Time        | <10ms                |
| **Service Discovery**     | Update Propagation | <1 second            |

### Memory Usage

| Component          | Base Memory | Per Agent | Per Capability |
| ------------------ | ----------- | --------- | -------------- |
| **Registry**       | 20MB        | +2KB      | +1KB           |
| **Agent (Python)** | 50MB        | N/A       | +5KB           |
| **meshctl**        | 10MB        | N/A       | N/A            |

### Network Overhead

- **Heartbeat Size**: ~2KB per agent every 30 seconds
- **Discovery Query**: ~1KB request, ~5KB response
- **Tool Call**: Standard MCP JSON-RPC (varies by payload)

## Security Model

### Authentication and Authorization

Currently MCP Mesh operates in a trusted network model:

- **No Built-in Auth**: Assumes secure network environment
- **HTTP Only**: HTTPS support planned for production
- **Service-to-Service**: Direct HTTP communication between agents
- **Registry Access**: Open access to all agents in network

### Security Recommendations

For production deployments:

1. **Network Segmentation**: Use private networks or VPNs
2. **Service Mesh**: Deploy with Istio/Linkerd for mTLS
3. **API Gateway**: Use gateway for external access control
4. **Container Security**: Use non-root containers and security contexts

### Planned Security Features

- **mTLS Support**: Mutual TLS for service-to-service communication
- **RBAC**: Role-based access control for capabilities
- **API Keys**: Agent authentication with registry
- **Network Policies**: Kubernetes network policy integration

## Deployment Patterns

### 1. Local Development

```
┌─────────────────────────────────────┐
│          Developer Machine          │
│                                     │
│  ┌─────────────┐  ┌─────────────┐   │
│  │  Registry   │  │   Agent 1   │   │
│  │ localhost:  │  │ localhost:  │   │
│  │    8000     │  │    8080     │   │
│  └─────────────┘  └─────────────┘   │
│         │                │          │
│         └────────────────┘          │
│                                     │
│  ┌─────────────┐  ┌─────────────┐   │
│  │   Agent 2   │  │   Agent 3   │   │
│  │ localhost:  │  │ localhost:  │   │
│  │    8081     │  │    8082     │   │
│  └─────────────┘  └─────────────┘   │
│         │                │          │
│         └────────────────┘          │
└─────────────────────────────────────┘
```

### 2. Docker Compose

```
┌─────────────────────────────────────┐
│           Docker Network            │
│                                     │
│  ┌─────────────┐  ┌─────────────┐   │
│  │  registry   │  │hello-world- │   │
│  │             │  │   agent     │   │
│  │   :8000     │  │   :8080     │   │
│  └─────────────┘  └─────────────┘   │
│         │                │          │
│         └────────────────┘          │
│                                     │
│  ┌─────────────┐  ┌─────────────┐   │
│  │ weather-    │  │  system-    │   │
│  │  agent      │  │   agent     │   │
│  │   :8081     │  │   :8082     │   │
│  └─────────────┘  └─────────────┘   │
│         │                │          │
│         └────────────────┘          │
└─────────────────────────────────────┘
```

### 3. Kubernetes

```
┌─────────────────────────────────────────────────────────┐
│                    Kubernetes Cluster                   │
│                                                         │
│  ┌─────────────────┐    ┌─────────────────────────────┐ │
│  │   mcp-registry  │    │        mcp-agents           │ │
│  │                 │    │                             │ │
│  │ ┌─────────────┐ │    │ ┌─────────┐ ┌─────────────┐ │ │
│  │ │   Service   │ │    │ │ Agent-A │ │  Agent-B    │ │ │
│  │ │registry:8000│ │    │ │ Pod     │ │  Pod        │ │ │
│  │ └─────────────┘ │    │ └─────────┘ └─────────────┘ │ │
│  │ ┌─────────────┐ │    │ ┌─────────┐ ┌─────────────┐ │ │
│  │ │ StatefulSet │ │    │ │ Agent-C │ │  Agent-D    │ │ │
│  │ │  (SQLite)   │ │    │ │ Pod     │ │  Pod        │ │ │
│  │ └─────────────┘ │    │ └─────────┘ └─────────────┘ │ │
│  └─────────────────┘    └─────────────────────────────┘ │
│           │                           │                 │
│           └───────────────────────────┘                 │
│                     Service Discovery                   │
└─────────────────────────────────────────────────────────┘
```

## Extension Points

### 1. Custom Dependency Resolvers

```python
class CustomDependencyResolver(DependencyResolver):
    async def resolve_capability(self, capability_spec):
        # Custom logic for finding capabilities
        # e.g., geographic proximity, cost optimization
        candidates = await super().find_candidates(capability_spec)
        return self.apply_custom_selection(candidates)

    def apply_custom_selection(self, candidates):
        # Custom selection algorithm
        return min(candidates, key=lambda c: c.latency)
```

### 2. Custom Health Checks

```python
@mesh.tool(
    capability="database_service",
    health_check=custom_db_health_check
)
def query_database():
    pass

async def custom_db_health_check():
    try:
        await db.execute("SELECT 1")
        return {"status": "healthy", "connections": db.pool.size}
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}
```

### 3. Custom Load Balancing

```python
class WeightedLoadBalancer(LoadBalancer):
    def select_provider(self, providers, request_context):
        # Weighted selection based on capacity
        weights = [p.metadata.get('capacity', 1) for p in providers]
        return random.choices(providers, weights=weights)[0]
```

## Future Architecture Considerations

### Planned Enhancements

1. **Multi-Registry Federation**: Cross-cluster service discovery
2. **Circuit Breakers**: Automatic failure isolation
3. **Request Tracing**: Distributed tracing integration
4. **Metrics Collection**: Prometheus/OpenTelemetry integration
5. **Configuration Management**: Dynamic configuration updates
6. **Plugin System**: Custom middleware and extensions

### Scalability Roadmap

1. **Registry Clustering**: Multi-node registry for high availability
2. **Capability Caching**: Local capability caches for faster resolution
3. **Connection Pooling**: Efficient connection reuse between agents
4. **Batch Operations**: Bulk capability updates and queries

### Performance Optimizations

1. **gRPC Support**: Binary protocol for high-throughput scenarios
2. **Compression**: Message compression for large payloads
3. **Streaming**: Bidirectional streaming for real-time scenarios
4. **Edge Caching**: CDN-like caching for static capabilities

---

This architecture enables MCP Mesh to provide a seamless, scalable, and developer-friendly service orchestration platform that preserves the simplicity of FastMCP while adding powerful distributed system capabilities.

The design emphasizes **developer experience**, **operational simplicity**, and **runtime performance** - making it easy to build complex distributed systems without sacrificing the rapid development cycle that makes MCP attractive.
