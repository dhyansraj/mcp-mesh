# MCP Mesh Simple Examples

This directory contains simple Python agents that demonstrate MCP Mesh capabilities using published packages. Perfect for getting started quickly and understanding MCP Mesh concepts.

> **🔧 For Contributors:** If you're developing MCP Mesh itself, see the [development setup guide](../../docs/02-local-development.md) for building from source.

## 🚀 Quick Start

### 1. Install MCP Mesh

```bash
# Install from PyPI with semantic versioning (allows patch updates)
pip install "mcp-mesh>=0.1.0,<0.2.0"
```

This installs the latest stable version of MCP Mesh and all dependencies.

### 2. Start the Registry

```bash
# Download and start the registry service (use minor version for latest patches)
curl -sSL https://raw.githubusercontent.com/dhyansraj/mcp-mesh/main/install.sh | bash -s -- --registry-only --version v0.3
registry --host 0.0.0.0 --port 8000
```

The registry will start on `http://localhost:8000` and handle agent discovery and coordination.

### 3. Start Agents

Open separate terminals for each agent:

**Terminal 1 - Hello World Agent:**

```bash
python hello_world.py
```

**Terminal 2 - System Agent:**

```bash
python system_agent.py
```

Both agents will:

- ✅ Start HTTP servers (ports auto-assigned)
- ✅ Register with the registry
- ✅ Set up dependency injection automatically

## 🧪 Testing and Validation

### 1. Check Agent Registration

```bash
# Install meshctl CLI tool first (use minor version for latest patches)
curl -sSL https://raw.githubusercontent.com/dhyansraj/mcp-mesh/main/install.sh | bash -s -- --meshctl-only --version v0.3

# List all registered agents
meshctl list agents

# Get detailed agent information
meshctl get agent hello-world
meshctl get agent system-agent
```

### 2. Test Individual Agent Capabilities

```bash
# Find agent ports (auto-assigned)
meshctl list agents | grep http_port

# List available tools on an agent (replace PORT with actual port)
curl -s -X POST http://localhost:PORT/mcp/ \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/list",
    "params": {}
  }' | grep "^data:" | sed 's/^data: //' | jq '.result.tools[] | {name: .name, description: .description}'

# Test system agent directly (replace PORT with actual port)
curl -s -X POST http://localhost:PORT/mcp/ \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
      "name": "get_current_time",
      "arguments": {}
    }
  }' | grep "^data:" | sed 's/^data: //' | jq -r '.result.content[0].text'

# Test hello world agent (replace PORT with actual port)
curl -s -X POST http://localhost:PORT/mcp/ \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
      "name": "hello_mesh_simple",
      "arguments": {}
    }
  }' | grep "^data:" | sed 's/^data: //' | jq -r '.result.content[0].text'

# Test tools with required arguments (example: generate_report on dependent agent)
curl -s -X POST http://localhost:9093/mcp/ \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
      "name": "generate_report",
      "arguments": {"title": "Test Report"}
    }
  }' | grep "^data:" | sed 's/^data: //' | jq -r '.result.content[0].text'
```

### 3. Test Dependency Injection

The hello world agent depends on the system agent for date services. Test this:

```bash
# This should show current date from system agent
curl -s -X POST http://localhost:PORT/mcp/ \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
      "name": "hello_mesh_simple",
      "arguments": {}
    }
  }' | grep "^data:" | sed 's/^data: //' | jq -r '.result.content[0].text'

# Expected response: "Hello from MCP Mesh! Today is [current date]"
```

### 4. Test Resilience

```bash
# Stop system agent (Ctrl+C in its terminal)
# Test hello world agent - should gracefully degrade
curl -s -X POST http://localhost:PORT/mcp/ \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
      "name": "hello_mesh_simple",
      "arguments": {}
    }
  }' | grep "^data:" | sed 's/^data: //' | jq -r '.result.content[0].text'

# Expected response: "Hello from MCP Mesh! (Date service not available yet)"

# Restart system agent - dependency injection should resume automatically
```

## 📁 Agent Files

### `hello_world.py`

Simple greeting agent that demonstrates:

- ✨ Basic `@mesh.agent` and `@mesh.tool` decorators
- 🔗 Dependency injection (depends on system agent)
- 🛡️ Graceful degradation when dependencies unavailable
- 🎯 Multiple tool functions with different dependency patterns

### `system_agent.py`

System monitoring agent that provides:

- 📅 Date/time services (`get_current_time`)
- 💻 System information (`fetch_system_overview`)
- 📊 Health monitoring capabilities
- 🏷️ Tag-based capability advertising

### `fastapi_app.py` (NEW - Development Preview)

FastAPI integration example that demonstrates:

- 🌐 **`@mesh.route` decorators** for dependency injection in FastAPI routes
- 🏗️ **Development testing ground** for API pipeline implementation
- 🔧 **Graceful degradation** when MCP agents are unavailable
- 📖 **Interactive API docs** at http://localhost:8080/docs

**Current Status**: Phase 1 - Decorator registration works, dependency injection coming in Phase 2

See [FASTAPI_EXAMPLE.md](FASTAPI_EXAMPLE.md) for detailed usage and testing instructions.

## 🔧 Development Workflow

### 1. Modify an Agent

```bash
# Edit agent file
vim hello_world.py

# Restart the agent (Ctrl+C, then restart)
python hello_world.py
```

Changes are picked up immediately on restart.

### 2. Add New Tools

```python
@mesh.tool(
    capability="my_new_feature",
    description="Description of what this tool does"
)
def my_new_function():
    return "Hello from my new tool!"
```

### 3. Add Dependencies

```python
@mesh.tool(
    dependencies=["date_service"],  # Simple dependency
    description="Tool that needs date service"
)
def tool_with_dependency(date_service=None):
    if date_service:
        current_time = date_service()
        return f"Current time: {current_time}"
    return "Date service not available"
```

### 4. Debug Issues

```bash
# Run agent with debug logging
export MCP_MESH_LOG_LEVEL=DEBUG
python hello_world.py

# Check registry status
meshctl status

# Check dependency graph
meshctl dependencies
```

## 🌐 Network Configuration

By default, agents use auto-assigned ports. To use specific ports:

```bash
# Set environment variables
export MCP_MESH_HTTP_PORT=8081
python hello_world.py

export MCP_MESH_HTTP_PORT=8082
python system_agent.py
```

Or modify the `@mesh.agent` decorator:

```python
@mesh.agent(
    name="hello-world",
    http_port=8081  # Fixed port
)
class HelloWorldAgent:
    pass
```

## 🔍 Advanced Features

### Environment Variables

Set these for customization:

```bash
# Registry connection
export MCP_MESH_REGISTRY_URL=http://localhost:8000

# Logging
export MCP_MESH_LOG_LEVEL=DEBUG
export MCP_MESH_DEBUG_MODE=true

# Agent behavior
export MCP_MESH_AUTO_RUN=true
export MCP_MESH_AUTO_RUN_INTERVAL=30
```

### Custom Registry

```bash
# Start registry on different port
registry --host 0.0.0.0 --port 9000

# Connect agents to custom registry
export MCP_MESH_REGISTRY_URL=http://localhost:9000
python hello_world.py
```

## 🐛 Troubleshooting

### Agent Won't Start

```bash
# Check if port is in use
netstat -tlnp | grep :8080

# Try different port
export MCP_MESH_HTTP_PORT=8090
python hello_world.py
```

### Registry Connection Issues

```bash
# Check registry health
curl http://localhost:8000/health

# Check network connectivity
ping localhost
```

### Dependency Injection Not Working

```bash
# Verify both agents are registered
meshctl list agents

# Check dependency resolution
meshctl dependencies

# Look for errors in agent logs
```

## 🚀 Next Steps

1. **Experiment** with the existing agents
2. **Create** your own agent by copying and modifying `hello_world.py`
3. **Try** Docker Compose for a more realistic environment
4. **Deploy** to Kubernetes for production scenarios

The local development setup is perfect for rapid prototyping and understanding MCP Mesh concepts before moving to containerized deployments.

## 🆘 Getting Help

- 📖 Check the main [examples README](../README.md) for other deployment options
- 🐛 Use `--verbose` flag for detailed logging
- 🔧 Try `meshctl --help` for CLI commands or check [install guide](../../README.md) for setup
- 💬 Review agent logs for specific error messages
