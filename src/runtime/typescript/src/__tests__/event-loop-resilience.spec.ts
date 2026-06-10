/**
 * Regression tests for #1163 MED-1 — the mesh event loop must outlive
 * individual failures.
 *
 * Previously all three event loops (MeshAgent, ApiRuntime, MeshExpress)
 * wrapped the entire `nextEvent()` + switch in one try/catch whose catch
 * did `console.error(...); break;` — a single throw (transient napi
 * rejection from nextEvent(), malformed event hitting a non-null
 * assertion inside a handler) killed dependency-event processing for the
 * process lifetime while the agent kept serving: frozen topology.
 *
 * The fixed loops:
 *   - isolate each event: a handler throw is logged and the loop keeps
 *     consuming events;
 *   - retry `nextEvent()` rejections with a bounded exponential backoff
 *     (100ms doubling, capped at 5s, reset on success);
 *   - exit only on the "shutdown" event or a torn-down handle.
 *
 * Pattern mirrors registry-disconnect-retains-deps.spec.ts: drive the
 * REAL private `runEventLoop` against a stub `this`.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";

import { MeshAgent } from "../agent.js";
import { ApiRuntime } from "../api-runtime.js";
import { MeshExpress } from "../express.js";
import { RouteRegistry } from "../route.js";
import { MAX_CONSECUTIVE_NEXT_EVENT_FAILURES } from "../config.js";

/** Replays the given event sequence once, then parks forever. */
function stubHandle(events: Array<Record<string, unknown>>) {
  let i = 0;
  return {
    nextEvent: async () => {
      if (i < events.length) return events[i++] as never;
      return new Promise<never>(() => {});
    },
  };
}

function depEvent(capability: string): Record<string, unknown> {
  return {
    eventType: "dependency_available",
    capability,
    endpoint: "http://peer:9000",
    functionName: "fn",
    agentId: "peer-1",
    requestingFunction: "tool",
    depIndex: 0,
  };
}

const THROW_THEN_PROCESS_THEN_SHUTDOWN = [
  depEvent("first"), // handler throws on this one
  depEvent("second"), // must still be processed
  { eventType: "shutdown" },
];

describe("event loop survives a throwing event handler (#1163 MED-1)", () => {
  let errorSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    RouteRegistry.reset();
    errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    vi.spyOn(console, "log").mockImplementation(() => {});
    vi.spyOn(console, "warn").mockImplementation(() => {});
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  function throwingThenRecordingHandler() {
    return vi
      .fn()
      .mockImplementationOnce(() => {
        throw new Error("malformed event boom");
      })
      .mockImplementation(() => {
        /* subsequent events processed fine */
      });
  }

  it("MeshAgent keeps processing events after a handler throw", async () => {
    const handler = throwingThenRecordingHandler();
    const stubThis = {
      handle: stubHandle(THROW_THEN_PROCESS_THEN_SHUTDOWN),
      handleDependencyAvailable: handler,
    };
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const runEventLoop = (MeshAgent.prototype as any).runEventLoop;
    await runEventLoop.call(stubThis);

    // Both dependency events reached the handler; the throw on the first
    // one was logged and did NOT kill the loop, and shutdown still exits.
    expect(handler).toHaveBeenCalledTimes(2);
    expect(errorSpy).toHaveBeenCalledWith(
      expect.stringContaining("error handling event 'dependency_available'"),
      expect.any(Error),
    );
  });

  it("ApiRuntime keeps processing events after a handler throw", async () => {
    const handler = throwingThenRecordingHandler();
    const stubThis = {
      handle: stubHandle(THROW_THEN_PROCESS_THEN_SHUTDOWN),
      handleDependencyAvailable: handler,
    };
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const runEventLoop = (ApiRuntime.prototype as any).runEventLoop;
    await runEventLoop.call(stubThis);

    expect(handler).toHaveBeenCalledTimes(2);
    expect(errorSpy).toHaveBeenCalledWith(
      expect.stringContaining("error handling event 'dependency_available'"),
      expect.any(Error),
    );
  });

  it("MeshExpress keeps processing events after a handler throw", async () => {
    const handler = throwingThenRecordingHandler();
    const stubThis = {
      handle: stubHandle(THROW_THEN_PROCESS_THEN_SHUTDOWN),
      handleDependencyAvailable: handler,
    };
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const runEventLoop = (MeshExpress.prototype as any).runEventLoop;
    await runEventLoop.call(stubThis);

    expect(handler).toHaveBeenCalledTimes(2);
    expect(errorSpy).toHaveBeenCalledWith(
      expect.stringContaining("error handling event 'dependency_available'"),
      expect.any(Error),
    );
  });
});

describe("event loop retries nextEvent() rejections with bounded backoff (#1163 MED-1)", () => {
  let errorSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    RouteRegistry.reset();
    errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    vi.spyOn(console, "log").mockImplementation(() => {});
    vi.spyOn(console, "warn").mockImplementation(() => {});
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.useRealTimers();
  });

  /**
   * Extract the backoff delays from the loop's "retrying in Xms" log
   * lines. Deliberately NOT a setTimeout spy: a spy on the (fake)
   * global setTimeout survives `vi.restoreAllMocks()` re-runs in later
   * tests' afterEach hooks and re-installs the stale fake clock,
   * hanging unrelated real-timer tests.
   */
  function loggedBackoffs(): number[] {
    return errorSpy.mock.calls
      .map((c) => /retrying in (\d+)ms/.exec(String(c[0]))?.[1])
      .filter((m): m is string => m !== undefined)
      .map(Number);
  }

  it("MeshAgent survives repeated nextEvent failures and still exits on shutdown", async () => {
    vi.useFakeTimers();
    const failures = 8;
    let attempts = 0;
    const stubThis = {
      handle: {
        nextEvent: async () => {
          if (attempts < failures) {
            attempts++;
            throw new Error(`transient napi failure ${attempts}`);
          }
          return { eventType: "shutdown" };
        },
      },
    };

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const runEventLoop = (MeshAgent.prototype as any).runEventLoop;
    const loop: Promise<void> = runEventLoop.call(stubThis);

    // Each rejection schedules one backoff sleep; advancing by the cap
    // flushes whichever delay is pending.
    for (let i = 0; i < failures + 1; i++) {
      await vi.advanceTimersByTimeAsync(5000);
    }
    await loop; // resolves — the loop survived and exited on shutdown

    expect(attempts).toBe(failures);
    // Backoff delays: exponential from 100ms, hard-capped at 5000ms.
    expect(loggedBackoffs()).toEqual([100, 200, 400, 800, 1600, 3200, 5000, 5000]);
  });

  it("MeshAgent resets the backoff after a successful nextEvent", async () => {
    vi.useFakeTimers();
    // fail, fail, succeed (benign event), fail, shutdown
    const script: Array<"fail" | Record<string, unknown>> = [
      "fail",
      "fail",
      { eventType: "registry_connected" },
      "fail",
      { eventType: "shutdown" },
    ];
    let i = 0;
    const stubThis = {
      handle: {
        nextEvent: async () => {
          const step = script[i++];
          if (step === "fail") throw new Error("transient");
          return step;
        },
      },
    };

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const runEventLoop = (MeshAgent.prototype as any).runEventLoop;
    const loop: Promise<void> = runEventLoop.call(stubThis);

    for (let n = 0; n < script.length; n++) {
      await vi.advanceTimersByTimeAsync(5000);
    }
    await loop;

    // 100, 200 (two consecutive failures), then reset to 100 after the
    // successful event.
    expect(loggedBackoffs()).toEqual([100, 200, 100]);
  });

  it("ApiRuntime survives a nextEvent rejection and still exits on shutdown", async () => {
    let attempts = 0;
    const stubThis = {
      handle: {
        nextEvent: async () => {
          if (attempts === 0) {
            attempts++;
            throw new Error("transient");
          }
          return { eventType: "shutdown" };
        },
      },
    };
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const runEventLoop = (ApiRuntime.prototype as any).runEventLoop;
    await runEventLoop.call(stubThis); // real timers: single 100ms backoff
    expect(attempts).toBe(1);
  });

  it("MeshExpress survives a nextEvent rejection and still exits on shutdown", async () => {
    let attempts = 0;
    const stubThis = {
      handle: {
        nextEvent: async () => {
          if (attempts === 0) {
            attempts++;
            throw new Error("transient");
          }
          return { eventType: "shutdown" };
        },
      },
    };
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const runEventLoop = (MeshExpress.prototype as any).runEventLoop;
    await runEventLoop.call(stubThis);
    expect(attempts).toBe(1);
  });
});

describe("event loop terminates at the consecutive-failure ceiling instead of retrying forever", () => {
  let errorSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    RouteRegistry.reset();
    errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    vi.spyOn(console, "log").mockImplementation(() => {});
    vi.spyOn(console, "warn").mockImplementation(() => {});
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.useRealTimers();
  });

  /**
   * Drive a permanently-failing nextEvent() against the given class's
   * REAL private runEventLoop. Returns the number of nextEvent()
   * attempts before the loop gave up (the loop resolving at all IS the
   * regression assertion — before the ceiling it retried forever, and
   * its ref'd backoff timer kept the process alive).
   */
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  async function runUntilCeiling(proto: any): Promise<number> {
    vi.useFakeTimers();
    let attempts = 0;
    const stubThis = {
      handle: {
        nextEvent: async () => {
          attempts++;
          throw new Error("permanent napi failure");
        },
      },
    };
    const loop: Promise<void> = proto.runEventLoop.call(stubThis);
    // Failures 1..N-1 each schedule one backoff sleep (≤ the 5s cap);
    // the Nth failure terminates without sleeping. Each advance
    // flushes at most one pending sleep.
    for (let i = 0; i < MAX_CONSECUTIVE_NEXT_EVENT_FAILURES; i++) {
      await vi.advanceTimersByTimeAsync(5000);
    }
    await loop;
    return attempts;
  }

  function expectTerminationLogged() {
    expect(errorSpy).toHaveBeenCalledWith(
      expect.stringContaining(
        `terminating after ${MAX_CONSECUTIVE_NEXT_EVENT_FAILURES} consecutive nextEvent() failures`,
      ),
      expect.any(Error),
    );
  }

  it("MeshAgent stops retrying after the documented failure count", async () => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const attempts = await runUntilCeiling(MeshAgent.prototype as any);
    expect(attempts).toBe(MAX_CONSECUTIVE_NEXT_EVENT_FAILURES);
    expectTerminationLogged();
  });

  it("ApiRuntime stops retrying after the documented failure count", async () => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const attempts = await runUntilCeiling(ApiRuntime.prototype as any);
    expect(attempts).toBe(MAX_CONSECUTIVE_NEXT_EVENT_FAILURES);
    expectTerminationLogged();
  });

  it("MeshExpress stops retrying after the documented failure count", async () => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const attempts = await runUntilCeiling(MeshExpress.prototype as any);
    expect(attempts).toBe(MAX_CONSECUTIVE_NEXT_EVENT_FAILURES);
    expectTerminationLogged();
  });

  it("a failing loop exits promptly once shutdown() is requested (well before the ceiling)", async () => {
    vi.useFakeTimers();
    let attempts = 0;
    const stubThis = {
      shutdownRequested: false,
      handle: {
        nextEvent: async () => {
          attempts++;
          throw new Error("still broken");
        },
      },
    };
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const runEventLoop = (MeshAgent.prototype as any).runEventLoop;
    const loop: Promise<void> = runEventLoop.call(stubThis);

    await vi.advanceTimersByTimeAsync(100); // flush the first backoff
    stubThis.shutdownRequested = true; // shutdown() sets this flag
    await vi.advanceTimersByTimeAsync(5000); // flush the pending backoff

    await loop; // exits via the failure-branch shutdown check
    expect(attempts).toBeLessThan(MAX_CONSECUTIVE_NEXT_EVENT_FAILURES);
  });
});
