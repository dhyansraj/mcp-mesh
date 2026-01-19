# Getting Started with MCP Mesh

> From zero to distributed MCP services in 10 minutes

## Overview

MCP Mesh makes building distributed MCP services as easy as writing Python functions. Add decorators to your classes and functions, and they automatically discover and use other services across your network.

## What is MCP Mesh?

MCP Mesh is a **distributed service mesh framework** that enhances FastMCP with automatic discovery and dependency injection:

- 🔌 **Dual decorators**: Combine familiar `@app.tool` (FastMCP) with `@mesh.tool` (orchestration)
- 🔍 **All MCP decorators**: Support for `@app.tool`, `@app.prompt`, `@app.resource` from FastMCP
- 💉 **Smart dependency injection**: Use remote functions with type safety (`mesh.McpMeshTool`)
- 🏷️ **Tag-based resolution**: Smart capability matching using tags and metadata
- 🚀 **Zero boilerplate**: Mesh discovers your FastMCP `app` and handles everything
- 📦 **Production ready**: Go registry + Python agents + Kubernetes support

## The Simplest Example

```python
import mesh
from fastmcp import FastMCP

# Single FastMCP server instance
app = FastMCP("Hello World Service")

# 1. Add a simple tool with dual decorators
@app.tool()  # ← FastMCP decorator (familiar MCP development)
@mesh.tool(capability="greeting")  # ← Mesh decorator (adds orchestration)
def greet(name: str = "World") -> str:
    return f"Hello, {name}!"

# 2. Add a tool with dependency injection
@app.tool()  # ← FastMCP handles MCP protocol
@mesh.tool(
    capability="advanced_greeting",
    dependencies=["date_service"]  # ← Mesh handles service discovery
)
async def greet_with_date(name: str = "World", date_service: mesh.McpMeshTool = None) -> str:
    if date_service:
        current_date = await date_service()  # Calls remote system agent
        return f"Hello, {name}! Today is {current_date}"
    return f"Hello, {name}! (Date service not available)"

# 3. Configure the agent
@mesh.agent(
    name="hello-world",
    http_port=9090,
    auto_run=True  # Mesh handles server startup automatically
)
class HelloWorldAgent:
    pass

# No main method needed! Mesh discovers 'app' and handles everything.
```

That's it! The **dual decorator pattern** gives you:

- **FastMCP decorators** (`@app.tool`) for familiar MCP development
- **Mesh decorators** (`@mesh.tool`) for dependency injection and orchestration
- **Automatic discovery** - Mesh finds your FastMCP `app` and handles server startup
- **Zero boilerplate** - No main methods or manual server management needed

## Prerequisites

Before you begin, ensure you have the required tools installed.

### Required

#### Python 3.11+

```bash
# Check version
python --version  # Should show 3.11 or higher

# Install if needed
# macOS
brew install python@3.11

# Ubuntu/Debian
sudo apt install python3.11

# Windows - download from https://python.org
```

#### Virtual Environment

MCP Mesh expects a `.venv` directory in your project root:

```bash
# Create virtual environment
python -m venv .venv

# Activate it
source .venv/bin/activate  # Linux/macOS
.venv\Scripts\activate      # Windows

# Install MCP Mesh SDK
pip install "mcp-mesh>=0.8,<0.9"
```

!!! tip "Why .venv?"
`meshctl start` automatically detects and uses `.venv` if present. This keeps your project dependencies isolated and consistent.

#### Docker & Docker Compose

Required for the Docker quick start and production deployments:

```bash
# Check installation
docker --version
docker compose version

# Install if needed
# macOS
brew install --cask docker  # Installs Docker Desktop

# Ubuntu
sudo apt install docker.io docker-compose-v2

# Windows - download Docker Desktop from https://docker.com
```

#### meshctl CLI

The `meshctl` command-line tool manages agents, registry, and scaffolding:

```bash
# Install via npm (recommended)
npm install -g @mcpmesh/cli
```

<details>
<summary>Alternative: Homebrew (macOS)</summary>

```bash
brew tap dhyansraj/mcp-mesh
brew install mcp-mesh
```

</details>

<details>
<summary>Alternative: Install Script (Linux/macOS)</summary>

```bash
curl -sSL https://raw.githubusercontent.com/dhyansraj/mcp-mesh/main/install.sh | bash
```

</details>

<details>
<summary>Alternative: Build from Source</summary>

```bash
git clone https://github.com/dhyansraj/mcp-mesh.git
cd mcp-mesh
make install-dev
# Binary available at ./bin/meshctl
```

</details>

Verify installation:

```bash
meshctl version
```

### Optional (for Kubernetes)

#### Helm

Required for deploying to Kubernetes:

```bash
# macOS
brew install helm

# Linux
curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash

# Verify
helm version
```

#### Minikube (Local Kubernetes)

For local Kubernetes development:

```bash
# macOS
brew install minikube

# Linux
curl -LO https://storage.googleapis.com/minikube/releases/latest/minikube-linux-amd64
sudo install minikube-linux-amd64 /usr/local/bin/minikube

# Windows
choco install minikube

# Start cluster
minikube start --cpus=4 --memory=8192
```

### Quick Check

Run this to verify your setup:

```bash
echo "=== MCP Mesh Prerequisites Check ==="
echo -n "Python: "; python --version 2>/dev/null || echo "❌ Not found"
echo -n "pip: "; pip --version 2>/dev/null | head -c 20 || echo "❌ Not found"
echo -n "Docker: "; docker --version 2>/dev/null | head -c 25 || echo "❌ Not found"
echo -n "meshctl: "; meshctl version 2>/dev/null || echo "❌ Not found (optional for Docker quick start)"
echo -n "Helm: "; helm version --short 2>/dev/null || echo "⚠️ Not found (optional)"
echo -n "Minikube: "; minikube version --short 2>/dev/null || echo "⚠️ Not found (optional)"
```

---

## Quick Start (Docker - 2 Minutes)

**Easiest way to get started:**

```bash
# 1. Clone the repository (for agent code)
git clone https://github.com/dhyansraj/mcp-mesh.git
cd mcp-mesh/examples/docker-examples

# 2. Start everything (uses published Docker images)
docker-compose up

# 3. Test it (in another terminal)
meshctl call hello_mesh_simple --agent-url http://localhost:8081
```

**Expected response:**

```json
{
  "content": [
    {
      "type": "text",
      "text": "👋 Hello from MCP Mesh! Today is December 11, 2025 at 03:30 PM"
    }
  ],
  "isError": false
}
```

That's it! You now have a working distributed MCP service mesh! 🎉

## Quick Start with meshctl (2 Minutes)

**The simplest way to run agents locally:**

```bash
# 1. Install MCP Mesh
pip install "mcp-mesh>=0.8,<0.9"

# 2. Clone examples
git clone https://github.com/dhyansraj/mcp-mesh.git
cd mcp-mesh/examples/simple

# 3. Start agents (registry starts automatically!)
meshctl start system_agent.py     # Terminal 1
meshctl start hello_world.py      # Terminal 2

# 4. Test it
meshctl call hello_mesh_simple
```

!!! tip "Auto-Registry"
`meshctl start` automatically starts the registry if one isn't running. No need to manage it separately!

## Alternative Installation Methods

<details>
<summary><strong>Homebrew (macOS)</strong></summary>

```bash
# Install CLI tools via Homebrew
brew tap dhyansraj/mcp-mesh
brew install mcp-mesh

# Then follow the Quick Start above
pip install "mcp-mesh>=0.8,<0.9"
```

</details>

<details>
<summary><strong>Install Script (Linux/macOS)</strong></summary>

```bash
# Install meshctl binary
curl -sSL https://raw.githubusercontent.com/dhyansraj/mcp-mesh/main/install.sh | bash

# Then follow the Quick Start above
pip install "mcp-mesh>=0.8,<0.9"
```

</details>

<details>
<summary><strong>Build from Source</strong></summary>

**For contributors:**

```bash
# Build everything
make install-dev

# Start agents
./bin/meshctl start examples/simple/system_agent.py   # Terminal 1
./bin/meshctl start examples/simple/hello_world.py    # Terminal 2

# Check status
./bin/meshctl status
```

</details>

## Learning Paths

**Choose your journey based on your goals:**

### 🚀 I want to see it working (5 minutes)

1. **[Docker Quick Start](03-docker-deployment.md)** - Complete environment
2. **Test the examples** - See dependency injection in action
3. **Explore with meshctl** - Understand the architecture

### 🔧 I want to develop agents (15 minutes)

1. **[Local Development Setup](02-local-development.md)** - Set up your environment
2. **Run examples locally** - Direct binary execution
3. **Modify an agent** - Make your first change
4. **Create new tools** - Add your own functionality

### 🏭 I want production deployment (30 minutes)

1. **[Kubernetes Guide](06-helm-deployment.md)** - Production-ready setup
2. **Deploy to cluster** - Scale and monitor
3. **Test resilience** - Failure scenarios
4. **Monitor with meshctl** - Operational insights

### 📚 I want to understand everything (60 minutes)

1. **Start with Docker** to see the big picture
2. **Try local development** to understand internals
3. **Deploy to Kubernetes** for production patterns
4. **Read the [architecture docs](architecture-and-design.md)** for deep understanding

## How MCP Mesh Works

```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│   Registry      │    │  Hello World     │    │  System Agent  │
│   (Go + DB)     │    │  Agent (Python)  │    │  (Python)       │
│   Port: 8000    │◄──►│  Port: 8081      │◄──►│  Port: 8082     │
│   [Discovery]   │    │  [Capabilities]  │    │  [Services]     │
└─────────────────┘    └──────────────────┘    └─────────────────┘
        ▲                         ▲                       ▲
        │               ┌─────────┴────────┐              │
        └───────────────│  meshctl Client  │──────────────┘
                        │  (CLI/Dashboard) │
                        └──────────────────┘

Your Code                    MCP Mesh Runtime               Automatic
┌─────────────────┐         ┌────────────────────┐        ┌──────────────┐
│ @mesh.agent     │────────▶│ • HTTP Wrapper     │◄──────│ • Registry   │
│ @mesh.tool      │         │ • Dependency Graph │       │ • Discovery  │
│ def my_func():  │◄────────│ • JSON-RPC/MCP     │       │ • Health     │
└─────────────────┘         └────────────────────┘        └──────────────┘
   You write this             Handles complexity            Runs for you
```

## Key Concepts in 30 Seconds

1. **Agents**: Python classes decorated with `@mesh.agent` that group related tools
2. **Tools**: Functions decorated with `@mesh.tool` that provide specific capabilities
3. **Registry**: Go service that tracks all agents and handles service discovery
4. **Capabilities**: What each tool provides (e.g., "date_service", "weather", "database")
5. **Dependencies**: What capabilities a tool needs from other agents
6. **Injection**: Remote functions automatically injected as function parameters
7. **meshctl**: CLI tool for managing, monitoring, and debugging the mesh

## Why Developers Love MCP Mesh

- **Zero boilerplate**: Just add decorators to existing functions
- **Graceful degradation**: Agents work standalone, enhance when connected
- **MCP protocol**: Full compatibility with existing MCP tools and clients
- **Local to production**: Same code runs locally, in Docker, and Kubernetes
- **Real-time updates**: Hot dependency injection without restarts
- **Operational visibility**: Built-in monitoring and debugging tools

## Ready to Start?

**Choose your path:**

- 🚀 **Quick Demo**: Try the [Docker deployment](03-docker-deployment.md)
- 🔧 **Local Development**: Follow the [local development guide](02-local-development.md)
- 🏭 **Production Setup**: Deploy with [Helm to Kubernetes](06-helm-deployment.md)
- 📚 **Deep Dive**: Read the [architecture and design](architecture-and-design.md)

---

💡 **Tip**: Start with Docker for the complete experience, then try local development for faster iteration.

📚 **Note**: All examples use the same core agents, so you can easily switch between deployment methods.

## 🔧 Troubleshooting

Common issues when getting started:

**Docker Issues:**

- **Port conflicts**: Change ports in `.env.local` file
- **Build failures**: Try `docker-compose build --no-cache`
- **Registry connection**: Check `docker-compose logs registry`

**Local Development Issues:**

- **Build errors**: Ensure Go 1.21+ and Python 3.11+ are installed
- **Registry not starting**: Check if port 8000 is available
- **Agent connection failures**: Verify registry is running first
- **Import errors**: Run `make install-dev` to install dependencies

**Testing Issues:**

- **Tool calls fail**: Use `/mcp` endpoint, not `/tools/call`
- **No dependency injection**: Wait 30-60 seconds for full mesh setup
- **JSON errors**: Ensure proper JSON-RPC format in curl commands

For detailed solutions, see the troubleshooting sections in each example README.

## ⚠️ Known Limitations

- **Windows Support**: Native Windows support is experimental; WSL2 or Docker recommended
- **Python 3.10 and below**: Not supported; requires Python 3.11+
- **Network Policies**: Strict firewall/network policies may block agent communication

## 🎯 What's Next?

After getting started:

### Explore the Examples

- Modify existing agents to understand the patterns
- Add new tools to see dependency injection in action
- Test resilience by stopping and starting agents

### Build Your Own Agent

```bash
# Generate a new agent with meshctl scaffold
meshctl scaffold --name my-agent --capability my_tool

# Or generate with Docker Compose
meshctl scaffold --name my-agent --compose
```

- Customize the generated agent code
- Add your own capabilities and dependencies
- Test integration with existing agents

### Scale to Production

- Deploy to Kubernetes for production workloads
- Set up monitoring and alerting
- Configure security and access controls

### Advanced Features

- Tag-based dependency resolution
- Multi-replica agent deployments
- Cross-namespace service discovery
- Custom capability development

## 📚 Additional Resources

- **[Local Development](02-local-development.md)** - Set up your development environment
- **[Docker Deployment](03-docker-deployment.md)** - Deploy agents with Docker Compose
- **[Kubernetes Deployment](06-helm-deployment.md)** - Production deployment with Helm
- **[meshctl CLI Reference](meshctl-cli.md)** - Command reference for meshctl
