# CLI Commands for Development

> The `meshctl` command surface — lifecycle, inspection, schema registry, tooling

`meshctl` covers the full developer loop: scaffold an agent, start it (locally or detached), inspect its wiring, call its tools, watch its logs, and tear it back down. All commands talk to the registry over HTTP and share a common set of `--registry-*` flags.

## Quick Reference

| Command                  | Purpose                                                            |
| ------------------------ | ------------------------------------------------------------------ |
| `meshctl start`          | Launch agents and/or registry (local or detached)                  |
| `meshctl stop`           | Stop detached agents and/or registry                               |
| `meshctl status`         | Show agent wiring and dependency resolution                        |
| `meshctl list`           | List agents, tools, or canonical schemas                           |
| `meshctl logs`           | View detached agent logs (with rotation, follow, history)          |
| `meshctl call`           | Invoke a tool on any agent                                         |
| `meshctl trace`          | Render a distributed call tree from a trace ID                     |
| `meshctl audit`          | Inspect dependency-resolution decisions (issue #547)               |
| `meshctl schema diff`    | Diff two canonical schemas by content hash (issue #547)            |
| `meshctl scaffold`       | Generate a new agent from templates                                |
| `meshctl config`         | Show effective configuration                                       |
| `meshctl entity`         | Manage trusted entity CAs for registration trust                   |
| `meshctl man`            | Show offline manual pages                                          |

## Lifecycle

### `meshctl start`

Starts agents and (if no registry is reachable) an embedded registry. Supports Python, TypeScript, and Java/Spring Boot agents.

```bash
# Registry only (no agents)
meshctl start --registry-only

# Single agent (auto-starts registry if needed)
meshctl start examples/hello_world.py

# Multiple agents in mixed languages
meshctl start agent1.py agent2.ts examples/java/my-agent

# Run detached (background) and follow logs separately
meshctl start agent.py --detach
meshctl logs my-agent -f

# Watch + auto-restart on file changes
meshctl start agent.py --watch

# Distributed tracing turned on, dashboard UI started, env file loaded
meshctl start agent.py --dte --ui --env-file .env.dev

# Connect to an external registry (don't embed one)
meshctl start agent.py --connect-only --registry-url https://registry.example.com
```

### `meshctl stop`

Stops detached processes. Without arguments, stops everything (agents + UI + registry). With names, stops only those agents and keeps shared services running.

```bash
meshctl stop                    # Stop all agents + UI + registry
meshctl stop my-agent           # Stop only my-agent
meshctl stop agent1 agent2      # Stop multiple
meshctl stop --agents           # Stop all agents, keep registry/UI alive
meshctl stop --keep-registry    # Stop everything except the registry
meshctl stop --clean            # Stop all + delete db, logs, pids
```

### `meshctl logs`

Logs are written to `~/.mcp-mesh/logs/` with automatic rotation (5 logs per agent).

```bash
meshctl logs my-agent              # Last 100 lines
meshctl logs my-agent -f           # Follow (like tail -f)
meshctl logs my-agent -p           # Previous log (before last restart)
meshctl logs my-agent -p 2         # 2 restarts ago
meshctl logs my-agent --tail 50    # Last 50 lines
meshctl logs my-agent --since 1h   # Last hour
meshctl logs my-agent --list       # List available agent logs
```

### `meshctl status`

Detailed wiring view: which dependencies resolved, which providers were chosen, which are missing.

```bash
meshctl status                              # All healthy agents
meshctl status hello-world-5395c5e4         # Specific agent (full ID)
meshctl status --json                       # Machine-readable
meshctl status --registry-url http://remote:8000
```

## Inspection

### `meshctl list`

Lists agents, tools, or canonical schemas depending on flags.

```bash
# Agents (default)
meshctl list                       # Healthy agents
meshctl list --all                 # Include unhealthy (purged after MCP_MESH_RETENTION)
meshctl list --wide                # Endpoints + tool counts
meshctl list --filter hello        # Substring match on agent ID
meshctl list --since 1h            # Active in the last hour

# Tools
meshctl list --tools               # All tools across all agents
meshctl list -t                    # Short form
meshctl list --tools=get_weather   # Show input schema for one tool
meshctl list --tools=system-agent:get_time   # Tool details on a specific agent

# Schemas (issue #547)
meshctl list --schemas             # Most recent 100 canonical schemas
meshctl list --schemas --limit 20  # Last 20
meshctl list --schemas --json      # Raw envelope from GET /schemas
```

### `meshctl call`

Invoke an MCP tool. Tool lookup matches by MCP tool name first, then falls back to capability name. Calls route through the registry proxy by default — that's what makes `meshctl call` work for agents in Docker/Kubernetes without exposing per-agent ports.

```bash
# Most common - auto-discover by tool name
meshctl call get_weather
meshctl call add '{"a": 1, "b": 2}'             # JSON arguments inline
meshctl call process --file data.json           # From file

# Target a specific agent (full ID from 'meshctl list')
meshctl call weather-agent-7f3a2b:get_weather

# Skip the registry proxy (requires direct network access)
meshctl call get_weather --use-proxy=false
meshctl call get_weather --agent-url http://localhost:8080

# Capture a trace ID for distributed tracing
meshctl call smart_analyze '{"query": "test"}' --trace
# Output includes: Trace ID: abc123...
```

### `meshctl trace`

Render the call tree for a distributed trace ID (use with `meshctl call --trace`).

```bash
meshctl trace abc123def456789                  # Pretty tree
meshctl trace abc123def456789 --json           # JSON output
meshctl trace abc123def456789 --show-internal  # Include wrapper spans (proxy_call_wrapper, etc.)

# Example output:
# └─ smart_analyze (llm-agent) [120ms] OK
#    ├─ get_current_time (time-agent) [5ms] OK
#    └─ fetch_data (data-agent) [15ms] OK
```

## Schema Registry (issue #547)

The registry stores canonical, content-addressed JSON Schemas for every tool's input and output, plus consumer "expected" schemas. Three commands surface this data:

### `meshctl list --schemas`

Lists the most recent canonical schemas in the registry. See above under **Inspection**.

### `meshctl schema diff`

Compares two canonical schemas by their sha256 hash. Useful for "why isn't this matching?" investigation — fetch the consumer's expected hash and the producer's output hash from `meshctl audit`, then diff them.

```bash
meshctl schema diff sha256:abc... sha256:def...
meshctl schema diff sha256:abc... sha256:def... --json   # tsuite-friendly
```

Output highlights:

- `-` fields present in A but not in B (red)
- `+` fields present in B but not in A (green)
- `~` fields present in both with different types (yellow)

### `meshctl audit`

Inspects the registry's per-dependency resolution log. See `meshctl man audit` for the full reason taxonomy and event format.

```bash
meshctl audit hello-world                 # Tabular summary, last 20 events
meshctl audit hello-world --explain       # Stage tree (pretty)
meshctl audit hello-world --function lookupEmployee --dep 0
meshctl audit hello-world --json | jq '.events[]'
```

## Development Tooling

### `meshctl scaffold`

Generates new agents from templates. Three input modes: interactive wizard, CLI flags, or YAML config. See `meshctl man scaffold` for the full reference.

```bash
# Interactive wizard (recommended for first-time use)
meshctl scaffold

# CLI flags - basic tool agent
meshctl scaffold --name my-agent --agent-type tool

# Other languages
meshctl scaffold --name my-agent --agent-type tool --lang typescript
meshctl scaffold --name my-agent --agent-type tool --lang java

# LLM-powered agent + zero-code provider
meshctl scaffold --name analyzer --agent-type llm-agent --llm-selector claude
meshctl scaffold --name claude-provider --agent-type llm-provider --model anthropic/claude-sonnet-4-5

# Generate docker-compose.yml + observability stack
meshctl scaffold --compose --observability

# Preview only
meshctl scaffold --name my-agent --agent-type tool --dry-run
```

### `meshctl config`

Shows the effective configuration meshctl is using (defaults, env vars, flags merged).

```bash
meshctl config show     # Current effective configuration
meshctl config path     # Path to the config file
```

### `meshctl man`

Renders manual pages embedded in the binary — works fully offline.

```bash
meshctl man                          # Architecture overview
meshctl man --list                   # All available topics
meshctl man --search "schema"        # Cross-topic full-text search
meshctl man decorators               # Python decorators
meshctl man decorators --typescript  # TypeScript variant
meshctl man decorators --java        # Java/Spring Boot variant
meshctl man --raw decorators         # Raw markdown (LLM-friendly)
meshctl man tutorial --day 3         # Single day of the 10-day tutorial
```

## Trust & Security

### `meshctl entity`

Manages trusted entity CAs for registration trust. Each entity is identified by a CA certificate — any agent presenting a certificate signed by a trusted entity CA is allowed to register. Full reference in `meshctl man security`.

```bash
meshctl entity register "partner-corp" --ca-cert /path/to/ca.pem
meshctl entity list
meshctl entity revoke "partner-corp"
meshctl entity rotate                   # Trigger cert rotation for all agents
meshctl entity rotate "partner-corp"    # Rotate for one entity
```

## Common Flags

Most read commands share these registry-connection flags:

```bash
--registry-url http://remote:8000   # Full URL (overrides host/port)
--registry-host prod.example.com    # Just the host
--registry-port 9000                # Just the port
--registry-scheme https             # http or https (default http)
--insecure                          # Skip TLS verification (self-signed certs)
--timeout 30                        # Request timeout in seconds
--json                              # Machine-readable output
```

## Docker Compose (from host machine)

When agents run in Docker but `meshctl` runs on the host, calls route through the registry proxy by default — that lets `meshctl call` reach agents via container hostnames the host can't resolve directly.

```bash
meshctl call greet                              # Through proxy (default)
meshctl call greet --use-proxy=false --agent-url http://localhost:9001
```

## Kubernetes (with ingress)

```bash
# With DNS configured
meshctl call greet --ingress-domain mcp-mesh.local

# Port-forwarded ingress (no DNS)
meshctl call greet --ingress-domain mcp-mesh.local --ingress-url http://localhost:9080
```

## See Also

- `meshctl man scaffold` — Generating new agents in detail
- `meshctl man audit` — Dependency-resolution audit format and reason taxonomy
- `meshctl man schema-matching` — Schema-aware capability filtering
- `meshctl man security` — `meshctl entity` and trust backends
- `meshctl man testing` — MCP JSON-RPC protocol details
- `meshctl man environment` — All environment variables
