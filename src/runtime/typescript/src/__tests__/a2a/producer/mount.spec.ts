/**
 * End-to-end tests for `mount.ts` (issue #933).
 *
 * Coverage:
 * - POST {path} with sync handler -> Task envelope (state=completed)
 * - POST {path} with JobProxy return -> state=working
 * - GET {path}/.well-known/agent.json -> agent card
 * - GET {path}/.well-known/agent.json/ (trailing slash, spec §3.1) -> card
 * - POST {path} malformed JSON -> HTTP 400 + -32700
 * - POST {path} missing method field -> -32600 (NOT -32601 'null')
 * - POST {path} unknown method -> -32601 with actual method name
 * - POST {path} tasks/sendSubscribe -> SSE (text/event-stream)
 * - Auth gate: missing Authorization on bearer-mount -> 401 + -32001
 * - Multi-mount: routes don't collide
 *
 * Uses a real Express app behind Node http server (mirrors existing
 * `__tests__/a2a/a2a-job.spec.ts` server pattern). No supertest dep.
 *
 * Mocks `api-runtime.ts` so `getApiRuntime().scheduleStart()` doesn't
 * try to bind the real napi runtime — same pattern as existing
 * `mesh-job-submitter.spec.ts`.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import * as http from "node:http";
import type { AddressInfo } from "node:net";
import express from "express";

// Mock api-runtime so mount() doesn't try to spin up the real Rust core
// when scheduleStart() is invoked.
vi.mock("../../../api-runtime.js", () => ({
  getApiRuntime: () => ({
    scheduleStart: vi.fn(),
  }),
}));

// Mock @mcpmesh/core so JobProxy class detection can short-circuit on
// the duck-typed fallback path (we never actually construct a real
// JobProxy here).
vi.mock("@mcpmesh/core", async () => {
  const actual = await vi.importActual<Record<string, unknown>>("@mcpmesh/core");
  return {
    ...actual,
  };
});

import { mount, __getA2ATaskStore } from "../../../a2a/producer/mount.js";
import { A2AProducerRegistry } from "../../../a2a/producer/registry.js";
import { RouteRegistry } from "../../../route.js";

// ────────────────────────────────────────────────────────────────────────
// HTTP test harness
// ────────────────────────────────────────────────────────────────────────

interface TestServer {
  url: string;
  close: () => Promise<void>;
}

async function startServer(app: express.Application): Promise<TestServer> {
  return new Promise((resolve) => {
    const server = http.createServer(app);
    server.listen(0, "127.0.0.1", () => {
      const port = (server.address() as AddressInfo).port;
      resolve({
        url: `http://127.0.0.1:${port}`,
        close: () =>
          new Promise<void>((rs, rj) =>
            server.close((err) => (err ? rj(err) : rs())),
          ),
      });
    });
  });
}

interface JsonResponse {
  status: number;
  contentType: string | undefined;
  body: string;
  json: () => Record<string, unknown>;
}

async function postJson(
  url: string,
  body: unknown,
  headers: Record<string, string> = {},
): Promise<JsonResponse> {
  return doRequest(url, "POST", JSON.stringify(body), {
    "Content-Type": "application/json",
    ...headers,
  });
}

async function get(url: string): Promise<JsonResponse> {
  return doRequest(url, "GET", undefined, {});
}

function doRequest(
  url: string,
  method: string,
  body: string | undefined,
  headers: Record<string, string>,
): Promise<JsonResponse> {
  const u = new URL(url);
  return new Promise((resolve, reject) => {
    const req = http.request(
      {
        host: u.hostname,
        port: u.port,
        path: u.pathname + u.search,
        method,
        headers,
      },
      (res) => {
        const chunks: Buffer[] = [];
        res.on("data", (c) => chunks.push(c));
        res.on("end", () => {
          const text = Buffer.concat(chunks).toString("utf8");
          resolve({
            status: res.statusCode ?? 0,
            contentType: res.headers["content-type"],
            body: text,
            json: () => JSON.parse(text) as Record<string, unknown>,
          });
        });
      },
    );
    req.on("error", reject);
    if (body !== undefined) req.write(body);
    req.end();
  });
}

/** Send POST and read response as raw stream (for SSE checks). */
function postRaw(
  url: string,
  body: unknown,
  headers: Record<string, string> = {},
): Promise<{ status: number; contentType: string | undefined; body: string }> {
  return doRequest(url, "POST", JSON.stringify(body), {
    "Content-Type": "application/json",
    ...headers,
  });
}

/**
 * Send POST with a hand-crafted body string (no JSON.stringify) — used to
 * verify body-parser parse-error handling against malformed bodies.
 */
function postRawString(
  url: string,
  rawBody: string,
  headers: Record<string, string> = {},
): Promise<JsonResponse> {
  return doRequest(url, "POST", rawBody, {
    "Content-Type": "application/json",
    ...headers,
  });
}

// ────────────────────────────────────────────────────────────────────────
// Tests
// ────────────────────────────────────────────────────────────────────────

describe("mesh.a2a.mount: end-to-end via Express + node http", () => {
  let server: TestServer | null = null;

  beforeEach(() => {
    A2AProducerRegistry.reset();
    RouteRegistry.reset();
    __getA2ATaskStore().clear();
  });

  afterEach(async () => {
    if (server) {
      await server.close();
      server = null;
    }
  });

  /** Spec §4.3 sync path: handler return -> state=completed Task envelope. */
  it("POST {path} with sync handler -> state=completed envelope (spec §4.3)", async () => {
    const app = express();
    app.use(express.json());
    mount(
      app,
      { path: "/agents/sync", skillId: "sync-skill" },
      async (_deps, payload) => ({ echo: payload }),
    );
    server = await startServer(app);

    const res = await postJson(`${server.url}/agents/sync`, {
      jsonrpc: "2.0",
      id: 1,
      method: "tasks/send",
      params: { id: "t1", message: { role: "user", parts: [] } },
    });
    expect(res.status).toBe(200);
    expect(res.contentType).toMatch(/application\/json/);
    const json = res.json();
    expect(json.id).toBe(1);
    const result = json.result as Record<string, unknown>;
    const status = result.status as Record<string, unknown>;
    expect(status.state).toBe("completed");
    const artifacts = result.artifacts as Array<Record<string, unknown>>;
    const parts = artifacts[0].parts as Array<Record<string, unknown>>;
    expect(parts[0].type).toBe("text");
  });

  /** Spec §4.3 long-running: JobProxy return -> state=working. */
  it("POST {path} with JobProxy return -> state=working", async () => {
    const fakeProxy = {
      jobId: "job-mount",
      status: async () => ({ status: "running" }),
      wait: async () => null,
      cancel: async () => undefined,
    };
    const app = express();
    app.use(express.json());
    mount(
      app,
      { path: "/agents/lr", skillId: "lr-skill" },
      async () => fakeProxy as never,
    );
    server = await startServer(app);

    const res = await postJson(`${server.url}/agents/lr`, {
      jsonrpc: "2.0",
      id: 2,
      method: "tasks/send",
      params: { id: "t-lr" },
    });
    const result = res.json().result as Record<string, unknown>;
    expect((result.status as Record<string, unknown>).state).toBe("working");
  });

  /** Spec §3.2: agent card returned on GET {path}/.well-known/agent.json. */
  it("GET {path}/.well-known/agent.json -> valid card", async () => {
    const app = express();
    app.use(express.json());
    mount(
      app,
      {
        path: "/agents/card",
        skillId: "card-skill",
        skillName: "Card Skill",
        description: "Skill that has a card",
        tags: ["x"],
      },
      async () => "ok",
    );
    server = await startServer(app);

    const res = await get(`${server.url}/agents/card/.well-known/agent.json`);
    expect(res.status).toBe(200);
    expect(res.contentType).toMatch(/application\/json/);
    const card = res.json();
    expect(card.name).toBeTypeOf("string");
    expect((card.capabilities as Record<string, unknown>).streaming).toBe(true);
    const skills = card.skills as Array<Record<string, unknown>>;
    expect(skills).toHaveLength(1);
    expect(skills[0].id).toBe("card-skill");
    expect(skills[0].tags).toEqual(["x"]);
  });

  /** Spec §3.1: trailing slash also returns the card. */
  it("GET {path}/.well-known/agent.json/ (trailing slash) -> card", async () => {
    const app = express();
    app.use(express.json());
    mount(
      app,
      { path: "/agents/ts", skillId: "ts" },
      async () => "ok",
    );
    server = await startServer(app);

    const res = await get(`${server.url}/agents/ts/.well-known/agent.json/`);
    expect(res.status).toBe(200);
    const card = res.json();
    expect((card.skills as Array<Record<string, unknown>>)[0].id).toBe("ts");
  });

  /**
   * Spec §4.1: empty body that express.json() leaves as `null` parsed →
   * HTTP 400 + JSON-RPC -32700.
   *
   * Note: when express.json() ITSELF fails to parse (malformed JSON), it
   * emits its own HTML 400 — the dispatcher's -32700 path is only
   * reachable when express.json() succeeded but produced null/undefined.
   * We bypass express.json() here to drive the dispatcher directly with
   * a hand-built req.body = null path: use a no-op body parser so the
   * dispatcher sees the empty body.
   */
  it("POST {path} empty body -> HTTP 400 + -32700 JSON-RPC error", async () => {
    const app = express();
    // Custom body parser that leaves req.body as `undefined` for our
    // dispatcher to handle — exercises the spec §4.1 -32700 path.
    app.use((req, _res, next) => {
      (req as unknown as { body: unknown }).body = undefined;
      next();
    });
    mount(
      app,
      { path: "/agents/bad", skillId: "bad" },
      async () => "ok",
    );
    server = await startServer(app);

    const res = await postJson(`${server.url}/agents/bad`, {});
    expect(res.status).toBe(400);
    const body = res.json();
    expect((body.error as Record<string, unknown>).code).toBe(-32700);
  });

  /**
   * Spec §4.1: malformed JSON body rejected by `express.json()` -> producer
   * still returns a structured `-32700 Parse error` JSON-RPC envelope (HTTP
   * 400 + `application/json`), not Express's default HTML 400 page.
   *
   * Verifies the path-scoped body-parser error handler installed by
   * `mount()` — without it `express.json()` would short-circuit with an
   * HTML response and A2A clients would have no way to recover.
   */
  it("POST {path} malformed JSON body -> 400 + -32700 JSON-RPC envelope", async () => {
    const app = express();
    app.use(express.json());
    mount(
      app,
      { path: "/agents/malformed", skillId: "malformed" },
      async () => "ok",
    );
    server = await startServer(app);

    const res = await postRawString(
      `${server.url}/agents/malformed`,
      "not json at all",
    );
    expect(res.status).toBe(400);
    expect(res.contentType).toMatch(/application\/json/);
    // Parse structurally — don't string-grep the body shape.
    const body = res.json();
    expect(body.jsonrpc).toBe("2.0");
    expect(body.id).toBeNull();
    const err = body.error as Record<string, unknown>;
    expect(err.code).toBe(-32700);
    expect(typeof err.message).toBe("string");
  });

  /**
   * Regression guard for the parse-error handler: valid JSON bodies on the
   * producer route still dispatch normally — the error handler must only
   * fire on body-parser failures, never on the happy path.
   */
  it("POST {path} valid JSON body still dispatches after parse-error handler is wired", async () => {
    const app = express();
    app.use(express.json());
    mount(
      app,
      { path: "/agents/post-fix", skillId: "post-fix" },
      async () => "happy-path",
    );
    server = await startServer(app);

    const res = await postJson(`${server.url}/agents/post-fix`, {
      jsonrpc: "2.0",
      id: 7,
      method: "tasks/send",
      params: { id: "t-pf" },
    });
    expect(res.status).toBe(200);
    const result = res.json().result as Record<string, unknown>;
    expect((result.status as Record<string, unknown>).state).toBe("completed");
  });

  /**
   * Path-scope guard: the body-parser error handler must NOT intercept
   * parse errors on unrelated user routes mounted on the same Express app.
   * Hosts that wire their own routes outside the producer surface get
   * Express's default behavior (HTML 400) untouched.
   */
  it("unrelated route on same app with malformed JSON -> not intercepted by producer's parse-error handler", async () => {
    const app = express();
    app.use(express.json());
    // Unrelated user route — registered before the mount so a global
    // handler would catch its errors. Mount registers a path-scoped one.
    app.post("/user/echo", (req, res) => {
      res.status(200).json({ ok: true, echo: req.body });
    });
    mount(
      app,
      { path: "/agents/scoped", skillId: "scoped" },
      async () => "ok",
    );
    server = await startServer(app);

    const res = await postRawString(`${server.url}/user/echo`, "not json at all");
    // Default Express behavior is HTML 400 ("SyntaxError: Unexpected token …"
    // wrapped in a stack-trace page). The key assertion is that we do NOT
    // see the producer's JSON-RPC -32700 envelope leak onto the user route.
    expect(res.status).toBe(400);
    const contentType = res.contentType ?? "";
    if (contentType.includes("application/json")) {
      // If a future Express version starts emitting JSON for body-parser
      // errors, make sure it's NOT our -32700 envelope (which would mean
      // the path scope leaked).
      try {
        const body = JSON.parse(res.body) as Record<string, unknown>;
        const err = body.error as Record<string, unknown> | undefined;
        expect(err?.code).not.toBe(-32700);
      } catch {
        // Body wasn't JSON — fine, the scope didn't leak.
      }
    }
  });

  /** Spec §4.1 + #934: missing method field -> -32600 (NOT -32601 'null'). */
  it("POST {path} missing method field -> -32600 Invalid Request (#934)", async () => {
    const app = express();
    app.use(express.json());
    mount(app, { path: "/agents/mm", skillId: "mm" }, async () => "ok");
    server = await startServer(app);

    const res = await postJson(`${server.url}/agents/mm`, {
      jsonrpc: "2.0",
      id: 1,
    });
    const body = res.json();
    const err = body.error as Record<string, unknown>;
    expect(err.code).toBe(-32600);
    expect((err.message as string).toLowerCase()).not.toContain("'null'");
  });

  /** Spec §4.1: unknown method -> -32601 with actual method name. */
  it("POST {path} unknown method -> -32601 with method name (#934 guard)", async () => {
    const app = express();
    app.use(express.json());
    mount(app, { path: "/agents/um", skillId: "um" }, async () => "ok");
    server = await startServer(app);

    const res = await postJson(`${server.url}/agents/um`, {
      jsonrpc: "2.0",
      id: 1,
      method: "tasks/madeUp",
      params: {},
    });
    const body = res.json();
    const err = body.error as Record<string, unknown>;
    expect(err.code).toBe(-32601);
    expect(err.message).toContain("tasks/madeUp");
    expect((err.message as string).toLowerCase()).not.toContain("'null'");
  });

  /** Spec §4.6: tasks/sendSubscribe returns text/event-stream. */
  it("POST {path} tasks/sendSubscribe -> Content-Type: text/event-stream", async () => {
    const app = express();
    app.use(express.json());
    mount(
      app,
      { path: "/agents/sse", skillId: "sse" },
      async () => "sync-ok",
    );
    server = await startServer(app);

    const res = await postRaw(`${server.url}/agents/sse`, {
      jsonrpc: "2.0",
      id: 1,
      method: "tasks/sendSubscribe",
      params: { id: "t-sse" },
    });
    expect(res.contentType).toMatch(/text\/event-stream/);
    // Body has at least one `data:` frame.
    expect(res.body).toMatch(/^data: /m);
  });

  /** Spec §6.2: bearer auth gate rejects missing header with -32001. */
  it("POST {path} without Authorization on bearer-mount -> 401 + -32001", async () => {
    const app = express();
    app.use(express.json());
    mount(
      app,
      { path: "/agents/auth", skillId: "auth", auth: "bearer" },
      async () => "ok",
    );
    server = await startServer(app);

    const res = await postJson(`${server.url}/agents/auth`, {
      jsonrpc: "2.0",
      id: 1,
      method: "tasks/send",
      params: { id: "t-auth" },
    });
    expect(res.status).toBe(401);
    const err = res.json().error as Record<string, unknown>;
    expect(err.code).toBe(-32001);
  });

  /** Spec §6.2 + conformance checklist: card endpoint is always public. */
  it("GET card endpoint is public even on bearer-mount", async () => {
    const app = express();
    app.use(express.json());
    mount(
      app,
      { path: "/agents/auth2", skillId: "auth2", auth: "bearer" },
      async () => "ok",
    );
    server = await startServer(app);

    const res = await get(`${server.url}/agents/auth2/.well-known/agent.json`);
    expect(res.status).toBe(200);
    const card = res.json();
    const auth = card.authentication as Record<string, unknown>;
    expect(auth.schemes).toEqual(["bearer"]);
  });

  /** Spec §4: multiple mounts on the same app dispatch independently. */
  it("multiple mounts on same Express app -> routes do not collide", async () => {
    const app = express();
    app.use(express.json());
    mount(app, { path: "/m1", skillId: "m1" }, async () => "from-m1");
    mount(app, { path: "/m2", skillId: "m2" }, async () => "from-m2");
    server = await startServer(app);

    const r1 = await postJson(`${server.url}/m1`, {
      jsonrpc: "2.0",
      id: 1,
      method: "tasks/send",
      params: { id: "tm1" },
    });
    const r2 = await postJson(`${server.url}/m2`, {
      jsonrpc: "2.0",
      id: 2,
      method: "tasks/send",
      params: { id: "tm2" },
    });

    const a1 = (r1.json().result as Record<string, unknown>).artifacts as Array<
      Record<string, unknown>
    >;
    const a2 = (r2.json().result as Record<string, unknown>).artifacts as Array<
      Record<string, unknown>
    >;
    const p1 = a1[0].parts as Array<Record<string, unknown>>;
    const p2 = a2[0].parts as Array<Record<string, unknown>>;
    expect(p1[0].text).toBe("from-m1");
    expect(p2[0].text).toBe("from-m2");
  });
});
