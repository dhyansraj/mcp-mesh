# CLI Commands for Development

> Essential meshctl commands for developing and testing agents

## Quick Reference

| Command                | Purpose                    |
| ---------------------- | -------------------------- |
| `meshctl call`         | Invoke a tool on any agent |
| `meshctl list`         | Show healthy agents        |
| `meshctl list --tools` | List all available tools   |
| `meshctl status`       | Show agent wiring details  |

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
# Show healthy agents (default)
meshctl list

# Show all agents including unhealthy/expired
meshctl list --all

# Wide view with endpoints and tool counts
meshctl list --wide

# Filter by name
meshctl list --filter hello

# List tools from healthy agents
meshctl list --tools

# Show tool's input schema
meshctl list --tools=get_current_time
```

## Checking Status

```bash
# Show all healthy agents' wiring
meshctl status

# Show specific agent details
meshctl status hello-world-5395c5e4

# JSON output
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

Calls route through registry proxy by default, reaching agents via container hostnames:

```bash
# Calls route through registry proxy (default)
meshctl call greet
meshctl call calculator:add '{"a": 1, "b": 2}'

# Direct call bypassing proxy
meshctl call greet --agent-url http://localhost:9001 --use-proxy=false
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
