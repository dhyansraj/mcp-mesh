# Scaffolding A2A Consumers

Generate a complete, runnable A2A consumer agent from an upstream A2A producer's agent card. One mesh capability per skill in the card, in any of the three supported runtimes.

## Basic invocation

```bash
meshctl scaffold a2a-consumer \
    --url http://upstream.example.com/agents/forecast \
    --lang python \
    --name weather-bridge \
    --port 9201
```

| Flag             | Required | Default                  | Purpose                                       |
| ---------------- | -------- | ------------------------ | --------------------------------------------- |
| `--url`          | yes\*    | —                        | Producer URL (base or with `/.well-known/agent.json`) |
| `--lang`, `-l`   | no       | `python`                 | Target runtime: `python`, `typescript`, `java` |
| `--name`, `-n`   | yes      | —                        | Mesh agent name                               |
| `--output`, `-o` | no       | `.`                      | Output directory                              |
| `--port`, `-p`   | no       | `8080`                   | HTTP port for the generated agent             |
| `--description`  | no       | (from card)              | Agent description                             |
| `--auth-env`     | no       | `A2A_BEARER_TOKEN`       | Env var name for bearer token (used when card advertises bearer) |
| `--package`      | no       | `com.example.<agent-name>` | Java package name                             |
| `--offline`      | no       | `false`                  | Skip card fetch; emit a single TODO skill skeleton |
| `--dry-run`      | no       | `false`                  | Preview generated files without writing       |

\* `--url` is required unless `--offline` is set.

Source: `src/core/cli/scaffold/a2a_consumer_subcommand.go`.

## How it works

```mermaid
flowchart LR
    URL[--url] -->|HTTP GET| CARD[/.well-known/agent.json]
    OFFLINE[--offline] -->|placeholder| SKILLS
    CARD -->|parse| SKILLS[card.skills array]
    CARD -->|read| AUTH[card.authentication.schemes]
    SKILLS -->|one capability per skill| RENDER
    AUTH -->|bearer? yes| RENDER
    LANG[--lang] -->|select template| RENDER[Template renderer]
    RENDER -->|write files| OUT[Output tree]
```

1. Fetch `<url>/.well-known/agent.json` (skipped under `--offline`).
2. Parse `card.skills[]` — each becomes one mesh capability in the generated agent.
3. Detect `card.authentication.schemes` — if `bearer` is advertised, wire the env-var-based bearer block into the generated code.
4. Render the per-language template tree (Python / TypeScript / Java) into `--output`.

Under `--offline`, a single placeholder skill is emitted with TODO markers for the operator to fill in producer URL, skill ID, and auth.

## Generated output

=== "Python"

    ```
    weather-bridge/
    ├── __init__.py
    ├── __main__.py
    ├── main.py            # the @mesh.a2a_consumer-decorated handler(s)
    ├── requirements.txt
    ├── Dockerfile
    ├── helm-values.yaml
    └── README.md
    ```

    Source templates: `cmd/meshctl/templates/python/a2a-consumer/`.

=== "TypeScript"

    ```
    weather-bridge/
    ├── src/
    │   └── index.ts       # FastMCP + agent.addTool({ a2aConfig })
    ├── package.json
    ├── tsconfig.json
    ├── Dockerfile
    ├── helm-values.yaml
    └── README.md
    ```

    Source templates: `cmd/meshctl/templates/typescript/a2a-consumer/`.

=== "Java"

    ```
    weather-bridge/
    ├── src/main/java/<package>/
    │   └── <AgentName>Application.java   # @MeshAgent + @A2AConsumer methods
    ├── pom.xml
    ├── Dockerfile
    ├── helm-values.yaml
    └── README.md
    ```

    Source templates: `cmd/meshctl/templates/java/a2a-consumer/`.

## Post-scaffold customization

The generated handler bodies are minimal — they construct an A2A `message` from the function arguments and parse the artifact text on the way back. You will typically want to customize:

- **Schema.** The generated parameter schema is best-effort from the card. Tighten it (Zod / Pydantic / `@Param` annotations) to match the upstream skill's actual contract.
- **Message construction.** The default message body is `[{type: "text", text: "..."}]`. Real producers may expect structured payloads — adjust the `parts` array.
- **Auth wiring.** If the card did not declare auth but the producer requires it, add the bearer block manually (see [Authentication](authentication.md)).
- **Long-running.** The scaffolder generates sync consumers by default. To bridge a `task=True` upstream skill, add `task=True` (Python) / `task: true` (TS) / `task = true` (Java) and wire `bridge(JobController)` per [Long-Running & SSE](long-running.md).

## Offline placeholder

For environments where the producer URL isn't reachable at scaffold time (air-gapped builds, ahead-of-time codegen):

```bash
meshctl scaffold a2a-consumer \
    --offline \
    --lang python \
    --name placeholder-bridge \
    --port 9201
```

A single placeholder skill is emitted with `TODO` markers. The operator fills in the producer URL, skill ID, and auth before running the agent.

## See also

- [Consumer Quick Start](consumer-quickstart.md) — what the generated code looks like in context
- [Authentication](authentication.md) — env-var bearer wiring
- [Examples Gallery](examples.md) — runnable examples that mirror the scaffolded shape
