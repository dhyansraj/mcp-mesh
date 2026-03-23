---
title: "Distributed Dynamic Dependency Injection (DDDI)"
description: "DDDI is the core innovation of MCP Mesh — dependencies between agents are discovered, resolved, and injected at runtime across distributed systems."
---

# Distributed Dynamic Dependency Injection (DDDI)

> The core innovation of MCP Mesh — dependencies are discovered, injected, and updated at runtime across machines, languages, and clouds.

## What is DDDI?

**Distributed Dynamic Dependency Injection (DDDI)** is a term coined by the MCP Mesh project to describe a new approach to service composition in distributed AI agent systems.

Traditional dependency injection (Spring, Guice, Angular) wires dependencies at compile time or application startup on a single machine. DDDI is fundamentally different:

| Aspect | Traditional DI | DDDI (MCP Mesh) |
| --- | --- | --- |
| **When** | Compile/startup time | Runtime (continuous) |
| **Where** | Single process/machine | Across machines, clouds, runtimes |
| **Discovery** | Configuration files | Automatic via registry |
| **Updates** | Requires restart | Hot-swappable (no restart) |
| **Languages** | Single language | Cross-language (Python, TypeScript, Java) |
| **Protocol** | In-process calls | MCP (Model Context Protocol) |
| **Failure** | Application crashes | Graceful degradation |

## The Four Pillars of DDDI

### 1. Distributed

Dependencies span machines, containers, clouds, and language runtimes. A Python agent can depend on a Java service and a TypeScript tool — all wired automatically.

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│ Python Agent │────>│ Java Service │────>│  TS Tool     │
│ (Cloud A)    │     │ (Cloud B)    │     │ (Edge)       │
└──────────────┘     └──────────────┘     └──────────────┘
        All dependencies injected automatically via DDDI
```

### 2. Dynamic

Services are discovered and injected at **runtime**, not at startup. When a new agent joins the mesh, existing agents automatically discover it and receive updated dependency proxies — without any configuration change or restart.

### 3. Discovery-Driven

DDDI uses **capability-based discovery** with tag matching, not hardcoded service names:

=== "Python"

    ```python
    @mesh.tool(
        capability="greeting",
        dependencies=["calculator"],  # capability name, not service URL
    )
    async def greet(calculator: mesh.McpMeshTool = None):
        result = await calculator({"expression": "2+2"})
        return f"The answer is {result}"
    ```

=== "TypeScript"

    ```typescript
    agent.addTool({
      name: "greet",
      capability: "greeting",
      dependencies: ["calculator"],
      execute: async (args, { calculator }) => {
        const result = await calculator({ expression: "2+2" });
        return `The answer is ${result}`;
      },
    });
    ```

=== "Java"

    ```java
    @MeshTool(
        capability = "greeting",
        dependencies = @Selector(capability = "calculator")
    )
    public String greet(
        @Param("name") String name,
        McpMeshTool<String> calculator
    ) {
        String result = calculator.call(Map.of("expression", "2+2"));
        return "The answer is " + result;
    }
    ```

You declare **what** you need (a capability), not **where** it lives. The mesh finds it.

### 4. Injection

Dependencies are injected as **proxy objects** that transparently handle:

- Network communication (MCP protocol over HTTP)
- Serialization and deserialization
- Retry and failover
- Load balancing across multiple providers
- Health-aware routing (skip unhealthy instances)

The developer writes a function with typed parameters. The mesh fills them in.

## How DDDI Works in MCP Mesh

### Registration Phase

```
Agent starts --> Registers capabilities with Registry
                (name, capability, tags, version, endpoint)
```

### Resolution Phase

```
Agent declares dependency "calculator"
    --> Registry finds all agents with capability "calculator"
    --> Tag matching scores candidates (+preferred, -excluded)
    --> Best match selected (or load balanced)
    --> Proxy object created and injected
```

### Heartbeat Phase

```
Every 5 seconds:
    Agent --> HEAD /health --> Registry
    Registry responds:
        200 = no changes
        203 = topology changed --> agent re-registers --> dependencies re-resolved
```

### Hot-Swap Phase

```
New "calculator" agent joins mesh
    --> Registry detects topology change
    --> Existing agents get 203 on next heartbeat
    --> Dependencies re-resolved automatically
    --> New proxy injected -- zero downtime
```

## DDDI vs Traditional DI Frameworks

### Spring Framework (Java)

Spring DI wires beans at application startup via `@Autowired`. All beans must be in the same JVM. If a dependency fails, the application crashes.

**DDDI difference**: Dependencies span JVMs, machines, and languages. If a dependency fails, the agent continues with graceful degradation.

### Angular (TypeScript)

Angular DI is compile-time, single-process, and browser-only. Providers are registered in modules and resolved at component creation.

**DDDI difference**: Dependencies are resolved at runtime across distributed services, not at module compilation.

### Google Guice (Java)

Guice uses runtime binding but within a single JVM. Modules define bindings statically.

**DDDI difference**: Bindings are dynamic and cross-machine. No module configuration — capabilities are discovered automatically.

### Comparison Summary

| Feature | Spring | Angular | Guice | **DDDI** |
| --- | --- | --- | --- | --- |
| Cross-machine | No | No | No | **Yes** |
| Cross-language | No | No | No | **Yes** |
| Runtime discovery | No | No | Partial | **Yes** |
| Hot-swap | No | No | No | **Yes** |
| Graceful degradation | No | No | No | **Yes** |
| Protocol | In-process | In-process | In-process | **MCP/HTTP** |

## DDDI for AI Agents

Multi-agent AI systems have unique requirements that traditional DI cannot handle:

1. **Heterogeneous runtimes** — Python for ML models, Java for enterprise integration, TypeScript for web interfaces
2. **Dynamic composition** — Agents join and leave based on demand, scaling, or deployment
3. **LLM as a dependency** — LLM providers are injected like any other service, with capability matching for model selection
4. **Tool discovery** — LLM agents discover available tools at runtime and select them based on capability and tags
5. **Fault tolerance** — If an agent crashes, others continue working with degraded functionality rather than cascading failure

DDDI makes these scenarios work with zero configuration:

```python
# This agent automatically discovers:
# - An LLM provider matching tags ["+claude"]
# - All tools matching tags ["data", "tools"]
# No URLs, no config files, no restart when topology changes.

@mesh.llm(
    provider={"capability": "llm", "tags": ["+claude"]},
    filter=[{"tags": ["data", "tools"]}],
)
@mesh.tool(capability="analyst")
async def analyze(query: str, llm: mesh.MeshLlmAgent = None) -> str:
    return await llm(f"Analyze: {query}")
```

## Real-World Scenario

### Agent Lifecycle with DDDI

1. **Calculator agent starts** -- Registers capability `calculator` with registry
2. **Analyst agent starts** -- Declares dependency on `calculator` -- DDDI injects proxy
3. **Analyst calls calculator** -- Proxy handles MCP communication transparently
4. **Calculator crashes** -- Analyst detects failure, continues with graceful degradation
5. **Calculator restarts** -- Registry detects, analyst gets 203 heartbeat -- proxy re-injected
6. **Second calculator starts** -- DDDI load-balances between both instances
7. **Calculator v2 deployed** -- Version-aware routing sends traffic to v2

All of this happens **without any configuration changes or restarts** to the analyst agent.

## DDDI Design Principles

### Declare Intent, Not Location

Agents declare **what** they need ("a calculator capability") not **where** to find it ("http://calculator:8080"). The registry resolves intent to location at runtime.

### Injection is Continuous

Unlike traditional DI where injection happens once at startup, DDDI continuously monitors the mesh topology. When a better provider appears or a current one fails, proxies are transparently re-wired.

### Graceful Degradation Over Hard Failure

When a dependency is unavailable, DDDI injects `None` (Python), `null` (TypeScript/Java) instead of throwing an exception. Agents are designed to check availability and provide fallback behavior.

### Protocol-Agnostic Proxies

Injected proxies abstract away the communication protocol. Today they use MCP over HTTP; tomorrow they could use gRPC or WebSockets without any changes to agent code.

## Terminology Quick Reference

| Term | Definition |
| --- | --- |
| **DDDI** | Distributed Dynamic Dependency Injection — the overall pattern |
| **Capability** | A named function or service an agent provides (e.g., `calculator`) |
| **Dependency** | A capability that an agent needs from another agent |
| **Proxy** | An injected object that transparently calls the remote agent |
| **Tag** | A label for filtering and scoring capability matches |
| **Registry** | The central service that tracks all agents and their capabilities |
| **Heartbeat** | Periodic health check that also detects topology changes |
| **Hot-swap** | Replacing a dependency provider without restarting the consumer |
| **Topology** | The current set of agents, capabilities, and connections in the mesh |

## Learn More

- [Dependency Injection (Python)](../python/dependency-injection.md) — DDDI in action with Python decorators
- [Dependency Injection (TypeScript)](../typescript/dependency-injection.md) — DDDI with mesh functions
- [Dependency Injection (Java)](../java/dependency-injection.md) — DDDI with Spring Boot annotations
- [Architecture & Design](architecture.md) — How the registry and heartbeat system power DDDI
- [Health & Discovery](health-discovery.md) — The heartbeat protocol behind hot-swappable dependencies
- [Tag Matching](tag-matching.md) — How capability and tag scoring drives dependency resolution
