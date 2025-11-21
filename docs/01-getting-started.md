# Getting Started with MCP Mesh

> From zero to distributed MCP services in 10 minutes

## Overview

MCP Mesh makes building distributed MCP services as easy as writing Python functions. Add decorators to your classes and functions, and they automatically discover and use other services across your network.

## What is MCP Mesh?

MCP Mesh is a **distributed service mesh framework** that enhances FastMCP with automatic discovery and dependency injection:

- 🔌 **Dual decorators**: Combine familiar `@app.tool` (FastMCP) with `@mesh.tool` (orchestration)
- 🔍 **All MCP decorators**: Support for `@app.tool`, `@app.prompt`, `@app.resource` from FastMCP
- 💉 **Smart dependency injection**: Use remote functions with type safety (`mesh.McpMeshAgent`)
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
def greet_with_date(name: str = "World", date_service: mesh.McpMeshAgent = None) -> str:
    if date_service:
        current_date = date_service()  # Calls remote system agent
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

## Quick Start (Docker - 2 Minutes)

**Easiest way to get started:**

```bash
# 1. Clone the repository (for agent code)
git clone https://github.com/dhyansraj/mcp-mesh.git
cd mcp-mesh/examples/docker-examples

# 2. Start everything (uses published Docker images)
docker-compose up

# 3. Test it (in another terminal)
curl -s -X POST http://localhost:8081/mcp \
  -H "Content-Type: application/json" \
  -d '{"method": "tools/call", "params": {"name": "hello_mesh_simple", "arguments": {}}}' | jq .
```

**Expected response:**

```json
{
  "result": "Hello from MCP Mesh! Today is 2025-06-19 15:30:42"
}
```

That's it! You now have a working distributed MCP service mesh! 🎉

## Alternative: macOS with Homebrew (2 Minutes)

**For macOS users with Homebrew:**

```bash
# 1. Install MCP Mesh CLI tools
brew tap dhyansraj/mcp-mesh
brew install mcp-mesh

# 2. Install Python package with semantic versioning
pip install "mcp-mesh>=0.6,<0.7"

# 3. Download example agents
git clone https://github.com/dhyansraj/mcp-mesh.git
cd mcp-mesh/examples/simple

# 4. Start registry and agents
mcp-mesh-registry --host 0.0.0.0 --port 8000 &
python system_agent.py &
python hello_world.py &

# 5. Test it
curl -s -X POST http://localhost:8080/mcp \
  -H "Content-Type: application/json" \
  -d '{"method": "tools/call", "params": {"name": "hello_mesh_simple", "arguments": {}}}' | jq .
```

## Alternative: Linux/macOS Install Script (3 Minutes)

**For Linux or manual macOS installation:**

```bash
# 1. Install MCP Mesh with semantic versioning (allows patch updates)
pip install "mcp-mesh>=0.6,<0.7"

# 2. Download and start registry (use minor version for latest patches)
curl -sSL https://raw.githubusercontent.com/dhyansraj/mcp-mesh/main/install.sh | bash -s -- --registry-only --version v0.5
mcp-mesh-registry --host 0.0.0.0 --port 8000 &

# 3. Download example agents
git clone https://github.com/dhyansraj/mcp-mesh.git
cd mcp-mesh/examples/simple

# 4. Run agents
python system_agent.py &
python hello_world.py &

# 5. Test it
curl -s -X POST http://localhost:8080/mcp \
  -H "Content-Type: application/json" \
  -d '{"method": "tools/call", "params": {"name": "hello_mesh_simple", "arguments": {}}}' | jq .
```

## Alternative: Local Development (5 Minutes)

**For developers who want to build from source:**

```bash
# 1. Build the project
make install-dev

# 2. Start registry (terminal 1)
./bin/meshctl start-registry

# 3. Start system agent (terminal 2)
./bin/meshctl start examples/simple/system_agent.py

# 4. Start hello world agent (terminal 3)
./bin/meshctl start examples/simple/hello_world.py

# 5. Test it
./bin/meshctl list agents
```

## Learning Paths

**Choose your journey based on your goals:**

### 🚀 I want to see it working (5 minutes)

1. **[Docker Quick Start](../../examples/docker-examples/README.md)** - Complete environment
2. **Test the examples** - See dependency injection in action
3. **Explore with meshctl** - Understand the architecture

### 🔧 I want to develop agents (15 minutes)

1. **[Local Development Setup](../../examples/simple/README.md)** - Build from source
2. **Run examples locally** - Direct binary execution
3. **Modify an agent** - Make your first change
4. **Create new tools** - Add your own functionality

### 🏭 I want production deployment (30 minutes)

1. **[Kubernetes Guide](../../examples/k8s/README.md)** - Production-ready setup
2. **Deploy to cluster** - Scale and monitor
3. **Test resilience** - Failure scenarios
4. **Monitor with meshctl** - Operational insights

### 📚 I want to understand everything (60 minutes)

1. **Start with Docker** to see the big picture
2. **Try local development** to understand internals
3. **Deploy to Kubernetes** for production patterns
4. **Read the architecture docs** for deep understanding

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

- 🚀 **Quick Demo**: Try the [Docker examples](../../examples/docker-examples/README.md)
- 🔧 **Local Development**: Follow the [simple examples guide](../../examples/simple/README.md)
- 🏭 **Production Setup**: Deploy with [Kubernetes](../../examples/k8s/README.md)
- 📚 **Deep Dive**: Read the [complete examples overview](../../examples/README.md)

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

- **Build errors**: Ensure Go 1.21+ and Python 3.9+ are installed
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
- **Python 3.8**: Not supported; requires Python 3.9+
- **PyPI Package**: Not yet published; must build from source or use Docker
- **ARM Architecture**: Some Go binary builds may need local compilation
- **Network Policies**: Strict firewall/network policies may block agent communication

## 🎯 What's Next?

After getting started:

1. **Explore the Examples**:
   - Modify existing agents to understand the patterns
   - Add new tools to see dependency injection in action
   - Test resilience by stopping and starting agents

2. **Build Your Own Agent**:
   - Copy `hello_world.py` as a template
   - Add your own capabilities and dependencies
   - Test integration with existing agents

3. **Scale to Production**:
   - Deploy to Kubernetes for production workloads
   - Set up monitoring and alerting
   - Configure security and access controls

4. **Advanced Features**:
   - Tag-based dependency resolution
   - Multi-replica agent deployments
   - Cross-namespace service discovery
   - Custom capability development

## 📚 Additional Resources

- **[Examples Overview](../../examples/README.md)** - Compare all deployment options
- **[Docker Examples](../../examples/docker-examples/README.md)** - Complete containerized setup
- **[Kubernetes Examples](../../examples/k8s/README.md)** - Production deployment
- **[Local Development](../../examples/simple/README.md)** - Build and run from source
