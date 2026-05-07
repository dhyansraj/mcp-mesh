/**
 * Downstream sleeper agent (uc22 TS) — exercises cancel propagation.
 *
 * TS port of uc21_meshjob/fixtures/downstream-sleeper/main.py.
 *
 * Provides `slow_downstream`, a regular (non-task) tool that sleeps for
 * the requested number of seconds. The producer agent's
 * `report_with_downstream_call` invokes this via the mesh proxy; when
 * the producer's job is cancelled, the cancel token in the producer's
 * async-local context aborts the in-flight outbound HTTP — so this
 * sleeper never finishes its 30s timer for the cancel scenario.
 *
 * The sleeper logs a marker line to stderr if the request is aborted at
 * the inbound side (FastMCP-TS would have to surface client-disconnect
 * cancellation as a rejected promise for this to fire). At the time of
 * writing, the FastMCP-TS substrate does NOT propagate inbound HTTP
 * disconnects to the tool handler — the sleep runs to its natural end
 * regardless of whether the producer side cancelled. Same gap as the
 * Python equivalent (uc21/tc09 documents this in detail).
 *
 * Producer-side correctness (cancel landed, downstream HTTP aborted) is
 * still observable from outside via:
 *   - status == cancelled
 *   - progress message frozen at "calling downstream"
 *   - status != completed
 */
import { FastMCP, mesh } from "@mcpmesh/sdk";
import { z } from "zod";

const HTTP_PORT = parseInt(process.env.MCP_MESH_HTTP_PORT ?? "9112", 10);

const server = new FastMCP({
  name: "Downstream Sleeper (uc22 TS)",
  version: "1.0.0",
});

const agent = mesh(server, {
  name: "downstream-sleeper-ts",
  httpPort: HTTP_PORT,
  description:
    "Slow downstream tool used to verify mesh-job cancel propagation (TS).",
});

agent.addTool({
  name: "slow_downstream",
  capability: "slow_downstream",
  description:
    "Sleeps for the requested number of seconds (regular tool, not task=true).",
  parameters: z.object({
    user_id: z.string(),
    // 0 allowed for fast-finish edge cases; negative would yield an
    // immediate setTimeout completion and defeat the cancel scenario.
    seconds: z.number().int().min(0).default(30),
  }),
  execute: async ({ user_id, seconds }) => {
    process.stderr.write(
      `[downstream-sleeper-ts] starting ${seconds}s sleep for user=${user_id}\n`,
    );
    try {
      await new Promise<void>((resolve, reject) => {
        const t = setTimeout(resolve, seconds * 1000);
        // If the inbound transport surfaced a cancel as an event we'd
        // wire it here. FastMCP-TS does not yet expose such a hook —
        // documented gap, parallel to FastMCP-Python's #882.
        // No-op for now; the timer just runs to completion.
        void t;
      });
    } catch (err) {
      // UNREACHABLE — the Promise above never rejects (the only signal
      // is setTimeout's resolve). This catch + marker line is a
      // ready-for-#886 placeholder: once the TS proxy wires AbortSignal
      // to the per-job cancel registry AND FastMCP-TS surfaces inbound
      // client-disconnect to the tool handler, the inner Promise will
      // gain a `reject` path and this marker will start firing for
      // cancelled jobs. Do NOT debug "why doesn't the marker fire" —
      // it cannot until #886 lands. See header comment for context.
      process.stderr.write(
        `[downstream-sleeper-ts] sleep CANCELLED for user=${user_id} ` +
          `(client closed / cancel token fired) — err=${err}\n`,
      );
      throw err;
    }
    process.stderr.write(
      `[downstream-sleeper-ts] sleep completed for user=${user_id} (NOT cancelled)\n`,
    );
    return { user_id, slept: seconds };
  },
});

console.log(
  `downstream-sleeper-ts uc22 fixture defined on port ${HTTP_PORT}. Waiting for auto-start...`,
);
