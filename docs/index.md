---
title: Home
template: home.html
---

# Enterprise-Grade Distributed Service Mesh for AI Agents

MCP Mesh transforms the Model Context Protocol (MCP) from a development protocol into an enterprise-grade distributed system. Build production-ready AI agent networks with zero boilerplate.

---

## :rocket: Quick Start

```bash
# Install MCP Mesh
pip install "mcp-mesh>=0.5,<0.6"
```

```python
# Create your first agent
from fastmcp import FastMCP
import mesh

app = FastMCP("My Service")

@app.tool()
@mesh.tool(capability="greeting", dependencies=["date_service"])
def greet(date_service=None):
    return f"Hello! {date_service()}"

@mesh.agent(name="my-service", auto_run=True)
class MyAgent:
    pass
```

**That's it!** No manual server setup, no connection management, no networking code.

---

## :sparkles: Key Features

<div class="grid cards" markdown>

-   :electric_plug: **Zero Boilerplate**

    ---

    Two decorators replace hundreds of lines of networking code. Just write business logic.

-   :dart: **Smart Discovery**

    ---

    Tag-based service resolution with version constraints. Agents automatically find dependencies.

-   :material-kubernetes: **Kubernetes Native**

    ---

    Production-ready Helm charts with horizontal scaling, health checks, and observability.

-   :arrows_counterclockwise: **Dynamic Updates**

    ---

    Hot dependency injection without restarts. Add, remove, or upgrade services seamlessly.

-   :bar_chart: **Built-in Observability**

    ---

    Grafana dashboards, distributed tracing with Tempo, and Redis-backed session management.

-   :shield: **Enterprise Ready**

    ---

    Graceful failure handling, auto-reconnection, RBAC support, and real-time monitoring.

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

| Challenge | Traditional MCP | MCP Mesh |
|-----------|----------------|----------|
| **Connect 5 servers** | 200+ lines of networking code | 2 decorators |
| **Handle failures** | Manual error handling everywhere | Automatic graceful degradation |
| **Scale to production** | Custom Kubernetes setup | `helm install mcp-mesh` |
| **Monitor system** | Build custom dashboards | Built-in observability stack |
| **Add new capabilities** | Restart and reconfigure clients | Auto-discovery, zero downtime |

---

## :package: Installation Options

=== "PyPI"

    ```bash
    pip install "mcp-mesh>=0.5,<0.6"
    ```

=== "Homebrew"

    ```bash
    brew tap dhyansraj/mcp-mesh
    brew install mcp-mesh
    ```

=== "Docker"

    ```bash
    docker pull mcpmesh/registry:0.5.6
    docker pull mcpmesh/python-runtime:0.5.6
    ```

---

## :handshake: Community & Support

- [:fontawesome-brands-discord: Discord](https://discord.gg/KDFDREphWn) - Real-time help and discussions
- [:fontawesome-brands-github: GitHub Discussions](https://github.com/dhyansraj/mcp-mesh/discussions) - Share ideas and ask questions
- [:fontawesome-brands-github: Issues](https://github.com/dhyansraj/mcp-mesh/issues) - Report bugs or request features
- [:material-code-braces: Examples](https://github.com/dhyansraj/mcp-mesh/tree/main/examples) - Working code examples

---

## :star: Project Status

- **Latest Release**: v0.5.6 (September 2025)
- **License**: MIT
- **Language**: Python 3.11+ (runtime), Go 1.23+ (registry)
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

[Quick Tutorial](01-getting-started.md){ .md-button .md-button--primary }
[View on GitHub](https://github.com/dhyansraj/mcp-mesh){ .md-button }

**Star the repo** if MCP Mesh helps you build better AI systems! :star:

</div>
