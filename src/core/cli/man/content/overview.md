# MCP Mesh Architecture

> Enterprise-grade distributed service mesh for MCP agents with zero-boilerplate dependency injection

## Overview

MCP Mesh is a distributed service mesh that enables MCP (Model Context Protocol) agents to discover each other, share capabilities, and collaborate through automatic dependency injection. The system follows a "background coordination" philosophy where agents operate autonomously while the registry facilitates discovery.

## Core Philosophy

- **Agents are autonomous**: Each agent runs independently and communicates directly with other agents
- **Registry is a facilitator**: The registry helps agents find each other but doesn't proxy communication
- **Graceful degradation**: If a dependency is unavailable, agents continue operating with reduced functionality
- **Zero boilerplate**: Decorators handle all the complex wiring automatically

## Key Components

### 1. Registry

The central coordination service that:

- Accepts agent registrations via heartbeat
- Stores capability metadata in database (SQLite or PostgreSQL)
- Resolves dependencies when agents request them
- Monitors agent health and marks unhealthy agents
- Never calls agents directly - agents always initiate communication

### 2. Agents

Python services decorated with `@mesh.agent` that:

- Register capabilities with the registry on startup
- Send periodic heartbeats to maintain registration
- Receive dependency topology from registry
- Communicate directly with other agents via FastMCP

### 3. Capabilities

Named services that agents provide:

- Identified by capability name (e.g., "date_service", "weather_data")
- Can have multiple implementations with different tags
- Resolved by registry based on name, tags, and version constraints

### 4. Dependencies

Capabilities that an agent needs from other agents:

- Declared in `@mesh.tool` decorator via `dependencies` parameter
- Automatically injected as callable proxies at runtime
- Gracefully handle unavailability (injected as `None`)

## Communication Flow

```
┌─────────┐     Heartbeat/Register     ┌──────────┐
│  Agent  │ ─────────────────────────► │ Registry │
│    A    │ ◄───────────────────────── │          │
└─────────┘   Topology (dependencies)  └──────────┘
     │
     │ Direct MCP Call (tool invocation)
     ▼
┌─────────┐
│  Agent  │
│    B    │
└─────────┘
```

## Heartbeat System

MCP Mesh uses a dual-heartbeat system for fast topology detection:

- **HEAD requests** every ~5 seconds (lightweight, ~200 bytes)
- **POST requests** when topology changes (full registration, ~2KB)
- Registry detects failures in sub-20 seconds (4 missed heartbeats)

## See Also

- `meshctl man capabilities` - Capabilities system details
- `meshctl man dependency-injection` - How DI works
- `meshctl man health` - Health monitoring and auto-rewiring
- `meshctl man registry` - Registry operations
