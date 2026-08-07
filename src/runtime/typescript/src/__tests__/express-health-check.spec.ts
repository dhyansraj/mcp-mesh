/**
 * `healthCheck` on a `meshExpress` gateway — RFC #1502 step 3.
 *
 * Until now `MeshExpress` accepted the option, warned that it was IGNORED,
 * and did nothing with it: a route agent was a fan-out point, and withdrawing
 * one was thought to take the application down. Step 2 removed that harm —
 * `/ready` reports the mesh runtime, not the verdict — so suppressing the
 * heartbeat now stops registry traffic ONLY. The Express server keeps
 * listening, resolved dependencies are retained (#1131), the pod stays in its
 * Service endpoints and keeps taking ingress. A withdrawn gateway stops being
 * DISCOVERED; it does not go dark.
 *
 * What is pinned here:
 *
 *   - a failing check reaches `updateHealth` on a gateway (the whole change:
 *     this is what pauses the heartbeat);
 *   - the loop is the SHARED one, with a gateway's TTL and the same
 *     seed-does-not-publish rule — not a second implementation;
 *   - a gateway that declares no check starts no loop, so it behaves exactly
 *     as before;
 *   - `/ready` stays 200 and `/livez` stays unconditional while the verdict is
 *     unhealthy — the property that makes withdrawal safe here;
 *   - `/health` carries the verdict, because it is now the only surface where
 *     an operator can see why the gateway went quiet.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import type { MockInstance } from "vitest";
import type { Server } from "http";
import express from "express";

import type {
  HealthCheckLoop,
  HealthCheckLoopOptions,
  HealthVerdict,
  MeshHealthStatus,
} from "../health-check.js";

/** Captured options from the most recent `startHealthCheckLoop` call. */
let captured: HealthCheckLoopOptions | null = null;
/** Verdict the stub loop reports from `latest()`. */
let stubVerdict: HealthVerdict | null = null;
let stopped = 0;

// Replace only the loop starter: it captures the options and starts nothing,
// so `publish` can be driven directly instead of waiting out a TTL.
vi.mock("../health-check.js", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../health-check.js")>();
  return {
    ...actual,
    startHealthCheckLoop: (options: HealthCheckLoopOptions): HealthCheckLoop => {
      captured = options;
      return {
        latest: () => stubVerdict,
        stop: () => {
          stopped++;
        },
        seeded: async () => {},
      };
    },
  };
});

const { MeshExpress } = await import("../express.js");

/**
 * Drive the REAL private `startHealthRefresh` against a stub `this`, the way
 * `agent-health-publish.spec.ts` does for `MeshAgent`. Nothing here needs a
 * started gateway — the method reads four fields and calls the (mocked) loop
 * starter.
 */
function startRefresh(stub: {
  handle: { updateHealth: (s: MeshHealthStatus) => Promise<boolean> } | null;
  shutdownRequested: boolean;
  healthCheck?: HealthCheckLoopOptions["healthCheck"];
  healthCheckTtl?: number;
}): void {
  const stubThis = {
    handle: stub.handle,
    shutdownRequested: stub.shutdownRequested,
    serviceId: "gateway-a1b2c3d4",
    healthLoop: null,
    config: {
      name: "gateway",
      healthCheck: stub.healthCheck,
      healthCheckTtl: stub.healthCheckTtl ?? 30,
    },
  };
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  (MeshExpress.prototype as any).startHealthRefresh.call(stubThis);
}

describe("MeshExpress health refresh — the gateway is no longer exempt", () => {
  let warnSpy: MockInstance;

  beforeEach(() => {
    captured = null;
    stubVerdict = null;
    stopped = 0;
    warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    vi.spyOn(console, "log").mockImplementation(() => {});
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("a declared healthCheck starts the refresh loop", () => {
    // The whole of step 3 for TypeScript. Before it, this was a `console.warn`
    // and nothing else.
    startRefresh({
      handle: { updateHealth: async () => true },
      shutdownRequested: false,
      healthCheck: () => true,
      healthCheckTtl: 7,
    });

    expect(captured).not.toBeNull();
    expect(captured!.ttlSeconds).toBe(7);
    expect(captured!.agentName).toBe("gateway-a1b2c3d4");
  });

  it("no healthCheck declared → no loop, so nothing changes for that gateway", () => {
    startRefresh({
      handle: { updateHealth: async () => true },
      shutdownRequested: false,
      healthCheck: undefined,
    });

    expect(captured).toBeNull();
  });

  it("an unhealthy verdict is published to the mesh runtime", async () => {
    // `updateHealth("unhealthy")` is what stops the heartbeat in the Rust
    // core; the registry then ages the gateway out of discovery.
    const published: string[] = [];
    startRefresh({
      handle: {
        updateHealth: async (status) => {
          published.push(status);
          return true;
        },
      },
      shutdownRequested: false,
      healthCheck: () => false,
    });

    await captured!.publish("unhealthy");
    expect(published).toEqual(["unhealthy"]);
    expect(warnSpy).not.toHaveBeenCalled();
  });

  it("warns when the runtime does not take the verdict", async () => {
    // Left silent, an unhealthy gateway would keep heartbeating with nothing
    // in the logs to say why it was never withdrawn.
    startRefresh({
      handle: { updateHealth: async () => false },
      shutdownRequested: false,
      healthCheck: () => false,
    });

    await captured!.publish("unhealthy");

    expect(warnSpy).toHaveBeenCalledTimes(1);
    const message = String(warnSpy.mock.calls[0]?.[0]);
    expect(message).toContain("[mesh-health]");
    expect(message).toContain("gateway-a1b2c3d4");
    expect(message).toContain("not queued");
  });

  it("stays silent on the shutdown path", async () => {
    startRefresh({
      handle: { updateHealth: async () => false },
      shutdownRequested: true,
      healthCheck: () => false,
    });
    await expect(captured!.publish("unhealthy")).resolves.toBe(false);

    captured = null;
    startRefresh({
      handle: null,
      shutdownRequested: false,
      healthCheck: () => false,
    });
    await expect(captured!.publish("unhealthy")).resolves.toBe(false);

    expect(warnSpy).not.toHaveBeenCalled();
  });

  it("no 'healthCheck is IGNORED' warning is emitted any more", () => {
    const app = express();
    new MeshExpress(app, {
      name: "warn-free-gateway",
      httpPort: 0,
      healthCheck: () => true,
    });

    expect(
      warnSpy.mock.calls.some((c: unknown[]) =>
        String(c[0]).includes("healthCheck is IGNORED"),
      ),
    ).toBe(false);
  });
});

describe("MeshExpress probes under a failing gateway health check", () => {
  let server: Server;
  let base: string;
  let gateway: InstanceType<typeof MeshExpress>;

  async function listen(healthCheck?: HealthCheckLoopOptions["healthCheck"]) {
    const app = express();
    // Constructing MeshExpress wires the endpoints; start() is NOT called (it
    // would register with a registry and open a heartbeat).
    gateway = new MeshExpress(app, {
      name: "health-test-api",
      httpPort: 0,
      healthCheck,
    });
    await new Promise<void>((resolve) => {
      server = app.listen(0, "127.0.0.1", () => resolve());
    });
    const addr = server.address();
    const port = typeof addr === "object" && addr ? addr.port : 0;
    base = `http://127.0.0.1:${port}`;
  }

  /** Put the gateway in the state a failing check leaves it in. */
  function withVerdict(verdict: HealthVerdict): void {
    stubVerdict = verdict;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (gateway as any).healthLoop = {
      latest: () => stubVerdict,
      stop: () => {},
      seeded: async () => {},
    };
  }

  const UNHEALTHY: HealthVerdict = {
    status: "unhealthy",
    checks: { upstream_reachable: false },
    errors: ["upstream down"],
  };

  beforeEach(() => {
    stubVerdict = null;
    vi.spyOn(console, "warn").mockImplementation(() => {});
    vi.spyOn(console, "log").mockImplementation(() => {});
  });

  afterEach(async () => {
    vi.restoreAllMocks();
    if (server) {
      await new Promise<void>((resolve) => server.close(() => resolve()));
    }
  });

  it("/health carries the verdict and answers 503", async () => {
    await listen(() => false);
    withVerdict(UNHEALTHY);

    const res = await fetch(`${base}/health`);
    expect(res.status).toBe(503);
    const body = (await res.json()) as Record<string, unknown>;
    expect(body.status).toBe("unhealthy");
    expect(body.errors).toEqual(["upstream down"]);
    expect(body.agent).toBe("health-test-api");
    expect(typeof body.serviceId).toBe("string");
  });

  it("/health answers 200 for a gateway with no check", async () => {
    await listen(undefined);
    const res = await fetch(`${base}/health`);
    expect(res.status).toBe(200);
    expect(((await res.json()) as Record<string, unknown>).status).toBe(
      "healthy",
    );
  });

  it("/livez stays unconditional while the verdict is unhealthy", async () => {
    // A restart cannot fix an upstream outage; it only erases the evidence.
    await listen(() => false);
    withVerdict(UNHEALTHY);
    expect((await fetch(`${base}/livez`)).status).toBe(200);
  });

  it("/ready never reports the verdict — it is what keeps the ingress alive", async () => {
    // This is the property that makes withdrawing a gateway safe: readiness is
    // the mesh runtime alone, so the pod keeps its Service endpoints. Here the
    // runtime is down (start() was never called), so the 503 must cite the
    // runtime and not the check.
    await listen(() => false);
    withVerdict(UNHEALTHY);

    const res = await fetch(`${base}/ready`);
    const body = (await res.json()) as Record<string, unknown>;
    expect(body.ready).toBe(false);
    expect(JSON.stringify(body)).not.toContain("upstream down");
  });

  it("shutdown stops the refresh loop", async () => {
    await listen(() => false);
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (gateway as any).healthLoop = {
      latest: () => null,
      stop: () => {
        stopped++;
      },
      seeded: async () => {},
    };
    stopped = 0;

    await gateway.shutdown();
    expect(stopped).toBe(1);
  });
});
