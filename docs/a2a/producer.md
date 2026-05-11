# A2A Producer

Expose mesh tools to external A2A clients via the A2A v1.0 protocol surface.

!!! info "Producer support is complete across all three runtimes"
    Producer support ships in **Python**, **Java**, and **TypeScript** — all three runtimes have full A2A support on both the producer and consumer sides.

## Decoration and mounting

A producer agent's handler is decorated/mounted via a runtime-native entry point that simultaneously **stamps metadata** (skill id, name, description, tags, dependencies) and **attaches routes** (the JSON-RPC entry at `path` AND `/.well-known/agent.json` at `path/.well-known/agent.json`). The two-piece pattern is intentionally the same shape as `@mesh.route` / `@MeshRoute` for HTTP routes — same hosting framework, same lifecycle ownership, same DDDI for declared dependencies. The difference is that the producer entry registers the agent with the registry as `agent_type=a2a` (with the surfaces array populated), so other mesh agents and external scaffolding tools can discover the agent's A2A skills.

=== "Python"

    `@mesh.a2a.mount(app, path="/agents/<skill>", ...)` on a user-owned FastAPI app. The user owns the uvicorn lifecycle (no `@mesh.agent` decorator on the producer file).

    The standalone `@mesh.a2a(...)` decorator is also exposed for advanced cases (multi-app fan-out, custom mounting), but the recommended path for typical producer agents is `@mesh.a2a.mount(...)`.

=== "Java"

    `@MeshA2A(path = "/agents/<skill>", ...)` on a Spring Boot bean method (sibling to `@MeshRoute`). The framework auto-mounts both routes on the application's `DispatcherServlet` — the user owns the Spring Boot lifecycle (`SpringApplication.run(...)`).

    Mesh dependencies are declared via `@MeshDependency` entries on the annotation and injected at `@MeshInject` parameter slots, identical to the `@MeshRoute` DDDI path.

=== "TypeScript"

    `mesh.a2a.mount(app, config, handler)` on a user-owned Express app (sibling to `mesh.route(...)`). The user owns the Express app AND the `app.listen()` lifecycle — same shape as `mesh.route(...)` HTTP handlers. The mesh api-runtime pipeline picks up the mounted A2A surface from the `A2AProducerRegistry` and registers the agent with the registry as `agent_type=a2a` on each heartbeat.

    Mesh dependencies are declared via the `dependencies` array on the mount config and supplied to the handler under the `deps` argument keyed by capability name, identical to how `mesh.route(...)` injects resolved `McpMeshTool` proxies.

## Sync handler

The simplest case — the upstream returns within seconds, so there is no parking. The handler returns a value; the framework wraps it as an A2A v1.0 `Task` envelope with `state=completed`, placing the JSON-stringified return as `result.artifacts[0].parts[0].text`.

=== "Python"

    ```python
    import mesh
    from fastapi import FastAPI
    from mesh.types import McpMeshTool

    app = FastAPI(title="Date A2A Agent")


    @mesh.a2a.mount(
        app,
        path="/agents/date",
        dependencies=["date_service"],
        description="Get current date/time via A2A protocol",
        skill_id="get-date",
        skill_name="Get Date",
        tags=["system", "date"],
    )
    async def date_a2a(payload: dict, date_service: McpMeshTool = None):
        if date_service is None:
            return {"error": "date_service not yet resolved"}
        result = await date_service()
        return {"date": result}


    if __name__ == "__main__":
        import uvicorn
        uvicorn.run(app, host="0.0.0.0", port=9090, log_level="info")
    ```

=== "Java"

    ```java
    package com.example.dateproducer;

    import io.mcpmesh.MeshAgent;
    import io.mcpmesh.spring.web.MeshA2A;
    import io.mcpmesh.spring.web.MeshDependency;
    import io.mcpmesh.spring.web.MeshInject;
    import io.mcpmesh.types.McpMeshTool;
    import org.springframework.boot.SpringApplication;
    import org.springframework.boot.autoconfigure.SpringBootApplication;
    import org.springframework.stereotype.Component;

    import java.util.Map;

    @MeshAgent(name = "date-a2a-agent", port = 9090)
    @SpringBootApplication
    public class ProducerDateAgentApplication {

        public static void main(String[] args) {
            SpringApplication.run(ProducerDateAgentApplication.class, args);
        }

        @Component
        static class DateSkill {

            @MeshA2A(
                path = "/agents/date",
                skillId = "get-date",
                skillName = "Get Date",
                description = "Get current date/time via A2A protocol",
                tags = {"system", "date"},
                dependencies = {
                    @MeshDependency(capability = "date_service")
                }
            )
            public Map<String, Object> getDate(
                    Map<String, Object> message,
                    @MeshInject("date_service") McpMeshTool dateService) {
                if (dateService == null) {
                    return Map.of("error", "date_service not yet resolved");
                }
                return Map.of("date", dateService.call(Map.of()));
            }
        }
    }
    ```

=== "TypeScript"

    ```typescript
    import express from "express";
    import { mesh, type McpMeshTool } from "@mcpmesh/sdk";

    process.env.MCP_MESH_HTTP_PORT = process.env.MCP_MESH_HTTP_PORT ?? "9090";
    process.env.MCP_MESH_AGENT_NAME = process.env.MCP_MESH_AGENT_NAME ?? "date-a2a-agent";

    const app = express();
    app.use(express.json());

    mesh.a2a.mount(
      app,
      {
        path: "/agents/date",
        skillId: "get-date",
        skillName: "Get Date",
        description: "Get current date/time via A2A protocol",
        tags: ["system", "date"],
        dependencies: ["date_service"],
      },
      async (deps, _payload) => {
        const dateService = deps.date_service as McpMeshTool | null;
        if (dateService == null) {
          return { error: "date_service not yet resolved" };
        }
        return { date: await dateService.call({}) };
      },
    );

    app.listen(9090);
    ```

Two routes are now live on port 9090:

| Route                                      | Purpose                                       |
| ------------------------------------------ | --------------------------------------------- |
| `GET  /agents/date/.well-known/agent.json` | Auto-generated agent card (capabilities, skills, auth schemes) |
| `POST /agents/date`                        | JSON-RPC entry — dispatches `tasks/*` methods |

The card is built at agent registration time from the `@mesh.tool` / `@MeshA2A` / `mesh.a2a.mount(...)` metadata of declared dependencies and the producer-entry parameters (`skill_id`, `skill_name`, `description`, `tags`). Source: `src/runtime/python/_mcp_mesh/engine/a2a_card.py` (Python), `src/runtime/java/mcp-mesh-spring-boot-starter/.../MeshA2ACardBuilder.java` (Java), `src/runtime/typescript/src/a2a/producer/card-builder.ts` (TypeScript).

## Long-running handler (`task=True`)

When the underlying work is long-running (`task=True` in the dependency graph), the handler returns a `JobProxy` instead of a value. The framework parks the proxy in the A2A task store and responds to the inbound `tasks/send` immediately with `state=working` and a fresh task id. Subsequent `tasks/get` and `tasks/cancel` calls operate on the parked proxy via the underlying `MeshJob` lifecycle.

=== "Python"

    ```python
    import json
    import mesh
    from fastapi import FastAPI
    from mesh import MeshJob

    app = FastAPI(title="Report A2A Agent")


    @mesh.a2a.mount(
        app,
        path="/agents/report",
        dependencies=["generate_report"],
        description="Generate a long-form report via A2A (task=True streaming)",
        skill_id="generate-report",
        skill_name="Generate Report",
        tags=["reports", "long-running"],
    )
    async def report_a2a(payload: dict, generate_report: MeshJob = None):
        if generate_report is None:
            raise RuntimeError("generate_report dependency not yet resolved by mesh DI")

        args = {}
        parts = payload.get("parts") or []
        if parts and parts[0].get("type") == "text":
            try:
                args = json.loads(parts[0].get("text") or "{}")
            except json.JSONDecodeError:
                args = {}

        proxy = await generate_report.submit(
            user_id=args.get("user_id", "anon"),
            sections=args.get("sections") or ["overview"],
        )
        return proxy
    ```

=== "Java"

    ```java
    package com.example.reportproducer;

    import io.mcpmesh.JobProxy;
    import io.mcpmesh.MeshAgent;
    import io.mcpmesh.MeshJobSubmitter;
    import io.mcpmesh.spring.web.MeshA2A;
    import org.springframework.boot.SpringApplication;
    import org.springframework.boot.autoconfigure.SpringBootApplication;
    import org.springframework.stereotype.Component;

    import java.util.LinkedHashMap;
    import java.util.Map;
    import java.util.concurrent.TimeUnit;

    @MeshAgent(name = "report-a2a-agent", port = 9091)
    @SpringBootApplication
    public class ProducerReportAgentApplication {

        public static void main(String[] args) {
            SpringApplication.run(ProducerReportAgentApplication.class, args);
        }

        @Component
        static class ReportSkill {

            @MeshA2A(
                path = "/agents/report",
                skillId = "generate-report",
                skillName = "Generate Report",
                description = "Generate a long-form report via A2A (task=True streaming)",
                tags = {"reports", "long-running"}
            )
            public Object generateReport(
                    Map<String, Object> message,
                    MeshJobSubmitter jobSubmitter) throws Exception {
                // Issue #936: the framework auto-injects a MeshJobSubmitter
                // bound to the task capability — defaults to the first
                // declared @MeshDependency or, when none is declared, to the
                // skillId with '-' replaced by '_' (so "generate-report"
                // resolves to the generate_report task capability).
                Map<String, Object> payload = new LinkedHashMap<>();
                payload.put("user_id", "alice");
                payload.put("sections", java.util.List.of("intro", "body"));
                // Bounded wait — submit() is a registry round-trip, NOT the
                // long job itself. 30s is comfortable headroom; anything
                // longer is a registry/provider problem and should surface
                // as a failed A2A task rather than an indefinite hang.
                JobProxy proxy = jobSubmitter.submit(payload).get(30, TimeUnit.SECONDS);
                return proxy; // long-running mode trigger
            }
        }
    }
    ```

=== "TypeScript"

    ```typescript
    import express from "express";
    import { mesh } from "@mcpmesh/sdk";

    process.env.MCP_MESH_HTTP_PORT = process.env.MCP_MESH_HTTP_PORT ?? "9091";
    process.env.MCP_MESH_AGENT_NAME = process.env.MCP_MESH_AGENT_NAME ?? "report-a2a-agent";

    const app = express();
    app.use(express.json());

    mesh.a2a.mount(
      app,
      {
        path: "/agents/report",
        skillId: "generate-report",
        skillName: "Generate Report",
        description: "Generate a long-form report via A2A (task=True streaming)",
        tags: ["reports", "long-running"],
      },
      async (_deps, payload, jobSubmitter) => {
        // Issue #936: the framework auto-injects a MeshJobSubmitter as the
        // third positional handler arg. The capability defaults to the
        // first declared dependency or, when none is declared, to the
        // skillId with '-' replaced by '_' (so "generate-report" resolves
        // to the generate_report task capability).
        if (!jobSubmitter) {
          // api-runtime not yet started — submitter is unavailable until
          // the very first heartbeat. Surface a clear error so the client
          // knows to retry rather than hang.
          throw new Error("MeshJobSubmitter not yet available — retry shortly.");
        }

        const proxy = await jobSubmitter.submit({
          user_id: "alice",
          sections: ["intro", "body"],
        });
        return proxy; // long-running mode trigger
      },
    );

    app.listen(9091);
    ```

Returning the `JobProxy` switches the framework into long-running mode:

- The inbound `tasks/send` returns `state=working` immediately.
- The task is parked in `_A2A_TASK_STORE` keyed by a freshly-issued task id.
- Subsequent `tasks/get` polls the parked proxy via `MeshJob.status()`.
- `tasks/cancel` calls `MeshJob.cancel()`, propagating through to the underlying mesh job.

## SSE handler (`tasks/sendSubscribe`)

The same `JobProxy`-returning handler also services `tasks/sendSubscribe`. The framework opens an SSE stream and emits `TaskStatusUpdateEvent` + `TaskArtifactUpdateEvent` envelopes per A2A v1.0, sourced from the parked `JobProxy`'s status updates and final artifact.

The producer-side handler does NOT need to be SSE-aware — write it once for `tasks/send`, and the same code path handles `tasks/sendSubscribe` and `tasks/resubscribe`. The framework decides which envelope shape to emit based on the inbound method.

## Mixed-mode rejection

A single Python process may NOT host both `@mesh.tool`-style capabilities and a `mesh.a2a.mount(...)` surface. The framework raises a clear error at agent boot if both are present in the same process — they have different registration paths (`@mesh.tool` goes through the standard heartbeat; `mesh.a2a.mount` registers the agent as `agent_type=a2a`), and the agent card cannot represent both shapes coherently. The Java and TypeScript runtimes allow `@MeshTool` / `addTool(...)` and the A2A producer surface to coexist in the same process (the registration paths share a single heartbeat envelope), but the agent advertises `agent_type=a2a` as soon as one A2A surface is present.

If you need both runtimes' parallel semantics, split into two agents (one `@mesh.tool` / `@MeshTool` / `addTool(...)` provider for the underlying capability, one A2A-surface agent that depends on it via the producer-entry's dependencies). The `report_a2a_agent` example above is exactly this pattern — it depends on `generate_report` (provided by a separate `task=True` agent) and exposes it via A2A.

## Authentication

The producer side enforces bearer auth at the JSON-RPC route. Card auth schemes are auto-published in `/.well-known/agent.json` so consumers can scaffold against them. Phase 1 ships bearer only — OAuth / mTLS are future work. See [Authentication](authentication.md).

=== "Python"

    ```python
    @mesh.a2a.mount(
        app,
        path="/agents/date",
        skill_id="get-date",
        auth="bearer",
    )
    async def date_a2a(payload: dict): ...
    ```

=== "Java"

    ```java
    @MeshA2A(
        path = "/agents/date",
        skillId = "get-date",
        auth = "bearer"
    )
    public Map<String, Object> getDate(Map<String, Object> message) { ... }
    ```

=== "TypeScript"

    ```typescript
    mesh.a2a.mount(
      app,
      {
        path: "/agents/date",
        skillId: "get-date",
        auth: "bearer",
      },
      async (_deps, _payload) => { /* ... */ },
    );
    ```

## Working examples

- `examples/a2a/date_a2a_agent.py` — Python sync handler bridging the `date_service` capability
- `examples/a2a/report_a2a_agent.py` — Python long-running + SSE handler bridging `generate_report` (`task=True`)
- `examples/java/producer-date-agent/` — Java sync handler bridging the `date_service` capability via `@MeshA2A`
- `examples/java/producer-report-agent/` — Java long-running + SSE handler bridging `generate_report` (`task=true`) via `@MeshA2A`
- `examples/typescript/producer-date-agent/` — TypeScript sync handler bridging the `date_service` capability via `mesh.a2a.mount(...)`
- `examples/typescript/producer-report-agent/` — TypeScript long-running + SSE handler bridging `generate_report` (`task=true`) via `mesh.a2a.mount(...)`

## See also

- [Long-Running & SSE](long-running.md) — the consumer-side bridge for `task=True` and SSE
- [Authentication](authentication.md) — bearer setup on both producer and consumer
- [Architecture & Decisions](architecture.md) — `JobProxy` parking rationale
