# Architecture & Design

> Core architecture, agent coordination, and design philosophy

## Overview

MCP Mesh is a distributed service mesh for MCP (Model Context Protocol) agents. It provides:

- **Zero-boilerplate dependency injection** between agents
- **Automatic service discovery** via a central registry
- **Smart routing** with tag-based selection
- **Health monitoring** with heartbeat and topology updates

```mermaid
graph TB
    subgraph "MCP Mesh"
        R[Registry]
        A1[Agent 1]
        A2[Agent 2]
        A3[Agent 3]
    end

    A1 -->|register| R
    A2 -->|register| R
    A3 -->|register| R
    R -->|discover| A1
    A1 -->|call| A2
    A2 -->|call| A3
```

## Core Components

### Registry

The registry is the central coordination point:

- **Agent registration** - Agents register on startup
- **Capability tracking** - Tracks what each agent provides
- **Dependency resolution** - Resolves capability dependencies
- **Health monitoring** - Tracks agent health via heartbeats

### Agents

Agents are the workhorses of the mesh:

- **Capabilities** - Named services they provide
- **Dependencies** - Capabilities they consume
- **Tags** - Metadata for smart selection
- **Health checks** - Regular heartbeat to registry

### Proxies

Proxies handle inter-agent communication:

- **SelfDependencyProxy** - Same agent (direct call, no network overhead)
- **EnhancedUnifiedMCPProxy** - Cross-agent calls (auto-configured from decorator kwargs)

## Communication Flow

```mermaid
sequenceDiagram
    participant C as Consumer Agent
    participant R as Registry
    participant P as Provider Agent

    C->>R: 1. Register (capabilities, dependencies)
    P->>R: 2. Register (capabilities)
    R->>R: 3. Resolve dependencies
    R->>C: 4. Inject proxy for dependency
    C->>P: 5. Call via proxy
    P->>C: 6. Return result
```

## Dependency Injection

MCP Mesh uses **automatic dependency injection** based on capability names:

1. **Declaration**: Agent declares dependencies
2. **Discovery**: Registry finds matching providers
3. **Injection**: Proxy injected at function call time
4. **Routing**: Calls route through the mesh

```python
# Declaration
@mesh.tool(dependencies=["database"])
async def my_function(database=None):
    # database is automatically injected!
    result = await database(query="SELECT *")
```

## Service Discovery

### Capability-Based

Agents find each other by capability name:

```python
# Provider
@mesh.tool(capability="user_service")
def get_user(): pass

# Consumer
@mesh.tool(dependencies=["user_service"])
def my_function(user_service=None): pass
```

### Tag-Based Selection

When multiple providers exist, tags determine selection:

```python
# Multiple providers
@mesh.tool(capability="llm", tags=["claude", "opus"])
@mesh.tool(capability="llm", tags=["claude", "haiku"])

# Consumer selects
@mesh.tool(dependencies=[{"capability": "llm", "tags": ["+opus"]}])
```

## Health & Topology

### Heartbeat System

Agents send regular heartbeats to the registry:

```
Agent → Registry: heartbeat (every 30s default)
Registry: Update agent status, TTL
```

### Topology Updates

When agents join/leave, the registry updates topology:

1. New agent registers → Notify dependent agents
2. Agent disconnects → Mark unhealthy, reroute
3. Agent recovers → Restore routing

## Deployment Patterns

### Local Development

```mermaid
graph TD
    subgraph L_DM["Developer Machine"]
        L_A1[Agent 1] --> L_R[Registry]
        L_A2[Agent 2] --> L_R
    end
```

### Docker Compose

```mermaid
graph TD
    subgraph D_DN["Docker Network"]
        D_A1[agent-1] --> D_R[registry]
        D_A2[agent-2] --> D_R
    end
```

### Kubernetes

```mermaid
graph TD
    subgraph K_KC["Kubernetes Cluster"]
        K_A1["Agent Pod (replicas)"] --> K_R[Registry Service]
        K_A2["Agent Pod (replicas)"] --> K_R
    end
```

## Design Principles

### 1. Zero Boilerplate

No manual wiring, no service locators:

```python
# Just declare, mesh handles the rest
@mesh.tool(dependencies=["service"])
def my_function(service=None):
    return service()
```

### 2. Graceful Degradation

Always handle missing dependencies:

```python
if service is None:
    return "Fallback response"
```

### 3. Protocol Agnostic

Built on MCP, works with any MCP-compatible client.

### 4. Cloud Native

Designed for containers and Kubernetes.

## See Also

- [Registry](registry.md) - Registry details
- [Health & Discovery](health-discovery.md) - Health system
- [Tag Matching](tag-matching.md) - Selection algorithm
