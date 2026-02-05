# Inspect the Mesh (Java)

<div class="runtime-crossref">
  <span class="runtime-crossref-icon">&#x1F40D;</span>
  <span>Looking for Python? See <a href="../../python/local-development/04-inspecting-mesh/">Python Inspect Mesh</a></span>
  <span> | </span>
  <span class="runtime-crossref-icon">&#x1F4D8;</span>
  <span>Looking for TypeScript? See <a href="../../typescript/local-development/04-inspecting-mesh/">TypeScript Inspect Mesh</a></span>
</div>

> View agents, tools, and dependencies with `meshctl list` and `meshctl status`

These commands are language-agnostic -- they work the same regardless of whether your agents are Java, Python, or TypeScript.

## List Agents

```bash
# Show healthy agents (default)
meshctl list

# Show all agents including unhealthy
meshctl list --all

# Filter by name pattern
meshctl list --filter greeter

# Show additional columns (endpoints, tool counts)
meshctl list --wide
```

Example output:

```
NAME                    STATUS    DEPS     UPTIME
greeter-5395c5e4        healthy   2/2      5m
system-agent-a1b2c3d4   healthy   0/0      5m
weather-agent-x9y8z7    healthy   1/1      2m
```

## List Tools

```bash
# List all tools across all agents
meshctl list --tools
meshctl list -t

# Show details for a specific tool (schema, call spec)
meshctl list --tools=greeting

# Show tool from specific agent
meshctl list --tools=greeter:greeting
```

Example output:

```
TOOL                 AGENT                   CAPABILITY
greeting             greeter-5395c5e4        greeting
agent_info           greeter-5395c5e4        agent_info
get_weather          weather-agent-x9y8z7    weather_service
```

## Agent Status

```bash
# Show wiring details for all agents
meshctl status

# Show details for specific agent
meshctl status greeter-5395c5e4
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

Continue to [Call & Debug Tools](./05-calling-tools.md) ->
