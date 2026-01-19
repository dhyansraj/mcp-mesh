# MCP Mesh Architecture and Design

> Understanding the core architecture, design principles, and usage patterns of MCP Mesh

## Overview

MCP Mesh is a distributed service orchestration framework built on top of the Model Context Protocol (MCP) that enables seamless dependency injection, service discovery, and inter-service communication. The architecture combines familiar FastMCP development patterns with powerful mesh orchestration capabilities.

## Glossary

Key terms used throughout MCP Mesh documentation:

| Term                             | Definition                                                                                                                                                                                                                                                                                 |
| -------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **Agent**                        | A Python or TypeScript application that registers with the mesh and provides one or more tools. Each agent runs as an independent service.                                                                                                                                                 |
| **Tool**                         | A function decorated with `@app.tool()` and `@mesh.tool()` (Python) or registered with `agent.addTool()` (TypeScript) that can be discovered and called by other agents. Tools are the building blocks of MCP Mesh.                                                                        |
| **Capability**                   | A unique identifier (string) that describes what a tool provides. Other tools declare dependencies on capabilities, not specific agents. Example: `"redis_store_memory"`, `"analyze_emotion"`.                                                                                             |
| **Dependency**                   | A capability that a tool requires. MCP Mesh automatically discovers and injects dependencies at runtime.                                                                                                                                                                                   |
| **Registry**                     | The central service that tracks all agents, their capabilities, and health status. Agents register on startup and send periodic heartbeats. **Important:** The registry is a _facilitator_, not a proxy—it helps agents find each other, but actual tool calls go directly between agents. |
| **Heartbeat**                    | Periodic signal sent by agents to the registry to indicate they're alive. Default interval is 15 seconds.                                                                                                                                                                                  |
| **Proxy**                        | An injected object (`McpMeshTool`) that transparently handles communication with remote tools. You call it like a function; MCP Mesh handles the rest.                                                                                                                                    |
| **Tag**                          | Metadata attached to tools for filtering during dependency resolution. Supports `+` (prefer) and `-` (avoid) operators.                                                                                                                                                                    |
| **MCP (Model Context Protocol)** | The underlying protocol used for tool communication. MCP Mesh tools are standard MCP tools and can be invoked via HTTP using MCP's `tools/list` and `tools/call` endpoints.                                                                                                                |

### About FastMCP

MCP Mesh uses [FastMCP](https://github.com/jlowin/fastmcp) under the hood to handle MCP protocol details. You don't need to learn FastMCP separately—just use the `@app.tool()` decorator to define tools and MCP Mesh handles everything else.

**What FastMCP provides (handled automatically):**

- MCP protocol serialization/deserialization
- HTTP server for tool endpoints
- Tool schema generation from Python type hints

**What MCP Mesh adds:**

- Service discovery and registration
- Automatic dependency injection
- Health monitoring and heartbeats
- LLM integration (`@mesh.llm`)
- Multi-agent orchestration

**MCP Compatibility:**

MCP Mesh tools are standard MCP tools. They can be invoked using the meshctl CLI or any MCP client:

```bash
# List registered agents
meshctl list

# Call a tool (discovers agent via registry)
meshctl call my_tool '{"param":"value"}'

# Call with explicit agent
meshctl call my-agent:my_tool '{"param":"value"}'
```

<details>
<summary>Using curl directly (JSON-RPC)</summary>

```bash
# List available tools
curl -s -X POST http://localhost:8080/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'

# Call a tool
curl -s -X POST http://localhost:8080/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"my_tool","arguments":{"param":"value"}}}'
```

</details>

---

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
│                  │ │SQLite/  │ │                                │
│                  │ │Postgres │ │                                │
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

#### 1. **Agents (Python & TypeScript Runtime)**

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

## MCP Mesh Agents and Tools

MCP Mesh agents are simple Python or TypeScript applications that define one or more MCP tools. While tools communicate via the MCP protocol, all networking and communication complexity is abstracted away by MCP Mesh.

### What is an MCP Mesh Agent?

An agent is a Python or TypeScript application that:

1. Creates a FastMCP server
2. Wraps it with mesh capabilities
3. Defines tools with capabilities and dependencies

=== "Python"

    ```python
    import mesh
    from fastmcp import FastMCP

    app = FastMCP("My Agent")

    @app.tool()           # FastMCP decorator - defines MCP tool
    @mesh.tool(           # Mesh decorator - adds orchestration
        capability="greeting",
        dependencies=["time_service"]
    )
    async def greet(name: str, time_service: mesh.McpMeshTool = None):
        """Greet someone with the current time."""
        current_time = await time_service() if time_service else "unknown"
        return f"Hello {name}! The time is {current_time}"

    @mesh.agent(
        name="greeting-agent",
        http_port=8080,
        enable_http=True,
        auto_run=True,
    )
    class GreetingAgent:
        pass
    ```

=== "TypeScript"

    ```typescript
    import { FastMCP, mesh } from "@mcpmesh/sdk";
    import { z } from "zod";

    const server = new FastMCP({ name: "My Agent", version: "1.0.0" });
    const agent = mesh(server, { name: "greeting-agent", port: 8080 });

    agent.addTool({
      name: "greet",
      capability: "greeting",
      description: "Greet someone with the current time",
      dependencies: ["time_service"],
      parameters: z.object({ name: z.string() }),
      execute: async ({ name }, { time_service }) => {
        const currentTime = time_service ? await time_service() : "unknown";
        return `Hello ${name}! The time is ${currentTime}`;
      },
    });
    ```

That's all the code you need. MCP Mesh handles:

- **Service discovery** - Finding other agents in the network
- **Dependency injection** - Automatically wiring dependencies
- **Health monitoring** - Heartbeats and failure detection
- **HTTP exposure** - Tools callable via REST API

### Types of Tools

MCP Mesh supports four types of tools, each with its own decorator:

| Decorator            | Purpose                                     | Use Case                                   |
| -------------------- | ------------------------------------------- | ------------------------------------------ |
| `@mesh.tool`         | Standard MCP tool with dependency injection | Data processing, storage, utilities        |
| `@mesh.llm`          | LLM-powered tool with agentic capabilities  | AI analysis, content generation, reasoning |
| `@mesh.llm_provider` | Zero-code LLM vendor integration            | Claude, GPT-4, Gemini providers            |
| `@mesh.route`        | FastAPI route with tool injection           | REST APIs, webhooks, external interfaces   |

---

### 1. Standard Tools (`@mesh.tool`)

Standard tools are the building blocks of MCP Mesh. They expose capabilities that other agents can discover and call.

```python
@app.tool()
@mesh.tool(
    capability="redis_store_memory",
    description="Store a memory in Redis",
    version="1.0.0",
    tags=["redis", "storage", "write"],
)
async def store_memory(
    user_email: str,
    content: str,
    importance: int,
) -> dict:
    """Store a new memory in Redis."""
    key = f"memory:{user_email}:{timestamp}"
    await redis_client.set(key, json.dumps({
        "content": content,
        "importance": importance,
    }))
    return {"status": "success", "key": key}
```

**Key concepts:**

- **Capability**: A unique identifier that other tools use to declare dependencies
- **Tags**: Metadata for filtering during dependency resolution
- **Version**: Semantic versioning for compatibility matching
- **Dependencies**: List of capabilities this tool requires

#### Dependency Injection

When a tool declares dependencies, MCP Mesh automatically resolves and injects them:

```python
@app.tool()
@mesh.tool(
    capability="update_emotion",
    dependencies=["analyze_emotion"],  # Depends on another capability
)
async def update_emotion(
    user_email: str,
    avatar_id: str,
    analyze: mesh.McpMeshTool = None,  # Injected automatically
) -> dict:
    """Update emotion state using LLM analysis."""

    # Call the injected dependency like a function
    result = await analyze(
        user_email=user_email,
        avatar_id=avatar_id,
    )

    # Use the result
    return {"emotion": result.emotion, "intensity": result.intensity}
```

**How it works:**

1. Agent starts and registers its capabilities with the registry
2. MCP Mesh discovers agents that provide required dependencies
3. Proxy objects (`mesh.McpMeshTool`) are injected at runtime
4. Calling the proxy transparently invokes the remote tool via MCP
5. You don't manage URLs, connections, retries, or failures

#### Advanced Tag Matching

Tags support prefix operators for fine-grained control:

```python
@mesh.tool(
    capability="analyze",
    dependencies=[
        "storage",              # Must have "storage" tag
        {"capability": "llm", "tags": ["+claude", "-gpt"]},  # Prefer Claude, avoid GPT
    ]
)
```

| Operator | Meaning             | Example        |
| -------- | ------------------- | -------------- |
| (none)   | Must have tag       | `"storage"`    |
| `+`      | Prefer if available | `"+claude"`    |
| `-`      | Avoid if possible   | `"-expensive"` |

---

### 2. LLM Tools (`@mesh.llm`)

LLM tools add intelligence to any MCP tool. They can:

- Execute agentic loops with tool calling
- Use dynamic system prompts (Jinja2 templates)
- Filter available tools for the LLM
- Return structured JSON or plain text

```python
from pydantic import BaseModel, Field

class EmotionAnalysis(BaseModel):
    """Structured response from emotion analysis."""
    emotion: str = Field(..., description="Primary emotion")
    intensity: float = Field(..., ge=0.0, le=1.0)
    reasoning: str = Field(..., description="Brief explanation")

@app.tool()
@mesh.llm(
    provider={"capability": "llm", "tags": ["llm", "+gpt"]},  # Prefer GPT for speed
    max_iterations=1,                                          # Single LLM call
    system_prompt="file://prompts/emotion_analysis.jinja2",   # Dynamic prompt
    context_param="emotion_ctx",                               # Context injection
    response_format="json",                                    # Structured output
)
@mesh.tool(
    capability="analyze_emotion",
    tags=["emotion", "analysis", "llm"],
)
async def analyze_emotion(
    emotion_ctx: EmotionContext,
    llm: mesh.MeshLlmAgent = None,
) -> EmotionAnalysis:
    """Analyze avatar's emotional state from conversation."""
    return await llm("Analyze the avatar's emotional state")
```

#### LLM Decorator Options

| Option            | Description                          | Example                                      |
| ----------------- | ------------------------------------ | -------------------------------------------- |
| `provider`        | Which LLM to use (capability + tags) | `{"capability": "llm", "tags": ["+claude"]}` |
| `max_iterations`  | Max tool-calling loops               | `10` for agentic, `1` for single call        |
| `system_prompt`   | Static string or Jinja2 file         | `"file://prompts/system.jinja2"`             |
| `context_param`   | Parameter name for template context  | `"emotion_ctx"`                              |
| `response_format` | Output format                        | `"json"`, `"text"`                           |
| `filter`          | Filter available tools for LLM       | `{"tags": ["memory-agent"]}`                 |
| `filter_mode`     | How to apply filter                  | `"all"`, `"any"`                             |

#### Agentic Tool Calling

LLM tools can call other tools in a loop:

```python
@app.tool()
@mesh.llm(
    filter={"tags": ["memory-agent", "recall"]},  # Only memory tools available
    filter_mode="all",
    provider={"capability": "llm", "tags": ["+claude"]},
    max_iterations=10,  # Allow up to 10 tool calls
    system_prompt="file://prompts/avatar.jinja2",
    context_param="avatar_ctx",
    response_format="text",
)
@mesh.tool(
    capability="generic_avatar_respond",
    tags=["avatar", "companion"],
)
async def generic_respond(
    avatar_ctx: AvatarContext,
    llm: mesh.MeshLlmAgent = None,
) -> str:
    """Generate avatar response with memory recall capability."""
    # LLM can call memory_recall tool during its reasoning
    return await llm(avatar_ctx.conversation_history)
```

The LLM sees filtered tools and can call them autonomously. MCP Mesh handles the tool execution loop.

---

### 3. LLM Providers (`@mesh.llm_provider`)

LLM providers make any AI vendor available to the mesh with zero code:

```python
@mesh.llm_provider(
    model="anthropic/claude-sonnet-4-5",
    capability="llm",
    tags=["llm", "claude", "anthropic", "sonnet", "provider"],
    version="1.0.0",
)
def claude_provider():
    """Claude provider - automatically creates process_chat endpoint."""
    pass  # Implementation is in the decorator

@mesh.agent(
    name="claude-provider",
    http_port=9110,
    enable_http=True,
    auto_run=True,
    health_check=claude_health_check,
)
class ClaudeProviderAgent:
    pass
```

**What it provides:**

- Automatic `process_chat(request: MeshLlmRequest)` tool
- LiteLLM integration for unified API
- Error handling and retries
- Mesh registration with capability and tags

#### Multiple Providers

Deploy multiple providers and let tools choose at runtime:

```python
# claude_provider.py
@mesh.llm_provider(
    model="anthropic/claude-sonnet-4-5",
    tags=["llm", "claude", "anthropic", "expensive", "smart"],
)
def claude_provider():
    pass

# openai_provider.py
@mesh.llm_provider(
    model="openai/gpt-4o",
    tags=["llm", "openai", "gpt", "fast", "cheap"],
)
def openai_provider():
    pass
```

Tools select providers using tag matching:

```python
@mesh.llm(
    # Use Claude for complex reasoning
    provider={"capability": "llm", "tags": ["+claude", "+smart"]},
)
async def complex_analysis(...): ...

@mesh.llm(
    # Use GPT for fast, simple tasks
    provider={"capability": "llm", "tags": ["+gpt", "+fast"]},
)
async def quick_extraction(...): ...
```

---

### 4. FastAPI Routes (`@mesh.route`)

The `@mesh.route` decorator lets FastAPI endpoints call MCP tools as regular Python functions:

```python
from fastapi import APIRouter, Request
from mesh.types import McpMeshTool

router = APIRouter(prefix="/chat", tags=["chat"])

@router.post("/completions")
@mesh.route(dependencies=["avatar_chat"])
async def chat_completions(
    request: Request,
    chat_request: ChatCompletionRequest,
    avatar_id: str = "maya-creative",
    avatar_agent: McpMeshTool = None,  # Injected by @mesh.route
):
    """OpenAI-compatible chat endpoint."""

    # Extract user from JWT
    user_info = require_user_from_request(request)

    # Call MCP tool like a regular function
    result = await avatar_agent(
        user_email=user_info["email"],
        message=chat_request.messages[-1].content,
        avatar_id=avatar_id,
    )

    return ChatCompletionResponse(
        choices=[{"message": {"content": result["message"]}}]
    )
```

**Benefits:**

- **No network code**: MCP Mesh handles connections
- **Type safety**: Pydantic models work transparently
- **Dependency injection**: Tools injected like FastAPI dependencies
- **Decoupled architecture**: Routes don't know where tools run

---

### Putting It All Together

Here's how these components work together in a real system (Maya):

```
┌──────────────────────────────────────────────────────────────────┐
│                     FastAPI Backend                               │
│  @mesh.route(dependencies=["avatar_chat"])                       │
│  POST /chat/completions → avatar_agent()                         │
└──────────────────────────────────┬───────────────────────────────┘
                                   │
                                   ▼
┌──────────────────────────────────────────────────────────────────┐
│                    Orchestrator Agent                             │
│  @mesh.tool(capability="avatar_chat",                            │
│             dependencies=["generic_avatar_respond",              │
│                          "memory_recall", "update_emotion"])     │
└──────────┬───────────────────────┬───────────────────────────────┘
           │                       │
           ▼                       ▼
┌─────────────────────┐  ┌─────────────────────────────────────────┐
│   Avatar Agent      │  │          Memory LLM Agent               │
│  @mesh.llm(         │  │  @mesh.llm(provider={"+gpt"})           │
│    provider={"+claude"}│  │  @mesh.tool(capability="memory_recall")│
│  )                  │  │                                         │
└─────────┬───────────┘  └─────────────────┬───────────────────────┘
          │                                │
          ▼                                ▼
┌─────────────────────┐           ┌─────────────────────┐
│   Claude Provider   │           │   OpenAI Provider   │
│  @mesh.llm_provider │           │  @mesh.llm_provider │
│  model="claude..."  │           │  model="gpt-4o"     │
└─────────────────────┘           └─────────────────────┘
```

**Data flow:**

1. HTTP request hits FastAPI route
2. `@mesh.route` injects `avatar_agent` (Orchestrator)
3. Orchestrator calls Avatar Agent with injected dependencies
4. Avatar Agent uses Claude via `@mesh.llm`
5. Memory LLM uses GPT for fast extraction
6. Response flows back through the chain

All of this happens with:

- **Zero network code** in your tools
- **Automatic service discovery**
- **Runtime dependency injection**
- **Transparent LLM provider selection**

---

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

### 3. **Unified Proxy System**

MCP Mesh uses a unified proxy (`EnhancedUnifiedMCPProxy`) that auto-configures from decorator kwargs:

```python
@app.tool()
@mesh.tool(
    capability="enhanced_service",
    timeout=60,                    # Auto-configures proxy timeout
    retry_count=3,                 # Auto-configures retry policy
    session_required=True,         # Enables session management
    auth_required=True             # Auto-enables authentication
)
def enhanced_tool():
    pass
```

**Proxy Classes:**

- **UnifiedMCPProxy**: Base class using FastMCP client with all MCP protocol features
- **EnhancedUnifiedMCPProxy**: Enhanced version with retry logic (used for all dependencies)
- **SelfDependencyProxy**: Optimized proxy for local/same-agent calls (no network overhead)

**Features (all in one proxy):**

- Configurable timeout and retry with exponential backoff
- Session management for stateful operations
- Custom headers and authentication
- Distributed tracing integration
- HTTP fallback when FastMCP client unavailable

_Implementation: See `src/runtime/python/_mcp_mesh/engine/unified_mcp_proxy.py`_

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

**Key Insight**: Mesh decorators must process BEFORE FastMCP decorators to cache original functions. Since Python processes decorators bottom-up, `@mesh.tool()` goes below `@app.tool()`:

```python
@app.tool()   # ← FastMCP processes wrapped function (outer, applied second)
@mesh.tool()  # ← Processes first, caches original function (inner, applied first)
def hello(): pass
```

**Implementation**:

1. Mesh decorator caches `func._mesh_original_func = func`
2. Creates dependency injection wrapper
3. FastMCP receives wrapper (not original)
4. Runtime calls cached original with injected dependencies

#### Proxy Selection Logic

**Registry-Driven**: Heartbeat response determines proxy type based on dependency location.

```python
if current_agent_id == target_agent_id:
    # Same agent - direct local call (no network overhead)
    proxy = SelfDependencyProxy(original_func, function_name)
else:
    # Different agent - unified MCP proxy with auto-configuration
    proxy = EnhancedUnifiedMCPProxy(endpoint, function_name, kwargs_config)
```

The unified proxy automatically configures itself from `kwargs_config` passed from the `@mesh.tool()` decorator (timeout, retry, session, auth, etc.).

_Implementation: See `src/runtime/python/_mcp_mesh/pipeline/mcp_heartbeat/rust_heartbeat.py`_

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
- Store capability metadata (SQLite for local dev, PostgreSQL for production)
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

---

This architecture enables MCP Mesh to provide a seamless, scalable, and developer-friendly service orchestration platform that preserves the simplicity of FastMCP while adding powerful distributed system capabilities.

**For Implementation Details**: See source code in `src/runtime/python/` (Python), `src/runtime/typescript/` (TypeScript), and `cmd/registry/` (Go)
**For Examples**: See `examples/` directory for complete working examples
**For Configuration**: See [Environment Variables](./environment-variables.md) for all configuration options
