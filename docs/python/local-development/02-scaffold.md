# Scaffold Agents (Python)

<div class="runtime-crossref">
  <span class="runtime-crossref-icon">☕</span>
  <span>Looking for Java? See <a href="../../../java/local-development/02-scaffold/">Java Scaffold</a></span>
  <span> | </span>
  <span class="runtime-crossref-icon">📘</span>
  <span>Looking for TypeScript? See <a href="../../../typescript/local-development/02-scaffold/">TypeScript Scaffold</a></span>
</div>

> Generate agents with `meshctl scaffold`

## Interactive Mode (Recommended)

The easiest way to create an agent:

```bash
meshctl scaffold
```

This launches an interactive wizard that guides you through:

- Agent name and type
- Capabilities and tools
- Output directory

The generated code includes placeholder tools—you'll need to edit `main.py` to implement your logic.

## CLI Mode

For scripting or when you know what you want:

```bash
# Basic tool agent
meshctl scaffold basic --name my-agent

# LLM-powered agent
meshctl scaffold llm --name emotion-analyzer \
  --vendor openai --response-format json

# LLM provider (zero-code)
meshctl scaffold llm-provider --name claude-provider \
  --vendor claude --model anthropic/claude-sonnet-4-5
```

## Agent Types

| Subcommand     | Description                     | Use Case                             |
| -------------- | ------------------------------- | ------------------------------------ |
| `basic`        | Basic agent with `@mesh.tool`   | Services, utilities, data processing |
| `llm`          | LLM-powered with `@mesh.llm`    | AI assistants, text analysis         |
| `llm-provider` | Zero-code LLM wrapper           | Expose LLM as mesh capability        |
| `api`          | FastAPI gateway (`@mesh.route`) | HTTP APIs that call mesh tools       |

## Generated Files

```
my-agent/
├── main.py           # Agent code - edit this to add your logic
├── requirements.txt  # Add your dependencies here
├── Dockerfile        # Container build (ready to use)
├── helm-values.yaml  # Kubernetes config
└── README.md
```

**After scaffolding:** Edit `main.py` to implement your tool logic. The placeholder returns `"Not implemented"`.

## Generate Docker Compose

```bash
# Generate docker-compose.yml for all agents in directory
meshctl scaffold --compose

# With observability stack (registry + Redis + Tempo + Grafana)
meshctl scaffold --compose --observability
```

!!! tip "Local Tracing Setup"
Use `--compose --observability` even if you run agents locally. Start the infrastructure with `docker compose up -d`, then run agents with `meshctl start`—they auto-connect to the Docker registry. This enables `meshctl call --trace` and `meshctl trace`.

## Preview Before Creating

```bash
# Dry run - see what would be generated
meshctl scaffold basic --name my-agent --dry-run
```

## More Options

```bash
# See all scaffold options
meshctl scaffold --help
```

## Next Steps

Continue to [Run Agents](./03-running-agents.md) →
