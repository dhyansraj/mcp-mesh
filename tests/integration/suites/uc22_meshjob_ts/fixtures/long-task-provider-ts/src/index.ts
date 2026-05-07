/**
 * MeshJob test-suite producer (uc22_meshjob_ts) — TypeScript port of
 * uc21_meshjob/fixtures/long-task-provider/main.py.
 *
 * Hosts a small zoo of `task: true` capabilities, one per scenario the
 * suite needs to exercise. Each capability is intentionally minimal —
 * we avoid stuffing branching logic into a single tool because branching
 * across scenarios via payload args makes failures harder to triage when
 * the substrate misbehaves.
 *
 * Capabilities (mirror the Python fixture name-for-name):
 *
 *   - generate_report                   — happy path, progress + complete
 *   - report_with_explicit_complete     — explicit complete({...}) marker
 *   - report_with_implicit_complete     — return value WITHOUT complete()
 *   - report_with_explicit_fail         — calls fail("reason")
 *   - report_that_crashes               — raises mid-attempt
 *   - runs_overlong                     — long sleep loop for cancel tests
 *   - report_with_downstream_call       — calls slow_downstream regular tool
 */
import { FastMCP, mesh, type MeshJob, type McpMeshTool } from "@mcpmesh/sdk";
import { z } from "zod";

const HTTP_PORT = parseInt(process.env.MCP_MESH_HTTP_PORT ?? "9110", 10);

const server = new FastMCP({
  name: "Long Task Provider (uc22 TS)",
  version: "1.0.0",
});

const agent = mesh(server, {
  name: "long-task-provider-ts",
  httpPort: HTTP_PORT,
  description:
    "MeshJob test producer (uc22 TS) — multi-capability fixture for the integration suite.",
});

// ---------------------------------------------------------------------------
// Happy path
// ---------------------------------------------------------------------------
agent.addTool({
  name: "generate_report",
  capability: "generate_report",
  task: true,
  meshJobParamIndex: 1,
  description: "Long-running multi-section report generator with progress.",
  parameters: z.object({
    user_id: z.string(),
    sections: z.array(z.string()),
  }),
  execute: async ({ user_id, sections }, job: MeshJob | null = null) => {
    if (job?.updateProgress) {
      await job.updateProgress(0.0, "starting");
    }
    const results: { section: string; content: string }[] = [];
    const total = Math.max(sections.length, 1);
    for (let i = 0; i < sections.length; i++) {
      await new Promise((r) => setTimeout(r, 2000));
      results.push({
        section: sections[i],
        content: `Generated content for ${sections[i]}`,
      });
      if (job?.updateProgress) {
        await job.updateProgress(
          (i + 1) / total,
          `finished section ${i + 1}/${total}`,
        );
      }
    }
    const payload = { user_id, report: results };
    if (job?.complete) {
      await job.complete(payload);
    }
    return payload;
  },
});

// ---------------------------------------------------------------------------
// Explicit complete with fixed marker payload (tc03)
// ---------------------------------------------------------------------------
agent.addTool({
  name: "report_with_explicit_complete",
  capability: "report_with_explicit_complete",
  task: true,
  meshJobParamIndex: 1,
  description: "Calls job.complete({...}) with a fixed marker payload.",
  parameters: z.object({ user_id: z.string() }),
  execute: async ({ user_id }, job: MeshJob | null = null) => {
    if (job?.updateProgress) {
      await job.updateProgress(0.5, "midpoint");
      await new Promise((r) => setTimeout(r, 500));
    }
    const payload = { explicit: true, marker: "X", user_id };
    if (job?.complete) {
      await job.complete(payload);
    }
    return payload;
  },
});

// ---------------------------------------------------------------------------
// Implicit complete (auto-complete on return) (tc04)
// ---------------------------------------------------------------------------
agent.addTool({
  name: "report_with_implicit_complete",
  capability: "report_with_implicit_complete",
  task: true,
  meshJobParamIndex: 1,
  description:
    "Returns a value WITHOUT calling job.complete() — relies on auto-complete.",
  parameters: z.object({ user_id: z.string() }),
  execute: async ({ user_id }, job: MeshJob | null = null) => {
    // Update progress to confirm controller binding worked. We
    // intentionally do NOT call job.complete() — the runtime's
    // auto-complete-on-return path should fire.
    if (job?.updateProgress) {
      await job.updateProgress(0.5, "halfway");
      await new Promise((r) => setTimeout(r, 500));
      await job.updateProgress(0.9, "almost done");
    }
    return { implicit: true, user_id };
  },
});

// ---------------------------------------------------------------------------
// Explicit fail — no retry (tc05)
// ---------------------------------------------------------------------------
agent.addTool({
  name: "report_with_explicit_fail",
  capability: "report_with_explicit_fail",
  task: true,
  meshJobParamIndex: 1,
  description:
    "Calls job.fail('reason') — must NOT trigger retry even with max_retries > 0.",
  parameters: z.object({ user_id: z.string() }),
  execute: async ({ user_id: _user_id }, job: MeshJob | null = null) => {
    if (job?.updateProgress) {
      await job.updateProgress(0.1, "about to fail");
      await new Promise((r) => setTimeout(r, 300));
    }
    if (job?.fail) {
      await job.fail("explicit: not retryable");
    }
    return { failed: true, reason: "explicit: not retryable" };
  },
});

// ---------------------------------------------------------------------------
// Crash on attempt (tc12)
// ---------------------------------------------------------------------------
agent.addTool({
  name: "report_that_crashes",
  capability: "report_that_crashes",
  task: true,
  meshJobParamIndex: 1,
  description:
    "Always raises mid-attempt — drives crash-recovery / retry-exhaustion tests.",
  parameters: z.object({ user_id: z.string() }),
  execute: async ({ user_id: _user_id }, job: MeshJob | null = null) => {
    if (job?.updateProgress) {
      await job.updateProgress(0.1, "about to crash");
      await new Promise((r) => setTimeout(r, 300));
    }
    throw new Error("simulated crash for crash-recovery test");
  },
});

// ---------------------------------------------------------------------------
// Long-running task (tc06, tc09, tc10–tc13 use this via SIGKILL) (runs_overlong)
// ---------------------------------------------------------------------------
agent.addTool({
  name: "runs_overlong",
  capability: "runs_overlong",
  task: true,
  meshJobParamIndex: 1,
  description:
    "Sleeps for many small intervals so cancel / kill can land mid-flight.",
  parameters: z.object({
    user_id: z.string(),
    seconds: z.number().int().default(30),
  }),
  execute: async ({ user_id, seconds }, job: MeshJob | null = null) => {
    let elapsed = 0;
    const step = 0.5;
    const total = Math.max(seconds, step);
    while (elapsed < total) {
      await new Promise((r) => setTimeout(r, step * 1000));
      elapsed += step;
      if (job?.updateProgress) {
        await job.updateProgress(
          Math.min(elapsed / total, 0.99),
          `alive at ${elapsed.toFixed(1)}s`,
        );
      }
    }
    const payload = { user_id, elapsed };
    if (job?.complete) {
      await job.complete(payload);
    }
    return payload;
  },
});

// ---------------------------------------------------------------------------
// Job that calls a downstream regular tool (tc09)
// ---------------------------------------------------------------------------
agent.addTool({
  name: "report_with_downstream_call",
  capability: "report_with_downstream_call",
  task: true,
  // dep[0] is slow_downstream (regular McpMeshTool); job lands at sig pos 2.
  meshJobParamIndex: 2,
  dependencies: [{ capability: "slow_downstream" }],
  description:
    "Calls a downstream regular tool that sleeps; cancel must abort the in-flight HTTP.",
  parameters: z.object({ user_id: z.string() }),
  execute: async (
    { user_id },
    slow_downstream: McpMeshTool | null = null,
    job: MeshJob | null = null,
  ) => {
    if (job?.updateProgress) {
      await job.updateProgress(0.1, "calling downstream");
    }
    if (!slow_downstream) {
      // Mirror the Python fixture's deliberate fail() instead of returning
      // the error dict — auto-complete would otherwise mark the row
      // COMPLETED with the error dict as result.
      if (job?.fail) {
        await job.fail("slow_downstream dependency not injected");
      }
      return null;
    }
    // Downstream sleeps 30s. With cancel propagation working, the cancel
    // token aborts the in-flight HTTP well before the 30s timer elapses.
    const result = await slow_downstream({ user_id, seconds: 30 });
    if (job?.complete) {
      await job.complete(result);
    }
    return result;
  },
});

console.log(
  `long-task-provider-ts uc22 fixture defined on port ${HTTP_PORT}. Waiting for auto-start...`,
);
