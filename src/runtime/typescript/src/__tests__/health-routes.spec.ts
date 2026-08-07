/**
 * Mesh-aware `/ready` and `/health` tests (issue #1478, RFC #1502).
 *
 * Before #1478 both URLs were FastMCP's built-ins — `/ready` a hardcoded
 * 200 in stateless mode, `/health` the literal string `✓ Ok` — so an
 * operator who curled `/health` learned nothing about the agent.
 *
 * RFC #1502 step 2 then split what the two report, and that split is the
 * subject of most of this file:
 *
 *   - `/ready` reports the MESH RUNTIME STATE and nothing else. A failing
 *     or throwing `healthCheck` must not move it. A failing check already
 *     withdraws the agent by pausing the heartbeat; a 503 here would
 *     additionally empty the Kubernetes Service the mesh routes through,
 *     turning a failover into a connection error.
 *   - `/health` still answers 503 for a non-healthy verdict. Nothing
 *     probes it, so its status code is free to carry information.
 *
 * The runtime floor is not decoration: `startupCheck` defaults to passing,
 * so `/startupz` answers 200 before `startAgent()` has returned, and an
 * unconditional `/ready` would put a pod in the Service with no mesh
 * runtime behind it. It is also the only probe that can notice a runtime
 * that dies while the process lives, since `/livez` consults nothing.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import type { FastMCP } from "fastmcp";
import {
  registerHealthRoutes,
  buildHealthBody,
  buildReadyBody,
  readyStatusCodeFor,
  statusCodeFor,
} from "../health-routes.js";
import type { RuntimeState } from "../health-routes.js";
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

/** `registerHealthRoutes` with the runtime up, which is the normal case. */
function register(
  server: FastMCP,
  agentName: string,
  getVerdict: () => HealthVerdict | null,
  getRuntimeState: () => RuntimeState = () => "up",
): boolean {
  return registerHealthRoutes(server, agentName, getVerdict, getRuntimeState);
}

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
    expect(register(server, "my-agent", () => null)).toBe(true);

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

    expect(register(server, "my-agent", () => null)).toBe(false);
    expect(errorSpy).toHaveBeenCalledOnce();
    const msg = errorSpy.mock.calls[0][0] as string;
    expect(msg).toContain("/ready and /health routes NOT registered");
    expect(msg).toContain("FastMCP server not started");
  });

  it("logs at console.error when getApp() returns null", () => {
    const server = { getApp: () => null } as unknown as FastMCP;

    expect(register(server, "my-agent", () => null)).toBe(false);
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

    expect(register(server, "my-agent", () => null)).toBe(false);
    expect(errorSpy.mock.calls[0][0] as string).toContain(
      "hono internal: route conflict",
    );
  });
});

// ---------------------------------------------------------------------------
// RFC #1502: /ready is the mesh runtime, and only the mesh runtime
// ---------------------------------------------------------------------------

describe("/ready reports the mesh runtime state, not the verdict", () => {
  // THE assertion of this change. Before it, an unhealthy verdict answered
  // 503 here — which emptied the Service endpoints the mesh itself routes
  // through, so a consumer calling the withdrawn provider got a connection
  // error instead of failing over to another one.
  it.each([
    ["unhealthy", unhealthy],
    ["degraded", degraded],
  ])("stays 200 through a %s verdict while the runtime is up", (_name, verdict) => {
    const { server, routes } = stubServer();
    register(server, "provider-a", () => verdict, () => "up");

    const { body, status } = dispatch(routes, "/ready", "GET");
    expect(status).toBe(200);
    expect(body.ready).toBe(true);
    expect(body.reason).toBeUndefined();
  });

  it("stays 200 when the verdict source throws", () => {
    const { server, routes } = stubServer();
    register(
      server,
      "provider-a",
      () => {
        throw new Error("verdict source exploded");
      },
      () => "up",
    );

    expect(dispatch(routes, "/ready", "GET").status).toBe(200);
  });

  // Not merely "the verdict does not change the answer" — it is never read.
  // A handler that still consulted it and happened to map every verdict to
  // 200 would pass the cases above and reintroduce the coupling the moment
  // someone re-added a branch.
  it("never reads the verdict source at all", () => {
    const { server, routes } = stubServer();
    const source = vi.fn(() => unhealthy);
    register(server, "provider-a", source, () => "up");

    dispatch(routes, "/ready", "GET");
    expect(source).not.toHaveBeenCalled();
  });

  it("carries the runtime state and no verdict fields", () => {
    const { server, routes } = stubServer();
    register(server, "provider-a", () => unhealthy, () => "up");

    const { body } = dispatch(routes, "/ready", "GET");
    expect(body.runtime).toBe("up");
    expect(body.agent).toBe("provider-a");
    expect(body.mcp_wrappers).toBe(1);
    expect(body.status).toBeUndefined();
    expect(body.errors).toBeUndefined();
  });

  // The floor. `startupCheck` defaults to passing, so /startupz answers 200
  // before startAgent() returns; without this a pod would enter its Service
  // with no mesh runtime behind it.
  it("answers 503 while the runtime is still starting, healthy verdict or not", () => {
    const { server, routes } = stubServer();
    register(server, "provider-a", () => healthy, () => "starting");

    const { body, status } = dispatch(routes, "/ready", "GET");
    expect(status).toBe(503);
    expect(body.ready).toBe(false);
    expect(body.runtime).toBe("starting");
    expect(body.reason).toBe("Mesh runtime has not started yet");
  });

  it("answers 503 while shutting down", () => {
    const { server, routes } = stubServer();
    register(server, "provider-a", () => healthy, () => "shutting_down");

    const { body, status } = dispatch(routes, "/ready", "GET");
    expect(status).toBe(503);
    expect(body.runtime).toBe("shutting_down");
    expect(body.reason).toBe("Mesh runtime is shutting down");
  });

  // The state is re-read per request, not captured at registration: the
  // routes are mounted BEFORE startAgent() runs, so a handler that cached
  // the boot value would answer 503 forever.
  it("reads the runtime state per request rather than caching it", () => {
    const { server, routes } = stubServer();
    let state: RuntimeState = "starting";
    register(server, "provider-a", () => null, () => state);

    expect(dispatch(routes, "/ready", "GET").status).toBe(503);
    state = "up";
    expect(dispatch(routes, "/ready", "GET").status).toBe(200);
    state = "shutting_down";
    expect(dispatch(routes, "/ready", "GET").status).toBe(503);
  });

  // A probe that cannot answer is not evidence the runtime is up, and a 500
  // is not an answer a kubelet can act on.
  it("reports not ready when the runtime-state source throws", () => {
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    const { server, routes } = stubServer();
    register(server, "provider-a", () => null, () => {
      throw new Error("handle read exploded");
    });

    const { body, status } = dispatch(routes, "/ready", "GET");
    expect(status).toBe(503);
    expect(body.runtime).toBe("starting");
    expect(warnSpy).toHaveBeenCalled();
    warnSpy.mockRestore();
  });

  it("HEAD answers the same status as GET", () => {
    const { server, routes } = stubServer();
    register(server, "provider-a", () => unhealthy, () => "up");
    expect(dispatch(routes, "/ready", "HEAD").status).toBe(200);

    const { server: down, routes: downRoutes } = stubServer();
    register(down, "provider-a", () => healthy, () => "starting");
    expect(dispatch(downRoutes, "/ready", "HEAD").status).toBe(503);
  });
});

// ---------------------------------------------------------------------------
// /health is unchanged: it still carries the verdict, including in its code
// ---------------------------------------------------------------------------

describe("/health still reports the verdict", () => {
  it("an unhealthy verdict answers 503 carrying checks and errors", () => {
    const { server, routes } = stubServer();
    register(server, "provider-a", () => unhealthy);

    const { body, status } = dispatch(routes, "/health", "GET");
    expect(status).toBe(503);
    expect(body.status).toBe("unhealthy");
    expect(body.agent).toBe("provider-a");
    expect(body.checks).toEqual({ vendor_api_reachable: false });
    expect(body.errors).toEqual(["vendor returned 503"]);
    expect(typeof body.timestamp).toBe("string");
  });

  // Python's `200 if status == "healthy" else 503` and Java's `serving()`
  // both answer 503 for degraded on this endpoint too.
  it("a degraded verdict answers 503", () => {
    const { server, routes } = stubServer();
    register(server, "provider-a", () => degraded);

    expect(dispatch(routes, "/health", "GET").status).toBe(503);
    expect(dispatch(routes, "/health", "GET").body.status).toBe("degraded");
  });

  it("a healthy verdict answers 200", () => {
    const { server, routes } = stubServer();
    register(server, "provider-a", () => healthy);

    const health = dispatch(routes, "/health", "GET");
    expect(health.status).toBe(200);
    expect(health.body.status).toBe("healthy");
    expect(health.body.checks).toEqual({ vendor_api_reachable: true });
  });

  // THE compatibility guarantee. Making this endpoint mesh-aware must not
  // change what an agent WITHOUT a health check answers.
  it("no healthCheck configured (null verdict) answers 200", () => {
    const { server, routes } = stubServer();
    register(server, "plain-agent", () => null);

    const health = dispatch(routes, "/health", "GET");
    expect(health.status).toBe(200);
    expect(health.body.status).toBe("healthy");
    expect(health.body.checks).toEqual({});
    expect(health.body.errors).toEqual([]);
  });

  it("the verdict is re-read per request rather than cached", () => {
    const { server, routes } = stubServer();
    let current: HealthVerdict | null = null;
    register(server, "provider-a", () => current);

    expect(dispatch(routes, "/health", "GET").status).toBe(200);
    current = unhealthy;
    expect(dispatch(routes, "/health", "GET").status).toBe(503);
    current = healthy;
    expect(dispatch(routes, "/health", "GET").status).toBe(200);
  });

  // One snapshot per request. Reading the source twice could mix two
  // verdicts into one response — a 200 status line over an unhealthy body.
  it("takes one verdict snapshot per request", () => {
    const { server, routes } = stubServer();
    const source = vi.fn(() => unhealthy);
    register(server, "provider-a", source);

    dispatch(routes, "/health", "GET");
    expect(source).toHaveBeenCalledOnce();
  });

  // A diagnostic endpoint that 500s tells an operator less than one that
  // says "no verdict".
  it("a throwing verdict source answers as if no check were configured", () => {
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    const { server, routes } = stubServer();
    register(server, "provider-a", () => {
      throw new Error("verdict source exploded");
    });

    expect(dispatch(routes, "/health", "GET").status).toBe(200);
    expect(warnSpy).toHaveBeenCalled();
    warnSpy.mockRestore();
  });

  it("HEAD answers the same status as GET", () => {
    const { server, routes } = stubServer();
    register(server, "provider-a", () => unhealthy);
    expect(dispatch(routes, "/health", "HEAD").status).toBe(503);
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

  it("/ready carries ready, agent, runtime, mcp_wrappers and timestamp", () => {
    expect(Object.keys(buildReadyBody("a", "up")).sort()).toEqual([
      "agent",
      "mcp_wrappers",
      "ready",
      "runtime",
      "timestamp",
    ]);
  });

  it("readyStatusCodeFor is 200 only once the runtime is up", () => {
    expect(readyStatusCodeFor("up")).toBe(200);
    expect(readyStatusCodeFor("starting")).toBe(503);
    expect(readyStatusCodeFor("shutting_down")).toBe(503);
  });

  it("statusCodeFor is 200 only for healthy", () => {
    expect(statusCodeFor(null)).toBe(200);
    expect(statusCodeFor(healthy)).toBe(200);
    expect(statusCodeFor(degraded)).toBe(503);
    expect(statusCodeFor(unhealthy)).toBe(503);
  });
});

// ---------------------------------------------------------------------------
// The runtime-state source the agent actually passes
// ---------------------------------------------------------------------------

describe("MeshAgent.getRuntimeState", () => {
  function agentWithHandle(handle: unknown, shutdownRequested = false): MeshAgent {
    const server = {
      addTool: vi.fn(),
      start: vi.fn().mockResolvedValue(undefined),
      getApp: () => ({ on: vi.fn(), post: vi.fn() }),
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
    } as any;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const agent = new MeshAgent(server, { name: "state-test", httpPort: 0 }) as any;
    agent.handle = handle;
    agent.shutdownRequested = shutdownRequested;
    return agent as MeshAgent;
  }

  beforeEach(() => {
    // The constructor schedules _autoStart, whose rejection handler calls
    // process.exit(1) — existing convention in this file.
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    vi.spyOn(MeshAgent.prototype as any, "_autoStart").mockImplementation(
      async () => undefined,
    );
    vi.spyOn(console, "log").mockImplementation(() => {});
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("is 'starting' before startAgent() returns a handle", () => {
    expect(agentWithHandle(null).getRuntimeState()).toBe("starting");
  });

  it("is 'up' once a handle exists", () => {
    expect(agentWithHandle({}).getRuntimeState()).toBe("up");
  });

  // Checked BEFORE the handle: shutdown() nulls the handle only after the
  // napi teardown returns, and a pod being drained is not "starting".
  it("is 'shutting_down' from the moment shutdown is requested", () => {
    expect(agentWithHandle({}, true).getRuntimeState()).toBe("shutting_down");
  });
});

describe("_autoStart aborts when /ready and /health cannot be registered", () => {
  // Same fail-loud posture as /livez: an unregistered route here does NOT
  // fall back to something harmless — FastMCP's built-in answers a
  // hardcoded 200, so the pod would enter its Service before the mesh
  // runtime exists, which is the boot window the runtime floor closes.
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
