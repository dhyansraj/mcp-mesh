# meshctl CLI Reference

> Command-line tool for MCP Mesh development and deployment

## Installation

**Supported platforms:** macOS, Linux (Windows users: use WSL or Git Bash)

=== "npm (Recommended)"

    ```bash
    npm install -g @mcpmesh/cli
    ```

=== "Homebrew"

    ```bash
    brew install dhyansraj/tap/meshctl
    ```

=== "curl"

    ```bash
    curl -sSL https://raw.githubusercontent.com/dhyansraj/mcp-mesh/main/install.sh | bash
    ```

Verify installation:

```bash
meshctl --version
```

## Commands

| Command      | Description                       |
| ------------ | --------------------------------- |
| `start`      | Start agents with mesh runtime    |
| `stop`       | Stop detached agents and registry |
| `list`       | List running agents               |
| `status`     | Show detailed agent status        |
| `call`       | Call an MCP tool on an agent      |
| `trace`      | Display distributed call trace    |
| `logs`       | View agent logs (detached mode)   |
| `scaffold`   | Generate new agent from template  |
| `man`        | Show built-in documentation       |
| `config`     | Manage meshctl configuration      |
| `completion` | Generate shell autocompletion     |

## Quick Reference

### Start Agents

```bash
meshctl start my_agent.py              # Start Python agent
meshctl start src/index.ts             # Start TypeScript agent
meshctl start -w my_agent.py           # Hot reload on changes
meshctl start -d my_agent.py           # Detached (background)
meshctl start --debug my_agent.py      # Debug logging
meshctl start --registry-only          # Start registry only
meshctl start agent1.py agent2.ts      # Multiple agents
```

### Call Tools

```bash
meshctl call get_weather                    # Auto-discover agent
meshctl call add '{"a": 1, "b": 2}'         # With JSON args
meshctl call --trace get_weather            # With tracing
meshctl call weather-agent-7f3a:get_weather # Specific agent
```

### Inspect Mesh

```bash
meshctl list                   # List healthy agents
meshctl list --all             # Include unhealthy
meshctl list --tools           # List all tools
meshctl list --tools=add       # Show tool schema
meshctl status                 # Show wiring details
meshctl status my-agent        # Specific agent
```

### Scaffold Agents

```bash
meshctl scaffold                              # Interactive wizard
meshctl scaffold --name my-agent              # Python agent
meshctl scaffold --name my-agent -l ts        # TypeScript agent
meshctl scaffold --compose                    # Generate docker-compose
meshctl scaffold --compose --observability    # With tracing stack
```

### View Documentation

```bash
meshctl man --list              # List all topics
meshctl man decorators          # Python decorators
meshctl man decorators -t       # TypeScript version
meshctl man deployment          # Deployment guide
```

### Manage Background Agents

```bash
meshctl logs my-agent           # View logs
meshctl logs my-agent -f        # Follow logs
meshctl stop my-agent           # Stop specific agent
meshctl stop                    # Stop all + registry
```

## Detailed Help

Each command has comprehensive built-in help with examples:

```bash
meshctl --help              # All commands
meshctl start --help        # Start options
meshctl call --help         # Call options
meshctl scaffold --help     # Scaffold options
meshctl man --help          # Man page options
```

## Environment Variables

| Variable                | Description                             | Default                 |
| ----------------------- | --------------------------------------- | ----------------------- |
| `MCP_MESH_REGISTRY_URL` | Registry URL                            | `http://localhost:8000` |
| `MCP_MESH_LOG_LEVEL`    | Log level (TRACE/DEBUG/INFO/WARN/ERROR) | `INFO`                  |
| `MCP_MESH_HTTP_PORT`    | Agent HTTP port                         | Auto-assigned           |

See [Environment Variables](../environment-variables.md) for the full list.
