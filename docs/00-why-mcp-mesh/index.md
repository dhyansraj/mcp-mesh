# Why MCP Mesh?

## The Problem: Building Agents is Easy, Deploying Them is Hard

Every AI framework lets you build agents. But when it's time to deploy:

- **How do you deploy 10 agents to Kubernetes?**
- **How do agents discover each other at runtime?**
- **How do you scale Agent A independently from Agent B?**
- **How do you monitor which agent called which?**

The answer from most frameworks: _"That's your problem."_

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

MCP Mesh is the only framework with **Distributed Dynamic Dependency Injection**. Dependencies are discovered, injected, and hot-swapped at runtime across machines and languages — no config files, no restarts. [What is DDDI? -->](../concepts/dddi.md)

### 2. Decorators That Do Everything

```python
@mesh.agent(name="my-agent", port=8080)      # Register with mesh
@mesh.tool(capability="process")              # Expose as callable tool
@mesh.llm(provider="anthropic")               # Add LLM capabilities
@mesh.route("/api/endpoint")                  # REST API endpoint
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
  --version 1.1.0-beta.2 -n mcp-mesh --create-namespace
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

---

## Next Steps

Ready to build your first agent?

[Get Started in 5 Minutes](../01-getting-started.md){ .md-button .md-button--primary }
[View Architecture](../architecture-and-design.md){ .md-button }
