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
meshctl scaffold basic --name hello --lang java

# LLM-powered agent
meshctl scaffold llm --name analyzer --lang java \
  --vendor openai --response-format json

# LLM provider (zero-code)
meshctl scaffold llm-provider --name claude-provider --lang java \
  --vendor claude --model anthropic/claude-sonnet-4-5
```

## Agent Types

| Subcommand     | Annotation         | Use Case                              |
| -------------- | ------------------ | ------------------------------------- |
| `basic`        | `@MeshTool`        | Services, utilities, data processing  |
| `llm`          | `@MeshLlm`         | AI assistants, text analysis          |
| `llm-provider` | `@MeshLlmProvider` | Expose LLM as mesh capability         |
| `api`          | `@MeshRoute`       | Spring Boot HTTP gateway              |

## Generated Files

```
hello/
├── src/
│   └── main/
│       ├── java/com/example/hello/
│       │   └── HelloApplication.java   # Agent code - edit @MeshTool methods
│       └── resources/
│           └── application.yml
├── pom.xml             # Maven build with mcp-mesh-spring-boot-starter
├── Dockerfile          # Container build (ready to use)
├── helm-values.yaml    # Kubernetes config
└── README.md
```

**After scaffolding:** Edit the `@MeshTool` annotated methods to implement your tool logic. The placeholder returns `"Not implemented"`.

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
meshctl scaffold basic --name hello --lang java --dry-run
```

## More Options

```bash
# See all scaffold options
meshctl scaffold --help
```

## Next Steps

Continue to [Run Agents](./03-running-agents.md) ->
