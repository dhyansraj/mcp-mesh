# Scaffold Agents (TypeScript)

<div class="runtime-crossref">
  <span class="runtime-crossref-icon">🐍</span>
  <span>Looking for Python? See <a href="../../../python/local-development/02-scaffold/">Python Scaffold</a></span>
  <span> | </span>
  <span class="runtime-crossref-icon">☕</span>
  <span>Looking for Java? See <a href="../../../java/local-development/02-scaffold/">Java Scaffold</a></span>
</div>

> Generate agents with `meshctl scaffold`

## Interactive Mode (Recommended)

The easiest way to create an agent:

```bash
meshctl scaffold
```

This launches an interactive wizard that guides you through:

- Agent name and type
- Language (choose TypeScript)
- Capabilities and tools
- Output directory

The generated code includes placeholder tools—you'll need to edit `src/index.ts` to implement your logic.

## CLI Mode

For scripting or when you know what you want:

```bash
# Basic tool agent
meshctl scaffold basic --name my-agent --lang typescript

# LLM-powered agent
meshctl scaffold llm --name emotion-analyzer \
  --vendor openai --lang typescript

# LLM provider (zero-code)
meshctl scaffold llm-provider --name claude-provider \
  --vendor claude --model anthropic/claude-sonnet-4-5 --lang typescript
```

## Agent Types

| Subcommand     | Description                        | Use Case                             |
| -------------- | ---------------------------------- | ------------------------------------ |
| `basic`        | Basic agent with `addTool()`       | Services, utilities, data processing |
| `llm`          | LLM-powered agent                  | AI assistants, text analysis         |
| `llm-provider` | Zero-code LLM wrapper              | Expose LLM as mesh capability        |
| `api`          | Express gateway (`mesh.route()`)   | HTTP APIs that call mesh tools       |

## Generated Files

```
my-agent/
├── src/
│   └── index.ts      # Agent code - edit this to add your logic
├── package.json      # Add your dependencies here
├── tsconfig.json     # TypeScript config (ready to use)
├── Dockerfile        # Container build (ready to use)
├── helm-values.yaml  # Kubernetes config
└── README.md
```

**After scaffolding:**

1. `cd my-agent && npm install`
2. Edit `src/index.ts` to implement your tool logic (placeholder returns `"Not implemented"`)

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
meshctl scaffold basic --name my-agent --lang typescript --dry-run
```

## More Options

```bash
# See all scaffold options
meshctl scaffold --help
```

## Next Steps

Continue to [Run Agents](./03-running-agents.md) →
