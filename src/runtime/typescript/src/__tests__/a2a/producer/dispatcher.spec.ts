/**
 * Unit tests for `dispatcher.ts` (spec §4).
 *
 * Coverage — JSON-RPC tasks/send / tasks/get / tasks/cancel verbs +
 * error semantics. Asserts JSON shape (not string-grep) per Appendix A.
 *
 * Mirrors Java's `MeshA2ADispatcherTest`.
 *
 * Mocking strategy:
 * - Use the duck-typed `isJobProxy` fallback path with a plain object that
 *   exposes `{jobId, status, wait, cancel}` — avoids binding the real
 *   napi `JobProxy` class.
 * - Fake Express Request/Response: a tiny capturing stub matching the
 *   methods the dispatcher actually calls (`status`, `type`, `send`).
 */
import { describe, it, expect, beforeEach, vi } from "vitest";
import type { Request, Response } from "express";

import { RouteRegistry } from "../../../route.js";
import { A2ATaskStore } from "../../../a2a/producer/task-store.js";
import {
  buildDispatcherMiddleware,
  type A2AHandler,
  type DispatcherDeps,
  JSONRPC_PARSE_ERROR,
  JSONRPC_INVALID_REQUEST,
  JSONRPC_METHOD_NOT_FOUND,
  JSONRPC_INVALID_PARAMS,
} from "../../../a2a/producer/dispatcher.js";
import type { A2ASurfaceMetadata } from "../../../a2a/producer/registry.js";

// ────────────────────────────────────────────────────────────────────────
// Test fixtures
// ────────────────────────────────────────────────────────────────────────

interface Captured {
  status?: number;
  contentType?: string;
  body?: string;
}

function makeRes(captured: Captured): Response {
  return {
    status(code: number) {
      captured.status = code;
      return this;
    },
    type(t: string) {
      captured.contentType = t;
      return this;
    },
    send(body: string) {
      captured.body = body;
      return this;
    },
  } as unknown as Response;
}

function makeReq(body: unknown): Request {
  return { body, headers: {} } as unknown as Request;
}

function parseBody(captured: Captured): Record<string, unknown> {
  expect(captured.body).toBeDefined();
  return JSON.parse(captured.body!) as Record<string, unknown>;
}

interface FakeProxyOptions {
  jobId?: string;
  status?: () => Promise<Record<string, unknown>>;
  wait?: (timeoutSecs?: number) => Promise<unknown>;
  cancel?: (reason?: string) => Promise<void>;
}

function fakeProxy(opts: FakeProxyOptions = {}): {
  jobId: string;
  status: (...args: unknown[]) => Promise<Record<string, unknown>>;
  wait: (...args: unknown[]) => Promise<unknown>;
  cancel: (...args: unknown[]) => Promise<void>;
} {
  return {
    jobId: opts.jobId ?? "job-fake",
    status: vi.fn(opts.status ?? (async () => ({ status: "running" }))) as never,
    wait: vi.fn(opts.wait ?? (async () => null)) as never,
    cancel: vi.fn(opts.cancel ?? (async () => undefined)) as never,
  };
}

function makeSurface(
  overrides: Partial<A2ASurfaceMetadata> = {},
): A2ASurfaceMetadata {
  return {
    path: "/agents/test",
    skillId: "test-skill",
    skillName: "Test Skill",
    description: "test",
    tags: [],
    dependencies: [],
    auth: "",
    routeId: "route_0_A2A:/agents/test",
    ...overrides,
  };
}

function makeDeps(
  handler: A2AHandler,
  taskStore: A2ATaskStore,
): DispatcherDeps {
  const surface = makeSurface();
  const routeRegistry = RouteRegistry.getInstance();
  // Register the surface's synthetic route so getDependenciesForRoute()
  // returns a fresh empty dict.
  const routeId = routeRegistry.registerRoute("A2A", surface.path, []);
  return {
    surface: { ...surface, routeId },
    handler,
    taskStore,
    routeRegistry,
  };
}

async function dispatch(
  deps: DispatcherDeps,
  body: unknown,
): Promise<Captured> {
  const middleware = buildDispatcherMiddleware(deps);
  const captured: Captured = {};
  await middleware(makeReq(body), makeRes(captured), () => {
    /* the JSON-RPC middleware never calls next */
  });
  return captured;
}

// ────────────────────────────────────────────────────────────────────────
// tasks/send
// ────────────────────────────────────────────────────────────────────────

describe("dispatcher: tasks/send (spec §4.3)", () => {
  let store: A2ATaskStore;
  beforeEach(() => {
    RouteRegistry.reset();
    store = new A2ATaskStore();
  });

  /**
   * Spec §4.3 sync branch: handler returns a value → state=completed.
   * Appendix A: parts[0].type === "text" + result JSON-stringified.
   */
  it("sync handler return -> state=completed with text part (Appendix A)", async () => {
    const handler: A2AHandler = async () => ({ greeting: "hello" });
    const deps = makeDeps(handler, store);

    const captured = await dispatch(deps, {
      jsonrpc: "2.0",
      id: 1,
      method: "tasks/send",
      params: { id: "task-1", message: { role: "user", parts: [] } },
    });

    expect(captured.status).toBe(200);
    const body = parseBody(captured);
    expect(body.jsonrpc).toBe("2.0");
    expect(body.id).toBe(1);
    const result = body.result as Record<string, unknown>;
    expect(result.id).toBe("task-1");
    const status = result.status as Record<string, unknown>;
    expect(status.state).toBe("completed");
    const artifacts = result.artifacts as Array<Record<string, unknown>>;
    expect(artifacts).toHaveLength(1);
    const parts = artifacts[0].parts as Array<Record<string, unknown>>;
    // Appendix A: parts[0].type MUST be the literal "text".
    expect(parts[0].type).toBe("text");
    expect(parts[0].text).toBe('{"greeting":"hello"}');
  });

  /** Appendix B item 7: sessionId defaults to taskId when not supplied. */
  it("sessionId defaults to taskId per spec Appendix B item 7", async () => {
    const handler: A2AHandler = async () => "ok";
    const deps = makeDeps(handler, store);

    const captured = await dispatch(deps, {
      jsonrpc: "2.0",
      method: "tasks/send",
      params: { id: "task-no-session" },
    });

    const result = parseBody(captured).result as Record<string, unknown>;
    expect(result.sessionId).toBe("task-no-session");
  });

  /** Spec §4.3 long-running: handler returns JobProxy → state=working. */
  it("JobProxy return -> state=working; task parked with proxy ref", async () => {
    const proxy = fakeProxy({ jobId: "job-long" });
    const handler: A2AHandler = async () => proxy;
    const deps = makeDeps(handler, store);

    const captured = await dispatch(deps, {
      jsonrpc: "2.0",
      id: "abc",
      method: "tasks/send",
      params: { id: "task-lr" },
    });

    const result = parseBody(captured).result as Record<string, unknown>;
    expect((result.status as Record<string, unknown>).state).toBe("working");
    // artifacts MAY be present-but-empty per spec §4.3.
    expect(result.artifacts).toEqual([]);

    // Task store: parked with JobProxy reference preserved.
    const parked = store.get("task-lr");
    expect(parked).toBeDefined();
    expect(parked!.jobProxy).toBe(proxy);
    expect(parked!.terminalAt).toBeUndefined();
  });

  /** Spec §4.3 "handler raised": exception → state=failed (NOT JSON-RPC error). */
  it("handler exception -> state=failed (NOT JSON-RPC error)", async () => {
    const handler: A2AHandler = async () => {
      throw new Error("boom");
    };
    const deps = makeDeps(handler, store);

    const captured = await dispatch(deps, {
      jsonrpc: "2.0",
      id: 7,
      method: "tasks/send",
      params: { id: "task-fail" },
    });

    const body = parseBody(captured);
    expect(body.error).toBeUndefined();
    const result = body.result as Record<string, unknown>;
    const status = result.status as Record<string, unknown>;
    expect(status.state).toBe("failed");
    const msg = status.message as Record<string, unknown>;
    const parts = msg.parts as Array<Record<string, unknown>>;
    expect(parts[0].type).toBe("text");
    expect(parts[0].text).toBe("boom");
    expect(result.artifacts).toEqual([]);
  });

  /** Spec §4.3: duplicate in-flight task_id -> -32602. */
  it("duplicate task id -> -32602", async () => {
    const handler: A2AHandler = async () => "ok";
    const deps = makeDeps(handler, store);

    await dispatch(deps, {
      jsonrpc: "2.0",
      method: "tasks/send",
      params: { id: "dup-1" },
    });
    const second = await dispatch(deps, {
      jsonrpc: "2.0",
      method: "tasks/send",
      params: { id: "dup-1" },
    });

    const body = parseBody(second);
    const err = body.error as Record<string, unknown>;
    expect(err.code).toBe(JSONRPC_INVALID_PARAMS);
    expect((err.message as string).toLowerCase()).toContain("already in use");
  });

  /**
   * Regression: two concurrent tasks/send with the same id must NOT both
   * slip through. Atomic reserveTask() in the task store closes the race
   * window between a non-atomic `contains()` pre-check and the post-await
   * `put()` (the `await handler(...)` between them yields control to the
   * event loop, so a separate request can pass the same pre-check).
   *
   * Acceptance: exactly one request returns state=completed, the other
   * returns JSON-RPC -32602 "already in use".
   */
  it("concurrent tasks/send with same id -> exactly one succeeds, other -32602", async () => {
    // Handler that yields to the event loop a couple of times before
    // returning — simulates the original race window between the
    // pre-check and the post-await put().
    const handler: A2AHandler = async () => {
      await Promise.resolve();
      await Promise.resolve();
      return "ok";
    };
    const deps = makeDeps(handler, store);
    const body = {
      jsonrpc: "2.0",
      method: "tasks/send",
      params: { id: "concurrent-1" },
    };
    const [first, second] = await Promise.all([
      dispatch(deps, body),
      dispatch(deps, body),
    ]);
    const firstBody = parseBody(first);
    const secondBody = parseBody(second);
    // Exactly one is a JSON-RPC error -32602, the other is a success.
    const errorBodies = [firstBody, secondBody].filter((b) => "error" in b);
    const successBodies = [firstBody, secondBody].filter((b) => "result" in b);
    expect(errorBodies).toHaveLength(1);
    expect(successBodies).toHaveLength(1);
    const err = errorBodies[0].error as Record<string, unknown>;
    expect(err.code).toBe(JSONRPC_INVALID_PARAMS);
    expect((err.message as string).toLowerCase()).toContain("already in use");
    const result = successBodies[0].result as Record<string, unknown>;
    const status = result.status as Record<string, unknown>;
    expect(status.state).toBe("completed");
  });
});

// ────────────────────────────────────────────────────────────────────────
// tasks/get
// ────────────────────────────────────────────────────────────────────────

describe("dispatcher: tasks/get (spec §4.4)", () => {
  let store: A2ATaskStore;
  beforeEach(() => {
    RouteRegistry.reset();
    store = new A2ATaskStore();
  });

  /** Spec §4.4: terminal record returns cached envelope. */
  it("terminal record returns cached envelope", async () => {
    const env = {
      id: "t1",
      sessionId: "t1",
      status: { state: "completed", timestamp: "2026-01-01T00:00:00.000Z" },
      artifacts: [],
      history: [],
    };
    store.put("t1", {
      sessionId: "t1",
      terminalEnvelope: env,
      terminalAt: Date.now(),
      jobProxy: null,
    });
    const deps = makeDeps((async () => "ok") as A2AHandler, store);

    const captured = await dispatch(deps, {
      jsonrpc: "2.0",
      id: 1,
      method: "tasks/get",
      params: { id: "t1" },
    });
    const body = parseBody(captured);
    expect(body.result).toEqual(env);
  });

  /** Spec §4.4: non-terminal + proxy.status() working → state=working. */
  it("non-terminal record + working proxy -> state=working (no artifact)", async () => {
    const proxy = fakeProxy({ status: async () => ({ status: "running" }) });
    store.put("t2", { sessionId: "t2", jobProxy: proxy as never });
    const deps = makeDeps((async () => null) as A2AHandler, store);

    const captured = await dispatch(deps, {
      jsonrpc: "2.0",
      id: 1,
      method: "tasks/get",
      params: { id: "t2" },
    });
    const result = parseBody(captured).result as Record<string, unknown>;
    expect((result.status as Record<string, unknown>).state).toBe("working");
    expect(result.artifacts).toEqual([]);
    expect(proxy.wait).not.toHaveBeenCalled();
  });

  /** Spec §4.4: non-terminal + status=completed → calls proxy.wait(1.0) for artifact. */
  it("non-terminal + completed status calls proxy.wait(1.0) for artifact", async () => {
    const proxy = fakeProxy({
      status: async () => ({ status: "completed" }),
      wait: async () => "final-result",
    });
    store.put("t3", { sessionId: "t3", jobProxy: proxy as never });
    const deps = makeDeps((async () => null) as A2AHandler, store);

    const captured = await dispatch(deps, {
      jsonrpc: "2.0",
      id: 1,
      method: "tasks/get",
      params: { id: "t3" },
    });

    const result = parseBody(captured).result as Record<string, unknown>;
    expect((result.status as Record<string, unknown>).state).toBe("completed");
    const artifacts = result.artifacts as Array<Record<string, unknown>>;
    expect(artifacts).toHaveLength(1);
    const parts = artifacts[0].parts as Array<Record<string, unknown>>;
    expect(parts[0].type).toBe("text");
    expect(parts[0].text).toBe("final-result");
    expect(proxy.wait).toHaveBeenCalledWith(1.0);
  });

  /** Spec §4.4: non-terminal + status=failed → state=failed; do NOT call wait(). */
  it("non-terminal + failed status -> state=failed; wait() not called", async () => {
    const proxy = fakeProxy({
      status: async () => ({ status: "failed", error: "kaboom" }),
    });
    store.put("t4", { sessionId: "t4", jobProxy: proxy as never });
    const deps = makeDeps((async () => null) as A2AHandler, store);

    const captured = await dispatch(deps, {
      jsonrpc: "2.0",
      id: 1,
      method: "tasks/get",
      params: { id: "t4" },
    });

    const result = parseBody(captured).result as Record<string, unknown>;
    const status = result.status as Record<string, unknown>;
    expect(status.state).toBe("failed");
    const msg = status.message as Record<string, unknown>;
    const parts = msg.parts as Array<Record<string, unknown>>;
    expect(parts[0].text).toBe("kaboom");
    expect(proxy.wait).not.toHaveBeenCalled();
  });

  /** Spec §7.2 UK→US: non-terminal + status=cancelled → state=canceled. */
  it("non-terminal + cancelled mesh status -> A2A state=canceled (US spelling)", async () => {
    const proxy = fakeProxy({ status: async () => ({ status: "cancelled" }) });
    store.put("t5", { sessionId: "t5", jobProxy: proxy as never });
    const deps = makeDeps((async () => null) as A2AHandler, store);

    const captured = await dispatch(deps, {
      jsonrpc: "2.0",
      id: 1,
      method: "tasks/get",
      params: { id: "t5" },
    });

    const result = parseBody(captured).result as Record<string, unknown>;
    expect((result.status as Record<string, unknown>).state).toBe("canceled");
    expect((result.status as Record<string, unknown>).state).not.toBe(
      "cancelled",
    );
  });

  /** Spec §4.4: status() throws → state=working with error text (NOT -32602). */
  it("proxy.status() throw -> state=working with 'status unavailable' (spec §4.4)", async () => {
    const proxy = fakeProxy({
      status: async () => {
        throw new Error("registry unreachable");
      },
    });
    store.put("t6", { sessionId: "t6", jobProxy: proxy as never });
    const deps = makeDeps((async () => null) as A2AHandler, store);

    const captured = await dispatch(deps, {
      jsonrpc: "2.0",
      id: 1,
      method: "tasks/get",
      params: { id: "t6" },
    });

    const body = parseBody(captured);
    expect(body.error).toBeUndefined();
    const result = body.result as Record<string, unknown>;
    const status = result.status as Record<string, unknown>;
    expect(status.state).toBe("working");
    const msg = status.message as Record<string, unknown>;
    const parts = msg.parts as Array<Record<string, unknown>>;
    expect(parts[0].text).toMatch(/status unavailable:/);
    expect(parts[0].text).toMatch(/registry unreachable/);
  });

  /** Spec §4.4 errors: unknown task id -> -32602. */
  it("unknown task id -> -32602", async () => {
    const deps = makeDeps((async () => null) as A2AHandler, store);

    const captured = await dispatch(deps, {
      jsonrpc: "2.0",
      id: 1,
      method: "tasks/get",
      params: { id: "ghost" },
    });

    const err = (parseBody(captured).error as Record<string, unknown>);
    expect(err.code).toBe(JSONRPC_INVALID_PARAMS);
    expect((err.message as string).toLowerCase()).toContain("unknown task id");
  });

  /** Appendix A: progress emitted as JSON number, not string. */
  it("Appendix A: metadata.progress is a JSON number (not stringified)", async () => {
    const proxy = fakeProxy({
      status: async () => ({ status: "running", progress: 0.42 }),
    });
    store.put("t-prog", { sessionId: "t-prog", jobProxy: proxy as never });
    const deps = makeDeps((async () => null) as A2AHandler, store);

    const captured = await dispatch(deps, {
      jsonrpc: "2.0",
      id: 1,
      method: "tasks/get",
      params: { id: "t-prog" },
    });

    const result = parseBody(captured).result as Record<string, unknown>;
    const meta = result.metadata as Record<string, unknown>;
    expect(typeof meta.progress).toBe("number");
    expect(meta.progress).toBe(0.42);
  });

  /**
   * Appendix A defensive guard (W1): if `proxy.status()` returns
   * `progress` as a non-number (e.g. a string `"50%"`), the dispatcher
   * MUST NOT emit it verbatim — the SSE emitter already coerces to
   * `typeof progress === "number" ? progress : null` so the
   * `tasks/get` path needs to match. Omit `metadata` entirely when the
   * raw value isn't a number.
   */
  it("Appendix A defensive: non-number progress -> metadata omitted (W1)", async () => {
    const proxy = fakeProxy({
      status: async () => ({ status: "running", progress: "50%" }),
    });
    store.put("t-prog-str", { sessionId: "t-prog-str", jobProxy: proxy as never });
    const deps = makeDeps((async () => null) as A2AHandler, store);

    const captured = await dispatch(deps, {
      jsonrpc: "2.0",
      id: 1,
      method: "tasks/get",
      params: { id: "t-prog-str" },
    });

    const result = parseBody(captured).result as Record<string, unknown>;
    // metadata must be absent (no spec-violating string-typed progress).
    expect(result.metadata).toBeUndefined();
  });

  /**
   * Regression: after a live-status poll returns a terminal state
   * (completed / failed / canceled), the envelope MUST be persisted via
   * markTerminal() so subsequent tasks/get calls hit the cache and don't
   * re-poll the JobProxy. Without this, every tasks/get after the task
   * finishes makes another expensive status() + wait() round-trip.
   */
  it("terminal live-status -> persisted; subsequent tasks/get hits cache (no re-poll)", async () => {
    const proxy = fakeProxy({
      status: async () => ({ status: "completed" }),
      wait: async () => "final-payload",
    });
    store.put("t-cache", { sessionId: "t-cache", jobProxy: proxy as never });
    const deps = makeDeps((async () => null) as A2AHandler, store);

    // First tasks/get: polls the proxy and observes terminal state.
    const first = await dispatch(deps, {
      jsonrpc: "2.0",
      id: 1,
      method: "tasks/get",
      params: { id: "t-cache" },
    });
    const firstResult = parseBody(first).result as Record<string, unknown>;
    expect((firstResult.status as Record<string, unknown>).state).toBe(
      "completed",
    );
    expect(proxy.status).toHaveBeenCalledTimes(1);
    expect(proxy.wait).toHaveBeenCalledTimes(1);

    // The record is now terminal (markTerminal stamped it).
    const parked = store.get("t-cache");
    expect(parked!.terminalEnvelope).toBeDefined();
    expect(parked!.terminalAt).toBeDefined();

    // Second tasks/get: must hit the cached terminal envelope — no
    // additional proxy.status() / proxy.wait() invocations.
    const second = await dispatch(deps, {
      jsonrpc: "2.0",
      id: 2,
      method: "tasks/get",
      params: { id: "t-cache" },
    });
    const secondResult = parseBody(second).result as Record<string, unknown>;
    expect((secondResult.status as Record<string, unknown>).state).toBe(
      "completed",
    );
    expect(proxy.status).toHaveBeenCalledTimes(1);
    expect(proxy.wait).toHaveBeenCalledTimes(1);
  });

  /**
   * Negative case: working (non-terminal) live-status MUST NOT mark the
   * record terminal. tasks/get should re-poll on the next call so the
   * client sees fresh progress.
   */
  it("working live-status -> NOT persisted; next tasks/get re-polls", async () => {
    const proxy = fakeProxy({
      status: async () => ({ status: "running", progress: 0.3 }),
    });
    store.put("t-working", { sessionId: "t-working", jobProxy: proxy as never });
    const deps = makeDeps((async () => null) as A2AHandler, store);

    await dispatch(deps, {
      jsonrpc: "2.0",
      id: 1,
      method: "tasks/get",
      params: { id: "t-working" },
    });
    await dispatch(deps, {
      jsonrpc: "2.0",
      id: 2,
      method: "tasks/get",
      params: { id: "t-working" },
    });
    // Each call must re-poll — no cached envelope for non-terminal records.
    expect(proxy.status).toHaveBeenCalledTimes(2);
    const parked = store.get("t-working");
    expect(parked!.terminalEnvelope).toBeUndefined();
  });
});

// ────────────────────────────────────────────────────────────────────────
// tasks/cancel
// ────────────────────────────────────────────────────────────────────────

describe("dispatcher: tasks/cancel (spec §4.5)", () => {
  let store: A2ATaskStore;
  beforeEach(() => {
    RouteRegistry.reset();
    store = new A2ATaskStore();
  });

  /** Spec §4.5: missing id -> -32602. */
  it("missing id -> -32602", async () => {
    const deps = makeDeps((async () => null) as A2AHandler, store);
    const captured = await dispatch(deps, {
      jsonrpc: "2.0",
      id: 1,
      method: "tasks/cancel",
      params: {},
    });
    const err = parseBody(captured).error as Record<string, unknown>;
    expect(err.code).toBe(JSONRPC_INVALID_PARAMS);
  });

  /** Unknown task id -> -32602. */
  it("unknown task id -> -32602", async () => {
    const deps = makeDeps((async () => null) as A2AHandler, store);
    const captured = await dispatch(deps, {
      jsonrpc: "2.0",
      id: 1,
      method: "tasks/cancel",
      params: { id: "ghost" },
    });
    const err = parseBody(captured).error as Record<string, unknown>;
    expect(err.code).toBe(JSONRPC_INVALID_PARAMS);
  });

  /** Spec §4.5 idempotent ack: already-terminal -> echo cached envelope. */
  it("already-terminal task -> echo cached envelope (idempotent)", async () => {
    const env = {
      id: "t1",
      sessionId: "t1",
      status: { state: "canceled" },
      artifacts: [],
      history: [],
    };
    store.put("t1", {
      sessionId: "t1",
      terminalEnvelope: env,
      terminalAt: Date.now(),
      jobProxy: null,
    });
    const deps = makeDeps((async () => null) as A2AHandler, store);

    const captured = await dispatch(deps, {
      jsonrpc: "2.0",
      id: 1,
      method: "tasks/cancel",
      params: { id: "t1" },
    });
    const body = parseBody(captured);
    expect(body.result).toEqual(env);
  });

  /** Non-terminal: cancel succeeds and post-cancel status terminal → cached. */
  it("cancel + status terminal -> caches terminal envelope", async () => {
    const proxy = fakeProxy({
      status: async () => ({ status: "cancelled" }),
    });
    store.put("t2", { sessionId: "t2", jobProxy: proxy as never });
    const deps = makeDeps((async () => null) as A2AHandler, store);

    const captured = await dispatch(deps, {
      jsonrpc: "2.0",
      id: 1,
      method: "tasks/cancel",
      params: { id: "t2", reason: "user-cancel" },
    });

    const result = parseBody(captured).result as Record<string, unknown>;
    expect((result.status as Record<string, unknown>).state).toBe("canceled");
    expect(proxy.cancel).toHaveBeenCalledWith("user-cancel");

    // Cached terminal envelope so a follow-up tasks/get is idempotent.
    const parked = store.get("t2");
    expect(parked!.terminalEnvelope).toBeDefined();
  });

  /** cancel() throws but status() succeeds → uses status envelope. */
  it("cancel() throws + status() succeeds -> uses status envelope", async () => {
    const proxy = fakeProxy({
      cancel: async () => {
        throw new Error("cancel failed");
      },
      status: async () => ({ status: "completed" }),
      wait: async () => "result",
    });
    store.put("t3", { sessionId: "t3", jobProxy: proxy as never });
    const deps = makeDeps((async () => null) as A2AHandler, store);

    const captured = await dispatch(deps, {
      jsonrpc: "2.0",
      id: 1,
      method: "tasks/cancel",
      params: { id: "t3" },
    });

    // status() succeeded → returns the (live) projected envelope. State
    // will be "completed" since that's what status() reported, but since
    // status was terminal cancel marks terminal (whatever state status
    // reported gets cached).
    const result = parseBody(captured).result as Record<string, unknown>;
    // Status came back terminal → envelope reflects that (not synthesized).
    expect((result.status as Record<string, unknown>).state).toBe("completed");
  });

  /**
   * Java BLOCKER fix from #934: cancel() AND status() both throw →
   * synthesized state=canceled envelope (no exception propagation).
   */
  it("cancel() + status() both throw -> synthesized state=canceled (#934)", async () => {
    const proxy = fakeProxy({
      cancel: async () => {
        throw new Error("cancel failed");
      },
      status: async () => {
        throw new Error("status failed");
      },
    });
    store.put("t4", { sessionId: "t4", jobProxy: proxy as never });
    const deps = makeDeps((async () => null) as A2AHandler, store);

    const captured = await dispatch(deps, {
      jsonrpc: "2.0",
      id: 1,
      method: "tasks/cancel",
      params: { id: "t4", reason: "double-fail" },
    });

    const body = parseBody(captured);
    expect(body.error).toBeUndefined();
    const result = body.result as Record<string, unknown>;
    expect((result.status as Record<string, unknown>).state).toBe("canceled");

    // Subsequent tasks/get returns the synthesized envelope (cached).
    const parked = store.get("t4");
    expect(parked!.terminalEnvelope).toBeDefined();
    const cached = parked!.terminalEnvelope as Record<string, unknown>;
    expect((cached.status as Record<string, unknown>).state).toBe("canceled");
  });

  /**
   * Defensive: lost JobProxy on a non-terminal record → synthesized
   * state=canceled rather than -32602 error.
   */
  it("non-terminal record without JobProxy -> synthesized state=canceled", async () => {
    store.put("t5", { sessionId: "t5", jobProxy: null });
    const deps = makeDeps((async () => null) as A2AHandler, store);

    const captured = await dispatch(deps, {
      jsonrpc: "2.0",
      id: 1,
      method: "tasks/cancel",
      params: { id: "t5" },
    });

    const body = parseBody(captured);
    expect(body.error).toBeUndefined();
    const result = body.result as Record<string, unknown>;
    expect((result.status as Record<string, unknown>).state).toBe("canceled");
  });
});

// ────────────────────────────────────────────────────────────────────────
// JSON-RPC error semantics (spec §4.1)
// ────────────────────────────────────────────────────────────────────────

describe("dispatcher: JSON-RPC error semantics (spec §4.1)", () => {
  let store: A2ATaskStore;
  beforeEach(() => {
    RouteRegistry.reset();
    store = new A2ATaskStore();
  });

  /** Spec §4.1: empty / null body -> HTTP 400 + -32700. */
  it("empty body -> HTTP 400 + -32700", async () => {
    const deps = makeDeps((async () => null) as A2AHandler, store);
    const captured: Captured = {};
    const middleware = buildDispatcherMiddleware(deps);
    await middleware(
      { body: null, headers: {} } as unknown as Request,
      makeRes(captured),
      () => {},
    );
    expect(captured.status).toBe(400);
    const err = parseBody(captured).error as Record<string, unknown>;
    expect(err.code).toBe(JSONRPC_PARSE_ERROR);
  });

  /** Spec §4.1: array body -> -32700 (not a JSON-RPC object). */
  it("array body -> HTTP 400 + -32700", async () => {
    const deps = makeDeps((async () => null) as A2AHandler, store);
    const captured: Captured = {};
    const middleware = buildDispatcherMiddleware(deps);
    await middleware(
      { body: [], headers: {} } as unknown as Request,
      makeRes(captured),
      () => {},
    );
    expect(captured.status).toBe(400);
    const err = parseBody(captured).error as Record<string, unknown>;
    expect(err.code).toBe(JSONRPC_PARSE_ERROR);
  });

  /**
   * Spec §4.1 + #934 BLOCKER: missing `method` field -> -32600 Invalid Request.
   * NOT -32601 with "Method not implemented: 'null'".
   */
  it("missing method field -> -32600 Invalid Request (NOT -32601 'null')", async () => {
    const deps = makeDeps((async () => null) as A2AHandler, store);
    const captured = await dispatch(deps, { jsonrpc: "2.0", id: 1 });
    const err = parseBody(captured).error as Record<string, unknown>;
    expect(err.code).toBe(JSONRPC_INVALID_REQUEST);
    expect(err.code).not.toBe(JSONRPC_METHOD_NOT_FOUND);
    // The error message MUST NOT contain "null" — that was the #934 bug.
    expect((err.message as string).toLowerCase()).not.toContain("'null'");
  });

  /**
   * Spec §4.1: unknown method -> -32601 with the actual method name.
   * #934 explicit guard.
   */
  it("unknown method -> -32601 with actual method name (NOT 'null')", async () => {
    const deps = makeDeps((async () => null) as A2AHandler, store);
    const captured = await dispatch(deps, {
      jsonrpc: "2.0",
      id: 1,
      method: "tasks/madeUp",
      params: {},
    });
    const err = parseBody(captured).error as Record<string, unknown>;
    expect(err.code).toBe(JSONRPC_METHOD_NOT_FOUND);
    expect(err.message).toContain("tasks/madeUp");
    expect((err.message as string).toLowerCase()).not.toContain("'null'");
  });

  /** Request id is echoed verbatim (including 0 and null). */
  it("echoes id verbatim including 0", async () => {
    const handler: A2AHandler = async () => "ok";
    const deps = makeDeps(handler, store);

    const captured = await dispatch(deps, {
      jsonrpc: "2.0",
      id: 0,
      method: "tasks/send",
      params: { id: "t-id-zero" },
    });
    const body = parseBody(captured);
    expect(body.id).toBe(0);
  });

  it("echoes id verbatim including null", async () => {
    const handler: A2AHandler = async () => "ok";
    const deps = makeDeps(handler, store);

    const captured = await dispatch(deps, {
      jsonrpc: "2.0",
      id: null,
      method: "tasks/send",
      params: { id: "t-id-null" },
    });
    const body = parseBody(captured);
    expect(body.id).toBeNull();
  });
});
