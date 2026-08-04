/**
 * Liveness endpoint tests (issue #1467).
 *
 * The agent chart points its liveness probe at `/livez` and its readiness
 * probe at `/ready`. A TypeScript agent that does not answer `/livez`
 * 404s the liveness probe and gets restarted by Kubernetes — a worse
 * failure than the one the split was introduced to fix. These tests pin
 * both TS HTTP surfaces:
 *
 *   - the FastMCP-hosted MeshAgent (route registered on FastMCP's Hono app)
 *   - MeshExpress (route registered on the user's Express app)
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import type { FastMCP } from "fastmcp";
import type { Server } from "http";
import express from "express";
import { registerLivezRoute } from "../livez-route.js";
import { MeshExpress } from "../express.js";
import { MeshAgent } from "../agent.js";

describe("registerLivezRoute — FastMCP/Hono surface", () => {
  let errorSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
  });
  afterEach(() => {
    errorSpy.mockRestore();
  });

  it("registers GET and HEAD /livez on the Hono app", () => {
    const onSpy = vi.fn();
    const stubServer = {
      getApp: () => ({ on: onSpy }),
    } as unknown as FastMCP;

    expect(registerLivezRoute(stubServer, "my-agent")).toBe(true);
    expect(onSpy).toHaveBeenCalledWith(
      ["GET", "HEAD"],
      "/livez",
      expect.any(Function),
    );
    expect(errorSpy).not.toHaveBeenCalled();
  });

  it("the handler reports alive:true with the agent name", () => {
    let handler: ((c: unknown) => unknown) | undefined;
    const stubServer = {
      getApp: () => ({
        on: (_methods: string[], _path: string, h: (c: unknown) => unknown) => {
          handler = h;
        },
      }),
    } as unknown as FastMCP;

    registerLivezRoute(stubServer, "my-agent");
    expect(handler).toBeDefined();

    const json = vi.fn((body: unknown) => body);
    const body = handler!({ json }) as Record<string, unknown>;
    expect(body.alive).toBe(true);
    expect(body.agent).toBe("my-agent");
    expect(typeof body.timestamp).toBe("string");
  });

  it("logs at console.error when getApp() throws", () => {
    const stubServer = {
      getApp: () => {
        throw new Error("FastMCP server not started");
      },
    } as unknown as FastMCP;

    expect(registerLivezRoute(stubServer, "my-agent")).toBe(false);
    expect(errorSpy).toHaveBeenCalledOnce();
    const msg = errorSpy.mock.calls[0][0] as string;
    expect(msg).toContain("/livez route NOT registered");
    expect(msg).toContain("FastMCP server not started");
  });

  it("logs at console.error when getApp() returns null", () => {
    const stubServer = { getApp: () => null } as unknown as FastMCP;

    expect(registerLivezRoute(stubServer, "my-agent")).toBe(false);
    expect(errorSpy).toHaveBeenCalledOnce();
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

    expect(registerLivezRoute(stubServer, "my-agent")).toBe(false);
    expect(errorSpy).toHaveBeenCalledOnce();
    expect(errorSpy.mock.calls[0][0] as string).toContain(
      "hono internal: route conflict",
    );
  });
});

describe("_autoStart aborts when /livez cannot be registered", () => {
  // There is no degraded mode: an agent that serves without /livez is
  // restarted by the kubelet every probe interval. `_autoStart` must
  // therefore honour the boolean and fail fast (same class as
  // #1387/#1389 in Python, made fail-fast in v3.3.2).
  //
  // The auto-scheduled `_autoStart` tick from the constructor is stubbed
  // out (existing convention) — its rejection handler calls
  // `process.exit(1)`, which would take the test runner down. The
  // ORIGINAL method is captured and invoked explicitly instead.
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

  function newAgent(getApp: () => unknown): MeshAgent {
    const server = {
      addTool: vi.fn(),
      start: vi.fn().mockResolvedValue(undefined),
      getApp,
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
    } as any;
    return new MeshAgent(server, { name: "livez-abort-test", httpPort: 0 });
  }

  it("rejects with an actionable message when the route cannot be mounted", async () => {
    const agent = newAgent(() => {
      throw new Error("FastMCP server not started");
    });

    await expect(originalAutoStart.call(agent)).rejects.toThrow(
      /\/livez liveness route failed to register/,
    );
  });

  it("names the agent and the restart consequence in the abort message", async () => {
    const agent = newAgent(() => null);

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const err = await originalAutoStart.call(agent).catch((e: any) => e);
    expect(err).toBeInstanceOf(Error);
    expect(err.message).toContain("livez-abort-test");
    expect(err.message).toContain("cannot start");
    expect(err.message).toMatch(/restart/i);
  });

  it("continues past the /livez step when registration succeeds", async () => {
    const on = vi.fn();
    const agent = newAgent(() => ({ on, post: vi.fn() }));
    // Everything after the /livez step reaches the registry, the napi
    // handle and process-wide signal handlers — out of scope here.
    stubPrototype("registerLlmTools");
    stubPrototype("registerJobsHelperTools");
    stubPrototype("startHeartbeat", async () => undefined);
    stubPrototype("startClaimDispatchers");
    stubPrototype("installSignalHandlers");

    await expect(originalAutoStart.call(agent)).resolves.toBeUndefined();
    expect(on).toHaveBeenCalledWith(
      ["GET", "HEAD"],
      "/livez",
      expect.any(Function),
    );
  });
});

describe("MeshExpress health endpoints", () => {
  let server: Server;
  let base: string;

  beforeEach(async () => {
    const app = express();
    // Constructing MeshExpress wires the health endpoints; start() is NOT
    // called (it would register with a registry and open a heartbeat).
    new MeshExpress(app, { name: "livez-test-api", httpPort: 0 });
    await new Promise<void>((resolve) => {
      server = app.listen(0, "127.0.0.1", () => resolve());
    });
    const addr = server.address();
    const port = typeof addr === "object" && addr ? addr.port : 0;
    base = `http://127.0.0.1:${port}`;
  });

  afterEach(async () => {
    await new Promise<void>((resolve) => server.close(() => resolve()));
  });

  it("GET /livez returns 200 with alive:true", async () => {
    const res = await fetch(`${base}/livez`);
    expect(res.status).toBe(200);
    const body = (await res.json()) as Record<string, unknown>;
    expect(body.alive).toBe(true);
    expect(body.agent).toBe("livez-test-api");
    expect(typeof body.timestamp).toBe("string");
  });

  it("HEAD /livez returns 200", async () => {
    const res = await fetch(`${base}/livez`, { method: "HEAD" });
    expect(res.status).toBe(200);
  });

  it("/livez stays 200 while /ready is 503 (unstarted agent)", async () => {
    // The #1467 invariant: the condition that takes the service out of
    // rotation must NOT also restart it.
    expect((await fetch(`${base}/ready`)).status).toBe(503);
    expect((await fetch(`${base}/livez`)).status).toBe(200);
  });

  it("/health is unchanged", async () => {
    const res = await fetch(`${base}/health`);
    expect(res.status).toBe(200);
    const body = (await res.json()) as Record<string, unknown>;
    expect(body.status).toBe("healthy");
  });
});
