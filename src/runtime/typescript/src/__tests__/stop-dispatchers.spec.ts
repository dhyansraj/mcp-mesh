/**
 * Tests for #1173 — concurrent claim-dispatcher shutdown under one
 * shared drain budget, and #1163 MED-2 — `MeshAgent.shutdown()` reaching
 * the registry unregister (`handle.shutdown()`) regardless of drain
 * outcome.
 *
 * Mirrors the Python fix in PR #1172
 * (`_mcp_mesh/engine/claim_dispatcher.py::stop_dispatchers`):
 *   - N dispatchers drain CONCURRENTLY against the SAME window (one
 *     drain window of wall time, not N stacked 30s windows);
 *   - the whole phase is hard-capped at drain + grace, after which the
 *     remaining drains are abandoned with a warning;
 *   - never rejects — a wedged dispatcher must not prevent the registry
 *     cleanup callers sequence afterwards.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";

import { stopDispatchers, type ClaimDispatcher } from "../claim-dispatcher.js";
import { MeshAgent } from "../agent.js";
import { ApiRuntime } from "../api-runtime.js";
import { MeshExpress } from "../express.js";

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/** Build a stub dispatcher whose stop() runs the given impl. */
function fakeDispatcher(
  capability: string,
  stopImpl: (timeoutMs?: number) => Promise<void>,
): ClaimDispatcher {
  return {
    capability,
    stop: vi.fn(stopImpl),
  } as unknown as ClaimDispatcher;
}

describe("stopDispatchers (#1173)", () => {
  let warnSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    vi.spyOn(console, "log").mockImplementation(() => {});
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("stops dispatchers concurrently — wall time is one drain window, not N", async () => {
    const d1 = fakeDispatcher("cap-a", () => sleep(200));
    const d2 = fakeDispatcher("cap-b", () => sleep(200));
    const d3 = fakeDispatcher("cap-c", () => sleep(200));

    const t0 = Date.now();
    await stopDispatchers([d1, d2, d3], 2000, 2000);
    const elapsed = Date.now() - t0;

    // Sequential would be >= 600ms; concurrent is ~200ms. The 500ms
    // bound leaves ~300ms of CI scheduling-jitter headroom while still
    // failing a sequential drain.
    expect(elapsed).toBeLessThan(500);
    expect(d1.stop).toHaveBeenCalledWith(2000);
    expect(d2.stop).toHaveBeenCalledWith(2000);
    expect(d3.stop).toHaveBeenCalledWith(2000);
  });

  it("passes the SHARED drain window to every dispatcher", async () => {
    const ds = [
      fakeDispatcher("cap-a", async () => {}),
      fakeDispatcher("cap-b", async () => {}),
      fakeDispatcher("cap-c", async () => {}),
    ];
    await stopDispatchers(ds, 250, 100);
    for (const d of ds) {
      expect(d.stop).toHaveBeenCalledWith(250);
    }
  });

  it("abandons a hanging drain at the hard cap (drain + grace) with a warning", async () => {
    const hanging = fakeDispatcher("cap-stuck", () => new Promise(() => {}));

    const t0 = Date.now();
    await stopDispatchers([hanging], 50, 50);
    const elapsed = Date.now() - t0;

    // Returned at ~100ms (50 drain + 50 grace), not hung forever.
    expect(elapsed).toBeGreaterThanOrEqual(90);
    expect(elapsed).toBeLessThan(1000);
    expect(warnSpy).toHaveBeenCalledWith(
      expect.stringContaining("exceeded the shared budget"),
    );
  });

  it("a rejecting stop() does not skip its peers and does not reject", async () => {
    const bad = fakeDispatcher("cap-bad", async () => {
      throw new Error("stop blew up");
    });
    const good = fakeDispatcher("cap-good", () => sleep(20));

    await expect(stopDispatchers([bad, good], 500, 100)).resolves.toBeUndefined();
    expect(good.stop).toHaveBeenCalledTimes(1);
    expect(warnSpy).toHaveBeenCalledWith(
      expect.stringContaining("error stopping dispatcher capability=cap-bad"),
      expect.any(Error),
    );
  });

  it("is a no-op for an empty dispatcher list", async () => {
    await expect(stopDispatchers([], 50, 50)).resolves.toBeUndefined();
  });
});

describe("MeshAgent.shutdown() — unregister runs regardless of drain outcome (#1163 MED-2 / #1173)", () => {
  beforeEach(() => {
    vi.spyOn(console, "warn").mockImplementation(() => {});
    vi.spyOn(console, "log").mockImplementation(() => {});
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  /**
   * Drive the REAL `shutdown()` against a stub `this` (same pattern as
   * the event-loop specs) so we don't have to bind a full agent to the
   * napi runtime. Only the fields shutdown() reads are provided.
   */
  function stubAgentThis(dispatchers: ClaimDispatcher[]) {
    return {
      _claimDispatchers: dispatchers,
      _a2aClients: new Map(),
      httpsProxy: undefined,
      handle: { shutdown: vi.fn(async () => {}) },
    };
  }

  it("calls handle.shutdown() even when a dispatcher drain hangs", async () => {
    const hanging = fakeDispatcher("cap-stuck", () => new Promise(() => {}));
    const stubThis = stubAgentThis([hanging]);
    const handle = stubThis.handle; // shutdown() nulls this.handle

    const shutdown = MeshAgent.prototype.shutdown;
    await shutdown.call(stubThis as unknown as MeshAgent, {
      drainTimeoutMs: 30,
      drainGraceMs: 30,
    });

    expect(handle.shutdown).toHaveBeenCalledTimes(1);
    // Handle nulled + dispatcher list cleared after a successful unregister.
    expect((stubThis as { handle: unknown }).handle).toBeNull();
    expect(stubThis._claimDispatchers).toEqual([]);
  });

  it("calls handle.shutdown() even when a dispatcher stop() throws", async () => {
    const bad = fakeDispatcher("cap-bad", async () => {
      throw new Error("drain blew up");
    });
    const stubThis = stubAgentThis([bad]);
    const handle = stubThis.handle;

    const shutdown = MeshAgent.prototype.shutdown;
    await shutdown.call(stubThis as unknown as MeshAgent, {
      drainTimeoutMs: 30,
      drainGraceMs: 30,
    });

    expect(handle.shutdown).toHaveBeenCalledTimes(1);
  });

  it("drains slow dispatchers concurrently within one budget", async () => {
    const d1 = fakeDispatcher("cap-a", () => sleep(200));
    const d2 = fakeDispatcher("cap-b", () => sleep(200));
    const d3 = fakeDispatcher("cap-c", () => sleep(200));
    const stubThis = stubAgentThis([d1, d2, d3]);
    const handle = stubThis.handle;

    const shutdown = MeshAgent.prototype.shutdown;
    const t0 = Date.now();
    await shutdown.call(stubThis as unknown as MeshAgent, {
      drainTimeoutMs: 2000,
      drainGraceMs: 2000,
    });
    const elapsed = Date.now() - t0;

    // Sequential would be >= 600ms; concurrent is ~200ms. 500ms bound
    // leaves ~300ms of CI scheduling-jitter headroom.
    expect(elapsed).toBeLessThan(500);
    expect(handle.shutdown).toHaveBeenCalledTimes(1);
  });

  it("shutdown() is idempotent — repeat calls return the SAME promise and never re-run the teardown", async () => {
    const d = fakeDispatcher("cap-a", () => sleep(50));
    const stubThis = stubAgentThis([d]);
    const handle = stubThis.handle;

    const shutdown = MeshAgent.prototype.shutdown;
    const p1 = shutdown.call(stubThis as unknown as MeshAgent, {
      drainTimeoutMs: 1000,
      drainGraceMs: 1000,
    });
    // Re-entrant call while the first teardown is mid-drain — the
    // user-code-shutdown() + signal-during-drain race. Must NOT start
    // a second concurrent teardown (double dispatcher stop, double
    // napi handle.shutdown()).
    const p2 = shutdown.call(stubThis as unknown as MeshAgent, {
      drainTimeoutMs: 1000,
      drainGraceMs: 1000,
    });
    expect(p2).toBe(p1);

    await p1;

    // A call AFTER completion also returns the memoized promise.
    const p3 = shutdown.call(stubThis as unknown as MeshAgent);
    expect(p3).toBe(p1);
    await p3;

    expect(d.stop).toHaveBeenCalledTimes(1);
    expect(handle.shutdown).toHaveBeenCalledTimes(1);
    // shutdown() itself flags the shutdown so the event loop's failure
    // branch can exit promptly.
    expect(
      (stubThis as { shutdownRequested?: boolean }).shutdownRequested,
    ).toBe(true);
  });
});

describe("shutdown() idempotency — ApiRuntime / MeshExpress (same memoized-promise pattern)", () => {
  beforeEach(() => {
    vi.spyOn(console, "warn").mockImplementation(() => {});
    vi.spyOn(console, "log").mockImplementation(() => {});
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("ApiRuntime.shutdown() memoizes — one napi handle.shutdown() across repeat calls", async () => {
    const stubThis = {
      handle: { shutdown: vi.fn(async () => {}) },
      shutdownPromise: null,
      shutdownRequested: false,
    };
    const handle = stubThis.handle; // shutdown() nulls this.handle

    const shutdown = ApiRuntime.prototype.shutdown;
    const p1 = shutdown.call(stubThis as unknown as ApiRuntime);
    const p2 = shutdown.call(stubThis as unknown as ApiRuntime);
    expect(p2).toBe(p1);
    await p1;
    expect(shutdown.call(stubThis as unknown as ApiRuntime)).toBe(p1);

    expect(handle.shutdown).toHaveBeenCalledTimes(1);
    expect(stubThis.shutdownRequested).toBe(true);
  });

  it("MeshExpress.shutdown() memoizes — one napi handle.shutdown() across repeat calls", async () => {
    const stubThis = {
      handle: { shutdown: vi.fn(async () => {}) },
      server: null,
      shutdownPromise: null,
      shutdownRequested: false,
    };
    const handle = stubThis.handle;

    const shutdown = MeshExpress.prototype.shutdown;
    const p1 = shutdown.call(stubThis as unknown as MeshExpress);
    const p2 = shutdown.call(stubThis as unknown as MeshExpress);
    expect(p2).toBe(p1);
    await p1;
    expect(shutdown.call(stubThis as unknown as MeshExpress)).toBe(p1);

    expect(handle.shutdown).toHaveBeenCalledTimes(1);
    expect(stubThis.shutdownRequested).toBe(true);
  });
});
