/**
 * `startupCheck` and `/startupz` — RFC #1502, step 1.
 *
 * `healthCheck` answers "can I serve right now" and a failing one pauses the
 * heartbeat until it recovers. `startupCheck` answers "is this agent
 * configured such that it can ever serve", and the chart's `startupProbe` will
 * poll `/startupz` for it, so a check that never passes means the pod never
 * becomes ready and lands in CrashLoopBackOff where it is visible.
 *
 * Both TS HTTP surfaces are pinned, as `livez-route.spec.ts` does:
 *
 *   - the FastMCP-hosted MeshAgent (route on FastMCP's Hono app)
 *   - MeshExpress (route on the user's Express app)
 *
 * The verdict rules are the OPPOSITE of `healthCheck`'s and are asserted as
 * such: a throw fails (it does not degrade), and anything short of a clean
 * pass fails.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import type { FastMCP } from "fastmcp";
import type { Server } from "http";
import express from "express";
import {
  runStartupCheck,
  buildStartupBody,
  startupStatusCodeFor,
  type MeshStartupCheck,
} from "../startup-check.js";
import { registerStartupzRoute } from "../startupz-route.js";
import { MeshExpress } from "../express.js";
import { MeshAgent } from "../agent.js";

describe("runStartupCheck — the verdict rules", () => {
  let warnSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
  });
  afterEach(() => {
    warnSpy.mockRestore();
  });

  it("an absent check passes — the default is true", async () => {
    const verdict = await runStartupCheck(undefined, "a");
    expect(verdict.passed).toBe(true);
    expect(verdict.errors).toEqual([]);
  });

  it("true passes", async () => {
    expect((await runStartupCheck(() => true, "a")).passed).toBe(true);
  });

  it("an async true passes", async () => {
    const check: MeshStartupCheck = async () => true;
    expect((await runStartupCheck(check, "a")).passed).toBe(true);
  });

  it("false fails", async () => {
    const verdict = await runStartupCheck(() => false, "a");
    expect(verdict.passed).toBe(false);
    expect(verdict.errors).toEqual(["Startup check returned false"]);
    expect(verdict.checks).toEqual({ startup_check: false });
  });

  it("a throw FAILS rather than degrading — the opposite of healthCheck", async () => {
    // A throwing `healthCheck` is `degraded` and keeps the heartbeat alive: a
    // buggy probe must not withdraw a working provider. Here the question is
    // whether a possibly-misconfigured agent may come up at all, so an
    // indeterminate boot-time answer fails.
    const verdict = await runStartupCheck(() => {
      throw new Error("ANTHROPIC_API_KEY is not set");
    }, "a");
    expect(verdict.passed).toBe(false);
    expect(verdict.checks).toEqual({ startup_check_execution: false });
    expect(verdict.errors[0]).toContain("ANTHROPIC_API_KEY is not set");
  });

  it("an async rejection also fails", async () => {
    const check: MeshStartupCheck = async () => {
      throw new Error("vendor returned 401");
    };
    const verdict = await runStartupCheck(check, "a");
    expect(verdict.passed).toBe(false);
    expect(verdict.errors[0]).toContain("vendor returned 401");
  });

  it("a non-Error throw is still described", async () => {
    const verdict = await runStartupCheck(() => {
      throw "just a string";
    }, "a");
    expect(verdict.passed).toBe(false);
    expect(verdict.errors[0]).toContain("just a string");
  });

  it("a {status: healthy} object passes", async () => {
    expect(
      (await runStartupCheck(() => ({ status: "healthy" }), "a")).passed,
    ).toBe(true);
  });

  it("an object with no status passes (healthy is the default)", async () => {
    expect(
      (await runStartupCheck(() => ({ checks: { key: true } }), "a")).passed,
    ).toBe(true);
  });

  it("an unhealthy object fails and carries its checks and errors", async () => {
    const verdict = await runStartupCheck(
      () => ({
        status: "unhealthy",
        checks: { api_key: false },
        errors: ["no key"],
      }),
      "a",
    );
    expect(verdict.passed).toBe(false);
    expect(verdict.checks).toEqual({ api_key: false });
    expect(verdict.errors).toEqual(["no key"]);
  });

  it("degraded fails — there is no partial credit for 'am I configured'", async () => {
    const verdict = await runStartupCheck(() => ({ status: "degraded" }), "a");
    expect(verdict.passed).toBe(false);
    expect(verdict.errors).toEqual(["Startup check reported 'degraded'"]);
  });

  it("an unrecognized return fails", async () => {
    const verdict = await runStartupCheck(
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      (() => "yes") as any,
      "a",
    );
    expect(verdict.passed).toBe(false);
    expect(verdict.checks).toEqual({ startup_check_return_type: false });
    expect(warnSpy).toHaveBeenCalled();
  });

  it("undefined and null fail", async () => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    expect((await runStartupCheck((() => undefined) as any, "a")).passed).toBe(
      false,
    );
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    expect((await runStartupCheck((() => null) as any, "a")).passed).toBe(false);
  });

  it("runs on every call — there is no cache", async () => {
    const check = vi.fn(() => true);
    await runStartupCheck(check, "a");
    await runStartupCheck(check, "a");
    await runStartupCheck(check, "a");
    expect(check).toHaveBeenCalledTimes(3);
  });
});

describe("the /startupz body", () => {
  it("mirrors /ready's shape on success", () => {
    const body = buildStartupBody("agent-x", {
      passed: true,
      checks: {},
      errors: [],
    });
    expect(body.started).toBe(true);
    expect(body.agent).toBe("agent-x");
    expect(typeof body.timestamp).toBe("string");
    expect(body.reason).toBeUndefined();
  });

  it("carries a reason and errors on failure", () => {
    const verdict = { passed: false, checks: {}, errors: ["no key"] };
    const body = buildStartupBody("agent-x", verdict);
    expect(body.started).toBe(false);
    expect(body.reason).toBe("Startup check failed");
    expect(body.errors).toEqual(["no key"]);
    expect(startupStatusCodeFor(verdict)).toBe(503);
  });

  it("200 for a passing verdict", () => {
    expect(
      startupStatusCodeFor({ passed: true, checks: {}, errors: [] }),
    ).toBe(200);
  });
});

describe("registerStartupzRoute — FastMCP/Hono surface", () => {
  let errorSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    vi.spyOn(console, "warn").mockImplementation(() => {});
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  function capture(check: MeshStartupCheck | undefined) {
    let handler:
      | ((c: unknown) => unknown | Promise<unknown>)
      | undefined;
    const stubServer = {
      getApp: () => ({
        on: (
          _methods: string[],
          _path: string,
          h: (c: unknown) => unknown | Promise<unknown>,
        ) => {
          handler = h;
        },
      }),
    } as unknown as FastMCP;
    expect(registerStartupzRoute(stubServer, "my-agent", () => check)).toBe(
      true,
    );
    expect(handler).toBeDefined();
    return handler!;
  }

  async function call(handler: (c: unknown) => unknown | Promise<unknown>) {
    const seen: { body?: Record<string, unknown>; status?: number } = {};
    const json = vi.fn((body: unknown, status?: number) => {
      seen.body = body as Record<string, unknown>;
      seen.status = status;
      return body;
    });
    await handler({ json });
    return seen;
  }

  it("registers GET and HEAD /startupz on the Hono app", () => {
    const onSpy = vi.fn();
    const stubServer = {
      getApp: () => ({ on: onSpy }),
    } as unknown as FastMCP;

    expect(registerStartupzRoute(stubServer, "my-agent", () => undefined)).toBe(
      true,
    );
    expect(onSpy).toHaveBeenCalledWith(
      ["GET", "HEAD"],
      "/startupz",
      expect.any(Function),
    );
    expect(errorSpy).not.toHaveBeenCalled();
  });

  it("no check declared → 200", async () => {
    const seen = await call(capture(undefined));
    expect(seen.status).toBe(200);
    expect(seen.body!.started).toBe(true);
    expect(seen.body!.agent).toBe("my-agent");
  });

  it("a passing check → 200", async () => {
    const seen = await call(capture(() => true));
    expect(seen.status).toBe(200);
  });

  it("a failing check → 503", async () => {
    const seen = await call(capture(() => false));
    expect(seen.status).toBe(503);
    expect(seen.body!.started).toBe(false);
    expect(seen.body!.reason).toBe("Startup check failed");
  });

  it("a throwing check → 503, and the handler does not reject", async () => {
    const seen = await call(
      capture(() => {
        throw new Error("no key");
      }),
    );
    expect(seen.status).toBe(503);
    expect((seen.body!.errors as string[])[0]).toContain("no key");
  });

  it("a throwing check SOURCE → 503 rather than an unhandled rejection", async () => {
    let handler: ((c: unknown) => unknown | Promise<unknown>) | undefined;
    const stubServer = {
      getApp: () => ({
        on: (
          _m: string[],
          _p: string,
          h: (c: unknown) => unknown | Promise<unknown>,
        ) => {
          handler = h;
        },
      }),
    } as unknown as FastMCP;
    registerStartupzRoute(stubServer, "my-agent", () => {
      throw new Error("config not resolved");
    });
    const seen = await call(handler!);
    expect(seen.status).toBe(503);
  });

  it("logs at console.error when getApp() throws", () => {
    const stubServer = {
      getApp: () => {
        throw new Error("FastMCP server not started");
      },
    } as unknown as FastMCP;

    expect(registerStartupzRoute(stubServer, "my-agent", () => undefined)).toBe(
      false,
    );
    expect(errorSpy.mock.calls[0][0] as string).toContain(
      "/startupz route NOT registered",
    );
  });

  it("logs at console.error when getApp() returns null", () => {
    const stubServer = { getApp: () => null } as unknown as FastMCP;
    expect(registerStartupzRoute(stubServer, "my-agent", () => undefined)).toBe(
      false,
    );
    expect(errorSpy.mock.calls[0][0] as string).toContain("returned null");
  });

  it("logs at console.error when app.on() raises", () => {
    const stubServer = {
      getApp: () => ({
        on: () => {
          throw new Error("hono internal: route conflict");
        },
      }),
    } as unknown as FastMCP;
    expect(registerStartupzRoute(stubServer, "my-agent", () => undefined)).toBe(
      false,
    );
    expect(errorSpy.mock.calls[0][0] as string).toContain(
      "hono internal: route conflict",
    );
  });
});

describe("_autoStart mounts /startupz and aborts when it cannot", () => {
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

  it("mounts GET|HEAD /startupz during startup", async () => {
    const on = vi.fn();
    const server = {
      addTool: vi.fn(),
      start: vi.fn().mockResolvedValue(undefined),
      getApp: () => ({ on, post: vi.fn() }),
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
    } as any;
    const agent = new MeshAgent(server, {
      name: "startupz-agent",
      httpPort: 0,
      startupCheck: () => true,
    });
    stubPrototype("registerLlmTools");
    stubPrototype("registerJobsHelperTools");
    stubPrototype("startHeartbeat", async () => undefined);
    stubPrototype("startClaimDispatchers");
    stubPrototype("installSignalHandlers");

    await expect(originalAutoStart.call(agent)).resolves.toBeUndefined();
    expect(on).toHaveBeenCalledWith(
      ["GET", "HEAD"],
      "/startupz",
      expect.any(Function),
    );
  });

  it("a failing startupCheck does NOT stop the agent starting", async () => {
    // The probe reports it; the process keeps running so the kubelet can see
    // the 503 and the operator can exec in. Crash-on-boot would erase both.
    const on = vi.fn();
    const server = {
      addTool: vi.fn(),
      start: vi.fn().mockResolvedValue(undefined),
      getApp: () => ({ on, post: vi.fn() }),
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
    } as any;
    const agent = new MeshAgent(server, {
      name: "startupz-failing-agent",
      httpPort: 0,
      startupCheck: () => false,
    });
    stubPrototype("registerLlmTools");
    stubPrototype("registerJobsHelperTools");
    stubPrototype("startHeartbeat", async () => undefined);
    stubPrototype("startClaimDispatchers");
    stubPrototype("installSignalHandlers");

    await expect(originalAutoStart.call(agent)).resolves.toBeUndefined();
  });
});

describe("MeshExpress /startupz", () => {
  let server: Server;
  let base: string;

  async function listen(startupCheck?: MeshStartupCheck) {
    const app = express();
    // Constructing MeshExpress wires the endpoints; start() is NOT called
    // (it would register with a registry and open a heartbeat).
    new MeshExpress(app, {
      name: "startupz-test-api",
      httpPort: 0,
      startupCheck,
    });
    await new Promise<void>((resolve) => {
      server = app.listen(0, "127.0.0.1", () => resolve());
    });
    const addr = server.address();
    const port = typeof addr === "object" && addr ? addr.port : 0;
    base = `http://127.0.0.1:${port}`;
  }

  beforeEach(() => {
    vi.spyOn(console, "warn").mockImplementation(() => {});
  });

  afterEach(async () => {
    vi.restoreAllMocks();
    if (server) {
      await new Promise<void>((resolve) => server.close(() => resolve()));
    }
  });

  it("no check declared → 200 with started:true", async () => {
    await listen(undefined);
    const res = await fetch(`${base}/startupz`);
    expect(res.status).toBe(200);
    const body = (await res.json()) as Record<string, unknown>;
    expect(body.started).toBe(true);
    expect(body.agent).toBe("startupz-test-api");
    expect(typeof body.serviceId).toBe("string");
    expect(typeof body.timestamp).toBe("string");
  });

  it("a passing check → 200", async () => {
    await listen(() => true);
    expect((await fetch(`${base}/startupz`)).status).toBe(200);
  });

  it("a failing check → 503 with a reason", async () => {
    await listen(() => false);
    const res = await fetch(`${base}/startupz`);
    expect(res.status).toBe(503);
    const body = (await res.json()) as Record<string, unknown>;
    expect(body.started).toBe(false);
    expect(body.reason).toBe("Startup check failed");
  });

  it("a throwing check → 503, not 500", async () => {
    await listen(() => {
      throw new Error("MODEL_ENDPOINT is not set");
    });
    const res = await fetch(`${base}/startupz`);
    expect(res.status).toBe(503);
    const body = (await res.json()) as Record<string, unknown>;
    expect((body.errors as string[])[0]).toContain("MODEL_ENDPOINT is not set");
  });

  it("HEAD matches GET (Express routes HEAD to the GET handler)", async () => {
    await listen(() => false);
    const head = await fetch(`${base}/startupz`, { method: "HEAD" });
    const get = await fetch(`${base}/startupz`);
    expect(head.status).toBe(503);
    expect(get.status).toBe(head.status);
  });

  it("startupCheck is NOT ignored on a gateway, unlike healthCheck", async () => {
    // #1476 warns that `healthCheck` is ignored on MeshExpress — withdrawing a
    // fan-out point takes the application down. `startupCheck` withdraws
    // nothing; it only stops a misconfigured gateway from coming up.
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    await listen(() => false);
    expect((await fetch(`${base}/startupz`)).status).toBe(503);
    expect(
      warn.mock.calls.some((c) => String(c[0]).includes("startupCheck is IGNORED")),
    ).toBe(false);
  });

  it("/livez stays unconditional under a failing startup check", async () => {
    await listen(() => false);
    expect((await fetch(`${base}/livez`)).status).toBe(200);
  });

  it("/ready is unchanged by a failing startup check (step 1 is additive)", async () => {
    await listen(() => false);
    // `handle` is null (start() was not called), so /ready is 503 for the
    // reason it always was — the runtime, not the startup check.
    const res = await fetch(`${base}/ready`);
    const body = (await res.json()) as Record<string, unknown>;
    expect(body.ready).toBe(false);
    expect(body.reason).toBeUndefined();
  });
});
