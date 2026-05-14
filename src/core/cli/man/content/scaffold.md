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

| Subcommand     | Decorator            | Description                               |
| -------------- | -------------------- | ----------------------------------------- |
| `basic`        | `@mesh.tool`         | Basic capability agent                    |
| `llm`          | `@mesh.llm`          | LLM-powered agent that consumes providers |
| `llm-provider` | `@mesh.llm_provider` | Zero-code LLM provider                    |

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

## Key Flags

| Flag               | Description                                           |
| ------------------ | ----------------------------------------------------- |
| `--name`           | Agent name (required for non-interactive)             |
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
meshctl scaffold llm --name analyzer --filter '[{"capability": "calculator"}]'

# Filter tools by tags
meshctl scaffold llm --name analyzer --filter '[{"tags": ["tools"]}]'
```

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
