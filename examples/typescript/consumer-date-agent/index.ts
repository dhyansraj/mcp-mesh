/**
 * TypeScript A2A consumer example (issue #917) — port of
 * `examples/a2a/consumer_date_agent.py` and
 * `examples/java/consumer-date-agent`.
 *
 * Bridges the existing `examples/a2a/date_a2a_agent.py` `get-date`
 * skill into the mesh as a regular `current-date` capability. A
 * downstream mesh tool depending on `current-date` does not need to
 * know it is talking to an A2A backend — mesh's existing capability +
 * tag failover applies the moment a SECOND consumer (Python or Java)
 * registers the same `current-date` capability with a different
 * consumer-name tag.
 *
 * Each consumer auto-tags its capability with the surrounding agent
 * name (here `date-consumer-ts`) so downstream resolvers can pin a
 * specific backend via the dependency tag selector.
 *
 * Framework injection (matches Python's `@mesh.a2a_consumer` and
 * Java's `@A2AConsumer`): `a2aConfig` carries the upstream config;
 * the framework constructs an `A2AClient` per unique tuple and
 * injects it as the trailing argument of `execute`.
 *
 * Stack
 * =====
 *   1) Registry — `meshctl start --registry-only`
 *   2) System agent (Python) — provides `date_service`
 *   3) Date A2A surface (Python) — exposes `get-date` via A2A on
 *      `http://localhost:9090/agents/date`
 *   4) This TS consumer — bridges the get-date skill onto the mesh as
 *      `current-date` (port 9201)
 *
 * Run
 * ===
 *   cd examples/typescript/consumer-date-agent
 *   npm install
 *   npx tsx index.ts
 */
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
  description:
    "TypeScript A2A consumer bridge — re-publishes the date_a2a_agent get-date skill as a mesh current-date capability.",
});

agent.addTool({
  name: "current_date",
  capability: "current-date",
  tags: ["a2a-bridge"],
  description:
    "Get the current date by bridging the upstream A2A get-date skill.",
  parameters: z.object({}),
  a2aConfig: {
    url: "http://localhost:9090/agents/date",
    skillId: "get-date",
  },
  execute: async (_args, ..._injected) => {
    // The framework injects an `A2AClient` at the trailing slot when
    // `a2aConfig` is set on this tool. Pull + assert here so the rest
    // of the body is statically typed.
    const a2a = _injected[_injected.length - 1] as A2AClient | null;
    if (!a2a) {
      throw new Error("A2AClient was not injected — did you set a2aConfig?");
    }
    const r = await a2a.send({
      role: "user",
      parts: [{ type: "text", text: "now" }],
    });
    // The producer-side handler returns `{"date": "<iso-string>"}` and
    // the A2A surface JSON-stringifies it into the artifact text part —
    // so we JSON.parse on the consumer side to recover the dict.
    return JSON.parse(r.artifactText);
  },
});

console.log(
  `date-consumer-ts agent defined on port ${HTTP_PORT}. Waiting for auto-start...`,
);
