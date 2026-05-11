# A2A Consumer Quick Start

Bridge an external A2A `get-date` skill into the mesh as a `current-date` capability. Same task, three runtimes — pick yours.

## Prereqs

- A registry — `meshctl start --registry-only`
- An external A2A producer reachable at `http://localhost:9090/agents/date` exposing a `get-date` skill (the canonical example is `examples/a2a/date_a2a_agent.py` — see the [Producer (Python)](producer.md) page).

## The bridge

=== "Python"

    ```python
    import json
    import os

    HTTP_PORT = int(os.environ.setdefault("MCP_MESH_HTTP_PORT", "9201"))

    import mesh
    from fastmcp import FastMCP

    app = FastMCP("Date Consumer Bridge")


    @app.tool()
    @mesh.a2a_consumer(
        capability="current-date",
        a2a_url="http://localhost:9090/agents/date",
        a2a_skill_id="get-date",
        tags=["a2a-bridge"],
    )
    async def current_date(_a2a: mesh.A2AClient = None) -> dict:
        response = await _a2a.send(
            message={"role": "user", "parts": [{"type": "text", "text": "now"}]},
        )
        return json.loads(response.artifact_text)


    @mesh.agent(name="date-consumer", http_port=HTTP_PORT)
    class DateConsumer:
        pass
    ```

    Run with:

    ```bash
    python consumer_date_agent.py
    ```

=== "TypeScript"

    ```typescript
    import { FastMCP, mesh, type A2AClient } from "@mcpmesh/sdk";
    import { z } from "zod";

    const HTTP_PORT = parseInt(process.env.MCP_MESH_HTTP_PORT ?? "9201", 10);

    const server = new FastMCP({
      name: "Date Consumer Bridge (TS)",
      version: "1.0.0",
    });

    const agent = mesh(server, {
      name: "date-consumer-ts",
      httpPort: HTTP_PORT,
      description: "TypeScript A2A consumer bridge for get-date.",
    });

    agent.addTool({
      name: "current_date",
      capability: "current-date",
      tags: ["a2a-bridge"],
      parameters: z.object({}),
      a2aConfig: {
        url: "http://localhost:9090/agents/date",
        skillId: "get-date",
      },
      execute: async (_args, ..._injected) => {
        const a2a = _injected[0] as A2AClient;
        const r = await a2a.send({
          role: "user",
          parts: [{ type: "text", text: "now" }],
        });
        return r.artifactText ? JSON.parse(r.artifactText) : "";
      },
    });
    ```

    Run with:

    ```bash
    npx tsx index.ts
    ```

=== "Java"

    ```java
    package com.example.dateconsumer;

    import io.mcpmesh.MeshAgent;
    import io.mcpmesh.MeshTool;
    import io.mcpmesh.a2a.A2AClient;
    import io.mcpmesh.a2a.A2AConsumer;
    import io.mcpmesh.a2a.A2AResponse;
    import org.springframework.boot.SpringApplication;
    import org.springframework.boot.autoconfigure.SpringBootApplication;
    import tools.jackson.databind.ObjectMapper;

    import java.util.List;
    import java.util.Map;

    @MeshAgent(name = "date-consumer", port = 9201)
    @SpringBootApplication
    public class DateConsumerAgentApplication {

        private static final ObjectMapper JSON = new ObjectMapper();

        public static void main(String[] args) {
            SpringApplication.run(DateConsumerAgentApplication.class, args);
        }

        @MeshTool(capability = "current-date", tags = {"a2a-bridge"})
        @A2AConsumer(
            url = "http://localhost:9090/agents/date",
            skillId = "get-date"
        )
        public Map<String, Object> currentDate(A2AClient a2a) throws Exception {
            A2AResponse response = a2a.send(Map.of(
                "role", "user",
                "parts", List.of(Map.of("type", "text", "text", "now"))
            ));
            return JSON.readValue(response.artifactText(), Map.class);
        }
    }
    ```

    Run with:

    ```bash
    mvn spring-boot:run
    ```

## What just happened

All three runtimes register a regular mesh capability named `current-date`. Behind the surface they share the same architecture:

- **Framework-injected `A2AClient`.** Each runtime detects the consumer marker (Python decorator, TypeScript `a2aConfig`, Java `@A2AConsumer`), constructs one `A2AClient` per unique `(url, skillId, auth)` tuple, caches it for the agent's lifetime, and injects it at the right parameter slot. Lifecycle (incl. close) is owned by the framework — never construct or close the client yourself.
- **Auto-tagged with the consumer name.** The capability is registered with the surrounding agent name appended as a tag (`date-consumer`, `date-consumer-ts`). When two consumers bridge the same logical capability, downstream callers can pin a specific provider via tags. See [Failover & Federation](failover.md).
- **No A2A leakage.** A downstream tool that depends on `current-date` does not see the A2A backend. It calls the capability the same way it would call any other mesh tool — DDDI, capability+tag selection, retries, headers all behave identically.

## Calling the bridged capability

A downstream tool consumes the bridged capability via the standard mesh DI pattern — no A2A-specific code:

```python
@mesh.tool(
    capability="report",
    dependencies=[
        {"capability": "current-date", "tags": ["date-consumer"]},
    ],
)
async def report(current_date: McpMeshTool = None):
    return await current_date()
```

Drop the `tags` filter to let the resolver pick any healthy consumer.

## Generate from an agent card

If your upstream A2A producer publishes a `/.well-known/agent.json` card, you can scaffold a complete consumer (one mesh capability per skill) instead of writing it by hand:

```bash
meshctl scaffold a2a-consumer \
    --url http://localhost:9090/agents/date \
    --lang python --name date-bridge --port 9201
```

Same flag set generates Java (`--lang java`) and TypeScript (`--lang typescript`) consumers. See [Scaffolding](scaffolding.md).

## See also

- [Failover & Federation](failover.md) — multi-consumer setups + tag-pinning
- [Authentication](authentication.md) — wiring bearer tokens
- [Scaffolding](scaffolding.md) — `meshctl scaffold a2a-consumer`
- [Long-Running & SSE](long-running.md) — when the upstream skill is `task=True`
