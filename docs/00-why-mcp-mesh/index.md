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
from mcp_mesh import mesh
from fastmcp import FastMCP

app = FastMCP("My Agent")

# Define a tool with automatic dependency injection
@app.tool()
@mesh.tool(capability="greeting", dependencies=["time_service"])
async def greet(name: str, time_service: mesh.McpMeshTool = None):
    current_time = await time_service() if time_service else "unknown"
    return f"Hello {name}! The time is {current_time}"

# Expose a REST endpoint
@mesh.route("/api/greet/{name}", methods=["GET"])
async def greet_api(name: str):
    return {"message": greet(name)}

# Register as an agent
@mesh.agent(name="greeting-agent", port=8080)
class GreetingAgent:
    pass
```

That's a complete agent with:

- Tool that other agents can call
- REST API for external access
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

### 1. Decorators That Do Everything

```python
@mesh.agent(name="my-agent", port=8080)      # Register with mesh
@mesh.tool(capability="process")              # Expose as callable tool
@mesh.llm(provider="anthropic")               # Add LLM capabilities
@mesh.route("/api/endpoint")                  # REST API endpoint
```

### 2. Automatic Dependency Injection

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

### 3. One Command to Production

```bash
# Generate Docker Compose with observability
meshctl scaffold --compose --observability

# Or deploy to Kubernetes (OCI registry)
helm install my-mesh oci://ghcr.io/dhyansraj/mcp-mesh/mcp-mesh-core \
  --version 0.9.0-beta.3 -n mcp-mesh --create-namespace
```

### 4. Built-in Observability

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

## Next Steps

Ready to build your first agent?

[Get Started in 5 Minutes](../01-getting-started.md){ .md-button .md-button--primary }
[View Architecture](../architecture-and-design.md){ .md-button }
