/**
 * Mesh-aware `/ready` and `/health` tests (issue #1478).
 *
 * The agent chart gates Service endpoints on `/ready` (#1468). Before this
 * change both URLs were FastMCP's built-ins — `/ready` a hardcoded 200 in
 * stateless mode, `/health` the literal string `✓ Ok` — so a TypeScript
 * provider whose health check had withdrawn it from the mesh kept receiving
 * direct Service traffic, and `/health` told an operator nothing.
 *
 * Three properties are pinned here, and the third is the one most likely to
 * regress silently:
 *
 *   1. a non-healthy verdict answers 503 on BOTH endpoints, with detail;
 *   2. a healthy verdict answers 200;
 *   3. an agent with NO `healthCheck` configured is unaffected — it must
 *      keep answering ready/healthy exactly as it did before. Only a
 *      configured check may make these endpoints report not-ready.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import type { FastMCP } from "fastmcp";
import {
  registerHealthRoutes,
  buildHealthBody,
  buildReadyBody,
  statusCodeFor,
} from "../health-routes.js";
import type { HealthVerdict } from "../health-check.js";
import { MeshAgent } from "../agent.js";

/** One `app.on(...)` call. */
interface Registration {
  methods: string[];
  path: string;
  handler: (c: unknown) => unknown;
}

/** What a handler passed to `c.json(body, status)`. */
interface Answer {
  body: Record<string, unknown>;
  status: number;
}

/**
 * A FastMCP stub whose Hono app records registrations, plus helpers to
 * dispatch a request at one of them. Same shape as `livez-route.spec.ts`
 * and `jobs-cancel-route.spec.ts`: hono is a transitive dependency of
 * fastmcp rather than a declared one here, so the router is stubbed and
 * the handler contract is asserted directly.
 */
function stubServer(): { server: FastMCP; routes: Registration[] } {
  const routes: Registration[] = [];
  const server = {
    getApp: () => ({
      on: (methods: string[], path: string, handler: (c: unknown) => unknown) => {
        routes.push({ methods, path, handler });
      },
    }),
  } as unknown as FastMCP;
  return { server, routes };
}

/**
 * Invoke a registered handler as `method` would. GET and HEAD share one
 * handler by construction (`app.on(["GET", "HEAD"], ...)`), so dispatching
 * either must produce the same status — the property a HEAD probe depends
 * on.
 */
function dispatch(routes: Registration[], path: string, method: string): Answer {
  const route = routes.find((r) => r.path === path);
  if (!route) throw new Error(`no route registered for ${path}`);
  expect(route.methods).toContain(method);
  let answer: Answer | undefined;
  route.handler({
    req: { method },
    json: (body: Record<string, unknown>, status = 200) => {
      answer = { body, status };
      return body;
    },
  });
  if (!answer) throw new Error(`handler for ${path} never answered`);
  return answer;
}

const unhealthy: HealthVerdict = {
  status: "unhealthy",
  checks: { vendor_api_reachable: false },
  errors: ["vendor returned 503"],
};
const degraded: HealthVerdict = {
  status: "degraded",
  checks: { health_check_execution: false },
  errors: ["Health check failed: boom"],
};
const healthy: HealthVerdict = {
  status: "healthy",
  checks: { vendor_api_reachable: true },
  errors: [],
};

describe("registerHealthRoutes — registration", () => {
  let errorSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
  });
  afterEach(() => {
    errorSpy.mockRestore();
  });

  it("registers GET and HEAD for both /ready and /health", () => {
    const { server, routes } = stubServer();
    expect(registerHealthRoutes(server, "my-agent", () => null)).toBe(true);

    expect(routes.map((r) => r.path).sort()).toEqual(["/health", "/ready"]);
    for (const route of routes) {
      expect(route.methods).toEqual(["GET", "HEAD"]);
    }
    expect(errorSpy).not.toHaveBeenCalled();
  });

  it("logs at console.error when getApp() throws", () => {
    const server = {
      getApp: () => {
        throw new Error("FastMCP server not started");
      },
    } as unknown as FastMCP;

    expect(registerHealthRoutes(server, "my-agent", () => null)).toBe(false);
    expect(errorSpy).toHaveBeenCalledOnce();
    const msg = errorSpy.mock.calls[0][0] as string;
    expect(msg).toContain("/ready and /health routes NOT registered");
    expect(msg).toContain("FastMCP server not started");
  });

  it("logs at console.error when getApp() returns null", () => {
    const server = { getApp: () => null } as unknown as FastMCP;

    expect(registerHealthRoutes(server, "my-agent", () => null)).toBe(false);
    expect(errorSpy.mock.calls[0][0] as string).toContain("returned null");
  });

  it("logs at console.error when app.on() raises", () => {
    const server = {
      getApp: () => ({
        on: () => {
          throw new Error("hono internal: route conflict");
        },
      }),
    } as unknown as FastMCP;

    expect(registerHealthRoutes(server, "my-agent", () => null)).toBe(false);
    expect(errorSpy.mock.calls[0][0] as string).toContain(
      "hono internal: route conflict",
    );
  });
});

describe("the verdict drives both endpoints", () => {
  it("an unhealthy verdict answers 503 on /ready with the reason and errors", () => {
    const { server, routes } = stubServer();
    registerHealthRoutes(server, "provider-a", () => unhealthy);

    const { body, status } = dispatch(routes, "/ready", "GET");
    expect(status).toBe(503);
    expect(body.ready).toBe(false);
    expect(body.agent).toBe("provider-a");
    expect(body.status).toBe("unhealthy");
    expect(body.reason).toBe("Service is unhealthy");
    expect(body.errors).toEqual(["vendor returned 503"]);
  });

  it("an unhealthy verdict answers 503 on /health carrying checks and errors", () => {
    const { server, routes } = stubServer();
    registerHealthRoutes(server, "provider-a", () => unhealthy);

    const { body, status } = dispatch(routes, "/health", "GET");
    expect(status).toBe(503);
    expect(body.status).toBe("unhealthy");
    expect(body.agent).toBe("provider-a");
    expect(body.checks).toEqual({ vendor_api_reachable: false });
    expect(body.errors).toEqual(["vendor returned 503"]);
    expect(typeof body.timestamp).toBe("string");
  });

  // Python's `200 if status == "healthy" else 503` and Java's `serving()`
  // both answer 503 for degraded. The heartbeat keeps running (degraded
  // never withdraws), but a load balancer is told to stop adding load.
  it("a degraded verdict answers 503 on both endpoints", () => {
    const { server, routes } = stubServer();
    registerHealthRoutes(server, "provider-a", () => degraded);

    expect(dispatch(routes, "/ready", "GET").status).toBe(503);
    expect(dispatch(routes, "/health", "GET").status).toBe(503);
    expect(dispatch(routes, "/health", "GET").body.status).toBe("degraded");
  });

  it("a healthy verdict answers 200 on both endpoints", () => {
    const { server, routes } = stubServer();
    registerHealthRoutes(server, "provider-a", () => healthy);

    const ready = dispatch(routes, "/ready", "GET");
    expect(ready.status).toBe(200);
    expect(ready.body.ready).toBe(true);
    expect(ready.body.reason).toBeUndefined();

    const health = dispatch(routes, "/health", "GET");
    expect(health.status).toBe(200);
    expect(health.body.status).toBe("healthy");
    expect(health.body.checks).toEqual({ vendor_api_reachable: true });
  });

  // THE compatibility guarantee. Making these endpoints mesh-aware must not
  // change what an agent WITHOUT a health check answers — every existing
  // TypeScript agent is in that category, and a regression here would make
  // the whole fleet unready on upgrade.
  it("no healthCheck configured (null verdict) answers exactly as before: 200", () => {
    const { server, routes } = stubServer();
    registerHealthRoutes(server, "plain-agent", () => null);

    const ready = dispatch(routes, "/ready", "GET");
    expect(ready.status).toBe(200);
    expect(ready.body.ready).toBe(true);
    expect(ready.body.status).toBe("healthy");
    expect(ready.body.agent).toBe("plain-agent");
    expect(ready.body.mcp_wrappers).toBe(1);
    expect(ready.body.reason).toBeUndefined();

    const health = dispatch(routes, "/health", "GET");
    expect(health.status).toBe(200);
    expect(health.body.status).toBe("healthy");
    expect(health.body.checks).toEqual({});
    expect(health.body.errors).toEqual([]);
  });

  it("HEAD answers the same status as GET on both endpoints", () => {
    const { server, routes } = stubServer();
    registerHealthRoutes(server, "provider-a", () => unhealthy);

    expect(dispatch(routes, "/ready", "HEAD").status).toBe(503);
    expect(dispatch(routes, "/health", "HEAD").status).toBe(503);

    const { server: ok, routes: okRoutes } = stubServer();
    registerHealthRoutes(ok, "provider-a", () => null);
    expect(dispatch(okRoutes, "/ready", "HEAD").status).toBe(200);
    expect(dispatch(okRoutes, "/health", "HEAD").status).toBe(200);
  });

  // The verdict is re-read per request, not captured at registration: the
  // loop rewrites it every TTL and a route that cached the boot value would
  // answer 200 forever.
  it("reads the verdict per request rather than caching it", () => {
    const { server, routes } = stubServer();
    let current: HealthVerdict | null = null;
    registerHealthRoutes(server, "provider-a", () => current);

    expect(dispatch(routes, "/ready", "GET").status).toBe(200);
    current = unhealthy;
    expect(dispatch(routes, "/ready", "GET").status).toBe(503);
    current = healthy;
    expect(dispatch(routes, "/ready", "GET").status).toBe(200);
  });

  // One snapshot per request. Reading the source twice could mix two
  // verdicts into one response — a 200 status line over an unhealthy body.
  it("takes one verdict snapshot per request", () => {
    const { server, routes } = stubServer();
    const source = vi.fn(() => unhealthy);
    registerHealthRoutes(server, "provider-a", source);

    dispatch(routes, "/health", "GET");
    expect(source).toHaveBeenCalledOnce();
  });

  // A probe that cannot answer is not evidence the agent is broken, and a
  // 500 here would pull a working pod out of the Service.
  it("a throwing verdict source answers as if no check were configured", () => {
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    const { server, routes } = stubServer();
    registerHealthRoutes(server, "provider-a", () => {
      throw new Error("verdict source exploded");
    });

    expect(dispatch(routes, "/ready", "GET").status).toBe(200);
    expect(warnSpy).toHaveBeenCalled();
    warnSpy.mockRestore();
  });
});

describe("body builders match the Python contract", () => {
  it("/health carries status, agent, checks, errors and timestamp", () => {
    expect(Object.keys(buildHealthBody("a", unhealthy)).sort()).toEqual([
      "agent",
      "checks",
      "errors",
      "status",
      "timestamp",
    ]);
  });

  it("/ready carries ready, agent, status, mcp_wrappers and timestamp", () => {
    expect(Object.keys(buildReadyBody("a", healthy)).sort()).toEqual([
      "agent",
      "mcp_wrappers",
      "ready",
      "status",
      "timestamp",
    ]);
  });

  it("statusCodeFor is 200 only for healthy", () => {
    expect(statusCodeFor(null)).toBe(200);
    expect(statusCodeFor(healthy)).toBe(200);
    expect(statusCodeFor(degraded)).toBe(503);
    expect(statusCodeFor(unhealthy)).toBe(503);
  });
});

describe("_autoStart aborts when /ready and /health cannot be registered", () => {
  // Same fail-loud posture as /livez: an unregistered route here does NOT
  // fall back to something harmless — FastMCP's built-in answers a
  // hardcoded 200, so the agent would serve while lying about readiness,
  // which is the bug #1478 fixes. Silence would ship the regression.
  //
  // The auto-scheduled `_autoStart` tick from the constructor is stubbed
  // out (existing convention) — its rejection handler calls
  // `process.exit(1)`, which would take the test runner down. The ORIGINAL
  // method is captured and invoked explicitly instead.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const originalAutoStart = (MeshAgent.prototype as any)._autoStart;
  const spies: ReturnType<typeof vi.spyOn>[] = [];

  function stubPrototype(name: string, impl: () => unknown = () => undefined) {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    spies.push(vi.spyOn(MeshAgent.prototype as any, name).mockImplementation(impl));
  }

  beforeEach(() => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    vi.spyOn(console, "log").mockImplementation(() => {});
    stubPrototype("_autoStart", async () => undefined);
  });

  afterEach(() => {
    vi.restoreAllMocks();
    spies.length = 0;
  });

  /**
   * `/livez` registers first, so a getApp() that fails outright aborts
   * there and never reaches the health routes. To exercise THIS branch the
   * app must accept the `/livez` registration and reject the later ones.
   */
  function newAgent(failFrom: number): MeshAgent {
    let calls = 0;
    const server = {
      addTool: vi.fn(),
      start: vi.fn().mockResolvedValue(undefined),
      getApp: () => ({
        on: (_methods: string[], path: string) => {
          if (++calls > failFrom) {
            throw new Error(`hono internal: route conflict on ${path}`);
          }
        },
        post: vi.fn(),
      }),
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
    } as any;
    return new MeshAgent(server, { name: "ready-abort-test", httpPort: 0 });
  }

  it("rejects with an actionable message when the routes cannot be mounted", async () => {
    const agent = newAgent(1); // /livez succeeds, /ready fails

    const err = await originalAutoStart
      .call(agent)
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      .catch((e: any) => e);
    expect(err).toBeInstanceOf(Error);
    expect(err.message).toMatch(/\/ready and \/health routes failed to register/);
    expect(err.message).toContain("ready-abort-test");
    expect(err.message).toContain("cannot start");
  });

  it("registers /livez, /ready and /health when the app accepts them", async () => {
    const on = vi.fn();
    const server = {
      addTool: vi.fn(),
      start: vi.fn().mockResolvedValue(undefined),
      getApp: () => ({ on, post: vi.fn() }),
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
    } as any;
    const agent = new MeshAgent(server, {
      name: "ready-ok-test",
      httpPort: 0,
    });
    // Everything after route registration reaches the registry, the napi
    // handle and process-wide signal handlers — out of scope here.
    stubPrototype("registerLlmTools");
    stubPrototype("registerJobsHelperTools");
    stubPrototype("startHeartbeat", async () => undefined);
    stubPrototype("startClaimDispatchers");
    stubPrototype("startHealthRefresh");
    stubPrototype("installSignalHandlers");

    await expect(originalAutoStart.call(agent)).resolves.toBeUndefined();
    for (const path of ["/livez", "/ready", "/health"]) {
      expect(on).toHaveBeenCalledWith(
        ["GET", "HEAD"],
        path,
        expect.any(Function),
      );
    }
  });
});
