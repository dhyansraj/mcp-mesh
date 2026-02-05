# Agent Scaffolding

> Generate MCP Mesh agents from templates

Scaffold supports **Python**, **TypeScript**, and **Java** agents. Use `--lang typescript` for TypeScript or `--lang java` for Java/Spring Boot.

## Input Modes

| Mode        | Usage                                                | Best For         |
| ----------- | ---------------------------------------------------- | ---------------- |
| Interactive | `meshctl scaffold`                                   | First-time users |
| CLI flags   | `meshctl scaffold --name my-agent --agent-type tool` | Scripting        |
| Config file | `meshctl scaffold --config scaffold.yaml`            | Complex agents   |

## Agent Types

| Type           | Decorator            | Description                               |
| -------------- | -------------------- | ----------------------------------------- |
| `tool`         | `@mesh.tool`         | Basic capability agent                    |
| `llm-agent`    | `@mesh.llm`          | LLM-powered agent that consumes providers |
| `llm-provider` | `@mesh.llm_provider` | Zero-code LLM provider                    |

## Quick Examples

```bash
# Basic tool agent (Python - default)
meshctl scaffold --name my-agent --agent-type tool

# Basic tool agent (TypeScript)
meshctl scaffold --name my-agent --agent-type tool --lang typescript

# Basic tool agent (Java/Spring Boot)
meshctl scaffold --name my-agent --agent-type tool --lang java

# LLM agent using Claude
meshctl scaffold --name analyzer --agent-type llm-agent --llm-selector claude

# LLM provider exposing GPT-4
meshctl scaffold --name gpt-provider --agent-type llm-provider --model openai/gpt-4

# Preview without creating files
meshctl scaffold --name my-agent --agent-type tool --dry-run

# Non-interactive mode (for CI/scripts)
meshctl scaffold --name my-agent --agent-type tool --no-interactive
```

## Adding Tools to Existing Agents

```bash
# Add a basic tool
meshctl scaffold --name my-agent --add-tool new_function --tool-type mesh.tool

# Add an LLM-powered tool
meshctl scaffold --name my-agent --add-tool smart_function --tool-type mesh.llm
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

## Key Flags

| Flag               | Description                                           |
| ------------------ | ----------------------------------------------------- |
| `--name`           | Agent name (required for non-interactive)             |
| `--agent-type`     | `tool`, `llm-agent`, or `llm-provider`                |
| `--lang`           | Language: `python` (default), `typescript`, or `java` |
| `--dry-run`        | Preview generated code                                |
| `--no-interactive` | Disable prompts (for scripting)                       |
| `--output`         | Output directory (default: `.`)                       |
| `--port`           | HTTP port (default: 8080)                             |
| `--model`          | LiteLLM model for llm-provider                        |
| `--llm-selector`   | LLM provider for llm-agent: `claude`, `openai`        |
| `--filter`         | Tool filter for llm-agent (capability selector JSON)  |
| `--compose`        | Generate docker-compose.yml                           |
| `--observability`  | Add Redis/Tempo/Grafana to compose                    |

The `--filter` flag uses capability selector syntax. See `meshctl man capabilities` for details.

```bash
# Filter tools by capability
meshctl scaffold --name analyzer --agent-type llm-agent --filter '[{"capability": "calculator"}]'

# Filter tools by tags
meshctl scaffold --name analyzer --agent-type llm-agent --filter '[{"tags": ["tools"]}]'
```

## Hybrid Development Workflow

Run agents locally with `meshctl start` while using Docker for infrastructure and tracing:

```bash
# 1. Create registry + observability stack (no agents needed)
meshctl scaffold --compose --observability
docker compose up -d

# 2. Create .env file for local agents
cat > .env << 'EOF'
MCP_MESH_REGISTRY_URL=http://localhost:8000
MCP_MESH_DISTRIBUTED_TRACING_ENABLED=true
TRACE_EXPORTER_TYPE=otlp
TELEMETRY_ENDPOINT=localhost:4317
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
