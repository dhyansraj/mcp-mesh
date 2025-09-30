---
layout: default
title: Home
---

# MCP Mesh

> **The future of AI is not one large model, but many specialized agents working together.**

## 🎯 Enterprise-Grade Distributed Service Mesh for AI Agents

MCP Mesh transforms the Model Context Protocol (MCP) from a development protocol into an enterprise-grade distributed system. Build production-ready AI agent networks with zero boilerplate.

[![GitHub](https://img.shields.io/github/stars/dhyansraj/mcp-mesh?style=social)](https://github.com/dhyansraj/mcp-mesh)
[![PyPI](https://img.shields.io/pypi/v/mcp-mesh)](https://pypi.org/project/mcp-mesh/)
[![Documentation](https://img.shields.io/badge/docs-GitHub%20Pages-blue)](https://dhyansraj.github.io/mcp-mesh/)
[![Discord](https://img.shields.io/discord/1386739813083779112?color=7289DA&label=Discord&logo=discord&logoColor=white)](https://discord.gg/KDFDREphWn)

---

## 🚀 Quick Start

```bash
# Install MCP Mesh
pip install "mcp-mesh>=0.5,<0.6"

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

## ✨ Key Features

### 🔌 Zero Boilerplate
Two decorators (`@app.tool()` + `@mesh.tool()`) replace hundreds of lines of networking code. Just write business logic.

### 🎯 Smart Discovery
Tag-based service resolution with version constraints. Agents automatically find and connect to dependencies.

### ☸️ Kubernetes Native
Production-ready Helm charts with horizontal scaling, health checks, and comprehensive observability.

### 🔄 Dynamic Updates
Hot dependency injection without restarts. Add, remove, or upgrade services and agents adapt automatically.

### 📊 Built-in Observability
Grafana dashboards, distributed tracing with Tempo, and Redis-backed session management included.

### 🛡️ Enterprise Ready
Graceful failure handling, auto-reconnection, RBAC support, and real-time monitoring for production.

---

## 📚 Documentation

<div class="docs-grid">
  <div class="doc-card">
    <h3><a href="01-getting-started">⚡ Getting Started</a></h3>
    <p>Build your first distributed MCP agent in 10 minutes</p>
  </div>
  
  <div class="doc-card">
    <h3><a href="mesh-decorators">🔧 Mesh Decorators</a></h3>
    <p>Complete reference for @mesh.tool, @mesh.agent, and @mesh.route</p>
  </div>
  
  <div class="doc-card">
    <h3><a href="architecture-and-design">🏗️ Architecture</a></h3>
    <p>Understand how MCP Mesh works under the hood</p>
  </div>
  
  <div class="doc-card">
    <h3><a href="04-kubernetes-basics">☸️ Kubernetes</a></h3>
    <p>Deploy to production with Kubernetes and Helm</p>
  </div>
  
  <div class="doc-card">
    <h3><a href="07-observability">📊 Observability</a></h3>
    <p>Monitor and trace your distributed agent network</p>
  </div>
  
  <div class="doc-card">
    <h3><a href="environment-variables">⚙️ Configuration</a></h3>
    <p>Environment variables and configuration options</p>
  </div>
</div>

---

## 🌟 Why MCP Mesh?

### For Developers 👩‍💻
**Stop fighting infrastructure. Start building intelligence.**

- Zero boilerplate networking code
- Pure Python simplicity with FastMCP integration
- End-to-end FastAPI integration with `@mesh.route()`
- Same code runs locally, in Docker, and Kubernetes

### For Solution Architects 🏗️
**Design intelligent systems, not complex integrations.**

- Agent-centric architecture with clear capabilities
- Dynamic intelligence - agents get smarter automatically
- Domain-driven design with focused, composable agents
- Mix and match agents to create new capabilities

### For DevOps & Platform Teams ⚙️
**Production-ready AI infrastructure out of the box.**

- Kubernetes-native with battle-tested Helm charts
- Enterprise observability with Grafana, Tempo, and Redis
- Zero-touch operations with auto-discovery
- Scale from 2 agents to 200+ with same complexity

---

## 📦 Installation Options

### PyPI (Recommended)
```bash
pip install "mcp-mesh>=0.5,<0.6"
```

### Homebrew (macOS)
```bash
brew tap dhyansraj/mcp-mesh
brew install mcp-mesh
```

### Docker
```bash
docker pull mcpmesh/registry:0.5.6
docker pull mcpmesh/python-runtime:0.5.6
```

---

## 🎯 MCP vs MCP Mesh

| Challenge | Traditional MCP | MCP Mesh |
|-----------|----------------|----------|
| **Connect 5 servers** | 200+ lines of networking code | 2 decorators |
| **Handle failures** | Manual error handling everywhere | Automatic graceful degradation |
| **Scale to production** | Custom Kubernetes setup | `helm install mcp-mesh` |
| **Monitor system** | Build custom dashboards | Built-in observability stack |
| **Add new capabilities** | Restart and reconfigure clients | Auto-discovery, zero downtime |

---

## 🤝 Community & Support

- **[Discord](https://discord.gg/KDFDREphWn)** - Real-time help and discussions
- **[GitHub Discussions](https://github.com/dhyansraj/mcp-mesh/discussions)** - Share ideas and ask questions
- **[Issues](https://github.com/dhyansraj/mcp-mesh/issues)** - Report bugs or request features
- **[Examples](https://github.com/dhyansraj/mcp-mesh/tree/main/examples)** - Working code examples

---

## 📈 Project Status

- **Latest Release**: v0.5.6 (September 2025)
- **License**: MIT
- **Language**: Python 3.11+ (runtime), Go 1.23+ (registry)
- **Status**: Production-ready, actively developed

---

## 🙏 Acknowledgments

- **[Anthropic](https://anthropic.com)** for creating the MCP protocol
- **[FastMCP](https://github.com/jlowin/fastmcp)** for excellent MCP server foundations
- **[Kubernetes](https://kubernetes.io)** community for the infrastructure platform
- All **contributors** who help make MCP Mesh better

---

<div style="text-align: center; margin-top: 40px;">
  <p><strong>Ready to get started?</strong></p>
  <p>
    <a href="01-getting-started" style="background: #667eea; color: white; padding: 12px 30px; border-radius: 6px; text-decoration: none; font-weight: bold;">Get Started →</a>
    <a href="https://github.com/dhyansraj/mcp-mesh" style="background: #2d3748; color: white; padding: 12px 30px; border-radius: 6px; text-decoration: none; font-weight: bold; margin-left: 10px;">View on GitHub →</a>
  </p>
  <p style="margin-top: 20px;">
    <strong>Star the repo</strong> if MCP Mesh helps you build better AI systems! ⭐
  </p>
</div>

<style>
.docs-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 20px;
  margin: 30px 0;
}

.doc-card {
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 20px;
  background: #f7fafc;
  transition: all 0.3s;
}

.doc-card:hover {
  border-color: #667eea;
  box-shadow: 0 4px 6px rgba(102, 126, 234, 0.1);
  transform: translateY(-2px);
}

.doc-card h3 {
  margin-top: 0;
  margin-bottom: 10px;
}

.doc-card h3 a {
  color: #667eea;
  text-decoration: none;
}

.doc-card h3 a:hover {
  text-decoration: underline;
}

.doc-card p {
  margin: 0;
  color: #4a5568;
  font-size: 0.95em;
}
</style>
