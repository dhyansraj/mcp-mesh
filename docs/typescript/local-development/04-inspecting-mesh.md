# Inspect the Mesh (TypeScript)

<div class="runtime-crossref">
  <span class="runtime-crossref-icon">🐍</span>
  <span>Looking for Python? See <a href="../../python/local-development/04-inspecting-mesh/">Python Inspect Mesh</a></span>
</div>

> View agents, tools, and dependencies with `meshctl list` and `meshctl status`

## List Agents

```bash
# Show healthy agents (default)
meshctl list

# Show all agents including unhealthy
meshctl list --all

# Filter by name pattern
meshctl list --filter weather

# Show additional columns (endpoints, tool counts)
meshctl list --wide
```

Example output:

```
NAME                    STATUS    DEPS     UPTIME
hello-world-5395c5e4    healthy   2/2      5m
system-agent-a1b2c3d4   healthy   0/0      5m
weather-agent-x9y8z7    healthy   1/1      2m
```

## List Tools

```bash
# List all tools across all agents
meshctl list --tools
meshctl list -t

# Show details for a specific tool (schema, call spec)
meshctl list --tools=get_weather

# Show tool from specific agent
meshctl list --tools=weather-agent:get_weather
```

Example output:

```
TOOL                 AGENT                   CAPABILITY
get_weather          weather-agent-x9y8z7    weather_service
get_current_time     system-agent-a1b2c3d4   system_info
hello_mesh_simple    hello-world-5395c5e4    greeter
```

## Agent Status

```bash
# Show wiring details for all agents
meshctl status

# Show details for specific agent
meshctl status hello-world-5395c5e4
```

Shows:

- Agent metadata (name, version, capabilities)
- Resolved dependencies (which agents provide them)
- HTTP endpoint
- Health status

## JSON Output

For scripting and automation:

```bash
meshctl list --json
meshctl status --json
meshctl list --tools --json
```

## Remote Registry

Inspect agents on a remote registry:

```bash
meshctl list --registry-url http://remote:8000
meshctl status --registry-url http://remote:8000
```

## Quick Reference

| Command                  | Description         |
| ------------------------ | ------------------- |
| `meshctl list`           | List healthy agents |
| `meshctl list --all`     | List all agents     |
| `meshctl list -t`        | List all tools      |
| `meshctl list -t=<tool>` | Show tool details   |
| `meshctl status`         | Show agent wiring   |
| `meshctl status <agent>` | Show specific agent |

## Next Steps

Continue to [Call & Debug Tools](./05-calling-tools.md) →
