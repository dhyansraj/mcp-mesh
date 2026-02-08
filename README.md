# <img src="docs/assets/images/logo-cyan.svg" height="32" alt=""> MCP Mesh

[![Release](https://github.com/dhyansraj/mcp-mesh/actions/workflows/release.yml/badge.svg?event=release)](https://github.com/dhyansraj/mcp-mesh/actions/workflows/release.yml)
[![Python Version](https://img.shields.io/badge/python-3.11+-blue.svg)](https://python.org)
[![Java Version](https://img.shields.io/badge/java-17+-orange.svg)](https://openjdk.org)
[![TypeScript](https://img.shields.io/badge/typescript-5.0+-blue.svg)](https://www.typescriptlang.org)
[![Go Version](https://img.shields.io/badge/go-1.23+-blue.svg)](https://golang.org)
[![Rust](https://img.shields.io/badge/rust-stable-orange.svg)](https://www.rust-lang.org)
[![PyPI](https://img.shields.io/pypi/v/mcp-mesh?color=blue&logo=pypi&logoColor=white)](https://pypi.org/project/mcp-mesh/)
[![npm](https://img.shields.io/npm/v/@mcpmesh/cli?color=red&logo=npm&logoColor=white)](https://www.npmjs.com/package/@mcpmesh/cli)
[![Docker](https://img.shields.io/badge/docker-hub-blue.svg?logo=docker&logoColor=white)](https://hub.docker.com/u/mcpmesh)
[![Helm](https://img.shields.io/badge/helm-charts-blue.svg?logo=helm&logoColor=white)](https://github.com/dhyansraj/mcp-mesh/pkgs/container/mcp-mesh%2Fmcp-mesh-core)
[![Discord](https://img.shields.io/discord/1386739813083779112?color=7289DA&label=Discord&logo=discord&logoColor=white)](https://discord.gg/KDFDREphWn)
[![YouTube](https://img.shields.io/badge/YouTube-MCPMesh-red?logo=youtube&logoColor=white)](https://www.youtube.com/@MCPMesh)
[![License](https://img.shields.io/badge/license-Open%20Source-blue.svg)](#license)

> **The future of AI is not one large model, but many specialized agents working together.**

<p align="center">
  <a href="https://dhyansraj.github.io/mcp-mesh/"><strong>📚 Documentation</strong></a> ·
  <a href="https://dhyansraj.github.io/mcp-mesh/python/getting-started/"><strong>🚀 Quick Start</strong></a> ·
  <a href="https://www.youtube.com/@MCPMesh"><strong>🎬 YouTube</strong></a> ·
  <a href="https://discord.gg/KDFDREphWn"><strong>💬 Discord</strong></a>
</p>

---

## ⚡ Getting Started

```bash
# Install the CLI
npm install -g @mcpmesh/cli

# Explore commands
meshctl --help

# Built-in documentation
meshctl man
```

**[Python Quick Start →](https://dhyansraj.github.io/mcp-mesh/python/getting-started/)** | **[Java Quick Start →](https://dhyansraj.github.io/mcp-mesh/java/getting-started/)** | **[TypeScript Quick Start →](https://dhyansraj.github.io/mcp-mesh/typescript/getting-started/)**

---

## 🎯 Why MCP Mesh?

You write the agent logic. The mesh discovers, connects, heals, and traces — across languages, machines, and clouds.

---

### **For Developers 👩‍💻**

**Stop fighting infrastructure. Start building intelligence.**

- **Zero Boilerplate**: Simple decorators/functions replace hundreds of lines of networking code
- **Python & TypeScript**: Write MCP servers as simple functions in your preferred language - no manual client/server setup
- **Web Framework Integration**: Inject MCP agents directly into FastAPI (Python) or Express (TypeScript) APIs seamlessly
- **LLM as Dependencies**: Inject LLMs just like MCP agents - dynamic prompts with Jinja2 (Python) or Handlebars (TypeScript)
- **Seamless Development Flow**: Code locally, test with Docker Compose, deploy to Kubernetes - same code, zero changes
- **kubectl-like Management**: `meshctl` - a familiar command-line tool to run, monitor, and manage your entire agent network

```python
# MCP Agent
@app.tool()
@mesh.tool(dependencies=["weather_service"])
def plan_trip(weather_service=None):
    # Just write business logic - mesh handles the rest

# FastAPI Route with MCP DI
@api.post("/trip-planning")
@mesh.route(dependencies=["plan_trip"])
async def create_trip(trip_data: dict, plan_trip=None):
    # Use MCP agents directly in your web API
    return plan_trip(trip_data)
```

---

### **For Solution Architects 🏗️**

**Design intelligent systems, not complex integrations.**

- **Agent-Centric Architecture**: Design specialized agents with clear capabilities and dependencies, not monolithic systems
- **Dynamic Intelligence**: Agents get smarter automatically when new capabilities come online - no reconfiguration needed
- **Domain-Driven Design**: Solve business problems with ecosystems of focused agents that can be designed and developed independently
- **Composable Solutions**: Mix and match agents to create new business capabilities without custom integration code

**Example**: Deploy a financial analysis agent that automatically discovers and uses risk assessment, market data, and compliance agents as they become available.

---

### **For DevOps & Platform Teams ⚙️**

**AI infrastructure out of the box.**

- **Kubernetes-Native**: Deploy with Helm charts - horizontal scaling, health checks, and service discovery included
- **Enterprise Observability**: Built-in Grafana dashboards, distributed tracing, and centralized logging for complete system visibility
- **Zero-Touch Operations**: Agents self-register, auto-discover dependencies, and gracefully handle failures without network restarts
- **Standards-Based**: Leverage existing Kubernetes patterns - RBAC, network policies, service mesh integration, and security policies

**Scale from 2 agents to 200+ with the same operational complexity.**

---

### **For Support & Operations 🛠️**

**Complete visibility and zero-downtime operations.**

- **Real-Time Network Monitoring**: See every agent, dependency, and health status in live dashboards
- **Intelligent Scaling**: Agents scale independently based on demand - no cascading performance issues
- **Graceful Failure Handling**: Agents degrade gracefully when dependencies are unavailable, automatically reconnect when services return
- **One-Click Diagnostics**: `meshctl status` provides instant network health assessment with actionable insights

---

### **For Engineering Leadership 📈**

**Transform AI experiments into production revenue.**

- **Accelerated Time-to-Market**: Move from PoC to production deployment in weeks, not months
- **Cross-Team Collaboration**: Enable different departments to build agents that automatically enhance each other's capabilities
- **Risk Mitigation**: Proven patterns help ensure reliable AI deployments that scale with your business
- **Future-Proof Architecture**: Add new AI capabilities without disrupting existing systems

**Turn your AI strategy from "promising experiments" to "competitive advantage in production."**

---

## Architecture Overview

![MCP Mesh Architecture](images/mcp-mesh_arch.png)

**MCP Mesh handles the complexity so you don't have to:**

- **Zero Boilerplate**: Just add `@mesh.tool()` - networking handled automatically
- **Dynamic Everything**: Add/remove/upgrade services without touching other code
- **Complex Apps Made Simple**: Financial services example shows 6+ interconnected agents
- **Production Ready**: Built-in resilience, distributed observability, and scaling

**The Magic**: Write simple functions in Python or TypeScript, get distributed systems.

---

## Key Features

### **Dynamic Dependency Injection & Service Discovery**

- **Pull-based discovery** with runtime function injection - no networking code required
- **Automatic agent discovery** without configuration
- **Smart dependency resolution** with version constraints and tags
- **Load balancing** across multiple service providers
- **LLM dependency injection** - treat LLMs as first-class dependencies with automatic tool discovery and dynamic prompts

### **Resilience**

- **Registry as facilitator** - agents communicate directly with fault tolerance
- **Self-healing architecture** - automatic reconnection when services return
- **Graceful degradation** - agents work standalone when dependencies unavailable
- **Background orchestration** - mesh coordinates without blocking business logic

### **Observability**

- **Complete observability stack** - Grafana dashboards, Tempo tracing, Redis session management
- **Distributed tracing** with OTLP export and cross-agent context propagation
- **Real-time trace streaming** for multi-agent workflow monitoring
- **Advanced session management** with Redis-backed stickiness across pod replicas

### **Developer Experience & Operations**

- **Near-complete MCP protocol support** for distributed networks
- **Enhanced proxy system** with kwargs-driven auto-configuration for timeouts, retries, streaming
- **meshctl CLI** for lifecycle management and network insights
- **Kubernetes native** with scaling, health checks, and comprehensive observability

---

## MCP Mesh vs Other AI Agent Frameworks

| Feature                                      | Other Frameworks  | MCP Mesh               |
| -------------------------------------------- | ----------------- | ---------------------- |
| **Zero-config Dependency Injection**         | ❌                | ✅                     |
| **Dynamic Agent Discovery & Hot Join/Leave** | ❌                | ✅                     |
| **Cross-language Support**                   | ❌                | ✅ Python + Java + TypeScript |
| **Same Code: Local → Docker → K8s**          | ❌ Rewrite needed | ✅                     |
| **Developer CLI (scaffold, trace, status)**  | ❌                | ✅ `meshctl`           |
| **Kubernetes-native (Helm)**                 | ❌ DIY            | ✅                     |
| **Distributed Tracing (OpenTelemetry)**      | ❌ DIY            | ✅ Grafana/Tempo       |
| **Auto-failover & Graceful Degradation**     | ❌                | ✅                     |
| **LLM as Dependency (Discovery + Failover)** | ❌                | ✅                     |
| **Zero-config Testing (Topology Mocking)**   | ❌                | ✅                     |
| **Standard Protocol**                        | ❌ Custom         | ✅ MCP                 |
| **Framework Lock-in**                        | High (classes)    | Low (decorators)       |
| **Lines of Code per Agent**                  | ~50+              | ~10                    |

**[See full comparison →](https://dhyansraj.github.io/mcp-mesh/comparison/)**

---

## Contributing

We welcome contributions from the community! MCP Mesh is designed to be a collaborative effort to advance the state of distributed MCP applications.

### How to Contribute

1. **[Check the Issues](https://github.com/dhyansraj/mcp-mesh/issues)** - Find good first issues or suggest new features
2. **[Join Discussions](https://github.com/dhyansraj/mcp-mesh/discussions)** - Share ideas and get help from the community
3. **[Submit Pull Requests](https://github.com/dhyansraj/mcp-mesh/pulls)** - Contribute code, documentation, or examples
4. **Follow our development guidelines** - See project structure and coding standards below

---

## Community & Support

- **[Discord](https://discord.gg/KDFDREphWn)** - Real-time help and discussions
- **[GitHub Discussions](https://github.com/dhyansraj/mcp-mesh/discussions)** - Share ideas and ask questions
- **[Issues](https://github.com/dhyansraj/mcp-mesh/issues)** - Report bugs or request features
- **[Examples](examples/)** - Working code examples and deployment patterns

---

## License

This project is open source. License details will be provided in the LICENSE file.

---

## Acknowledgments

- **[Anthropic](https://anthropic.com)** for creating the MCP protocol that inspired this project
- **[FastMCP](https://github.com/jlowin/fastmcp)** for providing excellent MCP server foundations
- **[Kubernetes](https://kubernetes.io)** community for building the infrastructure platform that makes this possible
- All the **contributors** who help make MCP Mesh better

---

## 📚 Learn More

1. **[📚 Full Documentation](https://dhyansraj.github.io/mcp-mesh/)** - Complete guides and reference
2. **[⚡ Quick Tutorial](https://dhyansraj.github.io/mcp-mesh/01-getting-started/)** - Build your first distributed MCP agent
3. **[💬 Join Discord](https://discord.gg/KDFDREphWn)** - Connect with the community
4. **[🔧 Contribute](https://dhyansraj.github.io/mcp-mesh/contributing/)** - Help build the future of AI orchestration

**Star the repo** if MCP Mesh helps you build better AI systems! ⭐
