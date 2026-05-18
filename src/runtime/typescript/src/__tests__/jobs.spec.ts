/**
 * Tests for `mesh.jobs.postEvent` + the napi-bound `recvEvent` /
 * `sendEvent` plumbing (MeshJob event-injection — TS port of Python's
 * PR #1041, issue #1032).
 *
 * Strategy:
 *   - Mock `@mcpmesh/core` so we can drive the napi-rs surface (`JobController`,
 *     `JobProxy`) without binding to a real registry. The mock mirrors the
 *     napi-rs generated TS surface (`recvEvent` / `sendEvent` etc.).
 *   - Exercise the wrappers' public contracts: type filter, timeout
 *     validation, typed-error re-classification, LRU cache eviction,
 *     registry-URL resolution.
 *   - LRU cap is overridden via `MCP_MESH_JOBPROXY_CACHE_MAX=2` in the
 *     cache test so eviction is reproducible at small scale.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";

// Mock napi-rs core so we don't need a real registry. The shapes match
// the generated `index.d.ts` `JobController` / `JobProxy` classes plus
// the new `recvEvent` / `sendEvent` methods added in this PR.
vi.mock("@mcpmesh/core", async () => {
  const actual = await vi.importActual<Record<string, unknown>>("@mcpmesh/core");

  // Track constructed JobProxy instances per call so postEvent-cache
  // tests can assert how many distinct proxies were built.
  const proxyCalls: Array<{ jobId: string; registryUrl: string }> = [];
  const sendEventMock = vi.fn();
  class JobProxy {
    public readonly jobId: string;
    public readonly registryUrl: string;
    public readonly sendEvent: typeof sendEventMock;
    constructor(jobId: string, registryUrl: string) {
      this.jobId = jobId;
      this.registryUrl = registryUrl;
      this.sendEvent = sendEventMock;
      proxyCalls.push({ jobId, registryUrl });
    }
  }

  const recvEventMock = vi.fn();
  class JobController {
    public readonly jobId: string;
    public readonly recvEvent: typeof recvEventMock;
    constructor(jobId: string, _instanceId: string, _registryUrl: string) {
      this.jobId = jobId;
      this.recvEvent = recvEventMock;
    }
  }

  return {
    ...actual,
    JobController,
    JobProxy,
    // Expose the per-test mocks + ctor recorder via the module namespace
    // so the tests can reach for them.
    __sendEventMock: sendEventMock,
    __recvEventMock: recvEventMock,
    __proxyCalls: proxyCalls,
  };
});

import {
  postEvent,
  getOrCreateProxy,
  _clearProxyCache,
  translateJobError,
  JobNotFoundError,
  JobTerminalError,
} from "../jobs.js";

// Pull the mocks from the mocked module so test bodies can drive return
// values + read call counts.
const core = (await import("@mcpmesh/core")) as unknown as {
  __sendEventMock: ReturnType<typeof vi.fn>;
  __recvEventMock: ReturnType<typeof vi.fn>;
  __proxyCalls: Array<{ jobId: string; registryUrl: string }>;
  JobController: new (jobId: string, instanceId: string, registryUrl: string) => {
    recvEvent: (
      types?: string[] | null,
      timeoutSecs?: number | null,
    ) => Promise<unknown>;
  };
};

const sendEventMock = core.__sendEventMock;
const recvEventMock = core.__recvEventMock;
const proxyCalls = core.__proxyCalls;

beforeEach(() => {
  sendEventMock.mockReset();
  recvEventMock.mockReset();
  proxyCalls.length = 0;
  _clearProxyCache();
});

// ---------------------------------------------------------------------------
// translateJobError — substring → typed exception class
// ---------------------------------------------------------------------------
describe("translateJobError", () => {
  it("re-classifies 'job is terminal' messages to JobTerminalError", () => {
    const raw = new Error("job is terminal: completed at ts=...");
    const out = translateJobError(raw);
    expect(out).toBeInstanceOf(JobTerminalError);
    expect((out as Error).message).toContain("job is terminal");
  });

  it("re-classifies 'job not found' messages to JobNotFoundError", () => {
    const raw = new Error("backend error: job not found: abc-123");
    const out = translateJobError(raw);
    expect(out).toBeInstanceOf(JobNotFoundError);
  });

  it("passes unrelated errors through unchanged", () => {
    const raw = new Error("backend error: HTTP 500: boom");
    expect(translateJobError(raw)).toBe(raw);
  });

  it("leaves typed exception subclasses alone", () => {
    const already = new JobNotFoundError("nope");
    expect(translateJobError(already)).toBe(already);
  });
});

// ---------------------------------------------------------------------------
// JobController.recvEvent — invoked through the napi surface mock
// ---------------------------------------------------------------------------
describe("JobController.recvEvent (via napi mock)", () => {
  it("returns the event object on backend success", async () => {
    recvEventMock.mockResolvedValueOnce({
      job_id: "j-1",
      seq: 1,
      type: "signal",
      payload: { hello: "world" },
      trace_context: null,
      posted_by: "consumer-x",
      created_at: 1_700_000_000,
    });
    const controller = new core.JobController("j-1", "inst-1", "http://r");
    const ev = await controller.recvEvent(["signal"], 5);
    expect(ev).toMatchObject({ type: "signal", seq: 1 });
    expect((ev as { payload: { hello: string } }).payload.hello).toBe("world");
    expect(recvEventMock).toHaveBeenCalledWith(["signal"], 5);
  });

  it("returns null on timeout", async () => {
    recvEventMock.mockResolvedValueOnce(null);
    const controller = new core.JobController("j-1", "inst-1", "http://r");
    const ev = await controller.recvEvent(undefined, 0.1);
    expect(ev).toBeNull();
  });

  it("forwards the types filter through unchanged", async () => {
    recvEventMock.mockResolvedValueOnce(null);
    const controller = new core.JobController("j-1", "inst-1", "http://r");
    await controller.recvEvent(["target", "cancelled"], 1);
    expect(recvEventMock).toHaveBeenCalledWith(["target", "cancelled"], 1);
  });

  // The actual NaN/Infinity/negative guard lives in the Rust binding
  // (parse_timeout_secs in jobs_napi.rs), not in the TS wrapper — we
  // simulate the boundary error here so callers can validate they get a
  // catchable Error rather than a panic.
  it("surfaces a guard error when timeoutSecs is invalid", async () => {
    recvEventMock.mockRejectedValueOnce(
      new Error("timeoutSecs must be non-negative and finite, got NaN"),
    );
    const controller = new core.JobController("j-1", "inst-1", "http://r");
    await expect(controller.recvEvent(undefined, NaN)).rejects.toThrow(
      /non-negative and finite/,
    );
  });
});

// ---------------------------------------------------------------------------
// postEvent — happy path + error mapping + cache behavior
// ---------------------------------------------------------------------------
describe("postEvent", () => {
  it("constructs a JobProxy from MCP_MESH_REGISTRY_URL + calls sendEvent", async () => {
    process.env.MCP_MESH_REGISTRY_URL = "http://localhost:8000";
    sendEventMock.mockResolvedValueOnce({
      job_id: "j-1",
      seq: 1,
      created_at: 1_700_000_000,
    });
    const receipt = await postEvent("j-1", "signal", { hello: "world" });
    expect(receipt).toEqual({
      job_id: "j-1",
      seq: 1,
      created_at: 1_700_000_000,
    });
    expect(proxyCalls).toHaveLength(1);
    expect(proxyCalls[0]).toEqual({
      jobId: "j-1",
      registryUrl: "http://localhost:8000",
    });
    expect(sendEventMock).toHaveBeenCalledWith("signal", { hello: "world" });
  });

  it("normalises undefined/null payload to {}", async () => {
    process.env.MCP_MESH_REGISTRY_URL = "http://localhost:8000";
    sendEventMock.mockResolvedValue({ job_id: "j", seq: 1, created_at: 1 });
    await postEvent("j", "signal");
    expect(sendEventMock).toHaveBeenLastCalledWith("signal", {});
    await postEvent("j", "signal", null);
    expect(sendEventMock).toHaveBeenLastCalledWith("signal", {});
  });

  it("re-classifies a 'job not found' napi error to JobNotFoundError", async () => {
    process.env.MCP_MESH_REGISTRY_URL = "http://localhost:8000";
    sendEventMock.mockRejectedValueOnce(
      new Error("backend error: job not found: stale"),
    );
    await expect(postEvent("stale", "signal", {})).rejects.toBeInstanceOf(
      JobNotFoundError,
    );
  });

  it("re-classifies a 'job is terminal' napi error to JobTerminalError", async () => {
    process.env.MCP_MESH_REGISTRY_URL = "http://localhost:8000";
    sendEventMock.mockRejectedValueOnce(
      new Error("job is terminal: completed"),
    );
    await expect(postEvent("done", "signal", {})).rejects.toBeInstanceOf(
      JobTerminalError,
    );
  });

  it("throws when MCP_MESH_REGISTRY_URL is unset", async () => {
    delete process.env.MCP_MESH_REGISTRY_URL;
    await expect(postEvent("j", "signal", {})).rejects.toThrow(
      /MCP_MESH_REGISTRY_URL is not set/,
    );
  });

  it("caches the JobProxy per (registryUrl, jobId)", async () => {
    process.env.MCP_MESH_REGISTRY_URL = "http://localhost:8000";
    sendEventMock.mockResolvedValue({ job_id: "j", seq: 1, created_at: 1 });
    await postEvent("j-1", "signal", {});
    await postEvent("j-1", "signal", {});
    // Second call to same jobId must re-use the cached proxy.
    expect(proxyCalls).toHaveLength(1);
    // Different jobId constructs a fresh proxy.
    await postEvent("j-2", "signal", {});
    expect(proxyCalls).toHaveLength(2);
  });
});

// ---------------------------------------------------------------------------
// LRU eviction — cap=2 via env override
// ---------------------------------------------------------------------------
describe("getOrCreateProxy LRU eviction", () => {
  it("evicts the least-recently-used entry when the cap is reached", () => {
    process.env.MCP_MESH_JOBPROXY_CACHE_MAX = "2";
    // Insert 3 distinct entries — after the third insert only the 2
    // most recent ('b', 'c') should survive ('a' is evicted as LRU).
    const p1 = getOrCreateProxy("http://r", "a");
    const p2 = getOrCreateProxy("http://r", "b");
    const p3 = getOrCreateProxy("http://r", "c");
    expect(proxyCalls).toHaveLength(3);
    // Cache state at this point: { b, c }. 'c' is most-recent.
    // 'b' and 'c' still cached — no new construction.
    expect(getOrCreateProxy("http://r", "b")).toBe(p2);
    expect(getOrCreateProxy("http://r", "c")).toBe(p3);
    expect(proxyCalls).toHaveLength(3);
    // Re-fetching 'a' constructs a NEW proxy (the original was evicted
    // by the 'c' insert). proxyCalls grows; new ref differs from p1.
    const p1b = getOrCreateProxy("http://r", "a");
    expect(proxyCalls).toHaveLength(4);
    expect(p1b).not.toBe(p1);
    delete process.env.MCP_MESH_JOBPROXY_CACHE_MAX;
  });

  it("bumps an entry to most-recent on hit (LRU semantics)", () => {
    process.env.MCP_MESH_JOBPROXY_CACHE_MAX = "2";
    const a1 = getOrCreateProxy("http://r", "a");
    const b1 = getOrCreateProxy("http://r", "b");
    // Touch 'a' so it becomes most-recent and 'b' becomes least-recent.
    expect(getOrCreateProxy("http://r", "a")).toBe(a1);
    // Insert 'c' — should evict 'b' (the now-LRU), NOT 'a'.
    getOrCreateProxy("http://r", "c");
    // 'a' is still cached.
    expect(getOrCreateProxy("http://r", "a")).toBe(a1);
    // 'b' was evicted — re-fetching constructs a new instance.
    const b2 = getOrCreateProxy("http://r", "b");
    expect(b2).not.toBe(b1);
    delete process.env.MCP_MESH_JOBPROXY_CACHE_MAX;
  });
});
