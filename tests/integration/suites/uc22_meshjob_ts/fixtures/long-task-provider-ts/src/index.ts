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
 *   - report_with_transient_failures    — throws TransientError on first N
 *                                         attempts, succeeds on N+1 (retryOn)
 *   - runs_overlong                     — long sleep loop for cancel tests
 *   - report_with_downstream_call       — calls slow_downstream regular tool
 */
import { FastMCP, mesh, type MeshJob, type McpMeshTool } from "@mcpmesh/sdk";
import { z } from "zod";
import { readFileSync, writeFileSync, existsSync } from "node:fs";

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
// Transient-failure path — exercises retryOn (#894) (tc23 mirror)
// ---------------------------------------------------------------------------
//
// Mirrors Python's report_with_transient_failures
// (uc21_meshjob/fixtures/long-task-provider/main.py) and Java's
// reportWithTransientFailures (uc23_meshjob_java/...). The handler is
// declared with retryOn: [TransientError]: when the body throws
// TransientError the dispatch wrapper calls JobController.releaseLease
// (NOT fail), so the registry resets owner_instance_id and the next
// claim cycle re-runs the handler — proving the fast-retry path
// engaged rather than waiting for lease expiry.
//
// File-based counter shared with the Python fixture so the same
// integration assertions (attempt_count=3) work cross-runtime.
// ---------------------------------------------------------------------------
class TransientError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "TransientError";
  }
}

const RETRY_COUNTER_PATH = "/tmp/mesh-retry-on-counter";

function bumpRetryCounter(): number {
  let n = 0;
  if (existsSync(RETRY_COUNTER_PATH)) {
    const body = readFileSync(RETRY_COUNTER_PATH, "utf8").trim();
    n = body === "" ? 0 : parseInt(body, 10);
    if (Number.isNaN(n)) n = 0;
  }
  n += 1;
  writeFileSync(RETRY_COUNTER_PATH, String(n), "utf8");
  return n;
}

agent.addTool({
  name: "report_with_transient_failures",
  capability: "report_with_transient_failures",
  task: true,
  meshJobParamIndex: 1,
  retryOn: [TransientError],
  description:
    "Throws TransientError on the first N attempts, succeeds on N+1 — exercises retryOn (#894).",
  parameters: z.object({
    user_id: z.string(),
    transient_failures: z.number().int().default(2),
  }),
  execute: async (
    { user_id, transient_failures },
    job: MeshJob | null = null,
  ) => {
    if (job?.updateProgress) {
      await job.updateProgress(0.1, "checking transient counter");
    }
    const n = bumpRetryCounter();
    if (n <= transient_failures) {
      throw new TransientError(`simulated transient failure ${n}/${transient_failures}`);
    }
    const payload = { user_id, succeeded_on_attempt: n };
    if (job?.complete) {
      await job.complete(payload);
    }
    return payload;
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

// ---------------------------------------------------------------------------
// Event-injection scenarios (tc24/tc25/tc26 — recvEvent / sendEvent primitive)
// ---------------------------------------------------------------------------
//
// TS port of uc21_meshjob/fixtures/long-task-provider/main.py
// (run_with_event / run_with_filter / run_until_cancel). All three use
// `task: true` and call `job.recvEvent(...)` in the handler body. Each
// one targets a different facet of the event channel:
//
//   - run_with_event   — happy path: wait for ONE event of a single type.
//   - run_with_filter  — type-filter correctness: ignore unrelated events.
//   - run_until_cancel — synthetic cancel event: loop on recvEvent and
//                        exit gracefully when the registry posts the
//                        `{ type: "cancelled" }` synthetic event that
//                        fires inside CancelJob.
// ---------------------------------------------------------------------------

agent.addTool({
  name: "run_with_event",
  capability: "run_with_event",
  task: true,
  meshJobParamIndex: 1,
  description:
    "Wait for one 'signal' event and return its payload — happy path for recvEvent.",
  parameters: z.object({}).passthrough(),
  execute: async (_args, job: MeshJob | null = null) => {
    if (!job?.recvEvent) {
      return { status: "no_job_ctx" };
    }
    if (job.updateProgress) {
      await job.updateProgress(0.1, "parked on recvEvent");
    }
    const event = await job.recvEvent(["signal"], 10);
    if (event === null) {
      return { status: "timeout", received: false };
    }
    const payload = {
      status: "got_event",
      received: true,
      type: event.type,
      payload: event.payload,
      seq: event.seq,
    };
    if (job.complete) {
      await job.complete(payload);
    }
    return payload;
  },
});

agent.addTool({
  name: "run_with_filter",
  capability: "run_with_filter",
  task: true,
  meshJobParamIndex: 1,
  description:
    "Wait for a 'target' event and ignore other types — exercises recvEvent filter.",
  parameters: z.object({}).passthrough(),
  execute: async (_args, job: MeshJob | null = null) => {
    if (!job?.recvEvent) {
      return { status: "no_job_ctx" };
    }
    if (job.updateProgress) {
      await job.updateProgress(0.1, "parked with type filter");
    }
    // Long timeout so the consumer has slack to post 2 ignored events
    // before the matching one. If the filter is broken the producer
    // will wake on the FIRST event (ignore_a) and the assertions will
    // catch it.
    const event = await job.recvEvent(["target"], 15);
    if (event === null) {
      return { timeout: true };
    }
    const payload = {
      type: event.type,
      payload: event.payload,
      seq: event.seq,
    };
    if (job.complete) {
      await job.complete(payload);
    }
    return payload;
  },
});

agent.addTool({
  name: "run_until_done",
  capability: "run_until_done",
  task: true,
  meshJobParamIndex: 1,
  description:
    "Loop on recvEvent for 'work' events, exit on payload {final: true} — paired with subscribeEvents observer.",
  parameters: z.object({}).passthrough(),
  execute: async (_args, job: MeshJob | null = null) => {
    if (!job?.recvEvent) {
      return { status: "no_job_ctx" };
    }
    const eventsProcessed: Array<{ seq: number; payload: unknown }> = [];
    // Bounded loop — safety net so a missing termination event doesn't
    // hang the job indefinitely. Per-call long timeout matches the
    // consumer's posting cadence (consumer fires ~3 events within a
    // few seconds, so 10s/iteration is plenty).
    for (let i = 0; i < 20; i++) {
      const event = await job.recvEvent(["work"], 10);
      if (event === null) {
        return { status: "timeout", processed: eventsProcessed };
      }
      eventsProcessed.push({ seq: event.seq, payload: event.payload });
      const payload = event.payload as Record<string, unknown> | null;
      if (payload && typeof payload === "object" && payload.final === true) {
        const result = {
          status: "done",
          processed_count: eventsProcessed.length,
          events: eventsProcessed,
        };
        if (job.complete) {
          await job.complete(result);
        }
        return result;
      }
    }
    return { status: "loop_exhausted", processed: eventsProcessed };
  },
});

agent.addTool({
  name: "run_until_cancel",
  capability: "run_until_cancel",
  task: true,
  meshJobParamIndex: 1,
  description:
    "Loop on recvEvent for 'work'/'cancelled' types until cancelled-event arrives.",
  parameters: z.object({}).passthrough(),
  execute: async (_args, job: MeshJob | null = null) => {
    if (!job?.recvEvent) {
      return { status: "no_job_ctx" };
    }
    const eventsSeen: Array<{ type: string; payload: unknown }> = [];
    // Bounded loop count — safety net against runaway iterations if the
    // cancel event never lands. A correct flow exits via the
    // "cancelled" branch within ~3s of the consumer firing cancel.
    for (let i = 0; i < 20; i++) {
      const event = await job.recvEvent(["work", "cancelled"], 15);
      if (event === null) {
        return { status: "timeout", events_seen: eventsSeen };
      }
      eventsSeen.push({ type: event.type, payload: event.payload });
      if (event.type === "cancelled") {
        // Don't call job.complete()/fail() — the registry row is
        // already cancelled (the synthetic event was posted by
        // CancelJob AFTER the row transition). Auto-complete is a
        // no-op once terminal has been recorded, so returning here
        // is safe.
        //
        // Marker line for the test driver to grep on; mirrors the
        // Python fixture's `[run_until_cancel] cancelled_gracefully`
        // line.
        console.log(
          `[run_until_cancel] cancelled_gracefully events_seen=${JSON.stringify(eventsSeen)}`,
        );
        return { status: "cancelled_gracefully", events_seen: eventsSeen };
      }
    }
    return { status: "loop_exhausted", events_seen: eventsSeen };
  },
});

console.log(
  `long-task-provider-ts uc22 fixture defined on port ${HTTP_PORT}. Waiting for auto-start...`,
);
