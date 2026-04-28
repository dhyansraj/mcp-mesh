---
title: Home
template: home.html
---

# Distributed Service Mesh for AI Agents

You write the logic. The mesh discovers, connects, heals, and traces — across languages, machines, and clouds.

!!! tip "Complete Platform for AI Agents"
MCP Mesh is a complete platform for **building and deploying AI agents to production scale**. [See how MCP Mesh compares →](00-why-mcp-mesh/index.md)

!!! info "What is DDDI?"
**Distributed Dynamic Dependency Injection** — dependencies are discovered, injected, and updated at runtime across machines, languages, and clouds. No configuration files, no restart required. [Learn more →](concepts/dddi.md)

---

## :rocket: Quick Start

=== "Python"

    ```bash
    pip install mcp-mesh
    ```

    ```python
    from fastmcp import FastMCP
    import mesh

    app = FastMCP("TripPlanner")

    @app.tool()
    @mesh.tool(
        capability="plan_trip",
        dependencies=[
            {"capability": "weather", "tags": ["+claude"]},
            {"capability": "hotels",  "tags": ["+gpt"]},
            {"capability": "flights"},
            {"capability": "budget",  "tags": ["+claude"]},
        ],
    )
    async def plan_trip(
        destination: str,
        dates: str,
        weather: mesh.McpMeshTool = None,
        hotels:  mesh.McpMeshTool = None,
        flights: mesh.McpMeshTool = None,
        budget:  mesh.McpMeshTool = None,
    ) -> TripPlan:
        forecast = await weather(destination=destination, dates=dates)
        options  = await hotels(destination=destination, dates=dates)
        routes   = await flights(destination=destination, dates=dates)
        cost     = await budget(routes=routes, options=options)
        return TripPlan(forecast, options, routes, cost)

    @mesh.agent(name="trip-planner", auto_run=True)
    class TripAgent: pass
    ```

=== "Java"

    ```xml
    <dependency>
        <groupId>io.mcp-mesh</groupId>
        <artifactId>mcp-mesh-spring-boot-starter</artifactId>
        <version>1.4.1</version>
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
    import java.util.Map;

    @MeshAgent(name = "trip-planner", version = "1.0.0", port = 8080)
    @SpringBootApplication
    public class TripPlannerApp {

        public static void main(String[] args) {
            SpringApplication.run(TripPlannerApp.class, args);
        }

        @MeshTool(
            capability = "plan_trip",
            dependencies = {
                @Selector(capability = "weather", tags = {"+claude"}),
                @Selector(capability = "hotels",  tags = {"+gpt"}),
                @Selector(capability = "flights"),
                @Selector(capability = "budget",  tags = {"+claude"})
            }
        )
        public TripPlan planTrip(
            @Param("destination") String destination,
            @Param("dates") String dates,
            McpMeshTool<Forecast> weather,
            McpMeshTool<HotelOptions> hotels,
            McpMeshTool<FlightRoutes> flights,
            McpMeshTool<Cost> budget
        ) {
            var args = Map.of("destination", destination, "dates", dates);
            var forecast = weather.call(args);
            var options  = hotels.call(args);
            var routes   = flights.call(args);
            var cost     = budget.call(Map.of("routes", routes, "options", options));
            return new TripPlan(forecast, options, routes, cost);
        }
    }
    ```

=== "TypeScript"

    ```bash
    npm install @mcpmesh/sdk
    ```

    ```typescript
    import { FastMCP, mesh, McpMeshTool } from "@mcpmesh/sdk";
    import { z } from "zod";

    const server = new FastMCP({ name: "TripPlanner", version: "1.0.0" });
    const agent = mesh(server, { name: "trip-planner", httpPort: 8080 });

    agent.addTool({
      name: "plan_trip",
      capability: "plan_trip",
      description: "Plan a trip by composing weather, hotels, flights, and budget",
      dependencies: [
        { capability: "weather", tags: ["+claude"] },
        { capability: "hotels",  tags: ["+gpt"] },
        { capability: "flights" },
        { capability: "budget",  tags: ["+claude"] },
      ],
      parameters: z.object({
        destination: z.string(),
        dates: z.string(),
      }),
      execute: async (
        { destination, dates },
        weather: McpMeshTool | null,
        hotels: McpMeshTool | null,
        flights: McpMeshTool | null,
        budget: McpMeshTool | null,
      ) => {
        const forecast = await weather!({ destination, dates });
        const options  = await hotels!({ destination, dates });
        const routes   = await flights!({ destination, dates });
        const cost     = await budget!({ routes, options });
        return { forecast, options, routes, cost };
      },
    });
    ```

!!! abstract "What just happened?"
    Four distributed calls, composed like a local function. Each dep could live in this process, another machine, another language. Mesh handles discovery, transport, retry, and failover — your function stays a function. Each dep is just another `@mesh.tool`, defined the same way — in this agent or another.

    Any dep can be a plain tool **or** an LLM agent — your code can't tell. `weather` could be a REST API *or* a Claude-powered reasoning agent returning a typed pydantic forecast. `+claude` means prefer the reasoning agent; if it dies, mesh auto-rewires to the API. When Claude recovers, mesh rewires back. No deploy, no config, no code change.

???+ example "See how the Claude-powered weather agent is built (10 lines)"
    ```python
    from fastmcp import FastMCP
    import mesh

    app = FastMCP("ClaudeWeather")

    @app.tool()
    @mesh.llm(
        system_prompt="file://prompts/weather.j2",
        provider={"capability": "llm", "tags": ["+claude"]},
    )
    @mesh.tool(capability="weather", tags=["+claude"])
    def weather(destination: str, dates: str,
                llm: mesh.MeshLlmAgent = None) -> Forecast:
        return llm(f"Forecast for {destination} on {dates}")

    @mesh.agent(name="claude-weather", auto_run=True)
    class Agent: pass
    ```

    The LLM orchestrates tools via the mesh `filter` pattern and returns a typed pydantic `Forecast` — no agentic loop to write.

??? example "Route by Python if/else, not config"
    ```python
    # Two providers of the same capability, wired at runtime
    weather = reasoning_weather if user.wants_explanation else api_weather
    forecast = await weather(destination, dates)
    ```

**[See the full TripPlanner tutorial →](https://mcp-mesh.ai/tutorial/)**

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
### :arrows_counterclockwise: DDDI — Dynamic Injection
Distributed Dynamic Dependency Injection without restarts. Add, remove, or upgrade services seamlessly across the mesh.
</div>
<div class="feature-card" markdown>
### :bar_chart: Built-in Observability
Grafana dashboards, distributed tracing with Tempo, and Redis-backed session management.
</div>
<div class="feature-card" markdown>
### :shield: Enterprise Ready
Graceful failure handling, auto-reconnection, RBAC support, and real-time monitoring.
</div>
<div class="feature-card" markdown>
### :globe_with_meridians: Multi-Language Agents
Write agents in Python, TypeScript, or Java — they discover and call each other natively across the mesh via a shared Rust FFI core.
</div>
<div class="feature-card" markdown>
### :brain: Multi-Provider LLM Support
First-class support for Claude, GPT, and Gemini with agentic tool execution, structured output, and auto-resolution. Any provider supported by LiteLLM, Vercel AI SDK, or Spring AI works out of the box.
</div>
<div class="feature-card" markdown>
### :camera: Multimodal Support
Pass images, PDFs, and files between agents and LLMs. Claude, OpenAI, and Gemini each require different API structures for media — the mesh abstracts that away.
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
    pip install mcp-mesh
    ```

    Runtime for building agents with `@mesh.agent`, `@mesh.tool`, `@mesh.llm`, and `@mesh.llm_provider` decorators.
    Includes `@mesh.route()` for FastAPI integration.

=== "Java Runtime"

    ```xml
    <dependency>
        <groupId>io.mcp-mesh</groupId>
        <artifactId>mcp-mesh-spring-boot-starter</artifactId>
        <version>1.4.1</version>
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
    docker pull mcpmesh/registry:1.4.1
    docker pull mcpmesh/python-runtime:1.4.1
    docker pull mcpmesh/java-runtime:1.4.1
    docker pull mcpmesh/typescript-runtime:1.4.1
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

- **Latest Release**: v1.4.1 (March 2026)
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
