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

// ---------------------------------------------------------------------------
// Event-injection scenarios (tc24 / tc25 / tc26)
// ---------------------------------------------------------------------------
//
// Each capability submits one of the new `task: true` producers and
// drives `mesh.jobs.postEvent` from inside the consumer's tool body to
// exercise the producer's `recvEvent` long-poll. `mesh.jobs.postEvent`
// is the surface under test — it discovers the registry URL from
// `MCP_MESH_REGISTRY_URL` (set by the agent startup pipeline) and POSTs
// `/jobs/{id}/events`.
// ---------------------------------------------------------------------------

function sleepMs(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

agent.addTool({
  name: "commission_event",
  capability: "commission_event",
  dependencies: [{ capability: "run_with_event" }],
  meshJobDepIndex: 0,
  description:
    "Submit run_with_event, sleep so producer parks on recvEvent, then post one event.",
  parameters: z.object({}).passthrough(),
  execute: async (_args, runWithEvent: MeshJob | null = null) => {
    if (!runWithEvent?.submit) {
      return { error: "run_with_event submitter not injected" };
    }
    const proxy = await runWithEvent.submit({}, { maxDuration: 60 });
    const jobId = (proxy as { jobId?: string }).jobId ?? "";
    // Brief wait so producer reaches recvEvent before we post. Without
    // this, the post may land before the producer's claim worker has
    // pulled the job — the event would still be observable (cursor is
    // per-controller) but the test wouldn't exercise the long-poll
    // wake path.
    await sleepMs(2000);
    const receipt = await mesh.jobs.postEvent(jobId, "signal", {
      hello: "world",
      n: 42,
    });
    if (!proxy.wait) {
      return { job_id: jobId, post_seq: receipt.seq };
    }
    const result = await proxy.wait(30);
    return {
      job_id: jobId,
      post_seq: receipt.seq,
      job_result: result,
    };
  },
});

agent.addTool({
  name: "commission_event_filter",
  capability: "commission_event_filter",
  dependencies: [{ capability: "run_with_filter" }],
  meshJobDepIndex: 0,
  description:
    "Submit run_with_filter, post 2 ignored events, then the matching one.",
  parameters: z.object({}).passthrough(),
  execute: async (_args, runWithFilter: MeshJob | null = null) => {
    if (!runWithFilter?.submit) {
      return { error: "run_with_filter submitter not injected" };
    }
    const proxy = await runWithFilter.submit({}, { maxDuration: 60 });
    const jobId = (proxy as { jobId?: string }).jobId ?? "";
    // Give the producer a moment to claim + park on recvEvent.
    await sleepMs(2000);
    // Post 2 unrelated events — producer must NOT wake on these.
    const r1 = await mesh.jobs.postEvent(jobId, "ignore_a", { n: 1 });
    const r2 = await mesh.jobs.postEvent(jobId, "ignore_b", { n: 2 });
    // Brief gap so a buggy filter (one that DID wake on ignore_a) has
    // time to drive the producer to completion; if the producer is
    // already done by now, the matching post will get JobTerminalError.
    await sleepMs(1000);
    const r3 = await mesh.jobs.postEvent(jobId, "target", { got_it: true });
    if (!proxy.wait) {
      return {
        job_id: jobId,
        ignore_seqs: [r1.seq, r2.seq],
        target_seq: r3.seq,
      };
    }
    const result = await proxy.wait(30);
    return {
      job_id: jobId,
      ignore_seqs: [r1.seq, r2.seq],
      target_seq: r3.seq,
      result,
    };
  },
});

agent.addTool({
  name: "commission_subscribe_observer",
  capability: "commission_subscribe_observer",
  dependencies: [{ capability: "run_until_done" }],
  meshJobDepIndex: 0,
  description:
    "Submit run_until_done, concurrently post 'work' events and subscribe — verifies observer pattern.",
  parameters: z.object({}).passthrough(),
  execute: async (_args, runUntilDone: MeshJob | null = null) => {
    if (!runUntilDone?.submit) {
      return { error: "run_until_done submitter not injected" };
    }
    const proxy = await runUntilDone.submit({}, { maxDuration: 60 });
    const jobId = (proxy as { jobId?: string }).jobId ?? "";

    // Give the producer a moment to claim + park on recvEvent before
    // we post anything. Without this the first 'work' event could land
    // before the producer's claim worker has pulled the row off the
    // queue — the event would still be observable (the cursor is
    // per-controller), but the test would not exercise the long-poll
    // wake path.
    await sleepMs(2000);

    const observedEvents: Array<{ seq: number; payload: unknown }> = [];

    // Subscriber: observe events via subscribeEvents until the final one
    // arrives. Use a tighter long-poll than the default so the iterator
    // wakes more often during the test's narrow time budget.
    async function runSubscriber(): Promise<void> {
      for await (const event of mesh.jobs.subscribeEvents(jobId, {
        types: ["work"],
        longPollSecs: 5,
      })) {
        observedEvents.push({ seq: event.seq, payload: event.payload });
        const payload = event.payload as Record<string, unknown> | null;
        if (payload && typeof payload === "object" && payload.final === true) {
          return;
        }
      }
    }

    // Poster: fire 3 'work' events spaced ~500ms apart — the last
    // carries {final: true} to terminate the producer + subscriber.
    async function runPoster(): Promise<number[]> {
      const seqs: number[] = [];
      const payloads: Array<Record<string, unknown>> = [
        { item: 1 },
        { item: 2 },
        { item: 3, final: true },
      ];
      for (const payload of payloads) {
        await sleepMs(500);
        const receipt = await mesh.jobs.postEvent(jobId, "work", payload);
        seqs.push(receipt.seq);
      }
      return seqs;
    }

    // Start both concurrently. Subscriber races the producer for events,
    // but each has its own cursor — both must observe the same set.
    const subPromise = runSubscriber();
    const postedSeqs = await runPoster();

    // Bound the subscriber wait so a stuck observer doesn't hang the
    // whole test — 15s is well above the producer's expected runtime
    // (3 events * 500ms post spacing + handler overhead).
    let subscriberStatus: string;
    try {
      await Promise.race([
        subPromise,
        new Promise<never>((_, reject) =>
          setTimeout(
            () => reject(new Error("subscriber_timeout")),
            15000,
          ),
        ),
      ]);
      subscriberStatus = "ok";
    } catch (e) {
      // On timeout, suppress the subscriber promise's eventual rejection (or
      // resolution) to avoid an unhandled-rejection warning when we abandon
      // the wait. We CANNOT actually cancel the underlying long-poll from
      // here — `proxy.listEvents` is a fire-and-forget native await and JS
      // has no cancellation primitive for it. The subscriber will continue
      // to long-poll for up to `longPollSecs` after we report
      // subscriber_status="timeout" before resolving naturally. Plumbing an
      // AbortController through the napi layer would close this leak window
      // but is out of scope for this fixture.
      subPromise.catch(() => {});
      subscriberStatus =
        e instanceof Error && e.message === "subscriber_timeout"
          ? "timeout"
          : "error";
    }

    let jobResult: unknown = null;
    if (proxy.wait) {
      jobResult = await proxy.wait(30);
    }

    return {
      job_id: jobId,
      posted_seqs: postedSeqs,
      subscriber_status: subscriberStatus,
      observed_count: observedEvents.length,
      observed_events: observedEvents,
      job_result: jobResult,
    };
  },
});

agent.addTool({
  name: "commission_cancel_via_event",
  capability: "commission_cancel_via_event",
  dependencies: [{ capability: "run_until_cancel" }],
  meshJobDepIndex: 0,
  description:
    "Submit run_until_cancel, post a 'work' event, then cancel — synthetic 'cancelled' event must arrive.",
  parameters: z.object({}).passthrough(),
  execute: async (_args, runUntilCancel: MeshJob | null = null) => {
    if (!runUntilCancel?.submit) {
      return { error: "run_until_cancel submitter not injected" };
    }
    const proxy = await runUntilCancel.submit({}, { maxDuration: 60 });
    const jobId = (proxy as { jobId?: string }).jobId ?? "";
    await sleepMs(2000);
    const workReceipt = await mesh.jobs.postEvent(jobId, "work", { item: 1 });
    // Give the producer a moment to consume the 'work' event before we
    // fire the cancel. This makes the two events strictly ordered in
    // the producer's events_seen list (work first, cancelled second).
    await sleepMs(1000);
    if (proxy.cancel) {
      await proxy.cancel("external_stop_requested");
    }
    // The job is now cancelled — the producer's recvEvent loop will
    // observe the synthetic 'cancelled' event and return its dict via
    // the normal task return path. We CANNOT use proxy.wait() because
    // wait() raises on a cancelled terminal state. Instead read the
    // status row + the producer's log via the test driver.
    await sleepMs(3000);
    let terminalStatus: string | undefined;
    let terminalError: string | undefined;
    if (proxy.status) {
      const status = (await proxy.status()) as Record<string, unknown>;
      terminalStatus = status.status as string | undefined;
      terminalError = (status.error as string | undefined) ?? undefined;
    }
    return {
      job_id: jobId,
      work_seq: workReceipt.seq,
      terminal_status: terminalStatus,
      terminal_error: terminalError,
    };
  },
});

console.log(
  `long-task-consumer-ts uc22 fixture defined on port ${HTTP_PORT}. Waiting for auto-start...`,
);
