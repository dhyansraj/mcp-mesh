---
title: Home
template: home.html
---

# Distributed Service Mesh for AI Agents

You write the logic. The mesh discovers, connects, heals, and traces — across languages, machines, and clouds.

!!! tip "Complete Platform for AI Agents"
MCP Mesh is a complete platform for **building and deploying AI agents to production scale**. [See how MCP Mesh compares →](00-why-mcp-mesh/index.md)

---

## :rocket: Quick Start

=== "Python"

    ```bash
    pip install "mcp-mesh>=0.9,<1.0"
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

=== "Java"

    ```xml
    <dependency>
        <groupId>io.mcp-mesh</groupId>
        <artifactId>mcp-mesh-spring-boot-starter</artifactId>
        <version>0.9.3</version>
    </dependency>
    ```

    ```java
    import io.mcpmesh.MeshAgent;
    import io.mcpmesh.MeshTool;
    import io.mcpmesh.Param;
    import io.mcpmesh.Selector;
    import io.mcpmesh.types.McpMeshTool;
    import org.springframework.boot.SpringApplication;
    import org.springframework.boot.autoconfigure.SpringBootApplication;

    @MeshAgent(name = "my-service", version = "1.0.0", port = 8080)
    @SpringBootApplication
    public class MyServiceApplication {

        public static void main(String[] args) {
            SpringApplication.run(MyServiceApplication.class, args);
        }

        @MeshTool(
            capability = "greeting",
            dependencies = @Selector(capability = "date_service")
        )
        public String greet(
            @Param("name") String name,
            McpMeshTool<String> dateService
        ) {
            if (dateService != null && dateService.isAvailable()) {
                return "Hello, " + name + "! " + dateService.call();
            }
            return "Hello, " + name + "!";
        }
    }
    ```

=== "TypeScript"

    ```bash
    npm install @mcpmesh/sdk
    ```

    ```typescript
    import { FastMCP, mesh } from "@mcpmesh/sdk";
    import { z } from "zod";

    const server = new FastMCP({ name: "my-service", version: "1.0.0" });
    const agent = mesh(server, { name: "my-service", port: 8080 });

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
Helm charts with horizontal scaling, health checks, and observability.
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

    - **Zero Boilerplate**: Simple decorators/functions replace hundreds of lines of networking code
    - **Python, Java & TypeScript**: Write MCP servers as simple functions in your preferred language — no manual client/server setup
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
    pip install "mcp-mesh>=0.9,<1.0"
    ```

    Runtime for building agents with `@mesh.agent`, `@mesh.tool`, `@mesh.llm`, and `@mesh.llm_provider` decorators.
    Includes `@mesh.route()` for FastAPI integration.

=== "Java Runtime"

    ```xml
    <dependency>
        <groupId>io.mcp-mesh</groupId>
        <artifactId>mcp-mesh-spring-boot-starter</artifactId>
        <version>0.9.3</version>
    </dependency>
    ```

    Spring Boot starter for building agents with `@MeshAgent`, `@MeshTool`, `@MeshLlm`, and `@MeshLlmProvider` annotations.
    Includes `@MeshRoute` for Spring Boot REST integration.

=== "TypeScript Runtime"

    ```bash
    npm install @mcpmesh/sdk
    ```

    Runtime for building agents with `mesh()`, `addTool()`, `addLlm()`, and `addLlmProvider()` functions.
    Includes `addRoute()` for Express integration.

=== "Docker Images"

    ```bash
    docker pull mcpmesh/registry:0.9
    docker pull mcpmesh/python-runtime:0.9
    docker pull mcpmesh/java-runtime:0.9
    docker pull mcpmesh/typescript-runtime:0.9
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

- **Latest Release**: v0.9.3 (February 2026)
- **License**: MIT
- **Languages**: Python 3.11+, TypeScript/Node.js 18+, and Java 17+ (runtime), Go 1.23+ (registry)
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
[Java SDK](java/getting-started/index.md){ .md-button .md-button--primary }
[TypeScript SDK](typescript/getting-started/index.md){ .md-button .md-button--primary }
[View on GitHub](https://github.com/dhyansraj/mcp-mesh){ .md-button }

**Star the repo** if MCP Mesh helps you build better AI systems! :star:

</div>
