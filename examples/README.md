# MCP Mesh Examples

This directory contains examples demonstrating different deployment scenarios for MCP Mesh:

## 🚀 Quick Start Options

### 1. **Docker Compose** (Recommended for Development)

**Best for**: Local development, testing, and learning MCP Mesh concepts.

```bash
cd docker-examples/
docker-compose up --build
```

**Features**:

- 🔄 Automatic service discovery and dependency injection
- 🐳 Isolated containers with proper networking
- 📊 Built-in monitoring and health checks
- 🛠️ Easy to modify and experiment with agents

**→ [Full Docker Guide](docker-examples/README.md)**

---

### 2. **Kubernetes** (Production Ready)

**Best for**: Production deployments, scaling, and cloud environments.

```bash
cd k8s/
kubectl apply -k base/
```

**Features**:

- 🎯 Kubernetes-native service discovery
- 📈 Horizontal pod autoscaling
- 💾 Persistent storage with PostgreSQL
- 🔒 Production security and RBAC
- 🌐 Load balancing and high availability

**→ [Full Kubernetes Guide](k8s/README.md)**

---

### 3. **Local Development** (Manual Setup)

**Best for**: Understanding internals, debugging, and custom development.

```bash
cd simple/
# See simple/README.md for detailed instructions
```

**Features**:

- 🔧 Direct binary execution and debugging
- 🧪 Perfect for agent development and testing
- ⚡ Fast iteration cycles
- 🎯 Minimal overhead for development

**→ [Local Development Guide](simple/README.md)**

---

## 🎯 Which Option Should I Choose?

| Scenario                  | Recommended Option | Why                                  |
| ------------------------- | ------------------ | ------------------------------------ |
| **Learning MCP Mesh**     | Docker Compose     | Complete environment, easy setup     |
| **Developing new agents** | Local Development  | Fast feedback, easy debugging        |
| **Testing integrations**  | Docker Compose     | Realistic network conditions         |
| **Production deployment** | Kubernetes         | Scalability, reliability, monitoring |
| **Cloud/enterprise**      | Kubernetes         | Cloud-native, enterprise features    |

## 🏗️ Architecture Overview

All examples demonstrate the same core MCP Mesh architecture:

```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│   Registry      │    │  Hello World     │    │  System Agent   │
│   (Go + DB)     │    │  Agent (Python)  │    │  (Python)       │
│   Port: 8000    │◄──►│  Port: 8081      │◄──►│  Port: 8082     │
│   [Discovery]   │    │  [Capabilities]  │    │  [Services]     │
└─────────────────┘    └──────────────────┘    └─────────────────┘
        ▲                         ▲                       ▲
        │               ┌─────────┴────────┐              │
        └────────────── │  meshctl Client  │──────────────┘
                        │  (CLI/Dashboard) │
                        └──────────────────┘
```

### Key Features Demonstrated:

- **🔄 Automatic Service Discovery**: Agents find each other via registry
- **🔗 Dependency Injection**: Dynamic function parameter injection
- **🛡️ Resilient Architecture**: Agents work standalone, enhance when connected
- **📡 Cross-Agent Communication**: HTTP-based MCP protocol
- **⚡ Hot Reloading**: Dynamic capability updates without restarts

## 🧪 Testing Your Setup

Once you have any example running, test the core functionality:

```bash
# 1. Check agent registration
./bin/meshctl list agents

# 2. Test basic functionality
curl -s -X POST http://localhost:8081/mcp \
  -H "Content-Type: application/json" \
  -d '{"method": "tools/call", "params": {"name": "hello_mesh_simple", "arguments": {}}}' | jq .

# 3. Test dependency injection
curl -s -X POST http://localhost:8082/mcp \
  -H "Content-Type: application/json" \
  -d '{"method": "tools/call", "params": {"name": "get_current_time", "arguments": {}}}' | jq .
```

**Expected Results**:

- ✅ Agents register successfully with the registry
- ✅ Hello world agent gets current date from system agent
- ✅ Cross-agent communication works seamlessly

## 🔗 Next Steps

1. **Start with Docker Compose** to understand the basics
2. **Try local development** to build your own agents
3. **Deploy to Kubernetes** for production scenarios

Each directory contains detailed README files with step-by-step instructions, troubleshooting guides, and advanced configuration options.

## 🆘 Need Help?

- 📖 Check the specific README in each example directory
- 🐛 Look at logs: `docker-compose logs` or `kubectl logs`
- 🔧 Use meshctl for debugging: `./bin/meshctl status --verbose`
- 💬 Review the main project documentation
