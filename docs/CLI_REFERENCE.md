# MCP Mesh Developer CLI Reference

The MCP Mesh Developer CLI (`mcp_mesh_dev`) is a comprehensive command-line tool for developing, debugging, and managing MCP (Model Context Protocol) agents and services in a mesh architecture.

## Table of Contents

- [Installation](#installation)
- [Quick Start](#quick-start)
- [Commands](#commands)
- [Configuration](#configuration)
- [Examples](#examples)
- [Advanced Usage](#advanced-usage)

## Installation

```bash
# Install MCP Mesh Runtime package
pip install mcp-mesh-runtime

# Verify installation
mcp_mesh_dev --version
```

## Quick Start

```bash
# Start registry only
mcp_mesh_dev start

# Start registry with an agent
mcp_mesh_dev start my_agent.py

# Check status
mcp_mesh_dev status

# View running agents
mcp_mesh_dev list

# Stop all services
mcp_mesh_dev stop
```

## Commands

### `start` - Start MCP Mesh Services

Start the MCP Mesh registry and optionally one or more MCP agents.

**Syntax:**

```bash
mcp_mesh_dev start [OPTIONS] [AGENT_FILE ...]
```

**Options:**

- `--registry-port PORT` - Port for registry service (default: 8080)
- `--registry-host HOST` - Host for registry service (default: localhost)
- `--db-path PATH` - Path to SQLite database file (default: ./dev_registry.db)
- `--log-level LEVEL` - Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
- `--health-check-interval SECONDS` - Health check interval (default: 30)
- `--debug` - Enable debug mode
- `--startup-timeout SECONDS` - Startup timeout (default: 30)
- `--registry-only` - Start only the registry, no agents
- `--background` - Run services in background

**Examples:**

```bash
# Start registry only
mcp_mesh_dev start --registry-only

# Start with single agent
mcp_mesh_dev start intent_agent.py

# Start with multiple agents
mcp_mesh_dev start agent1.py agent2.py agent3.py

# Start with custom configuration
mcp_mesh_dev start --registry-port 8081 --debug agent.py

# Start in background
mcp_mesh_dev start --background agent.py
```

**Return Codes:**

- `0` - Success
- `1` - Failure (registry or agent startup failed)

---

### `stop` - Stop MCP Mesh Services

Stop running MCP Mesh services including registry and agents.

**Syntax:**

```bash
mcp_mesh_dev stop [OPTIONS]
```

**Options:**

- `--force` - Force stop services without graceful shutdown
- `--timeout SECONDS` - Timeout for graceful shutdown (default: 30)
- `--agent AGENT_NAME` - Stop only the specified agent

**Examples:**

```bash
# Stop all services gracefully
mcp_mesh_dev stop

# Force stop all services
mcp_mesh_dev stop --force

# Stop specific agent
mcp_mesh_dev stop --agent my_agent

# Stop with custom timeout
mcp_mesh_dev stop --timeout 60
```

**Return Codes:**

- `0` - All services stopped successfully
- `1` - Some services failed to stop or had issues

---

### `restart` - Restart Registry Service

Restart the MCP Mesh registry service while preserving configuration.

**Syntax:**

```bash
mcp_mesh_dev restart [OPTIONS]
```

**Options:**

- `--timeout SECONDS` - Timeout for graceful shutdown (default: 30)
- `--reset-config` - Reset to default configuration instead of preserving

**Examples:**

```bash
# Restart registry with current config
mcp_mesh_dev restart

# Restart with reset config
mcp_mesh_dev restart --reset-config

# Restart with custom timeout
mcp_mesh_dev restart --timeout 60
```

**Return Codes:**

- `0` - Registry restarted successfully
- `1` - Restart failed

---

### `restart-agent` - Restart Specific Agent

Restart an individual agent process while preserving configuration.

**Syntax:**

```bash
mcp_mesh_dev restart-agent AGENT_NAME [OPTIONS]
```

**Options:**

- `--timeout SECONDS` - Timeout for graceful shutdown (default: 30)

**Examples:**

```bash
# Restart specific agent
mcp_mesh_dev restart-agent my_agent

# Restart with custom timeout
mcp_mesh_dev restart-agent my_agent --timeout 60
```

**Return Codes:**

- `0` - Agent restarted successfully
- `1` - Restart failed

---

### `status` - Show Service Status

Display the current status and health of MCP Mesh services.

**Syntax:**

```bash
mcp_mesh_dev status [OPTIONS]
```

**Options:**

- `--verbose` - Show detailed status information
- `--json` - Output status in JSON format

**Examples:**

```bash
# Basic status
mcp_mesh_dev status

# Detailed status with performance metrics
mcp_mesh_dev status --verbose

# JSON output for automation
mcp_mesh_dev status --json
```

**Status Information:**

- Overall system health
- Registry service status and uptime
- Agent processes and their health
- Resource usage (with --verbose)
- Connection status

**Return Codes:**

- `0` - Status retrieved successfully
- `1` - Failed to get status

---

### `list` - List Agents and Services

List all available MCP Mesh agents and services with their status.

**Syntax:**

```bash
mcp_mesh_dev list [OPTIONS]
```

**Options:**

- `--agents` - Show only agents (default)
- `--services` - Show only services
- `--filter PATTERN` - Filter by name pattern (regex)
- `--json` - Output in JSON format

**Examples:**

```bash
# List all agents
mcp_mesh_dev list

# Filter by pattern
mcp_mesh_dev list --filter "test.*"

# JSON output
mcp_mesh_dev list --json

# Show only services
mcp_mesh_dev list --services
```

**Agent Information:**

- Agent name and status
- Process ID and uptime
- Registration status with registry
- Health status
- Capabilities and dependencies
- File path and endpoint

**Return Codes:**

- `0` - List retrieved successfully
- `1` - Failed to get agent list

---

### `logs` - Show Service Logs

Display logs from MCP Mesh services and components.

**Syntax:**

```bash
mcp_mesh_dev logs [OPTIONS]
```

**Options:**

- `--follow` - Follow log output in real-time
- `--agent AGENT_NAME` - Show logs for specific agent
- `--level LEVEL` - Minimum log level (DEBUG, INFO, WARNING, ERROR)
- `--lines N` - Number of recent log lines (default: 50)

**Examples:**

```bash
# Show recent logs for all services
mcp_mesh_dev logs

# Follow logs in real-time
mcp_mesh_dev logs --follow

# Show logs for specific agent
mcp_mesh_dev logs --agent my_agent

# Show only error logs
mcp_mesh_dev logs --level ERROR

# Show last 100 lines
mcp_mesh_dev logs --lines 100

# Follow specific agent logs
mcp_mesh_dev logs --agent my_agent --follow
```

**Log Features:**

- Automatic log level filtering
- Real-time log following
- Agent-specific log viewing
- System log integration (where available)

**Return Codes:**

- `0` - Logs retrieved successfully
- `1` - Failed to get logs

---

### `config` - Manage Configuration

Manage MCP Mesh Developer CLI configuration settings.

**Syntax:**

```bash
mcp_mesh_dev config ACTION [OPTIONS]
```

**Actions:**

- `show` - Display current configuration
- `set KEY VALUE` - Set configuration value
- `reset` - Reset to default configuration
- `path` - Show configuration file path
- `save` - Save current configuration as defaults

**Show Options:**

- `--format FORMAT` - Output format (yaml, json)

**Examples:**

```bash
# Show current configuration
mcp_mesh_dev config show

# Show configuration in JSON
mcp_mesh_dev config show --format json

# Set registry port
mcp_mesh_dev config set registry_port 8081

# Enable debug mode
mcp_mesh_dev config set debug_mode true

# Reset to defaults
mcp_mesh_dev config reset

# Show config file location
mcp_mesh_dev config path

# Save current settings
mcp_mesh_dev config save
```

**Configuration Keys:**

- `registry_port` - Registry service port (integer)
- `registry_host` - Registry service host (string)
- `db_path` - Database file path (string)
- `log_level` - Logging level (string)
- `health_check_interval` - Health check interval in seconds (integer)
- `auto_restart` - Enable auto-restart (boolean)
- `watch_files` - Enable file watching (boolean)
- `debug_mode` - Enable debug mode (boolean)
- `startup_timeout` - Startup timeout in seconds (integer)
- `shutdown_timeout` - Shutdown timeout in seconds (integer)
- `enable_background` - Enable background mode (boolean)
- `pid_file` - PID file path (string)

**Return Codes:**

- `0` - Configuration operation successful
- `1` - Configuration operation failed

## Configuration

### Configuration Sources

Configuration is loaded from multiple sources in order of precedence:

1. **Command-line arguments** (highest priority)
2. **Configuration file** (`~/.mcp_mesh/cli_config.json`)
3. **Environment variables** (prefixed with `MCP_MESH_`)
4. **Default values** (lowest priority)

### Environment Variables

All configuration options can be set via environment variables:

```bash
export MCP_MESH_REGISTRY_PORT=8081
export MCP_MESH_REGISTRY_HOST=0.0.0.0
export MCP_MESH_DEBUG_MODE=true
export MCP_MESH_LOG_LEVEL=DEBUG
```

### Configuration File

The configuration file is stored at `~/.mcp_mesh/cli_config.json`:

```json
{
  "registry_port": 8080,
  "registry_host": "localhost",
  "db_path": "./dev_registry.db",
  "log_level": "INFO",
  "health_check_interval": 30,
  "auto_restart": true,
  "watch_files": true,
  "debug_mode": false,
  "startup_timeout": 30,
  "shutdown_timeout": 30,
  "enable_background": false,
  "pid_file": "./mcp_mesh_dev.pid"
}
```

## Examples

### Development Workflow

```bash
# 1. Start development environment
mcp_mesh_dev start --debug my_agent.py

# 2. Monitor logs in another terminal
mcp_mesh_dev logs --follow --agent my_agent

# 3. Check agent status
mcp_mesh_dev status --verbose

# 4. Make changes to agent and restart
mcp_mesh_dev restart-agent my_agent

# 5. Test with multiple agents
mcp_mesh_dev start agent1.py agent2.py agent3.py

# 6. Clean shutdown
mcp_mesh_dev stop
```

### Production Monitoring

```bash
# Start services in background
mcp_mesh_dev start --background production_agent.py

# Monitor system health
mcp_mesh_dev status --json | jq '.system.overall_status'

# Check specific agent health
mcp_mesh_dev list --filter production_agent

# View error logs
mcp_mesh_dev logs --level ERROR --lines 100

# Restart unhealthy agent
mcp_mesh_dev restart-agent production_agent
```

### Debugging Issues

```bash
# Enable debug mode and verbose logging
mcp_mesh_dev config set debug_mode true
mcp_mesh_dev config set log_level DEBUG

# Start with debug configuration
mcp_mesh_dev start --debug problematic_agent.py

# Monitor all logs in real-time
mcp_mesh_dev logs --follow --level DEBUG

# Check detailed status
mcp_mesh_dev status --verbose

# Force stop if needed
mcp_mesh_dev stop --force
```

## Advanced Usage

### Process Management

The CLI includes sophisticated process management:

- **Process Tracking**: All started processes are tracked and can be monitored
- **Health Monitoring**: Regular health checks ensure services are running properly
- **Graceful Shutdown**: Services are stopped gracefully with configurable timeouts
- **Orphan Cleanup**: Orphaned processes are automatically detected and cleaned up

### Signal Handling

The CLI handles system signals gracefully:

- `SIGINT` (Ctrl+C): Graceful shutdown
- `SIGTERM`: Graceful shutdown
- `SIGHUP`: Reload configuration (where applicable)

### Background Mode

When running in background mode:

- Services run detached from the terminal
- PID files are created for process tracking
- Logs are written to files instead of stdout
- Status can be checked without affecting running services

### Integration with Other Tools

The CLI integrates well with other development tools:

```bash
# Use with systemd
systemctl --user start mcp-mesh-dev@my_agent

# Use with Docker
docker run -d --name mcp-mesh mcp-mesh:latest mcp_mesh_dev start agent.py

# Use with process managers
pm2 start "mcp_mesh_dev start agent.py" --name mcp-mesh

# Use in CI/CD pipelines
mcp_mesh_dev start --background test_agent.py
sleep 10
mcp_mesh_dev status --json | jq '.system.overall_status == "healthy"'
mcp_mesh_dev stop
```

### Performance Considerations

- Registry database is SQLite-based for simplicity and portability
- Health checks are optimized to minimize overhead
- Process tracking uses efficient native system calls
- Background mode reduces resource usage for long-running services

## Exit Codes

All CLI commands follow standard Unix exit code conventions:

- `0` - Success
- `1` - General error
- `2` - Misuse of shell command
- `130` - Interrupted by Ctrl+C

## See Also

- [Developer Workflow Guide](DEVELOPMENT_WORKFLOW.md)
- [Architecture Overview](ARCHITECTURE_OVERVIEW.md)
- [Troubleshooting Guide](TROUBLESHOOTING.md)
- [API Reference](../API_REFERENCE.md)
