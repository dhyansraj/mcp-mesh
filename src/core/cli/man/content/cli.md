# CLI Commands for Development

> Essential meshctl commands for developing and testing agents

## Quick Reference

| Command | Purpose |
|---------|---------|
| `meshctl call` | Invoke a tool on any agent |
| `meshctl list` | Show running agents |
| `meshctl list --tools` | List all available tools |
| `meshctl status` | Check mesh health |

## Calling Tools

```bash
# Call a tool (auto-discovers agent via registry)
meshctl call hello_mesh_simple

# Specify agent explicitly
meshctl call weather-agent:get_weather

# Pass arguments as JSON
meshctl call calculator:add '{"a": 1, "b": 2}'

# Arguments from file
meshctl call analyzer:process --file data.json

# Direct agent call (skip registry)
meshctl call hello_mesh --agent-url http://localhost:8080
```

## Listing Agents and Tools

```bash
# Show all running agents
meshctl list

# Wide view with endpoints and tool counts
meshctl list --wide

# Filter by name
meshctl list --filter hello

# List all tools across all agents
meshctl list --tools

# Show specific tool's schema
meshctl list --tools=get_current_time
```

## Checking Status

```bash
# Basic status
meshctl status

# Detailed information
meshctl status --verbose

# JSON output for scripting
meshctl status --json
```

## Remote Registry

All commands support connecting to remote registries:

```bash
meshctl call hello_mesh --registry-url http://remote:8000
meshctl list --registry-url http://remote:8000
meshctl status --registry-url http://remote:8000
```

## Docker Compose (from host machine)

Agents in Docker Compose register with container hostnames. To call from your host:

```bash
# Use --agent-url with mapped localhost port
meshctl call greet --agent-url http://localhost:9001
meshctl call calculator:add '{"a": 1, "b": 2}' --agent-url http://localhost:9002

# Find mapped ports
docker compose ps
```

## Kubernetes (with ingress)

```bash
# With DNS configured
meshctl call greet --ingress-domain mcp-mesh.local

# Port-forwarded ingress
meshctl call greet --ingress-domain mcp-mesh.local --ingress-url http://localhost:9080
```

## See Also

- `meshctl man testing` - MCP JSON-RPC protocol details
- `meshctl man scaffold` - Creating new agents
