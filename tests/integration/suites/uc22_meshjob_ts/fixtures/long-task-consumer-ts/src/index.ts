/**
 * MeshJob test-suite consumer (uc22_meshjob_ts) — TypeScript port of
 * uc21_meshjob/fixtures/long-task-consumer/main.py.
 *
 * Hosts several variants of the submit-and-await pattern so individual
 * test cases can exercise behavioural knobs without forking new agents.
 * Capability names match the Python fixture exactly so test assertions
 * (and the polyglot tc17–tc20 fixtures) can call them interchangeably.
 *
 *   - commission_report           — submit + wait; returns terminal payload
 *   - commission_with_options     — submit + wait with caller-supplied
 *                                   max_retries + total_deadline_secs;
 *                                   structured envelope on terminal failure
 *   - commission_submit_only      — submit and return {job_id} immediately
 *   - commission_explicit_fail    — submits report_with_explicit_fail
 *   - commission_crash            — submits report_that_crashes
 *   - commission_overlong         — submits runs_overlong
 *   - commission_downstream       — submits report_with_downstream_call
 *   - commission_transient_failures — submits report_with_transient_failures
 *                                     (#894 retryOn integration test driver)
 */
import { FastMCP, mesh, type MeshJob } from "@mcpmesh/sdk";
import { z } from "zod";

const HTTP_PORT = parseInt(process.env.MCP_MESH_HTTP_PORT ?? "9111", 10);

const server = new FastMCP({
  name: "Long Task Consumer (uc22 TS)",
  version: "1.0.0",
});

const agent = mesh(server, {
  name: "long-task-consumer-ts",
  httpPort: HTTP_PORT,
  description:
    "MeshJob test consumer (uc22 TS) — multi-capability fixture for the integration suite.",
});

function utcDeadlineFromRelative(secs?: number | null): number | undefined {
  if (secs === undefined || secs === null) return undefined;
  // Mesh-job submit accepts a unix-epoch (seconds) or Date — pass seconds.
  return Math.floor(Date.now() / 1000) + secs;
}

// ---------------------------------------------------------------------------
// Submit + wait — happy path baseline (tc01)
// ---------------------------------------------------------------------------
agent.addTool({
  name: "commission_report",
  capability: "commission_report",
  dependencies: [{ capability: "generate_report" }],
  meshJobDepIndex: 0,
  description: "Submit a generate_report job and wait up to 60s for the result.",
  parameters: z.object({
    user_id: z.string(),
    sections: z.array(z.string()),
  }),
  execute: async (
    { user_id, sections },
    generateReport: MeshJob | null = null,
  ) => {
    if (!generateReport?.submit) {
      return { error: "generate_report submitter not injected" };
    }
    const proxy = await generateReport.submit(
      { user_id, sections },
      { maxDuration: 60 },
    );
    if (!proxy.wait) {
      return { error: "submitter returned a proxy without .wait()" };
    }
    return await proxy.wait(60);
  },
});

// ---------------------------------------------------------------------------
// Submit + wait with caller-controlled retry / deadline knobs (tc13)
// ---------------------------------------------------------------------------
agent.addTool({
  name: "commission_with_options",
  capability: "commission_with_options",
  dependencies: [{ capability: "generate_report" }],
  meshJobDepIndex: 0,
  description:
    "Submit generate_report with caller-supplied max_retries / total_deadline_secs.",
  parameters: z.object({
    user_id: z.string(),
    sections: z.array(z.string()),
    max_retries: z.number().int().default(1),
    total_deadline_secs: z.number().int().nullable().optional(),
    wait_timeout_secs: z.number().int().default(60),
  }),
  execute: async (
    { user_id, sections, max_retries, total_deadline_secs, wait_timeout_secs },
    generateReport: MeshJob | null = null,
  ) => {
    if (!generateReport?.submit) {
      return { error: "generate_report submitter not injected" };
    }
    const proxy = await generateReport.submit(
      { user_id, sections },
      {
        maxDuration: 60,
        maxRetries: max_retries,
        totalDeadline: utcDeadlineFromRelative(total_deadline_secs),
      },
    );
    const job_id = (proxy as { jobId?: string }).jobId ?? null;
    if (!proxy.wait) {
      return { job_id, status: "submitted", result: null };
    }
    try {
      const result = await proxy.wait(wait_timeout_secs);
      return { job_id, status: "completed", result };
    } catch (e) {
      return {
        job_id,
        status: "wait_raised",
        error: e instanceof Error ? e.message : String(e),
      };
    }
  },
});

// ---------------------------------------------------------------------------
// Submit-only — return job_id immediately (tc02, tc06, tc10–tc12, tc14, tc16)
// ---------------------------------------------------------------------------
agent.addTool({
  name: "commission_submit_only",
  capability: "commission_submit_only",
  dependencies: [{ capability: "generate_report" }],
  meshJobDepIndex: 0,
  description: "Submit generate_report and return the job_id without waiting.",
  parameters: z.object({
    user_id: z.string(),
    sections: z.array(z.string()),
    max_retries: z.number().int().default(1),
    max_duration: z.number().int().default(60),
  }),
  execute: async (
    { user_id, sections, max_retries, max_duration },
    generateReport: MeshJob | null = null,
  ) => {
    if (!generateReport?.submit) {
      return { error: "generate_report submitter not injected" };
    }
    const proxy = await generateReport.submit(
      { user_id, sections },
      { maxDuration: max_duration, maxRetries: max_retries },
    );
    return { job_id: (proxy as { jobId?: string }).jobId ?? null };
  },
});

// ---------------------------------------------------------------------------
// Explicit-fail submitter (tc05)
// ---------------------------------------------------------------------------
agent.addTool({
  name: "commission_explicit_fail",
  capability: "commission_explicit_fail",
  dependencies: [{ capability: "report_with_explicit_fail" }],
  meshJobDepIndex: 0,
  description:
    "Submit report_with_explicit_fail with caller-supplied max_retries.",
  parameters: z.object({
    user_id: z.string(),
    max_retries: z.number().int().default(3),
    wait_timeout_secs: z.number().int().default(30),
  }),
  execute: async (
    { user_id, max_retries, wait_timeout_secs },
    reportWithExplicitFail: MeshJob | null = null,
  ) => {
    if (!reportWithExplicitFail?.submit) {
      return { error: "report_with_explicit_fail submitter not injected" };
    }
    const proxy = await reportWithExplicitFail.submit(
      { user_id },
      { maxDuration: 30, maxRetries: max_retries },
    );
    const job_id = (proxy as { jobId?: string }).jobId ?? null;
    if (!proxy.wait) {
      return { job_id, status: "submitted", result: null };
    }
    try {
      const result = await proxy.wait(wait_timeout_secs);
      return { job_id, status: "completed", result };
    } catch (e) {
      return {
        job_id,
        status: "wait_raised",
        error: e instanceof Error ? e.message : String(e),
      };
    }
  },
});

// ---------------------------------------------------------------------------
// Crash submitter (tc12)
// ---------------------------------------------------------------------------
agent.addTool({
  name: "commission_crash",
  capability: "commission_crash",
  dependencies: [{ capability: "report_that_crashes" }],
  meshJobDepIndex: 0,
  description:
    "Submit report_that_crashes (always raises) with caller-supplied retry/deadline.",
  parameters: z.object({
    user_id: z.string(),
    max_retries: z.number().int().default(0),
    total_deadline_secs: z.number().int().nullable().optional(),
  }),
  execute: async (
    { user_id, max_retries, total_deadline_secs },
    reportThatCrashes: MeshJob | null = null,
  ) => {
    if (!reportThatCrashes?.submit) {
      return { error: "report_that_crashes submitter not injected" };
    }
    const proxy = await reportThatCrashes.submit(
      { user_id },
      {
        maxDuration: 30,
        maxRetries: max_retries,
        totalDeadline: utcDeadlineFromRelative(total_deadline_secs),
      },
    );
    return { job_id: (proxy as { jobId?: string }).jobId ?? null };
  },
});

// ---------------------------------------------------------------------------
// Overlong submitter (tc06, tc20)
// ---------------------------------------------------------------------------
agent.addTool({
  name: "commission_overlong",
  capability: "commission_overlong",
  dependencies: [{ capability: "runs_overlong" }],
  meshJobDepIndex: 0,
  description: "Submit runs_overlong and return the job_id (no wait).",
  parameters: z.object({
    user_id: z.string(),
    seconds: z.number().int().default(30),
  }),
  execute: async (
    { user_id, seconds },
    runsOverlong: MeshJob | null = null,
  ) => {
    if (!runsOverlong?.submit) {
      return { error: "runs_overlong submitter not injected" };
    }
    const proxy = await runsOverlong.submit(
      { user_id, seconds },
      { maxDuration: 120 },
    );
    return { job_id: (proxy as { jobId?: string }).jobId ?? null };
  },
});

// ---------------------------------------------------------------------------
// Downstream-call submitter (tc09)
// ---------------------------------------------------------------------------
agent.addTool({
  name: "commission_downstream",
  capability: "commission_downstream",
  dependencies: [{ capability: "report_with_downstream_call" }],
  meshJobDepIndex: 0,
  description:
    "Submit report_with_downstream_call (provider calls slow_downstream) and return job_id.",
  parameters: z.object({ user_id: z.string() }),
  execute: async (
    { user_id },
    reportWithDownstreamCall: MeshJob | null = null,
  ) => {
    if (!reportWithDownstreamCall?.submit) {
      return { error: "report_with_downstream_call submitter not injected" };
    }
    const proxy = await reportWithDownstreamCall.submit(
      { user_id },
      { maxDuration: 120 },
    );
    return { job_id: (proxy as { jobId?: string }).jobId ?? null };
  },
});

// ---------------------------------------------------------------------------
// Transient-failures submitter — submits report_with_transient_failures (#894 tc23)
// ---------------------------------------------------------------------------
agent.addTool({
  name: "commission_transient_failures",
  capability: "commission_transient_failures",
  dependencies: [{ capability: "report_with_transient_failures" }],
  meshJobDepIndex: 0,
  description:
    "Submit report_with_transient_failures with caller-supplied max_retries.",
  parameters: z.object({
    user_id: z.string(),
    max_retries: z.number().int().default(3),
    transient_failures: z.number().int().default(2),
    wait_timeout_secs: z.number().int().default(30),
  }),
  execute: async (
    { user_id, max_retries, transient_failures, wait_timeout_secs },
    reportWithTransientFailures: MeshJob | null = null,
  ) => {
    if (!reportWithTransientFailures?.submit) {
      return { error: "report_with_transient_failures submitter not injected" };
    }
    const proxy = await reportWithTransientFailures.submit(
      { user_id, transient_failures },
      { maxDuration: 30, maxRetries: max_retries },
    );
    const job_id = (proxy as { jobId?: string }).jobId ?? null;
    if (!proxy.wait) {
      return { job_id, status: "submitted", result: null };
    }
    try {
      const result = await proxy.wait(wait_timeout_secs);
      return { job_id, status: "completed", result };
    } catch (e) {
      return {
        job_id,
        status: "wait_raised",
        error: e instanceof Error ? e.message : String(e),
      };
    }
  },
});

console.log(
  `long-task-consumer-ts uc22 fixture defined on port ${HTTP_PORT}. Waiting for auto-start...`,
);
