# Scaffold Agents (Java)

<div class="runtime-crossref">
  <span class="runtime-crossref-icon">&#x1F40D;</span>
  <span>Looking for Python? See <a href="../../../python/local-development/02-scaffold/">Python Scaffold</a></span>
  <span> | </span>
  <span class="runtime-crossref-icon">&#x1F4D8;</span>
  <span>Looking for TypeScript? See <a href="../../../typescript/local-development/02-scaffold/">TypeScript Scaffold</a></span>
</div>

> Generate Java agents with `meshctl scaffold`

## Interactive Mode (Recommended)

The easiest way to create an agent:

```bash
meshctl scaffold
```

This launches an interactive wizard that guides you through:

- Agent name and type
- Language selection (choose Java)
- Capabilities and tools
- Output directory

The generated code includes placeholder tools -- you'll need to edit the `@MeshTool` methods to implement your logic.

## CLI Mode

For scripting or when you know what you want:

```bash
# Basic tool agent
meshctl scaffold --name hello --agent-type basic --lang java

# LLM-powered agent
meshctl scaffold --name analyzer --agent-type llm-agent --lang java \
  --llm-selector openai --response-format json

# LLM provider (zero-code)
meshctl scaffold --name claude-provider --agent-type llm-provider --lang java \
  --model anthropic/claude-sonnet-4-5
```

## Agent Types

| Type           | Annotation         | Use Case                              |
| -------------- | ------------------ | ------------------------------------- |
| `basic`        | `@MeshTool`        | Services, utilities, data processing  |
| `llm-agent`    | `@MeshLlm`         | AI assistants, text analysis          |
| `llm-provider` | `@MeshLlmProvider` | Expose LLM as mesh capability         |

## Generated Files

```
hello/
├── src/
│   └── main/
│       ├── java/com/example/hello/
│       │   └── HelloAgentApplication.java   # Agent code - edit @MeshTool methods
│       └── resources/
│           └── application.properties
├── pom.xml             # Maven build with mcp-mesh-spring-boot-starter
├── Dockerfile          # Container build (ready to use)
├── helm-values.yaml    # Kubernetes config
└── README.md
```

**After scaffolding:** Edit the `@MeshTool` annotated methods to implement your tool logic. The placeholder returns `"Not implemented"`.

## Add Tools to Existing Agent

```bash
meshctl scaffold --name hello --add-tool \
  --tool-name process_data \
  --tool-description "Process incoming data"
```

## Generate Docker Compose

```bash
# Generate docker-compose.yml for all agents in directory
meshctl scaffold --compose

# With observability stack (registry + Redis + Tempo + Grafana)
meshctl scaffold --compose --observability
```

!!! tip "Local Tracing Setup"
Use `--compose --observability` even if you run agents locally. Start the infrastructure with `docker compose up -d`, then run agents with `meshctl start` -- they auto-connect to the Docker registry. This enables `meshctl call --trace` and `meshctl trace`.

## Preview Before Creating

```bash
# Dry run - see what would be generated
meshctl scaffold --name hello --agent-type basic --lang java --dry-run
```

## More Options

```bash
# See all scaffold options
meshctl scaffold --help

# See available agent templates
meshctl scaffold --list-modes
```

## Next Steps

Continue to [Run Agents](./03-running-agents.md) ->
