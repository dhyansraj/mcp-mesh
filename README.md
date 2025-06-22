# MCP Mesh

[![Release](https://github.com/dhyansraj/mcp-mesh/actions/workflows/release.yml/badge.svg)](https://github.com/dhyansraj/mcp-mesh/actions/workflows/release.yml)
[![Go Version](https://img.shields.io/badge/go-1.23+-blue.svg)](https://golang.org)
[![Python Version](https://img.shields.io/badge/python-3.11+-blue.svg)](https://python.org)
[![Docker](https://img.shields.io/badge/docker-ready-blue.svg)](https://hub.docker.com/u/mcpmesh)
[![Kubernetes](https://img.shields.io/badge/kubernetes-ready-green.svg)](https://kubernetes.io)
[![License](https://img.shields.io/badge/license-Open%20Source-blue.svg)](#license)

> **MCP Mesh extends the MCP ecosystem** to Kubernetes and distributed environments, bringing the same elegant simplicity of MCP to production-scale deployments with just two Python decorators. **MCP is revolutionizing AI tool integration** - but what if you could scale MCP applications across distributed infrastructure as easily as running them locally?

A Kubernetes-native platform for building and orchestrating distributed MCP (Model Context Protocol) applications with dynamic dependency injection. Each agent runs independently but can dynamically discover and connect to other capabilities in the mesh.

## Key Features

### **Dynamic Dependency Injection**

- **Pull-based capability discovery**: Agents declare what they need, registry coordinates who provides it
- **Runtime function injection**: Python runtime automatically injects remote capabilities as function parameters
- **Transparent remote calls**: Call functions on other agents exactly like local functions - no networking code required
- **Hot-swappable dependencies**: Add, remove, or update capabilities without restarting services
- **Graceful degradation**: Agents work standalone and enhance when dependencies become available

### **Resilient Architecture**

- **Registry as facilitator, not gatekeeper**: Service discovery through registry, but MCP calls flow directly between agents
- **Network-aware proxy generation**: Python runtime creates HTTP proxies for seamless remote MCP communication
- **Fault tolerance**: Agents continue working if registry becomes unavailable
- **Self-healing connections**: Automatic reconnection when services come back online

### **MCP Protocol Enhancement**

- **Full MCP compatibility**: Works with existing MCP clients and tools
- **Extended capabilities**: Advanced dependency resolution with version constraints and tags
- **Dynamic topology**: Real-time capability updates as services join or leave the mesh
- **Protocol transparency**: Remote calls look identical to local function calls

### **Production-Ready Infrastructure**

- **Kubernetes-native**: Deploy agents as independent pods with automatic scaling
- **Database flexibility**: SQLite for development, PostgreSQL for production
- **Multi-environment support**: Local development, Docker Compose, and Kubernetes deployment
- **Service mesh architecture**: Intelligent routing and load balancing between agents

### **Developer Experience**

- **Two-decorator architecture**: Build distributed MCP agents with just `@mesh.agent` and `@mesh.tool`
- **Zero boilerplate**: No manual server setup, routing, or service discovery code required
- **Local-to-distributed**: Same code works locally and scales to Kubernetes automatically
- **Familiar patterns**: Standard Python functions become distributed capabilities

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        MCP Mesh Architecture                    │
│                                                                 │
│  ┌─────────────────┐    ┌─────────────────┐    ┌─────────────┐  │
│  │   Agent A       │    │   Agent B       │    │   Agent C   │  │
│  │   @mesh.tool    │    │   @mesh.tool    │    │ @mesh.tool  │  │
│  │   ┌───────────┐ │    │   ┌───────────┐ │    │ ┌─────────┐ │  │
│  │   │FastMCP    │ │    │   │FastMCP    │ │    │ │FastMCP  │ │  │
│  │   │Server     │ │    │   │Server     │ │    │ │Server   │ │  │
│  │   └───────────┘ │    │   └───────────┘ │    │ └─────────┘ │  │
│  └─────────────────┘    └─────────────────┘    └─────────────┘  │
│           │                       │                     │       │
│           └───────────────────────┼─────────────────────┘       │
│                                   │                             │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │                    Registry Service                        │ │
│  │                                                            │ │
│  │  ┌─────────────────┐    ┌────────────────────────────────┐ │ │
│  │  │   Capability    │    │     Dependency Resolution      │ │ │
│  │  │   Discovery     │    │     & URL Coordination         │ │ │
│  │  └─────────────────┘    └────────────────────────────────┘ │ │
│  │                                                            │ │
│  │  ┌─────────────────┐    ┌────────────────────────────────┐ │ │
│  │  │   Health        │    │     Agent Lifecycle            │ │ │
│  │  │   Monitoring    │    │     Management                 │ │ │
│  │  └─────────────────┘    └────────────────────────────────┘ │ │
│  └────────────────────────────────────────────────────────────┘ │
│                                   │                             │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │                    Database Layer                          │ │
│  │              SQLite (dev) / PostgreSQL (prod)              │ │
│  └────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘

Flow: Agents register capabilities → Registry provides dependency URLs →
      Python runtime creates HTTP proxies → Dynamic injection enables remote MCP calls
```

### How Dynamic Injection Works

1. **Agent Registration**: Agents declare capabilities and dependencies using `@mesh.tool` decorators
2. **Registry Coordination**: Central registry provides discovery URLs for available capabilities
3. **Runtime Injection**: Python runtime creates HTTP proxies for remote MCP calls
4. **Transparent Access**: Remote capabilities work exactly like local function calls

**The Magic**: No manual networking code - just declare what you need with two decorators!

## Quick Start

### See MCP Mesh in Action

![MCP Mesh Demo](demo.gif)

_MCP Mesh sets the stage, but MCP agents steal the show! Watch as agents dynamically discover dependencies, gracefully degrade when services go down, and seamlessly reconnect when they come back online._

### Simple Agent Example

```python
#!/usr/bin/env python3
import mesh

@mesh.agent(name="hello-world")
class HelloWorldAgent:
    pass

@mesh.tool(
    capability="greeting",
    dependencies=["date_service"],
    description="Greet with current date"
)
def hello_mesh(date_service=None) -> str:
    if date_service is None:
        return "👋 Hello from MCP Mesh! (Date service not available yet)"

    try:
        current_date = date_service()
        return f"👋 Hello from MCP Mesh! Today is {current_date}"
    except Exception as e:
        return f"👋 Hello from MCP Mesh! (Error getting date: {e})"

# That's it! No manual server setup required.
# The agent will automatically:
# - Start a FastMCP server
# - Register with the mesh registry
# - Acquire dependencies when available
# - Provide capabilities to other agents
```

### System Service Agent

```python
#!/usr/bin/env python3
import mesh
from datetime import datetime

@mesh.agent(name="system-agent")
class SystemAgent:
    pass

@mesh.tool(
    capability="date_service",
    description="Get current system date and time",
    tags=["system", "time"]
)
def get_current_time() -> str:
    now = datetime.now()
    return now.strftime("%B %d, %Y at %I:%M %p")

# This agent provides the "date_service" capability
# that hello-world agent depends on
```

### See It In Action

```bash
# Start the system agent (provides date_service)
python system_agent.py &

# Start the hello world agent (consumes date_service)
python hello_world.py &

# Test the dynamic dependency injection
curl http://localhost:9090/mcp -X POST \
  -H "Content-Type: application/json" \
  -d '{"method": "tools/call", "params": {"name": "hello_mesh", "arguments": {}}}'

# Response: "👋 Hello from MCP Mesh! Today is December 19, 2024 at 02:30 PM"
```

**The magic**: `hello_world.py` automatically discovered and connected to `system_agent.py` without any manual configuration!

## 📦 Installation

### Python Package (Recommended)

```bash
# Install with semantic versioning (allows patches, not minor versions)
pip install "mcp-mesh>=0.1.0,<0.2.0"
```

### CLI Tools

```bash
# Install meshctl and registry binaries
curl -sSL https://raw.githubusercontent.com/dhyansraj/mcp-mesh/main/install.sh | bash
```

### Docker Images

```bash
# Registry service (gets latest patches for 0.1.x)
docker pull mcpmesh/registry:0.1

# Python runtime for agents (gets latest patches for 0.1.x)
docker pull mcpmesh/python-runtime:0.1

# CLI tools (gets latest patches for 0.1.x)
docker pull mcpmesh/cli:0.1
```

### Quick Setup Options

| Method             | Best For                | Command                                            |
| ------------------ | ----------------------- | -------------------------------------------------- |
| **Docker Compose** | Getting started quickly | `cd examples/docker-examples && docker-compose up` |
| **Python Package** | Agent development       | `pip install "mcp-mesh>=0.1.0,<0.2.0"`             |
| **Kubernetes**     | Production deployment   | `kubectl apply -k examples/k8s/base/`              |

> **🔧 For Development**: See [Local Development Guide](docs/02-local-development.md) to build from source.

### Real-World Example: Distributed Chat History Service

Here's a more practical example showing how MCP Mesh handles distributed data services like Redis caching for chat history - a common requirement in AI applications:

```python
# cache_service.py - Redis-backed chat history service
import mesh
import redis
import json
from typing import List, Dict, Any
from datetime import datetime

@mesh.agent(name="cache-service")
class CacheService:
    def __init__(self):
        self.redis_client = redis.Redis(host='redis', port=6379, decode_responses=True)

@mesh.tool(
    capability="chat_storage",
    description="Store and retrieve chat history from Redis cache",
    version="1.0.0",
    tags=["cache", "redis", "chat"]
)
def add_chat(user_id: str, message: str, role: str = "user") -> bool:
    """Add a chat message to user's history."""
    chat_entry = {
        "message": message,
        "role": role,
        "timestamp": datetime.now().isoformat()
    }

    # Store in Redis list with user-specific key
    key = f"chat_history:{user_id}"
    redis_client.lpush(key, json.dumps(chat_entry))
    redis_client.ltrim(key, 0, 99)  # Keep last 100 messages
    return True

@mesh.tool(
    capability="chat_retrieval",
    description="Get chat history for a user",
    version="1.0.0",
    tags=["cache", "redis", "chat"]
)
def get_chats(user_id: str, limit: int = 10) -> List[Dict[str, Any]]:
    """Retrieve recent chat messages for a user."""
    key = f"chat_history:{user_id}"
    messages = redis_client.lrange(key, 0, limit - 1)
    return [json.loads(msg) for msg in messages]
```

```python
# ai_assistant.py - Main AI assistant that uses chat history
import mesh
from mesh import McpMeshAgent
from typing import List, Dict, Any

@mesh.agent(name="ai-assistant")
class AIAssistant:
    pass

@mesh.tool(
    capability="chat_with_history",
    dependencies=[
        {"capability": "chat_storage", "version": ">= 1.0"},
        {"capability": "chat_retrieval", "version": ">= 1.0"}
    ],
    description="AI chat with persistent history"
)
def chat_with_context(
    user_id: str,
    message: str,
    add_chat: McpMeshAgent = None,      # Injected: cache_service.add_chat
    get_chats: McpMeshAgent = None      # Injected: cache_service.get_chats
) -> str:
    """Process user message with chat history context."""

    # Get previous conversation context
    history = []
    if get_chats:
        try:
            history = get_chats(user_id, limit=5)
        except Exception as e:
            print(f"Failed to get chat history: {e}")

    # Build context from history
    context = "Previous conversation:\n"
    for chat in reversed(history):
        context += f"{chat['role']}: {chat['message']}\n"

    # Generate AI response (simplified)
    ai_response = f"Based on our conversation, here's my response to: {message}"

    # Store both user message and AI response
    if add_chat:
        try:
            add_chat(user_id, message, "user")
            add_chat(user_id, ai_response, "assistant")
        except Exception as e:
            print(f"Failed to store chat: {e}")

    return ai_response
```

```bash
# Deploy to Kubernetes with Redis
kubectl apply -f - <<EOF
apiVersion: apps/v1
kind: Deployment
metadata:
  name: redis
spec:
  replicas: 1
  selector:
    matchLabels:
      app: redis
  template:
    metadata:
      labels:
        app: redis
    spec:
      containers:
      - name: redis
        image: redis:alpine
        ports:
        - containerPort: 6379
---
apiVersion: v1
kind: Service
metadata:
  name: redis
spec:
  selector:
    app: redis
  ports:
  - port: 6379
EOF

# Test the distributed chat system (port auto-assigned by MCP Mesh)
curl http://localhost:$(meshctl list --filter ai-assistant --json | jq -r '.[0].http_port')/mcp -X POST \
  -H "Content-Type: application/json" \
  -d '{
    "method": "tools/call",
    "params": {
      "name": "chat_with_context",
      "arguments": {
        "user_id": "user123",
        "message": "Hello, can you help me with Python?"
      }
    }
  }'
```

**Key Benefits Demonstrated:**

- **Service Separation**: Cache service runs independently from AI assistant
- **Automatic Discovery**: AI assistant finds cache service without hardcoded Redis URLs
- **Version Constraints**: Ensures compatible cache service versions (`>= 1.0`)
- **Graceful Degradation**: Chat works even if cache service is unavailable
- **Kubernetes Ready**: Easy to scale cache and AI services independently

## Why MCP Mesh?

While the Model Context Protocol (MCP) provides an excellent foundation for AI tool integration, scaling MCP applications in production environments presents unique challenges. MCP Mesh addresses these common pain points with a Kubernetes-native approach:

### **Service Discovery & Orchestration**

- **Challenge**: MCP applications typically require manual configuration to connect multiple servers, limiting dynamic service composition
- **Solution**: Automatic service discovery with registry-based coordination allows agents to find and connect to capabilities without hardcoded configurations

### **Scaling & Load Balancing**

- **Challenge**: Running multiple MCP servers requires external proxy tools and complex load balancing setups
- **Solution**: Native horizontal scaling with health-based routing distributes requests across available agent instances automatically

### **Development Complexity**

- **Challenge**: Setting up multi-server MCP environments involves significant boilerplate code and manual orchestration
- **Solution**: Two simple decorators (`@mesh.agent` + `@mesh.tool`) provide the same functionality with zero configuration overhead

### **Production Deployment**

- **Challenge**: Limited guidance exists for deploying MCP applications at scale with proper monitoring and fault tolerance
- **Solution**: Complete Kubernetes manifests, PostgreSQL integration, and production-ready observability out of the box

### **Dependency Management**

- **Challenge**: No standardized way to handle versioned dependencies or capability requirements between MCP servers
- **Solution**: Semantic versioning with constraint matching (e.g., `>= 2.0`) and tag-based capability selection for precise dependency resolution

### **Reliability & Fault Tolerance**

- **Challenge**: MCP server connection issues and shutdown problems can affect application stability
- **Solution**: Resilient architecture where agents work standalone and gracefully handle registry failures while maintaining service continuity

MCP Mesh transforms MCP from a point-to-point protocol into a distributed service mesh, making production-scale MCP deployments as simple as developing locally.

## Vision: Global AI Agent Network

MCP Mesh's architecture naturally enables a distributed ecosystem where AI agents can discover and collaborate across organizational and geographical boundaries. The same technology powering enterprise deployments can scale to support industry-wide cooperation.

### **Technical Foundation for Cross-Cluster Federation**

The registry-based discovery model supports federated architectures where agents from different Kubernetes clusters can participate in a shared capability network:

```yaml
# Multi-cluster registry federation
apiVersion: v1
kind: ConfigMap
metadata:
  name: registry-federation
data:
  federation.yaml: |
    primary_registry: "https://registry.my-org.com"
    federated_registries:
      - url: "https://public-registry.ai-consortium.org"
        trust_level: "verified"
        capabilities: ["translation", "analysis", "computation"]
      - url: "https://academic-registry.university.edu"
        trust_level: "research"
        capabilities: ["research_tools", "data_analysis"]
```

### **Potential Industry Applications**

**Enterprise Collaboration**: Organizations could share specialized AI capabilities while maintaining security boundaries - imagine a financial analysis agent discovering legal compliance tools from a partner firm's cluster, or supply chain optimization agents coordinating across vendor networks.

**Research Networks**: Academic institutions could pool computational resources and specialized models, allowing researchers worldwide to access domain-specific AI tools without complex bilateral agreements.

**Industry Standards**: Professional consortia could establish common capability registries, enabling standardized AI tool interfaces across competing platforms while preserving competitive differentiation in implementation.

### **Governance and Trust Framework**

Such a network would require:

- **Capability Verification**: Cryptographic signatures and reputation systems for agent capabilities
- **Access Control**: Fine-grained permissions based on organizational membership and trust relationships
- **Economic Models**: Usage metering and compensation mechanisms for capability providers
- **Quality Assurance**: SLA monitoring and capability performance benchmarking

### **Current State and Roadmap**

Today, MCP Mesh provides the core infrastructure patterns needed for this vision:

- ✅ **Registry Federation**: Multiple registries can already cross-reference capabilities
- ✅ **Security Boundaries**: Namespace isolation and RBAC controls
- ✅ **Standard Protocols**: HTTP APIs and MCP compatibility ensure interoperability
- 🔄 **In Development**: Enhanced authentication, capability verification, and cross-cluster networking
- 📋 **Future Work**: Economic frameworks, reputation systems, and governance tooling

The technology exists; what's needed is community coordination and trust frameworks. MCP Mesh provides the infrastructure foundation for organizations ready to explore collaborative AI agent networks.

## Installation

### One-Line Install (Recommended)

```bash
# Install everything with one command (requires curl and Python 3.11+)
curl -sSL https://raw.githubusercontent.com/dhyansraj/mcp-mesh/main/install.sh | bash -s -- --version v0.1
```

### Package Manager Installation

```bash
# Python package from PyPI (allows patch updates)
pip install "mcp-mesh>=0.1.0,<0.2.0"

# Docker images (use minor version tag for latest patches)
docker pull mcpmesh/registry:0.1
docker pull mcpmesh/python-runtime:0.1
docker pull mcpmesh/cli:0.1

# Download CLI binary directly (specific version)
curl -L https://github.com/dhyansraj/mcp-mesh/releases/download/v0.1.6/mcp-mesh_v0.1.6_linux_amd64.tar.gz | tar xz
sudo mv meshctl /usr/local/bin/
```

### Development Installation

```bash
# Clone and build from source
git clone https://github.com/dhyansraj/mcp-mesh.git
cd mcp-mesh
make install
```

For detailed installation options, see our [Installation Guide](docs/01-getting-started/02-installation.md).

## meshctl CLI Tool

MCP Mesh includes `meshctl`, a kubectl-like command-line tool for observing and monitoring the MCP Mesh network. It provides comprehensive visibility into distributed agent topologies with additional support for local development workflows.

### Key Capabilities

- **Network observability**: Monitor distributed agent topologies across environments
- **Real-time status monitoring**: View agent health, dependencies, and connectivity
- **Multi-environment support**: Connect to local, Docker, or Kubernetes registries
- **Beautiful visualizations**: kubectl-style table displays with filtering and sorting
- **Dependency tracking**: Observe capability resolution and injection status
- **Local development support**: Start agents for development and testing

### Monitoring Commands

```bash
# Observe all agents in the mesh network (kubectl-style)
./bin/meshctl list

# Monitor with detailed dependency information
./bin/meshctl list --wide --verbose

# Filter agents by name pattern
./bin/meshctl list --filter hello

# Show only healthy agents
./bin/meshctl list --healthy-only

# Connect to remote registry (Docker/K8s)
./bin/meshctl list --registry-url http://production-registry:8000

# Monitor Kubernetes registry
./bin/meshctl list --registry-url http://mcp-mesh-registry.mcp-mesh:8000

# JSON output for automation/scripting
./bin/meshctl list --json

# Show detailed status of entire mesh
./bin/meshctl status

# Monitor agents in real-time
watch ./bin/meshctl list --wide
```

### Local Development Support

```bash
# Start registry for local development
./bin/meshctl start --registry-only

# Start agent with development features
./bin/meshctl start examples/simple/hello_world.py --auto-restart --watch-files

# Start multiple agents for testing
./bin/meshctl start examples/simple/hello_world.py examples/simple/system_agent.py
```

### Available Commands

| Command              | Description                                   | Primary Use     |
| -------------------- | --------------------------------------------- | --------------- |
| `meshctl list`       | Display running agents with dependency status | **Monitoring**  |
| `meshctl status`     | Show detailed mesh network health             | **Monitoring**  |
| `meshctl start`      | Start agents (local development)              | **Development** |
| `meshctl config`     | Manage configuration settings                 | **Management**  |
| `meshctl completion` | Generate shell autocompletion                 | **Utilities**   |

### Observability Features

- **kubectl-style interface**: Familiar command patterns for Kubernetes users
- **Real-time monitoring**: Live status updates of agent health and dependencies
- **Multi-environment connectivity**: Monitor local, Docker, and Kubernetes registries
- **Filtering and sorting**: Find specific agents in large topologies
- **JSON output**: Integrate with monitoring and automation tools
- **Dependency visualization**: Understand capability resolution and injection status

## Why MCP Mesh? Scaling MCP to Production

### MCP's Success Creates New Opportunities

The MCP ecosystem has proven that standardized AI tool integration works brilliantly. Now teams want to:

- 🚀 Scale successful MCP applications across multiple machines
- 🏗️ Deploy MCP tools in production Kubernetes environments
- 🔄 Distribute MCP capabilities across microservices
- 📈 Build resilient, fault-tolerant MCP architectures

### MCP Mesh: Built for MCP Developers

- ✅ **Keep your existing MCP knowledge**: Same concepts, bigger scale
- ✅ **Just two decorators**: `@mesh.agent` and `@mesh.tool`
- ✅ **MCP protocol compatible**: Works with existing MCP clients and tools
- ✅ **Kubernetes-native**: Production-ready infrastructure patterns
- ✅ **Gradual adoption**: Start small, scale as needed
- ✅ **Community-driven**: Extending MCP together

### Beyond Traditional Approaches

While existing solutions focus on static tool definitions or centralized orchestration, MCP Mesh introduces:

- **Pull-based dependency model**: Agents declare what they need, registry coordinates discovery, Python runtime handles injection
- **Registry as facilitator, not gatekeeper**: Service discovery happens through the registry, but actual MCP calls flow directly between agents
- **Language runtime flexibility**: Currently supports Python with plans for additional language runtimes
- **Hot-swappable capabilities**: Add, remove, or update capabilities without restarting the entire system

## Documentation

| Resource                                                | Description                                  |
| ------------------------------------------------------- | -------------------------------------------- |
| **[Getting Started Guide](docs/01-getting-started.md)** | Quick start tutorial and basic concepts      |
| **[Examples](examples/)**                               | Sample agents and deployment patterns        |
| **[Local Development](docs/02-local-development.md)**   | Get started on your machine                  |
| **[Docker Deployment](docs/03-docker-deployment.md)**   | Multi-service development environment        |
| **[Kubernetes Basics](docs/04-kubernetes-basics.md)**   | Production deployment guide                  |
| **[Helm Charts](docs/06-helm-deployment.md)**           | Enterprise Kubernetes deployment             |
| **[Observability](docs/07-observability.md)**           | Monitoring, metrics, and distributed tracing |

### Quick Links

- **[Local Development](docs/02-local-development.md)** - Get started on your machine
- **[Docker Deployment](docs/03-docker-deployment.md)** - Multi-service development environment
- **[Kubernetes Basics](docs/04-kubernetes-basics.md)** - Production deployment guide
- **[Helm Charts](docs/06-helm-deployment.md)** - Enterprise Kubernetes deployment
- **[Observability](docs/07-observability.md)** - Monitoring, metrics, and distributed tracing

## Development

### Prerequisites

- **Go 1.21+** (for registry service)
- **Python 3.11+** (for agent runtime)
- **Docker** (for containerized development)
- **Kubernetes/Minikube** (for cluster deployment)

### Build and Test

```bash
# Build the entire project
make build

# Run tests
make test-all

# Local development with Docker Compose
make dev

# Deploy to Kubernetes
make deploy
```

### Project Structure

```
mcp-mesh/
├── src/core/           # Go registry service and CLI
├── src/runtime/        # Python agent runtime and decorators
├── examples/           # Sample agents and deployment examples
├── docs/              # Comprehensive documentation
├── helm/              # Helm charts for Kubernetes deployment
├── docker/            # Docker configurations
└── k8s/               # Kubernetes manifests
```

## Contributing

We welcome contributions from the community! MCP Mesh is designed to be a collaborative effort to advance the state of distributed MCP applications.

### How to Contribute

1. **[Check the Issues](https://github.com/dhyansraj/mcp-mesh/issues)** - Find good first issues or suggest new features
2. **[Join Discussions](https://github.com/dhyansraj/mcp-mesh/discussions)** - Share ideas and get help from the community
3. **[Submit Pull Requests](https://github.com/dhyansraj/mcp-mesh/pulls)** - Contribute code, documentation, or examples
4. **Follow our development guidelines** - See project structure and coding standards below

### Development Areas

- **Core Platform**: Go registry service, capability discovery, health monitoring
- **Python Runtime**: Agent decorators, dynamic injection, HTTP proxy generation, FastMCP integration
- **Language Runtimes**: Additional language support (Go, JavaScript, etc.)
- **Documentation**: Guides, tutorials, API documentation, examples
- **Deployment**: Helm charts, operators, CI/CD integration
- **Testing**: Unit tests, integration tests, performance benchmarks

## Support & Community

### Getting Help

- **[GitHub Discussions](https://github.com/dhyansraj/mcp-mesh/discussions)** - Ask questions and share ideas
- **[Documentation](docs/)** - Comprehensive guides and references
- **[Examples](examples/)** - Working code examples and patterns
- **[Issues](https://github.com/dhyansraj/mcp-mesh/issues)** - Report bugs or request features

### Community Guidelines

We are committed to providing a welcoming and inclusive environment for all contributors. We follow standard open source community practices for respectful collaboration.

## Roadmap

### Current Status

- ✅ Core registry service with dynamic dependency injection
- ✅ Python runtime with decorator-based agent development
- ✅ Local development environment
- ✅ Docker Compose deployment
- ✅ Basic Kubernetes deployment
- ✅ MCP protocol compatibility

### Upcoming Features

- 🔄 Enhanced monitoring and observability
- 🔄 Multi-cluster registry federation
- 🔄 Advanced security and RBAC
- 🔄 Performance optimizations and caching
- 🔄 Integration with service mesh (Istio/Linkerd)
- 🔄 Operator for automated Kubernetes deployment

## License

This project is open source. License details will be provided in the LICENSE file.

---

## Acknowledgments

- **[Anthropic](https://anthropic.com)** for creating the MCP protocol that inspired this project
- **[FastMCP](https://github.com/jlowin/fastmcp)** for providing excellent MCP server foundations
- **[Kubernetes](https://kubernetes.io)** community for building the infrastructure platform that makes this possible
- All the **contributors** who help make MCP Mesh better

---

## 🚀 Ready to Build the Future?

**MCP Mesh is pioneering distributed AI agent architecture.** Join developers building the next generation of AI systems.

### Get Started Now:

1. **[⚡ 5-Minute Tutorial](docs/01-getting-started.md)** - Build your first distributed MCP app
2. **[💬 Join Discussion](https://github.com/dhyansraj/mcp-mesh/discussions)** - Connect with the community
3. **[🔧 Contribute](CONTRIBUTING.md)** - Help shape the future of AI orchestration

**Star the repo** if MCP Mesh solves a problem you have! ⭐
