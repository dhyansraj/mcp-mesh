# MCP Mesh Developer Workflow Guide

This guide provides comprehensive workflows for developing, testing, and debugging MCP agents using the MCP Mesh Developer CLI.

## Table of Contents

- [Getting Started](#getting-started)
- [Basic Development Workflow](#basic-development-workflow)
- [Advanced Development Patterns](#advanced-development-patterns)
- [Testing and Debugging](#testing-and-debugging)
- [Best Practices](#best-practices)
- [Common Scenarios](#common-scenarios)

## Getting Started

### Prerequisites

1. Install MCP Mesh Runtime:

```bash
pip install mcp-mesh-runtime
```

2. Verify installation:

```bash
mcp_mesh_dev --version
```

3. Initialize development environment:

```bash
# Create project directory
mkdir my-mcp-project
cd my-mcp-project

# Create basic configuration
mcp_mesh_dev config show > mcp_mesh_config.yaml
```

### Your First Agent

Create a simple MCP agent to get started:

```python
# hello_agent.py
import asyncio
import json
from datetime import datetime

class HelloAgent:
    def __init__(self):
        self.name = "hello_agent"
        self.capabilities = ["greeting", "status"]

    async def handle_request(self, request):
        method = request.get("method")

        if method == "greeting":
            return {
                "result": {
                    "message": "Hello from MCP Agent!",
                    "timestamp": datetime.now().isoformat()
                }
            }
        elif method == "status":
            return {
                "result": {
                    "agent": self.name,
                    "status": "running",
                    "capabilities": self.capabilities
                }
            }
        else:
            return {
                "error": {
                    "code": -32601,
                    "message": f"Method not found: {method}"
                }
            }

    async def run(self):
        print(f"Starting {self.name}")
        try:
            while True:
                await asyncio.sleep(5)
                print(f"{self.name} heartbeat")
        except KeyboardInterrupt:
            print(f"{self.name} shutting down")

if __name__ == "__main__":
    agent = HelloAgent()
    asyncio.run(agent.run())
```

Test your agent:

```bash
# Start the agent
mcp_mesh_dev start hello_agent.py

# Check status
mcp_mesh_dev status

# View logs
mcp_mesh_dev logs --agent hello_agent

# Stop when done
mcp_mesh_dev stop
```

## Basic Development Workflow

### 1. Start Development Environment

```bash
# Start with debug mode for development
mcp_mesh_dev start --debug my_agent.py

# Or start registry only and add agents later
mcp_mesh_dev start --registry-only
```

### 2. Monitor Your Agent

Open a second terminal for monitoring:

```bash
# Follow logs in real-time
mcp_mesh_dev logs --follow --agent my_agent

# Or monitor all services
mcp_mesh_dev logs --follow
```

### 3. Check Agent Health

```bash
# Basic status check
mcp_mesh_dev status

# Detailed status with metrics
mcp_mesh_dev status --verbose

# List all agents
mcp_mesh_dev list
```

### 4. Iterate and Test

```bash
# Make changes to your agent code
vim my_agent.py

# Restart the agent to test changes
mcp_mesh_dev restart-agent my_agent

# Check that restart was successful
mcp_mesh_dev status
```

### 5. Clean Shutdown

```bash
# Stop all services gracefully
mcp_mesh_dev stop

# Or force stop if needed
mcp_mesh_dev stop --force
```

## Advanced Development Patterns

### Multi-Agent Development

Develop and test multiple agents simultaneously:

```bash
# Start multiple agents
mcp_mesh_dev start agent1.py agent2.py agent3.py

# Monitor specific agent
mcp_mesh_dev logs --agent agent2 --follow

# Check inter-agent communication
mcp_mesh_dev list --json | jq '.[] | {name, dependencies}'

# Restart specific agent
mcp_mesh_dev restart-agent agent1
```

### Configuration Management

Use different configurations for different environments:

```bash
# Development configuration
mcp_mesh_dev config set debug_mode true
mcp_mesh_dev config set log_level DEBUG
mcp_mesh_dev config set health_check_interval 10

# Save development config
mcp_mesh_dev config save

# Test configuration
mcp_mesh_dev config set registry_port 8081
mcp_mesh_dev start --registry-port 8081 test_agent.py

# Production configuration
mcp_mesh_dev config reset
mcp_mesh_dev config set log_level INFO
mcp_mesh_dev config set health_check_interval 60
```

### Background Development

Run services in background for long-term development:

```bash
# Start in background
mcp_mesh_dev start --background production_agent.py

# Check background services
mcp_mesh_dev status

# View background logs
mcp_mesh_dev logs --agent production_agent

# Stop background services
mcp_mesh_dev stop
```

## Testing and Debugging

### Debug Mode Development

Enable comprehensive debugging:

```bash
# Enable debug mode
mcp_mesh_dev config set debug_mode true
mcp_mesh_dev config set log_level DEBUG

# Start with debug flags
mcp_mesh_dev start --debug problematic_agent.py

# Monitor debug logs
mcp_mesh_dev logs --follow --level DEBUG
```

### Agent Communication Testing

Test agent-to-agent communication:

```python
# communication_test_agent.py
import asyncio
import json

class CommunicationTestAgent:
    def __init__(self):
        self.name = "comm_test_agent"
        self.dependencies = []

    def register_dependency(self, name, service):
        """Called by MCP Mesh when dependencies are available."""
        print(f"Registered dependency: {name}")
        self.dependencies.append(name)

    async def test_communication(self):
        """Test communication with other agents."""
        for dep in self.dependencies:
            print(f"Testing communication with {dep}")
            # Implement test logic here

    async def run(self):
        print(f"Starting {self.name}")
        while True:
            await asyncio.sleep(10)
            await self.test_communication()

if __name__ == "__main__":
    agent = CommunicationTestAgent()
    asyncio.run(agent.run())
```

Test communication:

```bash
# Start both agents
mcp_mesh_dev start comm_test_agent.py target_agent.py

# Monitor communication logs
mcp_mesh_dev logs --follow | grep -E "(comm_test|target)"
```

### Performance Testing

Monitor agent performance:

```bash
# Start with verbose monitoring
mcp_mesh_dev start performance_agent.py
mcp_mesh_dev status --verbose

# Monitor resource usage
watch -n 2 'mcp_mesh_dev status --json | jq ".system.resource_usage"'

# Check for memory leaks
mcp_mesh_dev logs --agent performance_agent | grep -i memory
```

### Error Debugging

Debug common issues:

```bash
# Check agent startup issues
mcp_mesh_dev start problematic_agent.py --debug
mcp_mesh_dev logs --level ERROR

# Debug registration issues
mcp_mesh_dev list --json | jq '.[] | select(.registered == false)'

# Debug communication issues
mcp_mesh_dev logs --follow | grep -E "(error|exception|failed)"

# Force restart problematic agent
mcp_mesh_dev restart-agent problematic_agent --timeout 60
```

## Best Practices

### 1. Agent Design Patterns

**Stateless Agents:**

```python
class StatelessAgent:
    """Stateless agents are easier to restart and scale."""

    async def handle_request(self, request):
        # Process request without relying on internal state
        return await self.process_stateless_request(request)
```

**Graceful Shutdown:**

```python
class GracefulAgent:
    def __init__(self):
        self.running = True
        self.cleanup_handlers = []

    def register_cleanup(self, handler):
        self.cleanup_handlers.append(handler)

    async def run(self):
        try:
            while self.running:
                await self.do_work()
        except KeyboardInterrupt:
            print("Gracefully shutting down...")
            for handler in self.cleanup_handlers:
                await handler()
```

**Health Monitoring:**

```python
class HealthyAgent:
    def __init__(self):
        self.health_status = "healthy"
        self.last_activity = time.time()

    async def health_check(self):
        # Implement health check logic
        if time.time() - self.last_activity > 300:
            self.health_status = "unhealthy"
        return self.health_status
```

### 2. Development Environment Setup

**Project Structure:**

```
my-mcp-project/
├── agents/
│   ├── hello_agent.py
│   ├── system_agent.py
│   └── communication_agent.py
├── tests/
│   ├── test_hello_agent.py
│   └── test_integration.py
├── config/
│   ├── development.json
│   └── production.json
├── scripts/
│   ├── start_dev.sh
│   └── run_tests.sh
└── requirements.txt
```

**Development Scripts:**

```bash
# scripts/start_dev.sh
#!/bin/bash
set -e

echo "Starting MCP Mesh development environment..."

# Load development configuration
mcp_mesh_dev config set debug_mode true
mcp_mesh_dev config set log_level DEBUG

# Start all development agents
mcp_mesh_dev start \
    agents/hello_agent.py \
    agents/system_agent.py \
    agents/communication_agent.py

echo "Development environment started!"
echo "Use 'mcp_mesh_dev status' to check health"
echo "Use 'mcp_mesh_dev logs --follow' to monitor logs"
```

### 3. Configuration Management

**Environment-Specific Configs:**

```bash
# Set up development environment
mcp_mesh_dev config set registry_port 8080
mcp_mesh_dev config set debug_mode true
mcp_mesh_dev config set health_check_interval 10
mcp_mesh_dev config save

# Set up testing environment
mcp_mesh_dev config set registry_port 8081
mcp_mesh_dev config set debug_mode false
mcp_mesh_dev config set health_check_interval 5
```

### 4. Testing Strategies

**Unit Testing:**

```python
# tests/test_hello_agent.py
import pytest
import asyncio
from agents.hello_agent import HelloAgent

@pytest.mark.asyncio
async def test_hello_agent_greeting():
    agent = HelloAgent()
    request = {"method": "greeting"}
    response = await agent.handle_request(request)

    assert "result" in response
    assert response["result"]["message"] == "Hello from MCP Agent!"

@pytest.mark.asyncio
async def test_hello_agent_status():
    agent = HelloAgent()
    request = {"method": "status"}
    response = await agent.handle_request(request)

    assert response["result"]["agent"] == "hello_agent"
    assert response["result"]["status"] == "running"
```

**Integration Testing:**

```bash
# scripts/run_tests.sh
#!/bin/bash
set -e

echo "Running MCP Mesh integration tests..."

# Start test environment
mcp_mesh_dev start --registry-port 8081 agents/test_agent.py &
TEST_PID=$!

# Wait for startup
sleep 5

# Run tests
python -m pytest tests/test_integration.py -v

# Cleanup
mcp_mesh_dev stop
wait $TEST_PID
```

## Common Scenarios

### Scenario 1: Adding a New Agent to Existing System

```bash
# Check current system status
mcp_mesh_dev status
mcp_mesh_dev list

# Test new agent in isolation first
mcp_mesh_dev start --registry-port 8081 new_agent.py

# Verify it works
mcp_mesh_dev status --registry-port 8081

# Add to existing system
mcp_mesh_dev stop --registry-port 8081
mcp_mesh_dev start new_agent.py  # Adds to main registry

# Verify integration
mcp_mesh_dev list
```

### Scenario 2: Debugging Agent Startup Issues

```bash
# Enable debug mode
mcp_mesh_dev config set debug_mode true
mcp_mesh_dev config set log_level DEBUG

# Try starting problematic agent
mcp_mesh_dev start problematic_agent.py

# If it fails, check logs
mcp_mesh_dev logs --level ERROR

# Try with increased timeout
mcp_mesh_dev config set startup_timeout 60
mcp_mesh_dev start problematic_agent.py

# Monitor startup process
mcp_mesh_dev logs --follow &
mcp_mesh_dev start problematic_agent.py
```

### Scenario 3: Performance Optimization

```bash
# Start with performance monitoring
mcp_mesh_dev start --debug performance_agent.py
mcp_mesh_dev status --verbose

# Monitor resource usage over time
while true; do
    mcp_mesh_dev status --json | jq '.agents.performance_agent.resource_usage'
    sleep 10
done

# Adjust health check interval
mcp_mesh_dev config set health_check_interval 60
mcp_mesh_dev restart-agent performance_agent

# Compare performance
mcp_mesh_dev status --verbose
```

### Scenario 4: Multi-Environment Development

```bash
# Development environment
export MCP_MESH_ENV=development
mcp_mesh_dev config set registry_port 8080
mcp_mesh_dev config set debug_mode true
mcp_mesh_dev start dev_agents/*.py

# Testing environment
export MCP_MESH_ENV=testing
mcp_mesh_dev config set registry_port 8081
mcp_mesh_dev config set debug_mode false
mcp_mesh_dev start test_agents/*.py

# Check both environments
mcp_mesh_dev status --registry-port 8080  # Development
mcp_mesh_dev status --registry-port 8081  # Testing
```

### Scenario 5: Production Deployment Preparation

```bash
# Test production configuration
mcp_mesh_dev config reset
mcp_mesh_dev config set log_level INFO
mcp_mesh_dev config set health_check_interval 60
mcp_mesh_dev config set auto_restart true

# Test with production agents
mcp_mesh_dev start production_agents/*.py

# Run health checks
mcp_mesh_dev status --verbose

# Test restart scenarios
mcp_mesh_dev restart-agent critical_agent
mcp_mesh_dev status

# Test graceful shutdown
mcp_mesh_dev stop --timeout 30
```

## Troubleshooting Quick Reference

### Common Issues

1. **Agent won't start:**

   ```bash
   mcp_mesh_dev logs --level ERROR
   mcp_mesh_dev config set startup_timeout 60
   ```

2. **Agent not registering:**

   ```bash
   mcp_mesh_dev list --json | jq '.[] | select(.registered == false)'
   mcp_mesh_dev restart-agent <agent_name>
   ```

3. **High resource usage:**

   ```bash
   mcp_mesh_dev status --verbose
   mcp_mesh_dev config set health_check_interval 120
   ```

4. **Communication issues:**

   ```bash
   mcp_mesh_dev logs --follow | grep -E "(error|timeout|connection)"
   ```

5. **Database issues:**
   ```bash
   mcp_mesh_dev stop
   rm ~/.mcp_mesh/dev_registry.db
   mcp_mesh_dev start
   ```

For more detailed troubleshooting, see the [Troubleshooting Guide](TROUBLESHOOTING.md).

## Next Steps

- Read the [CLI Reference](CLI_REFERENCE.md) for detailed command documentation
- Explore [Architecture Overview](ARCHITECTURE_OVERVIEW.md) to understand the system design
- Check out [Advanced Features](ADVANCED_FEATURES.md) for power-user functionality
- Review the [API Reference](../API_REFERENCE.md) for programmatic integration
