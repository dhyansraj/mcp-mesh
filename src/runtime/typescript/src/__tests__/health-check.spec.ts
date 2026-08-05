/**
 * Health-check verdict, TTL resolution and refresh-loop tests (issue #1476).
 *
 * The verdict table is the contract shared with Python (#1473) and Java
 * (#1475), and it is the part that has been shipped WRONG before: both
 * scaffolds once returned `degraded` for a real vendor outage, which kept
 * the heartbeat alive and made every scaffolded provider unable to
 * withdraw itself — the entire point of the feature. `unhealthy` is the
 * ONLY verdict that suppresses the heartbeat, so these tests pin exactly
 * which conditions produce it.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  normalizeHealthResult,
  runHealthCheck,
  resolveHealthCheckTtl,
  resolveHealthCheckTtlFromEnv,
  startHealthCheckLoop,
  describeThrown,
  DEFAULT_HEALTH_CHECK_TTL_SECONDS,
  HEALTH_CHECK_TTL_ENV,
  type MeshHealthStatus,
} from "../health-check.js";

describe("normalizeHealthResult — verdict table", () => {
  it("true is healthy, false is unhealthy", () => {
    expect(normalizeHealthResult(true).status).toBe("healthy");
    expect(normalizeHealthResult(false).status).toBe("unhealthy");
    expect(normalizeHealthResult(false).errors).toEqual([
      "Health check returned false",
    ]);
  });

  it("passes each declared status through verbatim", () => {
    for (const status of ["healthy", "degraded", "unhealthy"] as const) {
      expect(normalizeHealthResult({ status }).status).toBe(status);
    }
  });

  it("accepts surrounding whitespace and mixed case", () => {
    expect(normalizeHealthResult({ status: " UNHEALTHY " }).status).toBe(
      "unhealthy",
    );
  });

  it("a result with no status is reporting success (Python parity)", () => {
    expect(normalizeHealthResult({ checks: { api: true } }).status).toBe(
      "healthy",
    );
    expect(normalizeHealthResult({}).status).toBe("healthy");
  });

  it("carries checks and errors through untouched", () => {
    const verdict = normalizeHealthResult({
      status: "unhealthy",
      checks: { api_reachable: false, key_present: true },
      errors: ["vendor returned 503"],
    });
    expect(verdict.checks).toEqual({ api_reachable: false, key_present: true });
    expect(verdict.errors).toEqual(["vendor returned 503"]);
  });

  // A reporting defect must never withdraw a working agent from the mesh:
  // everything unparseable degrades, which keeps the heartbeat alive.
  it.each([
    ["unrecognized status string", { status: "down" }],
    ["non-string status", { status: 503 }],
    ["null", null],
    ["undefined", undefined],
    ["a number", 42],
    ["a string", "healthy"],
    ["an array", ["healthy"]],
  ])("degrades on %s — never unhealthy", (_label, raw) => {
    expect(normalizeHealthResult(raw).status).toBe("degraded");
  });

  it("tolerates non-object checks and non-array errors", () => {
    const verdict = normalizeHealthResult({
      status: "healthy",
      checks: "nope" as unknown as Record<string, unknown>,
      errors: "nope" as unknown as string[],
    });
    expect(verdict.checks).toEqual({});
    expect(verdict.errors).toEqual([]);
  });

  it("stringifies non-string error entries instead of leaking them", () => {
    const verdict = normalizeHealthResult({
      status: "unhealthy",
      errors: [new Error("boom"), 7] as unknown as string[],
    });
    expect(verdict.errors).toEqual(["boom", "7"]);
  });
});

describe("runHealthCheck — a broken check degrades, it does not withdraw", () => {
  let warnSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
  });
  afterEach(() => warnSpy.mockRestore());

  it("returns the normalized verdict of a sync check", async () => {
    expect((await runHealthCheck(() => false, "a")).status).toBe("unhealthy");
  });

  it("awaits an async check", async () => {
    const verdict = await runHealthCheck(
      async () => ({ status: "unhealthy" as const, errors: ["vendor 500"] }),
      "a",
    );
    expect(verdict.status).toBe("unhealthy");
    expect(verdict.errors).toEqual(["vendor 500"]);
  });

  it("a check that throws is degraded", async () => {
    const verdict = await runHealthCheck(() => {
      throw new Error("boom");
    }, "a");
    expect(verdict.status).toBe("degraded");
    expect(verdict.checks).toEqual({ health_check_execution: false });
    expect(verdict.errors[0]).toContain("boom");
  });

  it("a check that rejects is degraded", async () => {
    const verdict = await runHealthCheck(
      async () => Promise.reject(new Error("async boom")),
      "a",
    );
    expect(verdict.status).toBe("degraded");
    expect(verdict.errors[0]).toContain("async boom");
  });

  it.each([
    ["a string", "nope"],
    ["a number", 7],
    ["null", null],
    ["undefined", undefined],
  ])("survives a non-Error throw: %s", async (_label, thrown) => {
    const verdict = await runHealthCheck(() => {
      throw thrown;
    }, "a");
    expect(verdict.status).toBe("degraded");
  });

  it("survives a throw whose own toString throws", async () => {
    const hostile = {
      toString() {
        throw new Error("nope");
      },
    };
    const verdict = await runHealthCheck(() => {
      throw hostile;
    }, "a");
    expect(verdict.status).toBe("degraded");
    expect(verdict.errors[0]).toContain("<unprintable value>");
  });

  it("a check returning nothing degrades rather than crashing", async () => {
    const verdict = await runHealthCheck(
      (() => undefined) as unknown as () => boolean,
      "a",
    );
    expect(verdict.status).toBe("degraded");
  });
});

describe("describeThrown", () => {
  it("prefers the message, falls back to the name", () => {
    expect(describeThrown(new Error("msg"))).toBe("msg");
    const bare = new TypeError("");
    expect(describeThrown(bare)).toBe("TypeError");
  });
});

describe("resolveHealthCheckTtl", () => {
  let warnSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
  });
  afterEach(() => warnSpy.mockRestore());

  it("defaults to 15s", () => {
    expect(resolveHealthCheckTtl()).toBe(DEFAULT_HEALTH_CHECK_TTL_SECONDS);
    expect(resolveHealthCheckTtl(null, null)).toBe(15);
    expect(warnSpy).not.toHaveBeenCalled();
  });

  it("takes a valid configured value", () => {
    expect(resolveHealthCheckTtl(30)).toBe(30);
    expect(resolveHealthCheckTtl(1)).toBe(1);
    expect(warnSpy).not.toHaveBeenCalled();
  });

  it.each([
    ["zero", 0],
    ["negative", -5],
    ["sub-second", 0.5],
    ["non-integer", 2.5],
    ["NaN", Number.NaN],
    ["Infinity", Number.POSITIVE_INFINITY],
  ])("rejects a %s configured value and warns", (_label, configured) => {
    expect(resolveHealthCheckTtl(configured)).toBe(15);
    expect(warnSpy).toHaveBeenCalledOnce();
  });

  it("the env var overrides the configured value", () => {
    expect(resolveHealthCheckTtl(30, "5")).toBe(5);
    expect(resolveHealthCheckTtl(30, "  7  ")).toBe(7);
    expect(warnSpy).not.toHaveBeenCalled();
  });

  it("a blank or whitespace env var is 'not set', not an error", () => {
    expect(resolveHealthCheckTtl(30, "")).toBe(30);
    expect(resolveHealthCheckTtl(30, "   ")).toBe(30);
    expect(warnSpy).not.toHaveBeenCalled();
  });

  // "15s" is the trap `parseInt` walks straight into: it yields 15 and
  // silently accepts a format the other runtimes reject.
  it.each([
    ["a duration suffix", "15s"],
    ["a float", "1.5"],
    ["hex", "0x10"],
    ["words", "fifteen"],
    ["trailing junk", "10 seconds"],
  ])("rejects %s in the env var and keeps the configured value", (_l, raw) => {
    expect(resolveHealthCheckTtl(30, raw)).toBe(30);
    expect(warnSpy).toHaveBeenCalledOnce();
    expect(String(warnSpy.mock.calls[0][0])).toContain("not an");
  });

  it.each([
    ["zero", "0"],
    ["negative", "-3"],
  ])("rejects a %s env var and keeps the configured value", (_l, raw) => {
    expect(resolveHealthCheckTtl(30, raw)).toBe(30);
    expect(String(warnSpy.mock.calls[0][0])).toContain("below the 1s minimum");
  });

  it("falls back to the default when BOTH sources are invalid", () => {
    expect(resolveHealthCheckTtl(0, "0")).toBe(15);
  });

  // A warning has to name the TTL the agent actually runs with. Warning
  // "using 15s" while a valid env override goes on to win prints a number
  // that appears nowhere in the agent's behaviour.
  it("warns with the value that WINS, not the one it fell back to", () => {
    expect(resolveHealthCheckTtl(0, "7")).toBe(7);
    expect(warnSpy).toHaveBeenCalledOnce();
    const message = String(warnSpy.mock.calls[0][0]);
    expect(message).toContain("healthCheckTtl=0");
    expect(message).toContain("using 7s");
    expect(message).not.toContain("using 15s");
  });

  it("reads the environment via resolveHealthCheckTtlFromEnv", () => {
    const previous = process.env[HEALTH_CHECK_TTL_ENV];
    try {
      process.env[HEALTH_CHECK_TTL_ENV] = "3";
      expect(resolveHealthCheckTtlFromEnv(30)).toBe(3);
      delete process.env[HEALTH_CHECK_TTL_ENV];
      expect(resolveHealthCheckTtlFromEnv(30)).toBe(30);
    } finally {
      if (previous === undefined) delete process.env[HEALTH_CHECK_TTL_ENV];
      else process.env[HEALTH_CHECK_TTL_ENV] = previous;
    }
  });
});

describe("startHealthCheckLoop", () => {
  let warnSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    vi.useFakeTimers();
    warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
  });
  afterEach(() => {
    vi.useRealTimers();
    warnSpy.mockRestore();
  });

  it("seeds without publishing, then publishes every tick", async () => {
    const published: MeshHealthStatus[] = [];
    const loop = startHealthCheckLoop({
      agentName: "provider",
      healthCheck: () => true,
      ttlSeconds: 10,
      publish: (status) => {
        published.push(status);
        return true;
      },
    });

    await loop.seeded();
    // The agent registers and becomes visible first: the seed run stores a
    // verdict but must not be able to withdraw a just-registered agent.
    expect(published).toEqual([]);
    expect(loop.latest()?.status).toBe("healthy");

    await vi.advanceTimersByTimeAsync(10_000);
    expect(published).toEqual(["healthy"]);

    await vi.advanceTimersByTimeAsync(10_000);
    expect(published).toEqual(["healthy", "healthy"]);

    loop.stop();
  });

  it("publishes unhealthy — the verdict that withdraws the agent", async () => {
    const published: MeshHealthStatus[] = [];
    let outage = true;
    const loop = startHealthCheckLoop({
      agentName: "provider",
      healthCheck: () => (outage ? { status: "unhealthy" as const } : true),
      ttlSeconds: 5,
      publish: (status) => {
        published.push(status);
        return true;
      },
    });

    await loop.seeded();
    await vi.advanceTimersByTimeAsync(5_000);
    expect(published).toEqual(["unhealthy"]);

    // Recovery is detected on the next tick and restores the heartbeat.
    outage = false;
    await vi.advanceTimersByTimeAsync(5_000);
    expect(published).toEqual(["unhealthy", "healthy"]);

    loop.stop();
  });

  // A tick that blows up must not silently end all future refreshes: the
  // agent would keep running with a health check that never runs again,
  // so it could never be withdrawn, and nothing after the first error
  // would reach the logs.
  it("keeps ticking after a check throws", async () => {
    const published: MeshHealthStatus[] = [];
    let calls = 0;
    const loop = startHealthCheckLoop({
      agentName: "provider",
      healthCheck: () => {
        calls += 1;
        if (calls <= 2) throw new Error("probe exploded");
        return true;
      },
      ttlSeconds: 1,
      publish: (status) => {
        published.push(status);
        return true;
      },
    });

    await loop.seeded();
    await vi.advanceTimersByTimeAsync(3_000);
    expect(published).toEqual(["degraded", "healthy", "healthy"]);

    loop.stop();
  });

  it("keeps ticking after publish rejects", async () => {
    let publishCalls = 0;
    const loop = startHealthCheckLoop({
      agentName: "provider",
      healthCheck: () => true,
      ttlSeconds: 1,
      publish: async () => {
        publishCalls += 1;
        throw new Error("napi handle gone");
      },
    });

    await loop.seeded();
    await vi.advanceTimersByTimeAsync(3_000);
    expect(publishCalls).toBe(3);

    loop.stop();
  });

  it("keeps ticking after the verdict listener throws", async () => {
    let publishCalls = 0;
    const loop = startHealthCheckLoop({
      agentName: "provider",
      healthCheck: () => true,
      ttlSeconds: 1,
      publish: () => {
        publishCalls += 1;
        return true;
      },
      onVerdict: () => {
        throw new Error("listener exploded");
      },
    });

    await loop.seeded();
    await vi.advanceTimersByTimeAsync(2_000);
    expect(publishCalls).toBe(2);

    loop.stop();
  });

  // The failure a `finally`-based reschedule cannot catch: a promise that
  // never settles never reaches the `finally` at all. `await fetch(url)`
  // with no AbortSignal against a black-holed host is exactly this, and it
  // would leave the agent running with a health check that never runs
  // again — silently, since nothing more is ever logged.
  it("abandons a check that never settles and keeps ticking", async () => {
    const published: MeshHealthStatus[] = [];
    let started = 0;
    const loop = startHealthCheckLoop({
      agentName: "provider",
      healthCheck: () => {
        started += 1;
        return new Promise<boolean>(() => {
          /* never settles, like a connect to a black hole */
        });
      },
      ttlSeconds: 1,
      publish: (status) => {
        published.push(status);
        return true;
      },
    });

    // Nothing has been abandoned yet: the deadline is generous on purpose.
    await vi.advanceTimersByTimeAsync(29_000);
    expect(started).toBe(1);
    expect(loop.latest()).toBeNull();

    // 30s deadline (the floor, since one TTL is shorter) elapses: the run
    // is abandoned, degraded so the agent keeps heartbeating, and the loop
    // is rescheduled.
    await vi.advanceTimersByTimeAsync(2_000);
    expect(loop.latest()?.status).toBe("degraded");
    expect(loop.latest()?.checks).toEqual({ health_check_completed: false });
    expect(started).toBe(2);
    expect(String(warnSpy.mock.calls[0][0])).toContain("did not finish");

    // ...and the tick after that publishes, proving the loop is alive.
    await vi.advanceTimersByTimeAsync(31_000);
    expect(published).toEqual(["degraded"]);
    expect(started).toBe(3);

    loop.stop();
  });

  // `updateHealth` sends on a bounded command channel: a runtime that has
  // stopped draining it makes the send wait, not fail.
  it("abandons a publish that never settles and keeps ticking", async () => {
    let publishCalls = 0;
    let checkCalls = 0;
    const loop = startHealthCheckLoop({
      agentName: "provider",
      healthCheck: () => {
        checkCalls += 1;
        return true;
      },
      ttlSeconds: 1,
      publish: () => {
        publishCalls += 1;
        return new Promise<boolean>(() => {
          /* never settles, like a full command channel */
        });
      },
    });

    await loop.seeded();
    // 1s to the first publishing tick, then a 10s publish deadline, then
    // 1s to the next tick: three publishes inside ~35s.
    await vi.advanceTimersByTimeAsync(35_000);
    expect(publishCalls).toBeGreaterThanOrEqual(3);
    expect(checkCalls).toBeGreaterThanOrEqual(4);
    expect(String(warnSpy.mock.calls[0][0])).toContain("did not complete");

    loop.stop();
  });

  it("stop() ends the loop and is idempotent", async () => {
    let publishCalls = 0;
    const loop = startHealthCheckLoop({
      agentName: "provider",
      healthCheck: () => true,
      ttlSeconds: 1,
      publish: () => {
        publishCalls += 1;
        return true;
      },
    });

    await loop.seeded();
    await vi.advanceTimersByTimeAsync(1_000);
    expect(publishCalls).toBe(1);

    loop.stop();
    loop.stop();
    await vi.advanceTimersByTimeAsync(10_000);
    expect(publishCalls).toBe(1);
  });

  it("does not block on a slow check — startup never waits for the vendor", async () => {
    let resolveProbe: (() => void) | undefined;
    const loop = startHealthCheckLoop({
      agentName: "provider",
      healthCheck: () =>
        new Promise<boolean>((resolve) => {
          resolveProbe = () => resolve(true);
        }),
      ttlSeconds: 1,
      publish: () => true,
    });

    // The loop is already constructed and usable while the probe hangs.
    expect(loop.latest()).toBeNull();
    resolveProbe?.();
    await loop.seeded();
    expect(loop.latest()?.status).toBe("healthy");

    loop.stop();
  });

  // Fixed DELAY, not fixed rate: a probe slower than its own TTL (a
  // vendor timing out is exactly that) must not queue back-to-back runs
  // against an already-struggling upstream.
  it("waits a full TTL AFTER a slow check completes", async () => {
    let running = 0;
    let maxConcurrent = 0;
    const loop = startHealthCheckLoop({
      agentName: "provider",
      healthCheck: async () => {
        running += 1;
        maxConcurrent = Math.max(maxConcurrent, running);
        await new Promise((resolve) => setTimeout(resolve, 3_000));
        running -= 1;
        return true;
      },
      ttlSeconds: 1,
      publish: () => true,
    });

    await vi.advanceTimersByTimeAsync(20_000);
    expect(maxConcurrent).toBe(1);

    loop.stop();
  });
});
