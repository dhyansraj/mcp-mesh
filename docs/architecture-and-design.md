# MCP Mesh Architecture and Design

> Understanding the core architecture, design principles, and usage patterns of MCP Mesh

## Overview

MCP Mesh is a distributed service orchestration framework built on top of the Model Context Protocol (MCP) that enables seamless dependency injection, service discovery, and inter-service communication. The architecture combines familiar FastMCP development patterns with powerful mesh orchestration capabilities.

## Core Architecture

### High-Level Components

```
┌─────────────────────────────────────────────────────────────────┐
│                        MCP Mesh Ecosystem                       │
├─────────────────────────────────────────────────────────────────┤
│              ┌───────────────────────────────────┐              │
│              │           Redis                   │              │
│              │      (Session Storage)            │              │
│              │   session:* keys for stickiness   │              │
│              └─────────────┬─────────────────────┘              │
│                            │                                    │
│         ┌──────────────────┼──────────────────┐                 │
│         │                  │                  │                 │
│         ▼                  ▼                  ▼                 │
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
│  Direct MCP JSON-RPC calls between FastMCP servers              │
│  ◄──────────────────────────────────────────────────────────►   │
│  Registry for discovery, Redis for session stickiness           │
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

#### 4. **Redis (Session Storage)**

- **Session Affinity**: Maps session IDs to pod IPs for stateful operations
- **Distributed State**: Enables session stickiness across multiple pod replicas
- **Graceful Fallback**: Agents fall back to in-memory storage if Redis unavailable
- **TTL Management**: Automatic session cleanup and expiration

### Key Insight: Background Orchestration

**MCP Mesh operates as background infrastructure:**

- **Discovery Phase**: Registry helps agents find each other during startup
- **Runtime Phase**: Direct FastMCP-to-FastMCP communication (no proxy)
- **Monitoring Phase**: Continuous health checks and capability updates in background

## Design Principles

### 1. **True Resilient Architecture**

MCP Mesh implements a fundamentally resilient architecture where agents operate independently and enhance each other when available:

**Core Resilience Principles:**

- **Standalone Operation**: Agents function as vanilla FastMCP servers without any dependencies
- **Registry as Facilitator**: Registry enables discovery and wiring, but agents don't depend on it
- **Dynamic Enhancement**: Agents get enhanced capabilities when other agents are available
- **Graceful Degradation**: Loss of registry or other agents doesn't break existing functionality
- **Self-Healing**: Agents automatically reconnect and refresh when components return

**Architecture Flow:**

```
Agent Startup → Works Standalone (FastMCP mode)
       ↓
Registry Available → Agents Get Wired → Enhanced Capabilities
       ↓
Registry Down → Agents Continue Working → Direct MCP Communication Preserved
       ↓
Registry Returns → Agents Refresh → Topology Updates Resume
```

### 2. **Dual Decorator Pattern**

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

**Benefits:**

- **Familiar Development**: Developers keep using FastMCP patterns
- **Enhanced Capabilities**: Mesh adds dependency injection seamlessly
- **Zero Boilerplate**: No manual server management or configuration
- **Gradual Adoption**: Can add mesh features incrementally

### 3. **Enhanced Proxy System**

MCP Mesh v0.3+ introduces automatic proxy configuration from decorator kwargs:

```python
@mesh.tool(
    capability="enhanced_service",
    timeout=60,                    # Auto-configures proxy timeout
    retry_count=3,                 # Auto-configures retry policy
    streaming=True,                # Auto-selects streaming proxy
    auth_required=True             # Auto-enables authentication
)
def enhanced_tool():
    pass
```

**Proxy Types:**

- **EnhancedMCPClientProxy**: Timeout, retry, auth auto-configuration
- **EnhancedFullMCPProxy**: Streaming auto-selection + session management
- **Standard Proxies**: Backward compatibility for simple tools

_Implementation: See `src/runtime/python/_mcp_mesh/engine/` for proxy classes_

### 4. **Session Management and Stickiness**

For stateful operations, MCP Mesh provides automatic session affinity:

```python
@mesh.tool(
    capability="stateful_counter",
    session_required=True,         # Enables session stickiness
    stateful=True,                 # Marks as stateful operation
    auto_session_management=True   # Automatic session lifecycle
)
def increment_counter(session_id: str, increment: int = 1):
    # Automatically routed to same pod for this session
```

**Session Features:**

- **Redis-Backed Storage**: Distributed session affinity across pods
- **Automatic Routing**: Requests with same session_id go to same pod
- **Graceful Fallback**: In-memory storage when Redis unavailable
- **TTL Management**: Automatic session cleanup

_Implementation: See `src/runtime/python/_mcp_mesh/engine/http_wrapper.py`_

### 5. **Fast Heartbeat Architecture**

Optimized health monitoring with dual-heartbeat system:

```python
HEAD /heartbeat    # Lightweight timestamp update (5s intervals)
POST /heartbeat    # Full registration when triggered by HEAD response
```

**Benefits:**

- **Fast Failure Detection**: Sub-20s failure detection
- **Network Efficiency**: Minimal bandwidth usage
- **On-Demand Registration**: Full updates only when needed

_Implementation: See `cmd/registry/` for heartbeat handling_

## Implementation Architecture

### Two-Pipeline Design

MCP Mesh uses a sophisticated two-pipeline architecture that separates initialization from runtime operations:

#### Startup Pipeline (One-time Execution)

```
DecoratorCollectionStep → ConfigurationStep → HeartbeatPreparationStep →
FastMCPServerDiscoveryStep → HeartbeatLoopStep → FastAPIServerSetupStep
```

**Purpose**: Initialize agent, collect decorators, prepare for mesh integration
**Trigger**: Agent startup, decorator debounce completion
**Outcome**: Agent ready with capabilities registered and dependency injection configured

_Implementation: See `src/runtime/python/_mcp_mesh/pipeline/startup/`_

#### Heartbeat Pipeline (Continuous Loop)

```
RegistryConnectionStep → HeartbeatSendStep → DependencyResolutionStep
```

**Purpose**: Maintain mesh connectivity, update dependency topology
**Trigger**: Periodic execution (30s intervals)
**Outcome**: Updated dependency proxies, health status maintained

_Implementation: See `src/runtime/python/_mcp_mesh/pipeline/heartbeat/`_

### Decorator Processing and Debounce Coordination

**Challenge**: Decorators are processed as Python imports the module, but we need to wait for all decorators before starting mesh processing.

**Solution**: Debounce coordinator with configurable delay

```python
@mesh.tool()  # Triggers debounce timer
def tool1(): pass

@mesh.tool()  # Resets debounce timer
def tool2(): pass

# After MCP_MESH_DEBOUNCE_DELAY (default 1.0s) with no new decorators:
# → Startup pipeline begins
```

**Design Benefits**:

- Handles dynamic decorator registration during import
- Prevents race conditions in multi-decorator modules
- Configurable timing via `MCP_MESH_DEBOUNCE_DELAY`

_Implementation: See `src/runtime/python/_mcp_mesh/engine/debounce_coordinator.py`_

### Dependency Resolution and Proxy Architecture

#### Function Caching Strategy

**Key Insight**: Mesh decorators must process BEFORE FastMCP decorators to cache original functions.

```python
@mesh.tool()  # ← Processes first, caches original function
@app.tool()   # ← FastMCP processes wrapped function
def hello(): pass
```

**Implementation**:

1. Mesh decorator caches `func._mesh_original_func = func`
2. Creates dependency injection wrapper
3. FastMCP receives wrapper (not original)
4. Runtime calls cached original with injected dependencies

#### Proxy Selection Logic

**Registry-Driven**: Heartbeat response determines proxy type based on dependency location and configuration.

```python
if current_agent_id == target_agent_id:
    # Same agent - direct local call
    proxy = SelfDependencyProxy(original_func, function_name)
else:
    # Different agent - MCP JSON-RPC call
    if has_enhanced_config:
        proxy = EnhancedMCPClientProxy(endpoint, func_name, kwargs_config)
    else:
        proxy = MCPClientProxy(endpoint, func_name)
```

**Enhanced Proxy Auto-Selection**:

- `streaming=True` → `EnhancedFullMCPProxy`
- `session_required=True` → `EnhancedFullMCPProxy` with session management
- Custom timeout/retry → `EnhancedMCPClientProxy`
- Simple tools → Standard `MCPClientProxy`

_Implementation: See `src/runtime/python/_mcp_mesh/pipeline/heartbeat/dependency_resolution.py`_

### Hash-Based Change Detection

**Performance Optimization**: Only update dependency injection when topology actually changes.

```python
def _hash_dependency_state(dependency_state):
    state_str = json.dumps(dependency_state, sort_keys=True)
    return hashlib.sha256(state_str.encode()).hexdigest()

# In heartbeat pipeline:
current_hash = _hash_dependency_state(response.dependencies)
if current_hash == _last_dependency_hash:
    return  # Skip expensive dependency injection update
```

**Benefits**:

- Eliminates unnecessary proxy recreation
- Reduces CPU overhead in stable topologies
- Enables high-frequency heartbeats without performance penalty

### Registry as Facilitator Pattern

**Design Philosophy**: Registry coordinates but never controls agent execution.

**Registry Responsibilities**:

- Accept agent registrations via heartbeat
- Store capability metadata in SQLite
- Resolve dependencies and return topology
- Monitor health and mark unhealthy agents
- Generate audit events

**What Registry NEVER Does**:

- Make calls to agents (only agents call registry)
- Control agent lifecycle
- Proxy or intercept agent-to-agent communication
- Store business logic or state

**Agent Autonomy**: Agents poll registry for updates but operate independently. Registry failure doesn't break existing agent-to-agent connections.

_Implementation: See `cmd/registry/` for Go registry service_

## Usage Patterns

### Basic Agent Development

**1. Simple Tool Creation:**

```python
from fastmcp import FastMCP
import mesh

app = FastMCP("My Service")

@app.tool()
@mesh.tool(capability="greeting")
def say_hello(name: str) -> str:
    return f"Hello, {name}!"

@mesh.agent(name="greeting-service")
class GreetingAgent:
    pass
```

**2. With Dependencies:**

```python
@app.tool()
@mesh.tool(
    capability="time_greeting",
    dependencies=["time_service"]
)
def time_greeting(name: str, time_service=None) -> str:
    current_time = time_service() if time_service else "unknown time"
    return f"Hello, {name}! Current time: {current_time}"
```

### Enhanced Configuration

**3. Production-Ready Tool:**

```python
@app.tool()
@mesh.tool(
    capability="secure_data_processor",
    timeout=120,                           # 2 min timeout
    retry_count=3,                         # Retry on failure
    auth_required=True,                    # Require authentication
    custom_headers={"X-Service": "data"},  # Custom headers
    streaming=True                         # Enable streaming
)
async def process_large_dataset(data_url: str):
    # Auto-configured with enhanced proxy features
```

**4. Stateful Operations:**

```python
@app.tool()
@mesh.tool(
    capability="user_session",
    session_required=True,        # Enable session stickiness
    stateful=True,               # Mark as stateful
    timeout=30
)
def update_user_state(session_id: str, updates: dict):
    # Automatically routed to same pod for session consistency
```

### Deployment Patterns

**Local Development:**

```bash
# Terminal 1: Start registry
meshctl registry start

# Terminal 2: Start your agent
python my_agent.py
```

**Docker Compose:**

```yaml
version: "3.8"
services:
  registry:
    image: mcpmesh/registry:latest
    ports: ["8000:8000"]

  my-service:
    build: .
    environment:
      MCP_MESH_REGISTRY_URL: http://registry:8000
    depends_on: [registry]
```

**Kubernetes:**

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: my-service
spec:
  replicas: 3
  template:
    spec:
      containers:
        - name: agent
          image: my-service:latest
          env:
            - name: MCP_MESH_REGISTRY_URL
              value: "http://mcp-registry:8000"
            - name: REDIS_URL
              value: "redis://redis:6379" # For session storage
```

## Performance Characteristics

### Scalability Metrics

- **Registry**: 1000+ agents, 10,000+ capabilities, 100+ heartbeats/sec
- **Agent**: 1000+ tool calls/sec, <2s startup time
- **Discovery**: <10ms lookup time, <1s update propagation

### Network Overhead

- **HEAD Heartbeat**: ~200B per agent every 5 seconds
- **POST Heartbeat**: ~2KB per agent when topology changes
- **Tool Calls**: Standard MCP JSON-RPC (varies by payload)

_See `docs/performance/` for detailed benchmarks_

## Security Model

### Current Architecture

- **Trusted Network Model**: Assumes secure network environment
- **Service-to-Service**: Direct HTTP communication between agents
- **No Built-in Auth**: Authentication via proxy configuration

### Production Recommendations

1. **Network Segmentation**: Use private networks or VPNs
2. **Service Mesh**: Deploy with Istio/Linkerd for mTLS
3. **API Gateway**: Use gateway for external access control
4. **Enhanced Proxies**: Use `auth_required=True` with bearer tokens

_See `docs/security/` for detailed security guidance_

## Recent Enhancements (v0.3.x)

1. **✅ Redis Session Storage**: Distributed session affinity with Redis backend
2. **✅ Enhanced Proxy System**: Kwargs-based auto-configuration for proxies
3. **✅ Automatic Session Management**: Built-in session lifecycle management
4. **✅ HTTP Wrapper Improvements**: Session routing middleware and port resolution
5. **✅ Streaming Auto-Selection**: Automatic routing based on tool capabilities
6. **✅ Authentication Integration**: Bearer token support for enhanced proxies

## Extension Points

### Custom Dependency Resolvers

```python
class CustomDependencyResolver(DependencyResolver):
    async def resolve_capability(self, capability_spec):
        # Custom logic for finding capabilities
        candidates = await super().find_candidates(capability_spec)
        return self.apply_custom_selection(candidates)
```

### Custom Health Checks

```python
@mesh.tool(health_check=custom_health_check)
def database_tool():
    pass

async def custom_health_check():
    return {"status": "healthy", "connections": db.pool.size}
```

_See `src/runtime/python/_mcp_mesh/` for extension interfaces_

## Future Roadmap

### Planned Features

1. **Multi-Registry Federation**: Cross-cluster service discovery
2. **Circuit Breakers**: Automatic failure isolation
3. **Request Tracing**: Distributed tracing integration
4. **Metrics Collection**: Prometheus/OpenTelemetry integration
5. **Configuration Management**: Dynamic configuration updates

### Performance Optimizations

1. **gRPC Support**: Binary protocol for high-throughput scenarios
2. **Connection Pooling**: Efficient connection reuse between agents
3. **Edge Caching**: CDN-like caching for static capabilities

---

This architecture enables MCP Mesh to provide a seamless, scalable, and developer-friendly service orchestration platform that preserves the simplicity of FastMCP while adding powerful distributed system capabilities.

**For Implementation Details**: See source code in `src/runtime/python/_mcp_mesh/` and `cmd/registry/`
**For Examples**: See `examples/` directory for complete working examples
**For Performance**: See `docs/performance/` for benchmarks and optimization guides
