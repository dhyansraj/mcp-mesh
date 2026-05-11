/**
 * Unit tests for `sse-emitter.ts` (spec §4.6 / §4.7 / §5).
 *
 * Coverage:
 * - single-frame plan: artifact + terminal frames + headers
 * - sync-completed plan: artifact frame BEFORE terminal status frame
 * - long-running plan:
 *   - initial state=working, final=false
 *   - progress-changed frame
 *   - progress-unchanged → suppressed
 *   - keepalive comment after KEEPALIVE_MILLIS
 *   - terminal completed: artifact frame BEFORE terminal status frame
 *   - terminal failed / canceled: terminal status frame only (no artifact)
 *   - status() throws transiently → state=working frame, NOT terminal
 *     (Java BLOCKER #934 fix)
 *   - 5 consecutive status() failures → stream closes WITHOUT marking
 *     terminal (Java BLOCKER #934 fix)
 *   - MAX_STREAM_MILLIS cap → state=working, final=false frame, NOT
 *     final=true (Java BLOCKER #934 W3 fix)
 *   - Client disconnect mid-stream → loop exits without calling
 *     proxy.cancel() (spec §7.3)
 * - tasks/resubscribe:
 *   - Unknown id → JSON-RPC -32602 (NOT SSE)
 *   - Terminal task → one SSE frame with final=true
 *   - Lost JobProxy → single state=failed terminal frame
 *     (Java BLOCKER #934 fix)
 * - Appendix A golden-frame assertions:
 *   - typeof final === "boolean"
 *   - typeof metadata.progress === "number"
 *   - parts[0].type === "text"
 *
 * Mocking strategy:
 * - Fake Express Request/Response with capturing `write()`, `end()`,
 *   `setHeader()`, and `on()` so we can drive `close` events without
 *   binding a real http server.
 * - Fake JobProxy via the dispatcher's duck-typed path.
 * - vitest fake timers for keepalive + MAX_STREAM_MILLIS.
 *
 * Mirrors Java's `MeshA2ASseEmitterTest`.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { EventEmitter } from "node:events";
import type { Request, Response } from "express";

import { A2ATaskStore } from "../../../a2a/producer/task-store.js";
import { RouteRegistry } from "../../../route.js";
import {
  buildSseDispatcherMiddleware,
  renderSsePlan,
  POLL_INTERVAL_MILLIS,
  KEEPALIVE_MILLIS,
  MAX_STREAM_MILLIS,
  MAX_CONSECUTIVE_STATUS_FAILURES,
} from "../../../a2a/producer/sse-emitter.js";
import {
  buildResubscribeStream,
  buildStatusUpdateFrame,
  type A2AHandler,
  type DispatcherDeps,
  type SseStreamPlan,
  JSONRPC_INVALID_PARAMS,
} from "../../../a2a/producer/dispatcher.js";
import type { A2ASurfaceMetadata } from "../../../a2a/producer/registry.js";

// ────────────────────────────────────────────────────────────────────────
// Test fixtures
// ────────────────────────────────────────────────────────────────────────

interface FakeRes {
  status: ReturnType<typeof vi.fn>;
  setHeader: ReturnType<typeof vi.fn>;
  type: ReturnType<typeof vi.fn>;
  send: ReturnType<typeof vi.fn>;
  write: ReturnType<typeof vi.fn>;
  end: ReturnType<typeof vi.fn>;
  flushHeaders: ReturnType<typeof vi.fn>;
  on: (event: string, listener: (...args: unknown[]) => void) => void;
  removeListener: (event: string, listener: (...args: unknown[]) => void) => void;
  emit: (event: string) => boolean;
  writableEnded: boolean;
  destroyed: boolean;
  /** All `res.write(...)` calls captured in order. */
  _written: string[];
  /** All `_statusCode` captured. */
  _statusCode?: number;
  /** Captured body for non-streaming responses (status()/.type()/.send()). */
  _sentBody?: string;
  _sentType?: string;
}

function makeRes(): FakeRes {
  const ee = new EventEmitter();
  // Build the object first with placeholders so vi.fn closures can
  // reference the final res via lexical scope (no `this` binding needed —
  // .bind() strips the spy metadata so toHaveBeenCalled fails).
  const res = {
    writableEnded: false,
    destroyed: false,
    _written: [] as string[],
  } as FakeRes;
  res.status = vi.fn((code: number) => {
    res._statusCode = code;
    return res;
  }) as never;
  res.setHeader = vi.fn() as never;
  res.type = vi.fn((t: string) => {
    res._sentType = t;
    return res;
  }) as never;
  res.send = vi.fn((body: string) => {
    res._sentBody = body;
    return res;
  }) as never;
  res.write = vi.fn((data: string) => {
    res._written.push(data);
    return true;
  }) as never;
  res.end = vi.fn(() => {
    res.writableEnded = true;
    return res;
  }) as never;
  res.flushHeaders = vi.fn() as never;
  res.on = (e, l) => {
    ee.on(e, l);
  };
  res.removeListener = (e, l) => {
    ee.removeListener(e, l);
  };
  res.emit = (e) => ee.emit(e);
  return res;
}

function makeReq(body: unknown = {}): Request & {
  emit: (e: string) => boolean;
  _ee: EventEmitter;
} {
  const ee = new EventEmitter();
  return {
    body,
    headers: {},
    on: (e: string, l: (...args: unknown[]) => void) => {
      ee.on(e, l);
    },
    removeListener: (e: string, l: (...args: unknown[]) => void) => {
      ee.removeListener(e, l);
    },
    emit: (e: string) => ee.emit(e),
    _ee: ee,
  } as unknown as Request & { emit: (e: string) => boolean; _ee: EventEmitter };
}

/** Parse the JSON envelope from one `data: ...\n\n` frame. */
function parseFrame(raw: string): Record<string, unknown> {
  expect(raw.startsWith("data: ")).toBe(true);
  const json = raw.slice("data: ".length).replace(/\n\n$/, "");
  return JSON.parse(json) as Record<string, unknown>;
}

interface FakeProxyOptions {
  jobId?: string;
  status?: (...args: unknown[]) => Promise<Record<string, unknown>>;
  wait?: (...args: unknown[]) => Promise<unknown>;
  cancel?: (...args: unknown[]) => Promise<void>;
}

function fakeProxy(opts: FakeProxyOptions = {}): {
  jobId: string;
  status: (...args: unknown[]) => Promise<Record<string, unknown>>;
  wait: (...args: unknown[]) => Promise<unknown>;
  cancel: (...args: unknown[]) => Promise<void>;
} {
  return {
    jobId: opts.jobId ?? "job-x",
    status: vi.fn(opts.status ?? (async () => ({ status: "running" }))) as never,
    wait: vi.fn(opts.wait ?? (async () => null)) as never,
    cancel: vi.fn(opts.cancel ?? (async () => undefined)) as never,
  };
}

function makeSurface(): A2ASurfaceMetadata {
  return {
    path: "/agents/sse",
    skillId: "sse",
    skillName: "sse",
    description: "",
    tags: [],
    dependencies: [],
    auth: "",
    routeId: "rid",
  };
}

function makeDeps(
  handler: A2AHandler,
  taskStore: A2ATaskStore,
): DispatcherDeps {
  const surface = makeSurface();
  const routeRegistry = RouteRegistry.getInstance();
  const routeId = routeRegistry.registerRoute("A2A", surface.path, []);
  return {
    surface: { ...surface, routeId },
    handler,
    taskStore,
    routeRegistry,
  };
}

// ────────────────────────────────────────────────────────────────────────
// renderSsePlan — single-frame + sync-completed shapes
// ────────────────────────────────────────────────────────────────────────

describe("renderSsePlan: single-frame (spec §5)", () => {
  it("writes one data frame with the spec-mandated headers", async () => {
    const res = makeRes();
    const req = makeReq();
    const store = new A2ATaskStore();
    const frame = buildStatusUpdateFrame(
      1,
      "task-1",
      "completed",
      null,
      true,
      null,
    );
    const plan: SseStreamPlan = { kind: "single-frame", frame };

    await renderSsePlan(req as unknown as Request, res as unknown as Response, plan, store);

    // Headers per spec §5.1
    const headerMap = Object.fromEntries(res.setHeader.mock.calls);
    expect(headerMap["Content-Type"]).toBe("text/event-stream");
    expect(headerMap["Cache-Control"]).toBe("no-cache");
    expect(headerMap["Connection"]).toBe("keep-alive");
    expect(headerMap["X-Accel-Buffering"]).toBe("no");
    expect(res.flushHeaders).toHaveBeenCalled();

    // One data frame + end()
    expect(res._written).toHaveLength(1);
    expect(res._written[0]).toMatch(/^data: /);
    const parsed = parseFrame(res._written[0]);
    expect(parsed.jsonrpc).toBe("2.0");
    expect(res.end).toHaveBeenCalled();
  });
});

describe("renderSsePlan: sync-completed (spec §5.3)", () => {
  it("emits artifact frame BEFORE terminal status frame, then closes", async () => {
    const res = makeRes();
    const req = makeReq();
    const store = new A2ATaskStore();
    const plan: SseStreamPlan = {
      kind: "sync-completed",
      reqId: 1,
      taskId: "task-2",
      artifactFrame: {
        jsonrpc: "2.0",
        id: 1,
        result: {
          id: "task-2",
          artifact: { parts: [{ type: "text", text: "ok" }] },
        },
      },
      terminalFrame: buildStatusUpdateFrame(1, "task-2", "completed", null, true, null),
    };

    await renderSsePlan(req as unknown as Request, res as unknown as Response, plan, store);

    expect(res._written).toHaveLength(2);
    const f1 = parseFrame(res._written[0]);
    const f2 = parseFrame(res._written[1]);
    // Artifact first, then terminal status (spec §5.3 ordering).
    expect((f1.result as Record<string, unknown>).artifact).toBeDefined();
    expect(
      ((f2.result as Record<string, unknown>).status as Record<string, unknown>)
        .state,
    ).toBe("completed");
    // Appendix A: final on terminal frame is a real boolean.
    expect((f2.result as Record<string, unknown>).final).toBe(true);
    expect(typeof (f2.result as Record<string, unknown>).final).toBe("boolean");
    expect(res.end).toHaveBeenCalled();
  });
});

// ────────────────────────────────────────────────────────────────────────
// renderSsePlan: error plan
// ────────────────────────────────────────────────────────────────────────

describe("renderSsePlan: error plan -> JSON response (NOT SSE)", () => {
  it("returns the supplied JSON-RPC error body with the supplied HTTP status", async () => {
    const res = makeRes();
    const req = makeReq();
    const store = new A2ATaskStore();
    const plan: SseStreamPlan = {
      kind: "error",
      errorBody: {
        jsonrpc: "2.0",
        error: { code: JSONRPC_INVALID_PARAMS, message: "Unknown task id: ghost" },
        id: null,
      },
      httpStatus: 200,
    };

    await renderSsePlan(req as unknown as Request, res as unknown as Response, plan, store);

    expect(res._statusCode).toBe(200);
    expect(res._sentType).toBe("application/json");
    const body = JSON.parse(res._sentBody!);
    expect((body.error as Record<string, unknown>).code).toBe(JSONRPC_INVALID_PARAMS);
    // No SSE frames written.
    expect(res._written).toHaveLength(0);
  });
});

// ────────────────────────────────────────────────────────────────────────
// renderSsePlan: long-running poll loop
// ────────────────────────────────────────────────────────────────────────

describe("renderSsePlan: long-running poll loop (spec §5.3)", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  /**
   * Helper: drive a long-running plan to completion under fake timers.
   * Advances the timer in `pollCount` steps so the poll loop iterates.
   */
  async function runLongRunning(
    proxy: ReturnType<typeof fakeProxy>,
    taskId: string,
    polls: number,
  ): Promise<{ res: FakeRes; req: ReturnType<typeof makeReq>; store: A2ATaskStore }> {
    const res = makeRes();
    const req = makeReq();
    const store = new A2ATaskStore();
    store.put(taskId, { sessionId: taskId, jobProxy: proxy as never });
    const plan: SseStreamPlan = {
      kind: "long-running",
      reqId: 1,
      taskId,
      proxy: proxy as never,
    };

    const promise = renderSsePlan(
      req as unknown as Request,
      res as unknown as Response,
      plan,
      store,
    );
    // Iteratively flush microtasks + advance the poll timer.
    for (let i = 0; i < polls; i++) {
      await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MILLIS);
    }
    // One extra microtask flush so any final awaits resolve.
    await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MILLIS);
    await promise;
    return { res, req, store };
  }

  /**
   * Initial frame: state=working, final=false.
   * Terminal frame on completed: artifact BEFORE terminal status.
   */
  it("emits initial working frame, then artifact + terminal status on completed", async () => {
    let callCount = 0;
    const proxy = fakeProxy({
      status: async () => {
        callCount += 1;
        if (callCount >= 2) return { status: "completed" };
        return { status: "running" };
      },
      wait: async () => "final-payload",
    });

    const { res, store } = await runLongRunning(proxy, "task-lr-1", 3);

    // Expected order: initial working, then artifact, then terminal.
    expect(res._written.length).toBeGreaterThanOrEqual(3);

    const frames = res._written.filter((w) => w.startsWith("data: ")).map(parseFrame);
    const initial = frames[0].result as Record<string, unknown>;
    expect((initial.status as Record<string, unknown>).state).toBe("working");
    expect(initial.final).toBe(false);
    expect(typeof initial.final).toBe("boolean");

    // Find artifact frame + terminal status frame.
    const artifactFrame = frames.find(
      (f) => (f.result as Record<string, unknown>).artifact !== undefined,
    );
    expect(artifactFrame).toBeDefined();
    const terminalFrame = frames.find(
      (f) =>
        (f.result as Record<string, unknown>).final === true &&
        ((f.result as Record<string, unknown>).status as Record<string, unknown>)
          ?.state === "completed",
    );
    expect(terminalFrame).toBeDefined();

    // Task store: marked terminal with the projected envelope.
    const cached = store.get("task-lr-1");
    expect(cached!.terminalEnvelope).toBeDefined();
  });

  /** Terminal failed → single final=true status frame, NO artifact frame. */
  it("terminal=failed -> single final status frame, no artifact", async () => {
    let n = 0;
    const proxy = fakeProxy({
      status: async () => {
        n += 1;
        if (n >= 2) return { status: "failed", error: "boom" };
        return { status: "running" };
      },
    });

    const { res } = await runLongRunning(proxy, "task-lr-fail", 3);

    const frames = res._written.filter((w) => w.startsWith("data: ")).map(parseFrame);
    expect(frames.some((f) => (f.result as Record<string, unknown>).artifact)).toBe(
      false,
    );
    const terminal = frames.find(
      (f) =>
        (f.result as Record<string, unknown>).final === true &&
        ((f.result as Record<string, unknown>).status as Record<string, unknown>)
          ?.state === "failed",
    );
    expect(terminal).toBeDefined();
    const status = (terminal!.result as Record<string, unknown>)
      .status as Record<string, unknown>;
    const msg = status.message as Record<string, unknown>;
    const parts = msg.parts as Array<Record<string, unknown>>;
    // Appendix A: type === "text".
    expect(parts[0].type).toBe("text");
    expect(parts[0].text).toBe("boom");
    expect(proxy.wait).not.toHaveBeenCalled();
  });

  /** Terminal canceled → single final=true status frame; spelling US. */
  it("terminal=canceled (US spelling) -> single final status frame", async () => {
    let n = 0;
    const proxy = fakeProxy({
      status: async () => {
        n += 1;
        if (n >= 2) return { status: "cancelled" }; // mesh emits UK
        return { status: "running" };
      },
    });

    const { res } = await runLongRunning(proxy, "task-lr-cancel", 3);

    const frames = res._written.filter((w) => w.startsWith("data: ")).map(parseFrame);
    const terminal = frames.find(
      (f) => (f.result as Record<string, unknown>).final === true,
    );
    expect(terminal).toBeDefined();
    const state = (
      (terminal!.result as Record<string, unknown>).status as Record<string, unknown>
    ).state;
    expect(state).toBe("canceled"); // US spelling per spec §7.2
    expect(state).not.toBe("cancelled");
  });

  /**
   * Progress-changed → frame emitted.
   * Progress-unchanged on subsequent polls → suppression.
   */
  it("progress-changed -> frame; progress-unchanged -> suppressed", async () => {
    const responses: Array<Record<string, unknown>> = [
      { status: "running", progress: 0.1 }, // 1st poll: change -> emit
      { status: "running", progress: 0.1 }, // 2nd poll: same -> suppress
      { status: "running", progress: 0.5 }, // 3rd poll: change -> emit
      { status: "completed" }, // 4th poll: terminal
    ];
    let i = 0;
    const proxy = fakeProxy({
      status: async () => responses[Math.min(i++, responses.length - 1)],
      wait: async () => "done",
    });

    const { res } = await runLongRunning(proxy, "task-prog", 5);

    const frames = res._written.filter((w) => w.startsWith("data: ")).map(parseFrame);
    // Count working frames with metadata.progress.
    const workingProgressFrames = frames.filter((f) => {
      const r = f.result as Record<string, unknown>;
      const meta = r.metadata as Record<string, unknown> | undefined;
      const state = (r.status as Record<string, unknown>)?.state;
      return state === "working" && meta && typeof meta.progress === "number";
    });
    // Should be 2 distinct progress frames (0.1 and 0.5), NOT 3.
    expect(workingProgressFrames.length).toBe(2);
    expect(
      (workingProgressFrames[0].result as Record<string, unknown>)
        .metadata as Record<string, unknown>,
    ).toEqual({ progress: 0.1 });
    expect(
      (workingProgressFrames[1].result as Record<string, unknown>)
        .metadata as Record<string, unknown>,
    ).toEqual({ progress: 0.5 });
    // Appendix A: progress is a real JSON number.
    expect(
      typeof (
        (workingProgressFrames[0].result as Record<string, unknown>)
          .metadata as Record<string, unknown>
      ).progress,
    ).toBe("number");
  });

  /**
   * Keepalive: after KEEPALIVE_MILLIS of inactivity (no progress change),
   * a `: keepalive\n\n` comment line is emitted.
   */
  it("keepalive emitted after KEEPALIVE_MILLIS of inactivity", async () => {
    const proxy = fakeProxy({ status: async () => ({ status: "running" }) });
    const res = makeRes();
    const req = makeReq();
    const store = new A2ATaskStore();
    store.put("task-ka", { sessionId: "task-ka", jobProxy: proxy as never });

    const plan: SseStreamPlan = {
      kind: "long-running",
      reqId: 1,
      taskId: "task-ka",
      proxy: proxy as never,
    };
    const renderPromise = renderSsePlan(
      req as unknown as Request,
      res as unknown as Response,
      plan,
      store,
    );

    // Advance well past KEEPALIVE_MILLIS — should see one keepalive comment.
    const iters = Math.ceil((KEEPALIVE_MILLIS * 2) / POLL_INTERVAL_MILLIS);
    for (let i = 0; i < iters; i++) {
      await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MILLIS);
    }

    // Force disconnect to terminate the loop cleanly.
    res.writableEnded = true;
    res.emit("close");
    await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MILLIS);
    await renderPromise;

    const keepalives = res._written.filter((s) => s === ": keepalive\n\n");
    expect(keepalives.length).toBeGreaterThanOrEqual(1);
  });

  /**
   * W2 regression: a transient-failure frame counts as activity, so
   * `lastEventTime` MUST be refreshed when one is emitted. Otherwise
   * the keepalive branch can trip KEEPALIVE_MILLIS after the LAST
   * successful frame even though a transient data frame went out in
   * between. Cosmetic — but a deviation from the progress-changed
   * branch and the keepalive branch which BOTH update
   * `lastEventTime`.
   *
   * Scenario: drive the loop with continuous transient failures
   * starting at t=0. The cap (MAX_CONSECUTIVE_STATUS_FAILURES=5)
   * closes the stream within ~5 seconds — well under
   * KEEPALIVE_MILLIS=15s — so a legitimate keepalive should never
   * fire. We assert exactly MAX_CONSECUTIVE_STATUS_FAILURES
   * "status unavailable" data frames and ZERO keepalive comment
   * lines. With the bug, the test still passes because the bug
   * manifests on a SUBSEQUENT suppressed-progress poll, not within
   * the transient loop itself — so we additionally insert one
   * suppressed-progress poll between transients to expose the
   * stale-`lastEventTime` path: the bug emits a keepalive between
   * the transient frames within KEEPALIVE_MILLIS; the fix does not.
   */
  it("transient frames refresh lastEventTime — no spurious keepalive within KEEPALIVE_MILLIS (W2)", async () => {
    let n = 0;
    const proxy = fakeProxy({
      status: async () => {
        n += 1;
        // First call: success frame to anchor `lastEventTime`.
        if (n === 1) return { status: "running" };
        // Throw on every subsequent call so we hit the transient
        // branch repeatedly. The cap (5 consecutive) closes the
        // stream — but we want to span > KEEPALIVE_MILLIS, so use a
        // higher consecutive count via interleaved successes.
        // Strategy: alternate throw / success-with-same-status so
        // `consecutiveStatusFailures` resets, but no progress change
        // → keepalive check is the only thing that can refresh
        // `lastEventTime` (in the bug path). With the fix, transient
        // frames refresh it. We drive 18 polls (well past
        // KEEPALIVE_MILLIS) and assert that with the fix at most 1
        // keepalive fires, vs. ≥ 2 without the fix.
        if (n % 2 === 0) throw new Error("transient");
        return { status: "running" };
      },
    });

    const res = makeRes();
    const req = makeReq();
    const store = new A2ATaskStore();
    store.put("task-w2", { sessionId: "task-w2", jobProxy: proxy as never });
    const plan: SseStreamPlan = {
      kind: "long-running",
      reqId: 1,
      taskId: "task-w2",
      proxy: proxy as never,
    };

    const renderPromise = renderSsePlan(
      req as unknown as Request,
      res as unknown as Response,
      plan,
      store,
    );

    // Drive 2 × KEEPALIVE_MILLIS worth of polls so two keepalives
    // could in principle fire. With the fix, transient frames keep
    // `lastEventTime` fresh — keepalives only fire when `now -
    // lastEventTime > KEEPALIVE_MILLIS` AND we hit the
    // suppressed-progress branch with no transient in between. Per
    // our alternating pattern, transient frames are emitted on
    // every even poll → `lastEventTime` is refreshed at most 1s
    // apart, suppressing every spurious keepalive.
    const iters = Math.ceil((2 * KEEPALIVE_MILLIS) / POLL_INTERVAL_MILLIS) + 2;
    for (let i = 0; i < iters; i++) {
      await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MILLIS);
    }
    res.writableEnded = true;
    res.emit("close");
    await renderPromise;

    const transients = res._written.filter(
      (w) => w.startsWith("data: ") && w.includes("status unavailable:"),
    );
    const keepalives = res._written.filter((s) => s === ": keepalive\n\n");

    // Several transient frames were emitted (one per even poll up
    // until disconnect).
    expect(transients.length).toBeGreaterThanOrEqual(2);
    // With the fix, every transient frame refreshes `lastEventTime`
    // so the gap to the next suppressed-progress poll is at most 1s
    // — well under KEEPALIVE_MILLIS=15s. ZERO keepalives are
    // expected. Without the fix, suppressed polls at t≈16, 17, ...
    // emit redundant keepalives even though a transient frame just
    // went out a poll earlier.
    expect(keepalives.length).toBe(0);
  });

  /**
   * #934 BLOCKER fix: status() throws transiently → emit state=working
   * frame (NOT terminal failed) and continue polling.
   */
  it("status() throw -> state=working frame, NOT terminal failed (#934)", async () => {
    let n = 0;
    const proxy = fakeProxy({
      status: async () => {
        n += 1;
        if (n === 1) return { status: "running" }; // initial poll OK
        if (n <= 3) throw new Error("transient");
        return { status: "running" };
      },
    });

    const res = makeRes();
    const req = makeReq();
    const store = new A2ATaskStore();
    store.put("task-trans", { sessionId: "task-trans", jobProxy: proxy as never });
    const plan: SseStreamPlan = {
      kind: "long-running",
      reqId: 1,
      taskId: "task-trans",
      proxy: proxy as never,
    };
    const renderPromise = renderSsePlan(
      req as unknown as Request,
      res as unknown as Response,
      plan,
      store,
    );
    // Drive through several polls.
    for (let i = 0; i < 5; i++) {
      await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MILLIS);
    }
    // Force disconnect to terminate cleanly.
    res.writableEnded = true;
    res.emit("close");
    await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MILLIS);
    await renderPromise;

    const frames = res._written.filter((w) => w.startsWith("data: ")).map(parseFrame);
    // No terminal=failed frame should have been emitted.
    const terminalFailed = frames.find(
      (f) =>
        (f.result as Record<string, unknown>).final === true &&
        ((f.result as Record<string, unknown>).status as Record<string, unknown>)
          ?.state === "failed",
    );
    expect(terminalFailed).toBeUndefined();

    // At least one working frame should carry "status unavailable:" message.
    const transientFrame = frames.find((f) => {
      const r = f.result as Record<string, unknown>;
      const status = r.status as Record<string, unknown>;
      const msg = status?.message as Record<string, unknown> | undefined;
      const parts = msg?.parts as Array<Record<string, unknown>> | undefined;
      const text = parts?.[0]?.text as string | undefined;
      return text?.startsWith("status unavailable:");
    });
    expect(transientFrame).toBeDefined();
    // Task store record is NOT marked terminal.
    expect(store.get("task-trans")?.terminalEnvelope).toBeUndefined();
  });

  /**
   * #934 BLOCKER fix: MAX_CONSECUTIVE_STATUS_FAILURES consecutive throws
   * close the stream WITHOUT marking the task store record terminal.
   */
  it("5 consecutive status() failures -> stream closes WITHOUT marking terminal (#934)", async () => {
    const proxy = fakeProxy({
      status: async () => {
        throw new Error("registry down");
      },
    });
    const res = makeRes();
    const req = makeReq();
    const store = new A2ATaskStore();
    store.put("task-cap", { sessionId: "task-cap", jobProxy: proxy as never });
    const plan: SseStreamPlan = {
      kind: "long-running",
      reqId: 1,
      taskId: "task-cap",
      proxy: proxy as never,
    };

    const renderPromise = renderSsePlan(
      req as unknown as Request,
      res as unknown as Response,
      plan,
      store,
    );
    // Drive enough iterations to exceed the cap.
    for (let i = 0; i < MAX_CONSECUTIVE_STATUS_FAILURES + 2; i++) {
      await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MILLIS);
    }
    await renderPromise;

    // res.end was called (stream closed).
    expect(res.end).toHaveBeenCalled();
    // Task store record was NOT marked terminal — client can resume.
    expect(store.get("task-cap")?.terminalEnvelope).toBeUndefined();
    expect(store.get("task-cap")?.jobProxy).toBe(proxy);
  });

  /**
   * #934 BLOCKER W3 fix: MAX_STREAM_MILLIS cap emits state=working,
   * final=false (NOT final=true) so clients know to resubscribe.
   */
  it("MAX_STREAM_MILLIS cap emits state=working, final=false (#934 W3)", async () => {
    const proxy = fakeProxy({ status: async () => ({ status: "running" }) });
    const res = makeRes();
    const req = makeReq();
    const store = new A2ATaskStore();
    store.put("task-cap2", { sessionId: "task-cap2", jobProxy: proxy as never });
    const plan: SseStreamPlan = {
      kind: "long-running",
      reqId: 1,
      taskId: "task-cap2",
      proxy: proxy as never,
    };

    const renderPromise = renderSsePlan(
      req as unknown as Request,
      res as unknown as Response,
      plan,
      store,
    );

    // Advance past the stream cap (1h).
    await vi.advanceTimersByTimeAsync(MAX_STREAM_MILLIS + POLL_INTERVAL_MILLIS);
    await renderPromise;

    // Filter out keepalive comment lines — only parse data frames.
    const dataFrames = res._written.filter((w) => w.startsWith("data: "));
    const frames = dataFrames.map(parseFrame);
    // Find the cap frame — last working frame with explanatory message.
    const capFrame = frames.find((f) => {
      const r = f.result as Record<string, unknown>;
      const status = r.status as Record<string, unknown>;
      const msg = status?.message as Record<string, unknown> | undefined;
      const parts = msg?.parts as Array<Record<string, unknown>> | undefined;
      const text = parts?.[0]?.text as string | undefined;
      return text?.includes("producer-side cap");
    });
    expect(capFrame).toBeDefined();
    const r = capFrame!.result as Record<string, unknown>;
    expect((r.status as Record<string, unknown>).state).toBe("working");
    // CRITICAL invariant: final=false, NOT true.
    expect(r.final).toBe(false);
    expect(typeof r.final).toBe("boolean");
    // Task store NOT marked terminal — client can resubscribe.
    expect(store.get("task-cap2")?.terminalEnvelope).toBeUndefined();
  });

  /**
   * Spec §7.3: client SSE disconnect MUST NOT cancel the underlying job.
   */
  it("client disconnect mid-stream -> loop exits WITHOUT proxy.cancel()", async () => {
    const proxy = fakeProxy({ status: async () => ({ status: "running" }) });
    const res = makeRes();
    const req = makeReq();
    const store = new A2ATaskStore();
    store.put("task-disc", { sessionId: "task-disc", jobProxy: proxy as never });
    const plan: SseStreamPlan = {
      kind: "long-running",
      reqId: 1,
      taskId: "task-disc",
      proxy: proxy as never,
    };

    const renderPromise = renderSsePlan(
      req as unknown as Request,
      res as unknown as Response,
      plan,
      store,
    );
    // Tick once so the loop is mid-sleep.
    await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MILLIS);
    // Simulate disconnect.
    res.writableEnded = true;
    res.emit("close");
    await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MILLIS);
    await renderPromise;

    // Spec §7.3: cancel() MUST NOT have been called.
    expect(proxy.cancel).not.toHaveBeenCalled();
    // Task store preserved (not marked terminal).
    expect(store.get("task-disc")?.terminalEnvelope).toBeUndefined();
    expect(store.get("task-disc")?.jobProxy).toBe(proxy);
  });
});

// ────────────────────────────────────────────────────────────────────────
// tasks/resubscribe
// ────────────────────────────────────────────────────────────────────────

describe("buildResubscribeStream (spec §4.7)", () => {
  let store: A2ATaskStore;
  beforeEach(() => {
    RouteRegistry.reset();
    store = new A2ATaskStore();
  });

  /** Spec §4.7 errors: unknown id → JSON-RPC -32602 (NOT SSE). */
  it("unknown task id -> JSON-RPC -32602 error plan (NOT SSE)", () => {
    const plan = buildResubscribeStream(1, { id: "ghost" }, store);
    expect(plan.kind).toBe("error");
    if (plan.kind === "error") {
      const err = plan.errorBody.error as Record<string, unknown>;
      expect(err.code).toBe(JSONRPC_INVALID_PARAMS);
      expect((err.message as string).toLowerCase()).toContain("unknown task id");
    }
  });

  /** Missing id → JSON-RPC -32602. */
  it("missing id -> JSON-RPC -32602 error plan", () => {
    const plan = buildResubscribeStream(1, {}, store);
    expect(plan.kind).toBe("error");
    if (plan.kind === "error") {
      expect((plan.errorBody.error as Record<string, unknown>).code).toBe(
        JSONRPC_INVALID_PARAMS,
      );
    }
  });

  /** Terminal record → single SSE frame with final=true. */
  it("terminal task -> single SSE frame with final=true", async () => {
    const env = {
      id: "t1",
      sessionId: "t1",
      status: { state: "completed", timestamp: "x" },
      artifacts: [],
      history: [],
    };
    store.put("t1", {
      sessionId: "t1",
      terminalEnvelope: env,
      terminalAt: Date.now(),
      jobProxy: null,
    });
    const plan = buildResubscribeStream(1, { id: "t1" }, store);
    expect(plan.kind).toBe("single-frame");
    if (plan.kind === "single-frame") {
      const result = plan.frame.result as Record<string, unknown>;
      expect(result.final).toBe(true);
      expect(typeof result.final).toBe("boolean");
      expect((result.status as Record<string, unknown>).state).toBe("completed");
    }
  });

  /** Non-terminal record + JobProxy → long-running plan. */
  it("non-terminal + JobProxy -> long-running plan", () => {
    const proxy = fakeProxy({ jobId: "j-resub" });
    store.put("t2", { sessionId: "t2", jobProxy: proxy as never });
    const plan = buildResubscribeStream(1, { id: "t2" }, store);
    expect(plan.kind).toBe("long-running");
    if (plan.kind === "long-running") {
      expect(plan.taskId).toBe("t2");
      expect(plan.proxy).toBe(proxy);
    }
  });

  /**
   * #934 BLOCKER fix: lost JobProxy on non-terminal record → single
   * SSE frame with state=failed + final=true so the client doesn't hang.
   */
  it("lost JobProxy non-terminal -> single state=failed terminal frame (#934)", () => {
    store.put("t3", { sessionId: "t3", jobProxy: null });
    const plan = buildResubscribeStream(1, { id: "t3" }, store);
    expect(plan.kind).toBe("single-frame");
    if (plan.kind === "single-frame") {
      const result = plan.frame.result as Record<string, unknown>;
      expect((result.status as Record<string, unknown>).state).toBe("failed");
      expect(result.final).toBe(true);
    }
  });
});

// ────────────────────────────────────────────────────────────────────────
// SSE dispatcher middleware fall-through
// ────────────────────────────────────────────────────────────────────────

describe("buildSseDispatcherMiddleware: routing", () => {
  let store: A2ATaskStore;
  beforeEach(() => {
    RouteRegistry.reset();
    store = new A2ATaskStore();
  });

  /** Non-SSE methods fall through to next(). */
  it("calls next() for non-SSE methods", async () => {
    const deps = makeDeps((async () => "ok") as A2AHandler, store);
    const mw = buildSseDispatcherMiddleware(deps);
    const next = vi.fn();
    const res = makeRes();
    await mw(
      makeReq({ jsonrpc: "2.0", method: "tasks/send", params: {} }) as unknown as Request,
      res as unknown as Response,
      next,
    );
    expect(next).toHaveBeenCalledTimes(1);
    expect(res._written).toHaveLength(0);
  });

  /** Non-object body falls through to next() (canonical -32700 from JSON-RPC dispatcher). */
  it("calls next() on null body", async () => {
    const deps = makeDeps((async () => "ok") as A2AHandler, store);
    const mw = buildSseDispatcherMiddleware(deps);
    const next = vi.fn();
    const res = makeRes();
    await mw(
      makeReq(null) as unknown as Request,
      res as unknown as Response,
      next,
    );
    expect(next).toHaveBeenCalledTimes(1);
  });
});
