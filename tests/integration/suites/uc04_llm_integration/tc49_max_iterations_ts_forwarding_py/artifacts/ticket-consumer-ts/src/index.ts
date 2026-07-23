#!/usr/bin/env npx tsx
/**
 * ticket-consumer-ts - TypeScript @mesh.llm consumer that forwards NOTHING
 * (issue #1360) and catches the typed exhaustion error (issue #1355).
 *
 * WHAT #1360 FIXED (the fix site is THIS consumer)
 * ------------------------------------------------
 * Before #1360 the TS consumer unconditionally forwarded `max_iterations: 10`
 * on the wire even when the user configured nothing, which SHADOWED any
 * provider-side MESH_LLM_MAX_ITERATIONS and made the provider's env inert.
 * After #1360 an UNSET `maxIterations` forwards no `max_iterations` at all, so
 * the provider's own MESH_LLM_MAX_ITERATIONS governs the loop.
 *
 * This consumer therefore declares NO `maxIterations`. In the tc the Python
 * provider is started with MESH_LLM_MAX_ITERATIONS=1 (on a private --env, not
 * the shared .env, so it can never leak to this consumer). If the fix holds,
 * the provider's env caps the loop at ONE tool round (PROBE_INVOCATIONS=[1]);
 * the pre-#1360 regression would forward 10, shadow the provider env, and let
 * the 4-step ticket run to completion (PROBE_INVOCATIONS=[4]).
 *
 * WHAT #1355 ADDED (observed here)
 * --------------------------------
 * On exhaustion the provider signals `_mesh_stop_reason == "max_iterations"`
 * (structural, never in `content`) and the TS MeshLlmAgent throws
 * `MaxIterationsError`. We catch it and return a sentinel naming the class so
 * the tc asserts on the TYPE, not the removed "Maximum tool call iterations
 * reached" string.
 */

import { FastMCP, mesh, MaxIterationsError } from "@mcpmesh/sdk";
import { z } from "zod";

const server = new FastMCP({
  name: "Ticket Consumer TS",
  version: "1.0.0",
});

const runTicketTs = mesh.llm({
  name: "run_ticket_ts",
  capability: "run_ticket_ts",
  description: "Drive the probe ticket using the advance_ticket tool (TS consumer)",
  tags: ["llm", "ticket", "iteration", "typescript"],
  version: "1.0.0",

  // Mesh delegation to the Python Claude provider.
  provider: { capability: "llm", tags: ["+claude", "+provider"] },

  // Only advance_ticket (capability "iteration_probe") is exposed to the model.
  // probe_count / probe_reset sit on different capabilities so the model can
  // neither read nor reset the counter it is being measured with.
  filter: [{ capability: "iteration_probe" }],
  filterMode: "all",

  // THE THING UNDER TEST (#1360): NO maxIterations. An unset cap must forward
  // NOTHING so the provider's MESH_LLM_MAX_ITERATIONS governs the loop.
  // (Do NOT add maxIterations here — that would defeat the regression guard.)

  // Plain string result; the tool catches exhaustion before any parse.
  returns: z.string(),

  parameters: z.object({
    ctx: z.object({
      instruction: z.string().describe("Multi-step ticket instruction"),
    }),
  }),
  contextParam: "ctx",

  systemPrompt:
    "You are a ticket-processing agent. You MUST use the advance_ticket tool " +
    "to make progress on a ticket; never guess, fabricate or predict a token, " +
    "a step number or a final_code. Call advance_ticket AT MOST ONCE per turn " +
    "and wait for its result before calling it again - the token for the next " +
    "call only exists in the previous call's response. Keep going until the " +
    "tool reports status COMPLETE, then reply with the final_code it returned.",

  execute: async ({ ctx }, { llm }) => {
    try {
      return await llm(ctx.instruction);
    } catch (e) {
      if (e instanceof MaxIterationsError) {
        // Typed exhaustion (#1355) — name the class so the tc asserts on TYPE.
        return `EXHAUSTED_TYPED type=${e.name}`;
      }
      throw e;
    }
  },
});

server.addTool(runTicketTs);

const agent = mesh(server, {
  name: "ticket-consumer-ts",
  version: "1.0.0",
  description:
    "TS consumer with UNSET maxIterations — defers to provider env (issue #1360)",
  httpPort: 9049,
});

console.log(
  "ticket-consumer-ts initialized. Waiting for mesh connections..."
);
