---
title: Home
template: home.html
---

# Enterprise-Grade Distributed Service Mesh for AI Agents

MCP Mesh transforms the Model Context Protocol (MCP) from a development protocol into an enterprise-grade distributed system. Build production-ready AI agent networks with zero boilerplate.

!!! tip "Complete Platform for AI Agents"
MCP Mesh is a complete platform for **building and deploying AI agents to production scale**. [See how MCP Mesh compares →](00-why-mcp-mesh/index.md)

---

## :rocket: Quick Start

=== "Python"

    ```bash
    pip install "mcp-mesh>=0.8,<0.9"
    ```

    ```python
    from fastmcp import FastMCP
    import mesh

    app = FastMCP("My Service")

    @app.tool()
    @mesh.tool(capability="greeting", dependencies=["date_service"])
    async def greet(date_service: mesh.McpMeshTool = None):
        return f"Hello! {await date_service()}"

    @mesh.agent(name="my-service", auto_run=True)
    class MyAgent:
        pass
    ```

=== "TypeScript"

    ```bash
    npm install @mcpmesh/sdk
    ```

    ```typescript
    import { FastMCP, mesh } from "@mcpmesh/sdk";
    import { z } from "zod";

    const server = new FastMCP({ name: "my-service", version: "1.0.0" });
    const agent = mesh(server, { name: "my-service", port: 9000 });

    agent.addTool({
      name: "greet",
      capability: "greeting",
      description: "Greet the user with current date",
      dependencies: ["date_service"],
      parameters: z.object({ name: z.string() }),
      execute: async ({ name }, { date_service }) => {
        const date = await date_service();
        return `Hello, ${name}! Today is ${date}`;
      },
    });
    ```

**That's it!** No manual server setup, no connection management, no networking code.

---

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
Production-ready Helm charts with horizontal scaling, health checks, and observability.
</div>
<div class="feature-card" markdown>
### :arrows_counterclockwise: Dynamic Updates
Hot dependency injection without restarts. Add, remove, or upgrade services seamlessly.
</div>
<div class="feature-card" markdown>
### :bar_chart: Built-in Observability
Grafana dashboards, distributed tracing with Tempo, and Redis-backed session management.
</div>
<div class="feature-card" markdown>
### :shield: Enterprise Ready
Graceful failure handling, auto-reconnection, RBAC support, and real-time monitoring.
</div>
</div>

---

## :fire: Why MCP Mesh?

=== "For Developers"

    **Stop fighting infrastructure. Start building intelligence.**

    - Zero boilerplate networking code
    - Pure Python simplicity with FastMCP integration
    - End-to-end FastAPI integration with `@mesh.route()`
    - Same code runs locally, in Docker, and Kubernetes

=== "For Solution Architects"

    **Design intelligent systems, not complex integrations.**

    - Agent-centric architecture with clear capabilities
    - Dynamic intelligence - agents get smarter automatically
    - Domain-driven design with focused, composable agents
    - Mix and match agents to create new capabilities

=== "For DevOps Teams"

    **Production-ready AI infrastructure out of the box.**

    - Kubernetes-native with battle-tested Helm charts
    - Enterprise observability with Grafana, Tempo, and Redis
    - Zero-touch operations with auto-discovery
    - Scale from 2 agents to 200+ with same complexity

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
    - **Risk Mitigation**: Battle-tested enterprise patterns ensure reliable AI deployments that scale with your business
    - **Future-Proof Architecture**: Add new AI capabilities without disrupting existing systems

    Turn your AI strategy from "promising experiments" to "competitive advantage in production."

---

## :chart_with_upwards_trend: MCP vs MCP Mesh

| Challenge                | Traditional MCP                  | MCP Mesh                       |
| ------------------------ | -------------------------------- | ------------------------------ |
| **Connect 5 servers**    | 200+ lines of networking code    | 2 decorators                   |
| **Handle failures**      | Manual error handling everywhere | Automatic graceful degradation |
| **Scale to production**  | Custom Kubernetes setup          | `helm install mcp-mesh`        |
| **Monitor system**       | Build custom dashboards          | Built-in observability stack   |
| **Add new capabilities** | Restart and reconfigure clients  | Auto-discovery, zero downtime  |

---

## :vs: MCP Mesh vs Other Frameworks

| Framework     | K8s Native              | Independent Scaling               | Service Discovery           | Best For              |
| ------------- | ----------------------- | --------------------------------- | --------------------------- | --------------------- |
| **MCP Mesh**  | :white_check_mark: Helm | :white_check_mark: Per-agent pods | :white_check_mark: Built-in | Production deployment |
| LangGraph     | :x: Manual              | :x: Same process                  | :x: DIY                     | Complex workflows     |
| CrewAI        | :x: Manual              | :x: Limited                       | :x: None                    | Rapid prototyping     |
| AutoGen       | :x: Manual              | :x: Manual                        | :x: DIY                     | Enterprise/Azure      |
| OpenAI Agents | :x: Manual              | :x: Manual                        | :x: None                    | OpenAI-centric        |

[:material-arrow-right: Full comparison with code examples](00-why-mcp-mesh/index.md){ .md-button }

---

## :package: Installation

=== "meshctl (CLI)"

    ```bash
    npm install -g @mcpmesh/cli
    ```

    Command-line tool for managing agents, registry, and mesh operations.

=== "Registry"

    ```bash
    npm install -g @mcpmesh/cli
    ```

    Service discovery and coordination server. Included with the npm package above.

=== "Python Runtime"

    ```bash
    pip install "mcp-mesh>=0.8,<0.9"
    ```

    Runtime for building agents with `@mesh.agent` and `@mesh.tool` decorators.

=== "TypeScript Runtime"

    ```bash
    npm install @mcpmesh/sdk
    ```

    Runtime for building agents with `mesh()`, `agent()`, and `addTool()` functions.

=== "Docker Images"

    ```bash
    docker pull mcpmesh/registry:0.8
    docker pull mcpmesh/python-runtime:0.8
    ```

    Official container images for production deployments.

=== "Helm Charts"

    ```bash
    helm install mcp-mesh oci://ghcr.io/dhyansraj/mcp-mesh/charts/mcp-mesh
    ```

    Kubernetes deployment with the umbrella chart.

---

## :handshake: Community & Support

- [:fontawesome-brands-discord: Discord](https://discord.gg/KDFDREphWn) - Real-time help and discussions
- [:fontawesome-brands-github: GitHub Discussions](https://github.com/dhyansraj/mcp-mesh/discussions) - Share ideas and ask questions
- [:fontawesome-brands-github: Issues](https://github.com/dhyansraj/mcp-mesh/issues) - Report bugs or request features
- [:material-code-braces: Examples](https://github.com/dhyansraj/mcp-mesh/tree/main/examples) - Working code examples

---

## :star: Project Status

- **Latest Release**: v0.9.0-beta.3 (February 2026)
- **License**: MIT
- **Languages**: Python 3.11+ and TypeScript/Node.js 18+ (runtime), Go 1.23+ (registry)
- **Status**: Production-ready, actively developed

---

## :pray: Acknowledgments

- **[Anthropic](https://anthropic.com)** for creating the MCP protocol
- **[FastMCP](https://github.com/jlowin/fastmcp)** for excellent MCP server foundations
- **[Kubernetes](https://kubernetes.io)** community for the infrastructure platform
- All **contributors** who help make MCP Mesh better

---

<div class="center" markdown>

**Ready to get started?**

[Python SDK](python/getting-started/index.md){ .md-button .md-button--primary }
[TypeScript SDK](typescript/getting-started/index.md){ .md-button .md-button--primary }
[View on GitHub](https://github.com/dhyansraj/mcp-mesh){ .md-button }

**Star the repo** if MCP Mesh helps you build better AI systems! :star:

</div>
