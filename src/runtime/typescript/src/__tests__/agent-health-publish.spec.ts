/**
 * The `publish` bridge between the health refresh loop and the Rust core
 * (issue #1476).
 *
 * `updateHealth` returns false when the verdict was NOT queued to the
 * runtime, and the loop only checks for its own publish deadline — so a
 * dropped verdict has to be reported here or nowhere. Left silent, an
 * agent that reported `unhealthy` keeps heartbeating, is never withdrawn,
 * and no log line anywhere says why.
 *
 * The shutdown path returns the same false and must stay silent: the
 * handle is nulled by `shutdown()`, so warning there would make every
 * clean exit print a spurious failure.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import type { MockInstance } from "vitest";

import type {
  HealthCheckLoop,
  HealthCheckLoopOptions,
  MeshHealthStatus,
} from "../health-check.js";

/** Captured `publish` from the most recent `startHealthCheckLoop` call. */
let captured: HealthCheckLoopOptions | null = null;

// Replace only the loop starter: it captures the options and starts
// nothing, so `publish` can be driven directly instead of waiting a TTL.
vi.mock("../health-check.js", async (importOriginal) => {
  const actual =
    await importOriginal<typeof import("../health-check.js")>();
  return {
    ...actual,
    startHealthCheckLoop: (options: HealthCheckLoopOptions): HealthCheckLoop => {
      captured = options;
      return {
        latest: () => null,
        stop: () => {},
        seeded: async () => {},
      };
    },
  };
});

const { MeshAgent } = await import("../agent.js");

/**
 * Drive the REAL private `startHealthRefresh` against a stub `this` and
 * hand back the `publish` closure it built. Nothing here needs a
 * constructed agent — the method reads five fields and calls the (mocked)
 * loop starter.
 */
function buildPublish(stub: {
  handle: { updateHealth: (s: MeshHealthStatus) => Promise<boolean> } | null;
  shutdownRequested: boolean;
}): (status: MeshHealthStatus) => boolean | Promise<boolean> {
  const stubThis = {
    ...stub,
    agentId: "claude-provider-a1b2c3d4",
    healthLoop: undefined,
    config: { healthCheck: async () => true, healthCheckTtl: 30 },
  };
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const startHealthRefresh = (MeshAgent.prototype as any).startHealthRefresh;
  startHealthRefresh.call(stubThis);
  if (!captured) throw new Error("health refresh loop was never started");
  return captured.publish;
}

describe("MeshAgent health publish — a dropped verdict is reported", () => {
  let warnSpy: MockInstance;

  beforeEach(() => {
    captured = null;
    warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    vi.spyOn(console, "log").mockImplementation(() => {});
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("warns when updateHealth reports the verdict was not queued", async () => {
    const publish = buildPublish({
      handle: { updateHealth: async () => false },
      shutdownRequested: false,
    });

    await expect(publish("unhealthy")).resolves.toBe(false);

    expect(warnSpy).toHaveBeenCalledTimes(1);
    const message = String(warnSpy.mock.calls[0]?.[0]);
    expect(message).toContain("[mesh-health]");
    expect(message).toContain("unhealthy");
    expect(message).toContain("claude-provider-a1b2c3d4");
    expect(message).toContain("not queued");
  });

  it("stays silent when the verdict is queued", async () => {
    const publish = buildPublish({
      handle: { updateHealth: async () => true },
      shutdownRequested: false,
    });

    await expect(publish("healthy")).resolves.toBe(true);
    expect(warnSpy).not.toHaveBeenCalled();
  });

  it("stays silent on the shutdown path", async () => {
    // shutdown() sets the flag before it nulls the handle; both orderings
    // are the same non-error, and neither may warn.
    const shuttingDown = buildPublish({
      handle: { updateHealth: async () => false },
      shutdownRequested: true,
    });
    await expect(shuttingDown("unhealthy")).resolves.toBe(false);

    const tornDown = buildPublish({ handle: null, shutdownRequested: false });
    await expect(tornDown("unhealthy")).resolves.toBe(false);

    expect(warnSpy).not.toHaveBeenCalled();
  });
});
