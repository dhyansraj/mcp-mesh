# MCP Mesh Control CLI Reference

The MCP Mesh Control CLI (`meshctl`) is a Go-based command-line tool for developing, debugging, and managing MCP (Model Context Protocol) agents and services in a mesh architecture.

## Table of Contents

- [Installation](#installation)
- [Quick Start](#quick-start)
- [Commands](#commands)
- [Configuration](#configuration)
- [Examples](#examples)
- [Advanced Usage](#advanced-usage)

## Installation

### Pre-built Binaries

Download the latest release for your platform from the [releases page](https://github.com/yourusername/mcp-mesh/releases).

### Building from Source

```bash
# Clone the repository
git clone https://github.com/yourusername/mcp-mesh.git
cd mcp-mesh

# Build the CLI
go build -o meshctl cmd/meshctl/main.go

# Build the registry
go build -o mcp-mesh-registry cmd/mcp-mesh-registry/main.go

# Verify installation
./meshctl --version
```

## Quick Start

```bash
# Start registry in one terminal
./mcp-mesh-registry

# In another terminal, start an agent
./meshctl start examples/hello_world.py

# Check status
./meshctl status

# View running agents
./meshctl list

# Stop an agent
./meshctl stop hello-world

# Stop all agents
./meshctl stop --all
```

## Commands

### `start` - Start MCP Agent

Start an MCP agent and register it with the mesh.

**Syntax:**

```bash
meshctl start <agent-file> [flags]
```

**Flags:**

- `--name` - Override agent name (default: derived from filename)
- `--env` - Set environment variables (can be used multiple times)
- `--registry` - Registry URL (default: http://localhost:8000)
- `--timeout` - Startup timeout in seconds (default: 30)

**Examples:**

```bash
# Basic start
meshctl start my_agent.py

# With custom name
meshctl start my_agent.py --name my-custom-agent

# With environment variables
meshctl start my_agent.py --env API_KEY=xxx --env DEBUG=true

# With custom registry
meshctl start my_agent.py --registry http://registry.example.com:8000
```

### `stop` - Stop MCP Agent(s)

Stop one or more running MCP agents.

**Syntax:**

```bash
meshctl stop [agent-name] [flags]
```

**Flags:**

- `--all` - Stop all running agents
- `--force` - Force stop without graceful shutdown

**Examples:**

```bash
# Stop specific agent
meshctl stop my-agent

# Stop all agents
meshctl stop --all

# Force stop
meshctl stop my-agent --force
```

### `status` - Show Status

Display status of registry and running agents.

**Syntax:**

```bash
meshctl status [flags]
```

**Flags:**

- `--json` - Output in JSON format
- `--verbose` - Show detailed information

**Examples:**

```bash
# Basic status
meshctl status

# Detailed status
meshctl status --verbose

# JSON output for scripting
meshctl status --json
```

### `list` - List Agents

List all registered agents in the mesh.

**Syntax:**

```bash
meshctl list [flags]
```

**Flags:**

- `--filter` - Filter by capability (can be used multiple times)
- `--status` - Filter by status (healthy, degraded, offline)
- `--json` - Output in JSON format

**Examples:**

```bash
# List all agents
meshctl list

# Filter by capability
meshctl list --filter file_operations --filter auth

# Filter by status
meshctl list --status healthy

# JSON output
meshctl list --json
```

### `logs` - View Agent Logs

Stream or view logs from running agents.

**Syntax:**

```bash
meshctl logs <agent-name> [flags]
```

**Flags:**

- `--follow` - Stream logs in real-time
- `--tail` - Number of lines to show from the end (default: 100)
- `--since` - Show logs since timestamp (e.g., "10m", "1h")

**Examples:**

```bash
# View recent logs
meshctl logs my-agent

# Stream logs
meshctl logs my-agent --follow

# Last 50 lines
meshctl logs my-agent --tail 50

# Logs from last 10 minutes
meshctl logs my-agent --since 10m
```

### `restart` - Restart Agent

Restart a running agent.

**Syntax:**

```bash
meshctl restart <agent-name> [flags]
```

**Flags:**

- `--env` - Update environment variables

**Examples:**

```bash
# Basic restart
meshctl restart my-agent

# Restart with new environment
meshctl restart my-agent --env DEBUG=false
```

### `config` - Manage Configuration

View and manage CLI configuration.

**Syntax:**

```bash
meshctl config [subcommand] [flags]
```

**Subcommands:**

- `show` - Display current configuration
- `set` - Set configuration value
- `get` - Get specific configuration value

**Examples:**

```bash
# Show all config
meshctl config show

# Set registry URL
meshctl config set registry.url http://localhost:8000

# Get specific value
meshctl config get registry.url
```

## Configuration

### Configuration File

The CLI uses a configuration file located at:

- Linux/macOS: `~/.config/mcp-mesh/config.yaml`
- Windows: `%APPDATA%\mcp-mesh\config.yaml`

**Example configuration:**

```yaml
registry:
  url: http://localhost:8000
  timeout: 30s

agent:
  default_timeout: 60s
  health_check_interval: 30s

logging:
  level: info
  format: json
```

### Environment Variables

The following environment variables can be used:

- `MCP_MESH_REGISTRY_URL` - Override registry URL
- `MCP_MESH_LOG_LEVEL` - Set log level (debug, info, warn, error)
- `MCP_MESH_CONFIG_PATH` - Custom config file path
- `MCP_MESH_DATA_DIR` - Data directory for logs and state

## Examples

### Basic Workflow

```bash
# 1. Start the registry (in terminal 1)
./mcp-mesh-registry

# 2. Start a file operations agent (in terminal 2)
./meshctl start examples/file_agent.py

# 3. Start a system agent (in terminal 3)
./meshctl start examples/system_agent.py

# 4. Check status
./meshctl status

# 5. View logs
./meshctl logs file-agent --follow

# 6. Stop all agents
./meshctl stop --all
```

### Development Workflow

```bash
# Start agent with debugging
./meshctl start my_agent.py --env MCP_MESH_DEBUG=true

# Monitor logs while developing
./meshctl logs my-agent --follow

# Restart after code changes
./meshctl restart my-agent

# Check agent health
./meshctl status --verbose
```

### Production Deployment

```bash
# Start with production config
export MCP_MESH_CONFIG_PATH=/etc/mcp-mesh/prod.yaml
./meshctl start production_agent.py

# Monitor with JSON logs
./meshctl logs production-agent --follow | jq '.'

# Health check endpoint
curl http://localhost:8000/health
```

## Advanced Usage

### Process Management

The CLI manages agent processes intelligently:

- Graceful shutdown with configurable timeout
- Automatic restart on failure (configurable)
- Process isolation and resource limits
- Signal handling (SIGTERM, SIGINT)

### Log Aggregation

All agent logs are aggregated and can be:

- Streamed in real-time
- Filtered by level
- Exported in JSON format
- Rotated automatically

### Registry Integration

The CLI automatically:

- Registers agents with the mesh registry
- Monitors agent health
- Updates capability information
- Handles network failures gracefully

### Multi-Agent Coordination

```bash
# Start multiple agents from a directory
for agent in agents/*.py; do
  ./meshctl start "$agent"
done

# Monitor all agents
./meshctl status --verbose

# Stop agents with specific capability
./meshctl list --filter auth --json | \
  jq -r '.agents[].name' | \
  xargs -I {} ./meshctl stop {}
```

## Troubleshooting

### Common Issues

1. **Registry Connection Failed**

   ```bash
   # Check if registry is running
   curl http://localhost:8000/health

   # Use custom registry URL
   ./meshctl start agent.py --registry http://registry:8000
   ```

2. **Agent Won't Start**

   ```bash
   # Check logs
   ./meshctl logs agent-name --tail 50

   # Start with debug logging
   ./meshctl start agent.py --env MCP_MESH_DEBUG=true
   ```

3. **Port Already in Use**

   ```bash
   # Find process using port
   lsof -i :8000

   # Use different port
   MCP_MESH_REGISTRY_PORT=8001 ./mcp-mesh-registry
   ```

### Debug Mode

Enable debug mode for verbose output:

```bash
export MCP_MESH_LOG_LEVEL=debug
./meshctl status --verbose
```

## Migration from Python CLI

If you're migrating from the old Python CLI (`mcp_mesh_dev`):

1. The commands are largely the same
2. Configuration format has changed from TOML to YAML
3. The Go CLI is significantly faster and uses less memory
4. All functionality has been preserved or improved

### Key Differences

| Python CLI                | Go CLI                           | Notes                   |
| ------------------------- | -------------------------------- | ----------------------- |
| `mcp_mesh_dev`            | `meshctl`                        | Different binary name   |
| `~/.mcp-mesh/config.toml` | `~/.config/mcp-mesh/config.yaml` | New config location     |
| Python 3.10+ required     | Standalone binary                | No runtime dependencies |
| 100MB+ memory             | <20MB memory                     | Much more efficient     |

## Contributing

The CLI is written in Go and located in `cmd/meshctl/`. Contributions welcome!

```bash
# Run tests
go test ./internal/cli/...

# Build with version info
go build -ldflags "-X main.Version=1.0.0" -o meshctl cmd/meshctl/main.go
```
