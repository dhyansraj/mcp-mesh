# Why MCP Mesh?

## The problem isn't building an agent. It's everything that happens when agents need each other.

Every framework helps you build an agent. Then the real work starts: that agent needs another — and in production the other one moves, dies, gets a new version, scales to ten copies, runs an LLM, holds state, or is written in another language. Most frameworks hand you a *pile* of separate problems — service discovery here, a retry library there, a job queue, a config system, a deployment story — and say _"that's your problem,"_ five times over.

Mesh has one answer to all of them, and it's a single idea: **Distributed Dynamic Dependency Injection (DDDI).** You declare what a piece of your system *needs* — a capability — and the mesh finds it, types it, health-routes it, and hot-swaps it at runtime, across machines and languages. That's the whole primitive. Everything else in mesh is a _consequence_ of it — which is why mesh is large in features but small in ideas.

Because a dependency is a *live, resolved capability*, problems that are normally entire subsystems just fall out:

- **An LLM is a dependency** → "prefer Claude, fall back to Gemini," model routing, and provider failover become declarations, not integrations.
- **A long-running job is a dependency that outlives the call** → durable jobs, resume, and cancel come for free — same primitive, longer lifetime.
- **A group of capabilities is a dependency you bundle** → a typed *service view*, functions from many agents behind one interface each resolving on its own, is just DDDI applied N times.
- **A dependency that moved, died, or upgraded re-wires itself** → the running consumer never restarts; a better provider appears and it rebinds live.
- **A Python capability consumed by Java is still just a dependency** → polyglot, typed, identical semantics, because the *mesh* owns the contract, not the language.
- **Local and Kubernetes are the same declaration** → same code, different transport; there's no second mental model between "build" and "deploy."

None of those is a bolt-on you integrate. They're the same idea from different angles. The traditionally-hard parts of a distributed AI system don't get _solved_ in mesh so much as they **stop being separate problems.**

So the "why" isn't "mesh has a feature for that." It's: **learn one idea — DDDI — and a platform's worth of hard problems quietly disappears.** You describe what your agents need; the mesh makes it true, keeps it true, and rearranges the world underneath them without asking.

And yes — it also deploys to Kubernetes, scales each agent independently, and traces every call. But that's the reassurance, not the reason.

---

## MCP Mesh: Build AND Deploy

MCP Mesh is a **complete platform** for building and deploying AI agents. You don't need LangGraph, CrewAI, or AutoGen.

### What MCP Mesh Provides

| Capability               | How                                                       |
| ------------------------ | --------------------------------------------------------- |
| **Build Agents**         | `@mesh.agent` - Define agents with automatic registration |
| **Create Tools**         | `@mesh.tool` - Tools with dependency injection            |
| **Add LLM Intelligence** | `@mesh.llm` - Integrate any LLM provider                  |
| **Expose APIs**          | `@mesh.route` - FastAPI endpoints with mesh integration   |
| **Deploy to Production** | Helm charts, Docker Compose, K8s-native                   |
| **Monitor Everything**   | Built-in Grafana, Tempo, health checks                    |

### Simple Example

```python
import mesh
from fastmcp import FastMCP

app = FastMCP("My Agent")

# Define a tool with automatic dependency injection
@app.tool()
@mesh.tool(capability="greeting", dependencies=["time_service"])
async def greet(name: str, time_service: mesh.McpMeshTool = None):
    current_time = await time_service() if time_service else "unknown"
    return f"Hello {name}! The time is {current_time}"

# Register as an agent
@mesh.agent(name="greeting-agent", port=8080)
class GreetingAgent:
    pass
```

That's a complete agent with:

- Tool that other agents can call
- Automatic registration with the mesh
- Dependency injection from other agents

---

## Framework Comparison

| Framework         | Build Agents         | K8s Deploy  | Independent Scaling | Service Discovery |
| ----------------- | -------------------- | ----------- | ------------------- | ----------------- |
| **MCP Mesh**      | `@mesh.*` decorators | Helm charts | Per-agent pods      | Built-in registry |
| **LangGraph**     | Graph-based          | Manual      | Same process        | DIY               |
| **CrewAI**        | Role-based           | Manual      | Limited             | None              |
| **AutoGen**       | Conversation         | Manual      | Manual              | DIY               |
| **OpenAI Agents** | Function calling     | Manual      | Manual              | None              |

### Key Insight

- **LangGraph/CrewAI/AutoGen** = Agent building frameworks (no deployment)
- **MCP Mesh** = Agent building + deployment + scaling + observability

---

## What Makes MCP Mesh Different

### 1. True DDDI (Distributed Dynamic Dependency Injection)

DDDI is the one idea everything above rests on — no other framework has it. If you skipped the opener: dependencies are discovered, typed, health-routed, and hot-swapped at runtime across machines and languages, with no config files and no restarts. [What is DDDI? -->](../concepts/dddi.md)

### 2. Decorators That Do Everything

```python
@mesh.agent(name="my-agent", port=8080)                      # Register with mesh
@mesh.tool(capability="process")                              # Expose as callable tool
@mesh.llm(provider={"capability": "llm", "tags": ["+claude"]}) # Add LLM capabilities
@mesh.route("/api/endpoint")                                  # REST API endpoint
```

### 3. Automatic Dependency Injection

```python
@mesh.tool(
    capability="analyze_data",
    dependencies=["db_service", "ml_service"]
)
async def analyze(data, db_service: mesh.McpMeshTool = None, ml_service: mesh.McpMeshTool = None):
    # db_service and ml_service are automatically injected
    # MCP Mesh finds them, connects them, handles failures
    records = await db_service(query=data) if db_service else {}
    return await ml_service(data=records) if ml_service else {}
```

### 4. One Command to Production

```bash
# Generate Docker Compose with observability
meshctl scaffold --compose --observability

# Or deploy to Kubernetes (OCI registry)
helm install my-mesh oci://ghcr.io/dhyansraj/mcp-mesh/mcp-mesh-core \
  --version 3.6.0 -n mcp-mesh --create-namespace
```

### 5. Built-in Observability

- **Grafana dashboards** - Pre-configured for agent metrics
- **Distributed tracing** - See request flow across agents
- **Health monitoring** - Automatic health checks and alerting

---

## When to Use MCP Mesh

### Use MCP Mesh When:

- Building multi-agent AI systems
- Deploying agents to Kubernetes or Docker
- Agents need to discover and call each other
- You want independent scaling per agent
- You need production observability

### Maybe Skip MCP Mesh When:

- Single agent running locally only
- Pure prototyping with no deployment plans

---

## Quick Comparison: Deploying 5 Agents

### Without MCP Mesh

```
├── agent-1/
│   ├── Dockerfile
│   ├── deployment.yaml
│   ├── service.yaml
│   └── configmap.yaml
├── agent-2/
│   └── ... (repeat)
├── service-discovery/
│   └── (build your own)
└── monitoring/
    └── (set up yourself)
```

**Result**: 50+ files, weeks of work

### With MCP Mesh

```python
# 5 Python files with @mesh.agent decorators
```

```bash
meshctl scaffold --compose --observability
docker-compose up
```

**Result**: 5 files + 1 command

---

## Already Using Another Framework?

If you're already invested in LangGraph, CrewAI, or AutoGen, MCP Mesh can help you deploy them to production:

- Wrap your existing agents with `@mesh.agent`
- Get automatic K8s deployment via Helm
- Add observability without code changes
- Scale agents independently

MCP Mesh doesn't replace your agent logic - it handles the infrastructure so you don't have to.

---

## 15 Requirements, 14 Lines of Code

Here's a real-world agent spec: a portfolio analyzer that needs provider failover, multi-tool discovery, structured output, context-aware prompts, and mesh registration. That's 15 requirements — and each one maps to a single line or decorator parameter.

### The Requirements

| #   | Requirement                               | MCP Mesh Feature                         |
| --- | ----------------------------------------- | ---------------------------------------- |
| 1   | Portfolio analysis agent with LLM         | `@mesh.llm` decorator                    |
| 2   | Claude as primary provider                | Provider tags with higher score          |
| 3   | Fall back to Gemini if Claude unavailable | Provider tags with lower score           |
| 4   | Fall back to any available LLM            | Automatic mesh resolution                |
| 5   | Deterministic provider selection          | Scored tag matching (more tags = higher) |
| 6   | Access to financial analysis tools        | Tool filter by tag                       |
| 7   | Access to data retrieval tools            | Tool filter by tag                       |
| 8   | Auto-discover new tools at runtime        | DDDI — automatic                         |
| 9   | System prompt from file                   | `system_prompt="file://..."`             |
| 10  | Context-aware dynamic rendering           | Jinja2 template with `context_param`     |
| 11  | Accept user query as input                | Function parameter                       |
| 12  | Accept analysis context object            | Function parameter                       |
| 13  | Structured `PortfolioAnalysis` output     | `output_type` with Pydantic/Zod/record   |
| 14  | Register capability for other agents      | `capability` parameter                   |
| 15  | Handle provider failures gracefully       | Built-in failover + error handling       |

### The Implementation

=== "Python"

    ```python
    @mesh.llm(
        provider={"capability": "llm", "tags": [
            ["+anthropic", "+sonnet"],  # Primary (score 2)
            ["+gemini"],                # Secondary (score 1)
        ]},
        filter=[{"tags": ["financial"]}, {"tags": ["data"]}],
        system_prompt="file://prompts/analyst.jinja2",
        context_param="ctx",
        max_iterations=5,
    )
    @mesh.tool(capability="analyze_portfolio")
    async def analyze(
        query: str, ctx: AnalysisContext, llm: mesh.MeshLlmAgent = None
    ) -> PortfolioAnalysis:
        return await llm(query)
    ```

=== "TypeScript"

    ```typescript
    agent.addLlmTool({
      name: "analyze",
      provider: { capability: "llm", tags: [
        ["+anthropic", "+sonnet"],  // Primary (score 2)
        ["+gemini"],                // Secondary (score 1)
      ]},
      filter: [{ tags: ["financial"] }, { tags: ["data"] }],
      systemPrompt: "file://prompts/analyst.jinja2",
      contextParam: "ctx",
      maxIterations: 5,
      capability: "analyze_portfolio",
      returns: PortfolioAnalysisSchema,
      execute: async ({ query, ctx }, { llm }) => {
        return await llm(query);
      },
    });
    ```

=== "Java"

    ```java
    @MeshLlm(
        providerSelector = @Selector(
            capability = "llm",
            filter = {
                @Tags({"+anthropic", "+sonnet"}),  // Primary (score 2)
                @Tags({"+gemini"})                 // Secondary (score 1)
            }
        ),
        filter = @Selector(tags = {"financial", "data"}),
        systemPrompt = "classpath:prompts/analyst.ftl",
    )
    @MeshTool(capability = "analyze_portfolio")
    public PortfolioAnalysis analyze(String query, MeshLlmAgent llm) {
        return llm.request().user(query).generate(PortfolioAnalysis.class);
    }
    ```

Every requirement is handled. The provider selector has two tag groups — Claude matches both `+anthropic` and `+sonnet` (score 2), while Gemini matches only `+gemini` (score 1). The mesh deterministically selects the highest-scoring provider and falls back automatically. Filter tags (`financial`, `data`) are hard requirements — only tools with those capabilities are wired in. No HTTP clients, no retry logic, no service discovery code. The mesh does it all.

## :sparkles: Key Features

<div class="grid-features" markdown>
<div class="feature-card" markdown>
### :electric_plug: Zero Boilerplate
Two decorators replace hundreds of lines of networking code. Just write business logic.
</div>
<div class="feature-card" markdown>
### :dart: Smart Discovery
Tag-based service resolution with version constraints. Agents automatically find dependencies.
</div>
<div class="feature-card" markdown>
### :material-kubernetes: Kubernetes Native
Helm charts with horizontal scaling, health checks, and observability.
</div>
<div class="feature-card" markdown>
### :arrows_counterclockwise: DDDI — Dynamic Injection
Distributed Dynamic Dependency Injection without restarts. Add, remove, or upgrade services seamlessly across the mesh.
</div>
<div class="feature-card" markdown>
### :bar_chart: Built-in Observability
Grafana dashboards, distributed tracing with Tempo, and Redis-backed session management.
</div>
<div class="feature-card" markdown>
### :shield: Enterprise Ready
Graceful failure handling, auto-reconnection, header-propagation-based authorization hooks, and real-time monitoring.
</div>
<div class="feature-card" markdown>
### :globe_with_meridians: Multi-Language Agents
Write agents in Python, TypeScript, or Java — they discover and call each other natively across the mesh via a shared Rust FFI core.
</div>
<div class="feature-card" markdown>
### :material-swap-horizontal: Multi-Protocol Bridging
Native support for MCP, Google's A2A v1.0, and REST. Consume external A2A producers as mesh capabilities, or expose mesh agents as A2A producers for non-mesh callers — same code, same `@mesh.tool` shape.
</div>
<div class="feature-card" markdown>
### :brain: Multi-Provider LLM Support
First-class support for Claude, GPT, and Gemini with agentic tool execution, structured output, and auto-resolution. Any provider supported by LiteLLM, Vercel AI SDK, or Spring AI works out of the box.
</div>
<div class="feature-card" markdown>
### :camera: Multimodal Support
Pass images, PDFs, and files between agents and LLMs. Claude, OpenAI, and Gemini each require different API structures for media — the mesh abstracts that away.
</div>
<div class="feature-card" markdown>
### :material-progress-clock: Long-Running with MeshJob
Mark a tool `task=True` and mesh handles the rest — job persistence, status polling, cancellation, SSE streaming, and retries on transient failure. No queue infrastructure to provision; the registry IS the job substrate.
</div>
<div class="feature-card" markdown>
### :material-console-line: meshctl CLI
A `kubectl`-style command-line tool that follows you from first agent to production — scaffold new agents, inspect the registry, view traces, call tools directly, and manage agent lifecycle. Same commands work against local dev, Docker, and Kubernetes.
</div>
</div>

The cards above are a summary; [Feature Comparison](../comparison.md) has the detailed treatment of the same ground, feature by feature.

---

## Who it is for

=== "For Developers"

    **Stop fighting infrastructure. Start building intelligence.**

    - **Zero Boilerplate**: Simple decorators/functions replace hundreds of lines of networking code
    - **Python, Java & TypeScript**: Write MCP servers as simple functions in your preferred language — no manual client/server setup
    - **Multi-Protocol**: Build MCP, A2A, and REST agents with the same framework. Bridge between protocols — consume external A2A producers, or expose mesh tools to A2A clients — without rewriting business logic
    - **Web Framework Integration**: Inject MCP agents directly into FastAPI (Python), Spring Boot (Java), or Express (TypeScript) APIs seamlessly
    - **LLM as Dependencies**: Inject LLMs just like MCP agents — dynamic prompts with Jinja2 (Python), FreeMarker (Java), or Handlebars (TypeScript)
    - **Seamless Development Flow**: Code locally, test with Docker Compose, deploy to Kubernetes — same code, zero changes
    - **kubectl-like Management**: `meshctl` — a familiar command-line tool to run, monitor, and manage your entire agent network

=== "For Solution Architects"

    **Design intelligent systems, not complex integrations.**

    - **Agent-Centric Architecture**: Design specialized agents with clear capabilities and dependencies, not monolithic systems
    - **Dynamic Intelligence**: Agents get smarter automatically when new capabilities come online — no reconfiguration needed
    - **Domain-Driven Design**: Solve business problems with ecosystems of focused agents that can be designed and developed independently
    - **Composable Solutions**: Mix and match agents to create new business capabilities without custom integration code

    **Example**: Deploy a financial analysis agent that automatically discovers and uses risk assessment, market data, and compliance agents as they become available.

=== "For DevOps Teams"

    **AI infrastructure out of the box.**

    - **Kubernetes-Native**: Deploy with Helm charts — horizontal scaling, health checks, and service discovery included
    - **Enterprise Observability**: Built-in Grafana dashboards, distributed tracing, and centralized logging for complete system visibility
    - **Zero-Touch Operations**: Agents self-register, auto-discover dependencies, and gracefully handle failures without network restarts
    - **Standards-Based**: Leverage existing Kubernetes patterns — RBAC, network policies, service mesh integration, and security policies

    **Scale from 2 agents to 200+ with the same operational complexity.**

=== "For Support & Operations"

    **Complete visibility and zero-downtime operations.**

    - **Real-Time Network Monitoring**: See every agent, dependency, and health status in live dashboards
    - **Intelligent Scaling**: Agents scale independently based on demand - no cascading performance issues
    - **Graceful Failure Handling**: Agents degrade gracefully when dependencies are unavailable, automatically reconnect when services return
    - **One-Click Diagnostics**: `meshctl status` provides instant network health assessment with actionable insights

=== "For Engineering Leadership"

    **Transform AI experiments into production revenue.**

    - **Accelerated Time-to-Market**: Move from PoC to production deployment in weeks, not months
    - **Cross-Team Collaboration**: Enable different departments to build agents that automatically enhance each other's capabilities
    - **Risk Mitigation**: Proven patterns help ensure reliable AI deployments that scale with your business
    - **Future-Proof Architecture**: Add new AI capabilities without disrupting existing systems

    Turn your AI strategy from "promising experiments" to "competitive advantage in production."

---

## Next Steps

Ready to build your first agent?

[Get Started in 5 Minutes](../tutorial/index.md){ .md-button .md-button--primary }
[View Architecture](../concepts/architecture.md){ .md-button }
