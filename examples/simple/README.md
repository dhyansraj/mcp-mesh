# MCP Mesh Local Development

This directory contains simple Python agents for local development and testing. Perfect for understanding MCP Mesh internals, developing new agents, and debugging.

## 🚀 Quick Start

### 1. Build the Project

```bash
# From project root
make install-dev
```

This installs MCP Mesh in development mode with all dependencies.

### 2. Start the Registry

```bash
# Start the Go registry service
./bin/meshctl start-registry
```

The registry will start on `http://localhost:8000` and handle agent discovery and coordination.

### 3. Start Agents

Open separate terminals for each agent:

**Terminal 1 - Hello World Agent:**

```bash
./bin/meshctl start examples/simple/hello_world.py
```

**Terminal 2 - System Agent:**

```bash
./bin/meshctl start examples/simple/system_agent.py
```

Both agents will:

- ✅ Start HTTP servers (ports auto-assigned)
- ✅ Register with the registry
- ✅ Set up dependency injection automatically

## 🧪 Testing and Validation

### 1. Check Agent Registration

```bash
# List all registered agents
./bin/meshctl list agents

# Get detailed agent information
./bin/meshctl get agent hello-world
./bin/meshctl get agent system-agent
```

### 2. Test Individual Agent Capabilities

```bash
# Find agent ports (auto-assigned)
./bin/meshctl list agents | grep http_port

# Test system agent directly (replace PORT with actual port)
curl -s -X POST http://localhost:PORT/mcp \
  -H "Content-Type: application/json" \
  -d '{"method": "tools/call", "params": {"name": "get_current_time", "arguments": {}}}' | jq .

# Test hello world agent (replace PORT with actual port)
curl -s -X POST http://localhost:PORT/mcp \
  -H "Content-Type: application/json" \
  -d '{"method": "tools/call", "params": {"name": "hello_mesh_simple", "arguments": {}}}' | jq .
```

### 3. Test Dependency Injection

The hello world agent depends on the system agent for date services. Test this:

```bash
# This should show current date from system agent
curl -s -X POST http://localhost:PORT/mcp \
  -H "Content-Type: application/json" \
  -d '{"method": "tools/call", "params": {"name": "hello_mesh_simple", "arguments": {}}}' | jq .

# Expected response: "Hello from MCP Mesh! Today is [current date]"
```

### 4. Test Resilience

```bash
# Stop system agent (Ctrl+C in its terminal)
# Test hello world agent - should gracefully degrade
curl -s -X POST http://localhost:PORT/mcp \
  -H "Content-Type: application/json" \
  -d '{"method": "tools/call", "params": {"name": "hello_mesh_simple", "arguments": {}}}' | jq .

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

## 🔧 Development Workflow

### 1. Modify an Agent

```bash
# Edit agent file
vim examples/simple/hello_world.py

# Restart the agent (Ctrl+C, then restart)
./bin/meshctl start examples/simple/hello_world.py
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
# Check logs with verbose output
./bin/meshctl start examples/simple/hello_world.py --verbose

# Check registry status
./bin/meshctl status

# Check dependency graph
./bin/meshctl dependencies
```

## 🌐 Network Configuration

By default, agents use auto-assigned ports. To use specific ports:

```bash
# Set environment variables
export MCP_MESH_HTTP_PORT=8081
./bin/meshctl start examples/simple/hello_world.py

export MCP_MESH_HTTP_PORT=8082
./bin/meshctl start examples/simple/system_agent.py
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
./bin/meshctl start-registry --port 9000

# Connect agents to custom registry
export MCP_MESH_REGISTRY_URL=http://localhost:9000
./bin/meshctl start examples/simple/hello_world.py
```

## 🐛 Troubleshooting

### Agent Won't Start

```bash
# Check if port is in use
netstat -tlnp | grep :8080

# Try different port
export MCP_MESH_HTTP_PORT=8090
./bin/meshctl start examples/simple/hello_world.py
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
./bin/meshctl list agents

# Check dependency resolution
./bin/meshctl dependencies

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
- 🔧 Try `./bin/meshctl --help` for all available commands
- 💬 Review agent logs for specific error messages
