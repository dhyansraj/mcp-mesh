# Agent Scaffolding

> Generate MCP Mesh agents from templates

Scaffold supports **Python**, **TypeScript**, and **Java** agents. Use `--lang typescript` for TypeScript or `--lang java` for Java/Spring Boot.

## Input Modes

| Mode        | Usage                                       | Best For         |
| ----------- | ------------------------------------------- | ---------------- |
| Interactive | `meshctl scaffold`                          | First-time users |
| CLI flags   | `meshctl scaffold basic --name my-agent`    | Scripting        |
| Config file | `meshctl scaffold --config scaffold.yaml`   | Complex agents   |

## Agent Types

| Subcommand     | Decorator                               | Description                                  |
| -------------- | --------------------------------------- | -------------------------------------------- |
| `basic`        | `@mesh.tool`                            | Basic capability agent                       |
| `llm`          | `@mesh.llm`                             | LLM-powered agent that consumes providers    |
| `llm-provider` | `@mesh.llm_provider`                    | Zero-code LLM provider                       |
| `a2a-consumer` | (A2A bridge)                            | Bridge external A2A producer skills          |
| `api`          | (`@mesh.route` / Express / Spring Boot) | HTTP API gateway consuming mesh capabilities |

## Quick Examples

```bash
# Basic tool agent (Python - default)
meshctl scaffold basic --name my-agent

# Basic tool agent (TypeScript)
meshctl scaffold basic --name my-agent --lang typescript

# Basic tool agent (Java/Spring Boot)
meshctl scaffold basic --name my-agent --lang java

# LLM agent using Claude
meshctl scaffold llm --name analyzer --vendor claude

# LLM provider exposing OpenAI
meshctl scaffold llm-provider --name gpt-provider --vendor openai

# Python FastAPI gateway with @mesh.route
meshctl scaffold api --name gateway --lang python

# TypeScript Express gateway
meshctl scaffold api --name gateway --lang typescript

# Java Spring Boot gateway
meshctl scaffold api --name gateway --lang java

# Preview without creating files
meshctl scaffold basic --name my-agent --dry-run

# Non-interactive mode (for CI/scripts)
meshctl scaffold basic --name my-agent --no-interactive
```

## Docker Compose Generation

```bash
# Generate docker-compose.yml for all agents in current directory
meshctl scaffold --compose

# Include observability stack (Redis, Tempo, Grafana)
meshctl scaffold --compose --observability

# Custom project name
meshctl scaffold --compose --project-name my-project
```

### Generate observability stack alone

If you only want the observability infra (Redis + Tempo + Grafana) without bundling it into your main `docker-compose.yml`, use the standalone `--observability` mode:

```bash
meshctl scaffold --observability
```

This emits a separate `docker-compose.observability.yml` file. Start it with:

```bash
docker compose -f docker-compose.observability.yml up -d
```

Combine with `--compose --observability` if you want a single merged file instead.

## Key Flags

Common flags (apply to all subcommands):

| Flag               | Description                                            |
| ------------------ | ------------------------------------------------------ |
| `--name`           | Agent name (required for non-interactive)              |
| `--lang`           | Language: `python` (default), `typescript`, or `java`  |
| `--output`         | Output directory (default: `.`)                        |
| `--port`           | HTTP port (default: 8080)                              |
| `--description`    | Agent description                                      |
| `--package`        | Java package name (default `com.example.<agent-name>`) |
| `--dry-run`        | Preview generated code                                 |
| `--no-interactive` | Disable prompts (for scripting)                        |

LLM agent flags (`llm` and `llm-provider` subcommands):

| Flag                | Description                                                                          |
| ------------------- | ------------------------------------------------------------------------------------ |
| `--vendor`          | Provider tag: `claude` (default), `openai`, `gemini`, `litellm-fallback`             |
| `--model`           | Override LiteLLM model string (default derived from `--vendor`)                      |
| `--response-format` | LLM response format: `text` (default), `json` (`llm` subcommand)                     |
| `--max-iterations`  | Max agentic loop iterations (default 1) (`llm` subcommand)                           |
| `--system-prompt`   | System prompt (inline or `file://path` for Jinja2 template) (`llm` subcommand)       |
| `--context-param`   | Context parameter name (default `ctx`)                                               |
| `--tags`            | Tags for discovery (comma-separated)                                                 |
| `--filter`          | Tool filter for `llm` agents (capability selector JSON)                              |
| `--filter-mode`     | Filter mode: `all` (default), `best_match`, `*` (wildcard) — companion to `--filter` |

Docker compose flags (top-level scaffold, no subcommand):

| Flag              | Description                                           |
| ----------------- | ----------------------------------------------------- |
| `--compose`       | Generate docker-compose.yml                           |
| `--observability` | Add Redis/Tempo/Grafana (compose or standalone)       |
| `--project-name`  | Docker compose project name (default: directory name) |

The `--filter` flag uses capability selector syntax. See `meshctl man capabilities` for details. Pair it with `--filter-mode` to control how multiple filter clauses combine.

```bash
# Filter tools by capability
meshctl scaffold llm --name analyzer --filter '[{"capability": "calculator"}]'

# Filter tools by tags
meshctl scaffold llm --name analyzer --filter '[{"tags": ["tools"]}]'

# Best-match mode (pick the single best-scoring provider)
meshctl scaffold llm --name analyzer --filter '[{"tags": ["math"]}]' --filter-mode best_match
```

## A2A Consumer Scaffold

Bridge an external A2A v1.0 producer's skills into the mesh as ordinary capabilities. Fetches the producer's `/.well-known/agent.json` at scaffold time; each skill in the card becomes a mesh capability in the generated agent.

```bash
# Python consumer bridging an external A2A producer
meshctl scaffold a2a-consumer --url http://localhost:9090/agents/date \
  --lang python --name date-bridge --port 9201

# TypeScript variant
meshctl scaffold a2a-consumer --url https://weather.com/agents/forecast \
  --lang typescript --name weather-bridge

# Java variant
meshctl scaffold a2a-consumer --url https://weather.com/agents/forecast \
  --lang java --name weather-bridge

# Offline placeholder (no fetch — user fills in URL, skill, auth later)
meshctl scaffold a2a-consumer --offline --lang python --name placeholder
```

If the producer's card declares bearer authentication, the generated code wires up an env-var-based bearer token placeholder (default `A2A_BEARER_TOKEN`).

See `meshctl man a2a` for the full A2A protocol bridge guide.

## Hybrid Development Workflow

Run agents locally with `meshctl start` while using Docker for infrastructure and tracing:

```bash
# 1. Create registry + observability stack (no agents needed)
meshctl scaffold --compose --observability
docker compose up -d

# 2. Create .env file for local agents
cat > .env << 'EOF'
MCP_MESH_DISTRIBUTED_TRACING_ENABLED=true
EOF

# 3. Run agents locally with file watching
meshctl start agent.py --watch --env-file .env
```

Benefits:

- Fast local development (edit code, auto-reload with `--watch`)
- Full observability (traces in Grafana at http://localhost:3000)
- Shared registry (all agents discover each other)

See `meshctl man environment` for all configuration options.

## See Also

- `meshctl man decorators` - Decorator reference
- `meshctl man llm` - LLM integration guide
- `meshctl man deployment` - Docker and Kubernetes deployment
