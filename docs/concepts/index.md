---
title: Concepts
description: Architecture, runtime model, and design rationale behind MCP Mesh
---

# Concepts

The Concepts section explains *why* MCP Mesh works the way it does — the
structural primitives, the runtime model, and the design tradeoffs behind
features like DDDI, tag matching, and the registry. It is reference-shaped: you
look up a concept when you need to understand a behavior, not when you need to
remember a function signature.

Use it alongside the other sections:

- [**Tutorial**](../tutorial/index.md) walks you through building a real
  multi-agent application from scratch.
- [**Reference**](../reference/index.md) covers exact API signatures, CLI
  flags, and environment variables you look up while writing code.
- The **Python SDK**, **Java SDK**, and **TypeScript SDK** sections in the top
  nav are the language-specific deep references.

Concepts is what you reach for when something works (or doesn't) and you want
to understand the mechanism behind it.

## Sections

<div class="grid cards" markdown>

-   :material-sitemap:{ .lg .middle } **Architecture core**

    ***

    The framework's structural primitives — how agents, the registry, and
    dependency injection compose into a mesh.

    - [Architecture & Design](architecture.md)
    - [DDDI: Distributed Dynamic Dependency Injection](dddi.md)
    - [Registry](registry.md)

-   :material-lan-connect:{ .lg .middle } **Discovery & matching**

    ***

    How the mesh wires agents together at runtime — heartbeats, capability
    resolution, and the matching rules that pick a provider.

    - [Health & Discovery](health-discovery.md)
    - [Tag Matching](tag-matching.md)
    - [Schema Matching](schema-matching.md)

-   :material-transit-connection-variant:{ .lg .middle } **Runtime surfaces**

    ***

    How data flows once agents are wired — streaming responses, long-running
    jobs with event injection, and the audit trail that records every call.

    - [Streaming](streaming.md)
    - [Long-Running Jobs](jobs.md)
    - [Audit Trail](audit.md)

-   :material-database-cog:{ .lg .middle } **Stateful patterns**

    ***

    Agents that hold state across calls — the session model and the in-process
    escape hatch for code that can't be made stateless.

    - [Stateful Agents](stateful-agents.md)
    - [In-Process State (Escape Hatch)](in-process-state.md)

</div>

## See also

- [Tutorial](../tutorial/index.md) — guided build of a multi-agent application.
- [Reference](../reference/index.md) — API signatures, CLI flags, env vars.
- [Python SDK](../python/index.md) — decorators, dependency injection, LLM
  integration, FastAPI wiring.
- [Java SDK](../java/index.md) — Spring Boot annotations and integration.
- [TypeScript SDK](../typescript/index.md) — mesh functions and Express wiring.
