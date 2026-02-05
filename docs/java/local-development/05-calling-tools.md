# Call & Debug Tools (Java)

<div class="runtime-crossref">
  <span class="runtime-crossref-icon">&#x1F40D;</span>
  <span>Looking for Python? See <a href="../../python/local-development/05-calling-tools/">Python Call Tools</a></span>
  <span> | </span>
  <span class="runtime-crossref-icon">&#x1F4D8;</span>
  <span>Looking for TypeScript? See <a href="../../typescript/local-development/05-calling-tools/">TypeScript Call Tools</a></span>
</div>

> Call tools and trace distributed calls with `meshctl call`, `meshctl trace`, and `meshctl logs`

These commands are language-agnostic -- they work the same regardless of whether your agents are Java, Python, or TypeScript.

## Call Tools

```bash
# Auto-discover agent by tool name (recommended)
meshctl call greeting

# With JSON arguments
meshctl call greeting '{"name": "World"}'

# Arguments from file
meshctl call process --file data.json
```

## Target Specific Agent

When multiple agents provide the same tool:

```bash
# Use full agent ID from 'meshctl list'
meshctl call greeter-5395c5e4:greeting '{"name": "World"}'
```

## Distributed Tracing

Tracing requires **Redis + Tempo** in addition to the registry. The easiest way to set this up for local development:

```bash
# 1. Generate docker-compose with observability stack
meshctl scaffold --compose --observability

# 2. Start infrastructure (registry + Redis + Tempo)
docker compose up -d

# 3. Run your agents locally (auto-connects to Docker registry)
meshctl start hello/
```

Now you can trace calls:

```bash
# Call with tracing enabled
meshctl call --trace greeting '{"name": "World"}'
```

Output includes a trace ID:

```
Result: {"message": "Hello, World! Welcome to MCP Mesh.", "timestamp": "...", "source": "greeter-java"}
Trace ID: abc123def456789
```

## View Call Tree

```bash
# View the full call tree
meshctl trace abc123def456789
```

Shows the complete call hierarchy:

```
greeting (greeter) 85ms
└── add (calculator) 12ms
```

!!! note "Without Docker"
If you're not running the observability stack, `meshctl call` still works but `--trace` won't capture data and `meshctl trace` won't return results.

## View Agent Logs

For agents running in background (detached mode):

```bash
# Last 100 lines (default)
meshctl logs greeter

# Follow logs in real-time
meshctl logs greeter -f

# Last 50 lines
meshctl logs greeter --tail 50

# Logs from last 10 minutes
meshctl logs greeter --since 10m

# Previous log (before last restart)
meshctl logs greeter -p

# List available agent logs
meshctl logs --list
```

## Built-in Documentation

```bash
# List all documentation topics
meshctl man --list

# View specific topic
meshctl man annotations       # Java annotations reference
meshctl man llm               # LLM integration guide
meshctl man di                # Dependency injection
meshctl man quickstart        # Getting started guide

# Raw markdown (for LLMs)
meshctl man annotations --raw
```

## Quick Reference

| Command                       | Description               |
| ----------------------------- | ------------------------- |
| `meshctl call <tool>`         | Call tool (auto-discover) |
| `meshctl call <tool> '{...}'` | Call with JSON args       |
| `meshctl call --trace <tool>` | Call with tracing         |
| `meshctl trace <id>`          | View call tree            |
| `meshctl logs <agent> -f`     | Follow agent logs         |
| `meshctl man --list`          | List doc topics           |
| `meshctl man <topic>`         | View documentation        |

## Troubleshooting Calls

If a call fails:

1. Check the agent is running: `meshctl list`
2. Check tool exists: `meshctl list --tools=<tool_name>`
3. Enable tracing: `meshctl call --trace <tool>`
4. Check logs: `meshctl logs <agent> --since 5m`

## Next Steps

See [Troubleshooting](./troubleshooting.md) for Java-specific issues ->
