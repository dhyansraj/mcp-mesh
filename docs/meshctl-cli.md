# meshctl CLI Reference

> Essential commands for managing MCP Mesh agents with the meshctl CLI tool

## Overview

`meshctl` is the command-line interface for MCP Mesh that helps you start, monitor, and manage your agents. It automatically handles the registry, provides beautiful monitoring displays, and simplifies development workflows.

## Quick Start

```bash
# Generate a new agent from template
meshctl scaffold --name my-agent --agent-type llm-agent

# Start registry + agent in one command
meshctl start examples/hello_world.py

# List running agents with beautiful table
meshctl list

# Check detailed status
meshctl status --verbose
```

## Essential Commands

### 1. Scaffolding New Agents

Generate new agents from templates with interactive or CLI-based configuration.

```bash
# Interactive mode (recommended for beginners)
meshctl scaffold

# Generate a basic tool agent
meshctl scaffold --name my-tool --agent-type tool

# Generate an LLM-powered agent
meshctl scaffold --name my-llm-agent --agent-type llm-agent --llm-selector claude

# Generate an LLM provider
meshctl scaffold --name claude-provider --agent-type llm-provider --model anthropic/claude-sonnet-4-5
```

📖 **See [Scaffold Command Reference](./meshctl-scaffold.md) for complete options and examples.**

### 2. Starting Services

#### Start Registry Only

```bash
# Start just the registry (useful for development)
meshctl start --registry-only

# Start registry on custom port
meshctl start --registry-only --registry-port 9000
```

#### Start Single Agent

```bash
# Start agent (registry starts automatically if needed)
meshctl start my_agent.py

# Start with custom configuration
meshctl start my_agent.py --debug --verbose
```

#### Start Multiple Agents

```bash
# Start multiple agents at once
meshctl start agent1.py agent2.py agent3.py

# Start with environment variables
meshctl start my_agent.py --env KEY=value --env DEBUG=true
```

### 3. Monitoring and Status

#### List All Agents

```bash
# Beautiful table view (recommended)
meshctl list

# Wide view with endpoints and tool counts
meshctl list --wide

# Filter by name pattern
meshctl list --filter weather

# Show only healthy agents
meshctl list
```

**Example output:**

```
AGENT NAME       STATUS    UPTIME     CAPABILITIES           DEPENDENCIES    ENDPOINT
weather-service  healthy   2m 30s     weather_data,forecast  date_service   http://localhost:9091
hello-world      healthy   1m 45s     greeting               date_service   http://localhost:9090
system-agent     healthy   3m 12s     date_service,info      -              http://localhost:8080
```

#### Detailed Status

```bash
# Show overall mesh status
meshctl status

# Verbose status with detailed information
meshctl status --verbose

# JSON output for automation
meshctl status --json
```

### 4. Configuration Management

#### View Configuration

```bash
# Show current configuration
meshctl config show

# Show config file location
meshctl config path
```

#### Update Configuration

```bash
# Set registry port
meshctl config set registry_port 9090

# Set log level
meshctl config set log_level DEBUG

# Reset to defaults
meshctl config reset
```

## Useful Development Flags

### Auto-Restart and File Watching

```bash
# Auto-restart on file changes (default: enabled)
meshctl start my_agent.py --auto-restart

# Custom file watch pattern
meshctl start my_agent.py --watch-pattern "*.py,*.json"

# Disable file watching
meshctl start my_agent.py --watch-files=false
```

### Debugging and Logging

```bash
# Enable debug mode
meshctl start my_agent.py --debug

# Set custom log level
meshctl start my_agent.py --log-level DEBUG

# Verbose output
meshctl start my_agent.py --verbose

# Quiet mode (errors only)
meshctl start my_agent.py --quiet
```

### Custom Configuration

```bash
# Custom database path
meshctl start --registry-only --db-path ./my_registry.db

# Custom working directory
meshctl start my_agent.py --working-dir /path/to/project

# Load environment file
meshctl start my_agent.py --env-file .env.development
```

## Remote Registry Operations

### Connect to Remote Registry

```bash
# Connect to remote registry
meshctl list --registry-url http://production-registry:8000

# Connect with custom host/port
meshctl list --registry-host prod.example.com --registry-port 9000

# List agents from remote registry
meshctl list --registry-url https://secure-registry.example.com
```

### Agent Registration

```bash
# Connect agent to external registry
meshctl start my_agent.py --registry-url http://remote-registry:8000 --connect-only
```

## Process Management

### Detached Mode

```bash
# Run in background (detached)
meshctl start my_agent.py --detach

# Custom PID file
meshctl start my_agent.py --detach --pid-file ./my_agent.pid

# Check status of detached services
meshctl status
```

### Graceful Shutdown

```bash
# Custom shutdown timeout
meshctl start my_agent.py --shutdown-timeout 60

# Custom startup timeout
meshctl start my_agent.py --startup-timeout 45
```

## Advanced Usage Examples

### Development Workflow

```bash
# Terminal 1: Start registry for development
meshctl start --registry-only --debug

# Terminal 2: Start your agent with hot reload
meshctl start my_agent.py --debug --verbose --auto-restart

# Terminal 3: Monitor all services
watch 'meshctl list --wide'
```

### Production-like Testing

```bash
# Start multiple services
meshctl start \
  services/auth.py \
  services/database.py \
  services/api.py \
  --detach \
  --log-level INFO

# Monitor the services
meshctl list
meshctl status --verbose
```

### Multi-Environment Setup

```bash
# Development environment
meshctl start my_agent.py \
  --env-file .env.development \
  --registry-port 8000 \
  --debug

# Staging environment
meshctl start my_agent.py \
  --env-file .env.staging \
  --registry-port 8001 \
  --log-level WARN

# Connect to production registry
meshctl list --registry-url https://prod-registry.company.com
```

## Configuration File

meshctl stores configuration in `~/.mcp_mesh/cli_config.json`:

```json
{
  "registry_host": "localhost",
  "registry_port": 8000,
  "log_level": "INFO",
  "auto_restart": true,
  "watch_files": true,
  "debug": false,
  "startup_timeout": 30,
  "shutdown_timeout": 30
}
```

### Common Configuration

```bash
# Set development defaults
meshctl config set debug true
meshctl config set log_level DEBUG
meshctl config set registry_port 8080

# Set production defaults
meshctl config set debug false
meshctl config set log_level WARN
meshctl config set auto_restart false
```

## Monitoring and Troubleshooting

### Health Checks

```bash
# Check overall system health
meshctl status

# Monitor specific agent
meshctl list --id agent-id-abc123

# Show agents active in last hour
meshctl list --since 1h
```

### Debugging Connection Issues

```bash
# Test registry connectivity
meshctl list --registry-url http://localhost:8000 --timeout 5

# Verbose status for debugging
meshctl status --verbose --json

# Check specific agent details
meshctl list --filter my-agent --verbose
```

### Log Analysis

```bash
# Start with debug logging
meshctl start my_agent.py --debug --log-level DEBUG

# Check status with verbose output
meshctl status --verbose
```

## Integration with Development Tools

### With Docker

```bash
# Start local registry
meshctl start --registry-only --registry-host 0.0.0.0

# Connect agents to containerized registry
meshctl start my_agent.py --registry-url http://docker-registry:8000
```

### With CI/CD

```bash
# Test agent startup in CI
meshctl start my_agent.py --startup-timeout 10 --quiet

# Validate agent health
meshctl status --json | jq '.agents[] | select(.status != "healthy")'

# Stop services after tests
pkill -f meshctl
```

### With Scripts

```bash
#!/bin/bash
# development.sh - Start development environment

echo "Starting MCP Mesh development environment..."

# Start registry
meshctl start --registry-only --detach --pid-file registry.pid

# Wait for registry
sleep 2

# Start services
meshctl start services/*.py --detach --env-file .env.dev

# Show status
meshctl list --wide

echo "Development environment ready!"
echo "Run 'meshctl list' to monitor services"
```

## Common Use Cases

### 1. Local Development

```bash
# Start everything you need for development
meshctl start --registry-only --debug &
meshctl start my_agent.py --debug --auto-restart
```

### 2. Testing Dependencies

```bash
# Start provider service
meshctl start provider_service.py --detach

# Start consumer service
meshctl start consumer_service.py

# Verify dependency resolution
meshctl list --wide
```

### 3. Multi-Service Demo

```bash
# Start complete demo environment
meshctl start \
  examples/system_agent.py \
  examples/hello_world.py \
  examples/weather_agent.py \
  --verbose

# Monitor all services
meshctl list --wide
```

### 4. Remote Development

```bash
# Connect to shared development registry
meshctl start my_agent.py --registry-url http://dev-registry.team.local:8000

# List all team's agents
meshctl list --registry-url http://dev-registry.team.local:8000
```

## Performance and Scaling

### Resource Monitoring

```bash
# Monitor agent resource usage
meshctl list --wide --verbose

# Check registry performance
meshctl status --json | jq '.registry.performance'
```

### Load Testing Support

```bash
# Start multiple instances
for i in {1..5}; do
  meshctl start my_agent.py --agent-name "agent-$i" --detach
done

# Monitor all instances
meshctl list --filter agent-
```

## Next Steps

Now that you know meshctl basics:

1. **[Local Development](./02-local-development.md)** - Professional development workflows
2. **[Production Deployment](./03-docker-deployment.md)** - Container orchestration
3. **[Mesh Decorators](./mesh-decorators.md)** - @mesh.tool, @mesh.llm decorators

---

💡 **Pro Tip**: Use `meshctl list --wide` as your primary monitoring command - it shows everything you need at a glance.

🔧 **Development Tip**: Keep a terminal with `watch 'meshctl list'` running to monitor your services in real-time.

📊 **Monitoring Tip**: Use `meshctl status --json` for automated health checks and monitoring integrations.
