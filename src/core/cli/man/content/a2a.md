# A2A (Agent-to-Agent Protocol)

> Bridge external A2A v1.0 endpoints into the mesh AND expose mesh tools as A2A skills
> Full guide: https://mcp-mesh.ai/a2a/

## Overview

MCP Mesh implements the A2A v1.0 protocol on both sides of the wire:

- **Producer** (Python only today): expose mesh tools as A2A skills via `@mesh.a2a` + `mesh.a2a.mount(app, ...)`. Auto-generates `/.well-known/agent.json` and the JSON-RPC entry route.
- **Consumer** (Python, Java, TypeScript): bridge an external A2A skill into the mesh as a regular capability. Downstream callers consume it with no awareness of A2A.

Cross-vendor failover, DDDI, health-driven rewiring, and long-running jobs all apply on top — without any changes to the A2A protocol itself. See `https://mcp-mesh.ai/a2a/` for the full guide with diagrams and architecture deep-dive.

## Quick consumer (the canonical bridge)

The same `get-date` bridge in three runtimes — re-publishes an upstream A2A `get-date` skill as a mesh `current-date` capability.

### Python

```python
import json
import mesh
from fastmcp import FastMCP

app = FastMCP("Date Consumer Bridge")


@app.tool()
@mesh.a2a_consumer(
    capability="current-date",
    a2a_url="http://localhost:9090/agents/date",
    a2a_skill_id="get-date",
)
async def current_date(_a2a: mesh.A2AClient = None) -> dict:
    response = await _a2a.send(
        message={"role": "user", "parts": [{"type": "text", "text": "now"}]},
    )
    return json.loads(response.artifact_text)


@mesh.agent(name="date-consumer", http_port=9201)
class DateConsumer:
    pass
```

### TypeScript

```typescript
import { FastMCP, mesh, type A2AClient } from "@mcpmesh/sdk";
import { z } from "zod";

const server = new FastMCP({ name: "Date Consumer Bridge", version: "1.0.0" });
const agent = mesh(server, { name: "date-consumer-ts", httpPort: 9201 });

agent.addTool({
  name: "current_date",
  capability: "current-date",
  parameters: z.object({}),
  a2aConfig: {
    url: "http://localhost:9090/agents/date",
    skillId: "get-date",
  },
  execute: async (_args, ..._injected) => {
    const a2a = _injected[0] as A2AClient;
    const r = await a2a.send({
      role: "user", parts: [{ type: "text", text: "now" }],
    });
    return r.artifactText ? JSON.parse(r.artifactText) : "";
  },
});
```

### Java

```java
@MeshAgent(name = "date-consumer", port = 9201)
@SpringBootApplication
public class DateConsumerAgentApplication {
    public static void main(String[] args) {
        SpringApplication.run(DateConsumerAgentApplication.class, args);
    }

    @MeshTool(capability = "current-date")
    @A2AConsumer(
        url = "http://localhost:9090/agents/date",
        skillId = "get-date"
    )
    public Map<String, Object> currentDate(A2AClient a2a) throws Exception {
        A2AResponse r = a2a.send(Map.of(
            "role", "user",
            "parts", List.of(Map.of("type", "text", "text", "now"))
        ));
        return new ObjectMapper().readValue(r.artifactText(), Map.class);
    }
}
```

## Producer (Python only)

```python
import mesh
from fastapi import FastAPI
from mesh.types import McpMeshTool

app = FastAPI(title="Date A2A Agent")


@mesh.a2a.mount(
    app,
    path="/agents/date",
    dependencies=["date_service"],
    skill_id="get-date",
    skill_name="Get Date",
)
async def date_a2a(payload: dict, date_service: McpMeshTool = None):
    if date_service is None:
        return {"error": "date_service not yet resolved"}
    return {"date": await date_service()}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=9090)
```

The user owns the FastAPI app AND the uvicorn lifecycle (no `@mesh.agent` decorator). `mesh.a2a.mount(...)` attaches BOTH:

- `GET  /agents/date/.well-known/agent.json` — auto-generated card
- `POST /agents/date` — JSON-RPC entry for `tasks/*` methods

A single Python process may NOT host both `@mesh.tool` capabilities and a `mesh.a2a.mount(...)` surface — the framework rejects mixed-mode at boot. Split into two agents (one provider, one A2A surface that depends on it).

Java and TypeScript producer support is future work.

## Consumer (Python / Java / TypeScript)

The consumer marker per runtime:

| Runtime    | Marker                                      | Injection                              |
| ---------- | ------------------------------------------- | -------------------------------------- |
| Python     | `@mesh.a2a_consumer(capability=..., a2a_url=...)` | `_a2a: mesh.A2AClient = None` kwarg |
| TypeScript | `addTool({ a2aConfig: { url, skillId } })`  | `_injected[N] as A2AClient`            |
| Java       | `@A2AConsumer(url=..., skillId=...)` on a `@MeshTool` method | `A2AClient` parameter slot |

**Auto-tag.** Every consumer registers its capability with the surrounding agent name appended as a tag, so multiple consumers bridging the same logical capability are distinguishable to downstream callers via `dependencies=[{capability: "...", tags: ["<consumer-name>"]}]`. Untagged dependencies let the resolver pick any healthy consumer.

## Long-running tasks (`task=True`)

When the upstream A2A skill is long-running, mark the consumer `task=True` and bridge the polling state into the framework-injected `JobController`:

```python
@app.tool()
@mesh.a2a_consumer(
    capability="report",
    a2a_url="http://localhost:9091/agents/report",
    a2a_skill_id="generate-report",
    task=True,
)
async def report(
    user_id: str,
    sections: list[str],
    _a2a: mesh.A2AClient = None,
    job: MeshJob = None,
) -> dict:
    a2a_job = await _a2a.submit(message={
        "role": "user",
        "parts": [{"type": "text", "text": json.dumps({"user_id": user_id, "sections": sections})}],
    })
    return await a2a_job.bridge(job)
```

`A2AJob.bridge(controller)` polls the upstream A2A `tasks/get`, mirrors progress into the controller, and returns the final artifact value when the task reaches a terminal state.

For SSE: `_a2a.subscribe(...)` returns an `A2AStream`; call `stream.bridge(job)` for the equivalent SSE consumption + bridge.

**Cancel propagation.** The polling bridge POSTs `tasks/cancel` upstream when the mesh-side job is cancelled. The SSE bridge does NOT (per A2A v1.0, client disconnect ≠ cancel). Use the polling bridge if cancel propagation to the upstream is required.

## Authentication (Phase 1: bearer)

```python
@mesh.a2a_consumer(
    capability="forecast",
    a2a_url="https://upstream.example.com/agents/forecast",
    a2a_skill_id="forecast-7day",
    auth=mesh.A2ABearer(token_env="UPSTREAM_TOKEN"),
)
```

Token resolves at call time, so a rotated env-var picks up the new value without restart. Mutually exclusive with literal `token=...`.

Java: `@A2AConsumer(authBearerEnv = "UPSTREAM_TOKEN")`.
TypeScript: `a2aConfig.auth = { tokenEnv: "UPSTREAM_TOKEN" }`.

OAuth and mTLS are future work.

## Scaffolding

Generate a complete consumer from an upstream A2A producer's agent card:

```bash
# Fetch the card and generate one capability per skill
meshctl scaffold a2a-consumer --url http://upstream.example.com/agents/forecast \
    --lang python --name weather-bridge --port 9201

# TypeScript
meshctl scaffold a2a-consumer --url ... --lang typescript --name weather-bridge

# Java
meshctl scaffold a2a-consumer --url ... --lang java --name weather-bridge

# Offline placeholder (no fetch)
meshctl scaffold a2a-consumer --offline --lang python --name placeholder
```

The scaffolder reads `card.authentication.schemes` and wires up the bearer block automatically when bearer is advertised. Default env-var name is `A2A_BEARER_TOKEN` — override with `--auth-env`.

## Working examples

- `examples/a2a/date_a2a_agent.py` — Python A2A producer (sync)
- `examples/a2a/report_a2a_agent.py` — Python A2A producer (long-running + SSE)
- `examples/a2a/consumer_date_agent.py` — Python consumer (sync)
- `examples/a2a/consumer_report_agent.py` — Python consumer (long-running poll)
- `examples/a2a/consumer_report_agent_sse.py` — Python consumer (SSE)
- `examples/typescript/consumer-date-agent/` — TS consumer (sync)
- `examples/typescript/consumer-report-agent/` — TS consumer (poll)
- `examples/typescript/consumer-report-agent-sse/` — TS consumer (SSE)
- `examples/java/consumer-date-agent/` — Java consumer (sync)
- `examples/java/consumer-report-agent/` — Java consumer (poll)
- `examples/java/consumer-report-agent-sse/` — Java consumer (SSE)

## See Also

- `meshctl man jobs` — `MeshJob` substrate that long-running A2A consumers bridge into
- `meshctl man scaffold` — generic scaffolding overview
- `meshctl man capabilities` — capability+tag system used for A2A consumer failover
- `meshctl man tags` — auto-tag mechanism semantics
- [`docs/a2a/`](https://mcp-mesh.ai/a2a/) — full guide with diagrams, architecture deep-dive, and per-runtime walkthroughs
- [A2A v1.0 specification](https://a2a-protocol.org/latest/specification/)
