/**
 * Tests for A2AClient (issue #917).
 *
 * Each test spins up a tiny http.Server bound to 127.0.0.1:<random
 * port> so we exercise the full undici fetch path including JSON-RPC
 * envelope build, polling backoff, error/timeout surfacing, and bearer
 * header injection.
 */
import { describe, it, expect, beforeEach, afterEach } from "vitest";
import * as http from "node:http";
import { AddressInfo } from "node:net";
import {
  A2AClient,
  isCanceledState,
  isTerminalState,
} from "../../a2a/a2a-client.js";
import {
  A2AError,
  A2ATimeoutError,
} from "../../a2a/errors.js";
import { A2ABearer } from "../../a2a/a2a-bearer.js";

interface TestServer {
  port: number;
  url: string;
  /** All received envelopes — assert against this in tests. */
  envelopes: Array<{ method: string; params: unknown; auth?: string }>;
  /** Reset between tests so no cross-test leakage. */
  reset: () => void;
  close: () => Promise<void>;
}

function startServer(
  handler: (req: {
    method: string;
    params: Record<string, unknown>;
    rpcId: number;
    headers: http.IncomingHttpHeaders;
  }) => unknown,
): Promise<TestServer> {
  return new Promise((resolve) => {
    const envelopes: TestServer["envelopes"] = [];
    const server = http.createServer((req, res) => {
      let body = "";
      req.on("data", (chunk) => {
        body += chunk;
      });
      req.on("end", () => {
        let envelope: Record<string, unknown>;
        try {
          envelope = JSON.parse(body);
        } catch {
          res.statusCode = 400;
          res.end("invalid json");
          return;
        }
        const method = String(envelope.method ?? "");
        const params =
          (envelope.params as Record<string, unknown>) ?? ({} as Record<string, unknown>);
        const rpcId = Number(envelope.id ?? 0);
        const auth = req.headers["authorization"];
        envelopes.push({ method, params, auth: typeof auth === "string" ? auth : undefined });

        let result: unknown;
        try {
          result = handler({ method, params, rpcId, headers: req.headers });
        } catch (err) {
          res.statusCode = 500;
          res.end((err as Error).message);
          return;
        }
        if (result === "__SERVER_ERROR__") {
          res.statusCode = 500;
          res.end("server error");
          return;
        }
        if (result === "__MALFORMED_JSON__") {
          res.setHeader("Content-Type", "application/json");
          res.end("not-json{{{");
          return;
        }
        if (result === "__NO_RESULT_NO_ERROR__") {
          res.setHeader("Content-Type", "application/json");
          res.end(JSON.stringify({ jsonrpc: "2.0", id: rpcId }));
          return;
        }
        if (
          result &&
          typeof result === "object" &&
          (result as Record<string, unknown>).__rpcError
        ) {
          res.setHeader("Content-Type", "application/json");
          res.end(
            JSON.stringify({
              jsonrpc: "2.0",
              id: rpcId,
              error: (result as Record<string, unknown>).__rpcError,
            }),
          );
          return;
        }
        res.setHeader("Content-Type", "application/json");
        res.end(JSON.stringify({ jsonrpc: "2.0", id: rpcId, result }));
      });
    });
    server.listen(0, "127.0.0.1", () => {
      const port = (server.address() as AddressInfo).port;
      resolve({
        port,
        url: `http://127.0.0.1:${port}/agents/test`,
        envelopes,
        reset: () => {
          envelopes.length = 0;
        },
        close: () =>
          new Promise<void>((resolveClose, rejectClose) => {
            server.close((err) => (err ? rejectClose(err) : resolveClose()));
          }),
      });
    });
  });
}

describe("isTerminalState / isCanceledState", () => {
  it("recognises completed/failed/canceled/cancelled (case-insensitive)", () => {
    for (const s of [
      "completed",
      "Completed",
      "FAILED",
      "canceled",
      "Cancelled",
    ]) {
      expect(isTerminalState(s)).toBe(true);
    }
    expect(isTerminalState("working")).toBe(false);
    expect(isTerminalState(undefined)).toBe(false);
    expect(isTerminalState(null)).toBe(false);
  });

  it("isCanceledState accepts both spellings", () => {
    expect(isCanceledState("canceled")).toBe(true);
    expect(isCanceledState("CANCELLED")).toBe(true);
    expect(isCanceledState("failed")).toBe(false);
    expect(isCanceledState(undefined)).toBe(false);
  });
});

describe("A2AClient.send", () => {
  let server: TestServer;

  beforeEach(async () => {
    // each test installs its own handler via reset+swap below
  });
  afterEach(async () => {
    await server?.close();
  });

  it("sends a tasks/send envelope and returns the artifact text on terminal completed", async () => {
    server = await startServer(({ method, params }) => {
      expect(method).toBe("tasks/send");
      expect((params as { id: string }).id).toMatch(/^c-/);
      return {
        status: { state: "completed" },
        artifacts: [
          { parts: [{ type: "text", text: '{"date":"2026-05-10"}' }] },
        ],
      };
    });
    const client = new A2AClient({ url: server.url, skillId: "get-date" });
    const r = await client.send({
      role: "user",
      parts: [{ type: "text", text: "now" }],
    });
    expect(r.state).toBe("completed");
    expect(r.artifactText).toBe('{"date":"2026-05-10"}');
    expect(r.taskId).toMatch(/^c-/);
    expect(server.envelopes).toHaveLength(1);
  });

  it("polls tasks/get with backoff until terminal", async () => {
    let pollCount = 0;
    server = await startServer(({ method }) => {
      if (method === "tasks/send") {
        return { status: { state: "working" } };
      }
      if (method === "tasks/get") {
        pollCount += 1;
        if (pollCount < 2) return { status: { state: "working" } };
        return {
          status: { state: "completed" },
          artifacts: [{ parts: [{ type: "text", text: "ok" }] }],
        };
      }
      return null;
    });
    const client = new A2AClient({
      url: server.url,
      skillId: "x",
      pollIntervalMs: 10,
      pollIntervalMaxMs: 50,
    });
    const r = await client.send({ role: "user", parts: [] });
    expect(r.artifactText).toBe("ok");
    expect(server.envelopes.map((e) => e.method)).toEqual([
      "tasks/send",
      "tasks/get",
      "tasks/get",
    ]);
  });

  it("times out when no terminal state arrives", async () => {
    server = await startServer(() => ({ status: { state: "working" } }));
    const client = new A2AClient({
      url: server.url,
      skillId: "x",
      pollIntervalMs: 10,
      pollIntervalMaxMs: 30,
    });
    await expect(
      client.send({ role: "user", parts: [] }, { timeoutMs: 100 }),
    ).rejects.toBeInstanceOf(A2ATimeoutError);
  });

  it("surfaces JSON-RPC error envelopes as A2AError", async () => {
    server = await startServer(() => ({
      __rpcError: { code: -32602, message: "bad params" },
    }));
    const client = new A2AClient({ url: server.url, skillId: "x" });
    await expect(
      client.send({ role: "user", parts: [] }),
    ).rejects.toThrow(/A2A error from .*: -32602 bad params/);
  });

  it("surfaces malformed JSON-RPC (no result, no error) as A2AError fast-fail", async () => {
    server = await startServer(() => "__NO_RESULT_NO_ERROR__");
    const client = new A2AClient({ url: server.url, skillId: "x" });
    await expect(
      client.send({ role: "user", parts: [] }),
    ).rejects.toThrow(/malformed JSON-RPC envelope/);
  });

  it("surfaces malformed JSON body as A2AError", async () => {
    server = await startServer(() => "__MALFORMED_JSON__");
    const client = new A2AClient({ url: server.url, skillId: "x" });
    await expect(
      client.send({ role: "user", parts: [] }),
    ).rejects.toThrow(/malformed JSON/);
  });

  it("injects Authorization header when auth is configured", async () => {
    server = await startServer(() => ({
      status: { state: "completed" },
      artifacts: [{ parts: [{ type: "text", text: "ok" }] }],
    }));
    const client = new A2AClient({
      url: server.url,
      skillId: "x",
      auth: new A2ABearer({ token: "secret123" }),
    });
    await client.send({ role: "user", parts: [] });
    expect(server.envelopes[0].auth).toBe("Bearer secret123");
  });

  it("treats config.auth as a bearer config shorthand", async () => {
    server = await startServer(() => ({
      status: { state: "completed" },
      artifacts: [{ parts: [{ type: "text", text: "ok" }] }],
    }));
    const client = new A2AClient({
      url: server.url,
      skillId: "x",
      auth: { token: "literal-token" },
    });
    await client.send({ role: "user", parts: [] });
    expect(server.envelopes[0].auth).toBe("Bearer literal-token");
  });

  it("rejects use after close()", async () => {
    server = await startServer(() => ({ status: { state: "completed" } }));
    const client = new A2AClient({ url: server.url, skillId: "x" });
    await client.close();
    await expect(
      client.send({ role: "user", parts: [] }),
    ).rejects.toThrow(/closed/);
  });

  it("trims trailing slashes from the configured URL", async () => {
    server = await startServer(() => ({ status: { state: "completed" } }));
    const client = new A2AClient({
      url: server.url + "///",
      skillId: "x",
    });
    expect(client.url).toBe(server.url);
  });
});

describe("A2AClient.submit", () => {
  let server: TestServer;
  afterEach(async () => {
    await server?.close();
  });

  it("returns A2AJob without polling", async () => {
    server = await startServer(({ method }) => {
      if (method === "tasks/send") {
        return { status: { state: "working" } };
      }
      throw new Error(`unexpected ${method}`);
    });
    const client = new A2AClient({ url: server.url, skillId: "x" });
    const job = await client.submit({ role: "user", parts: [] });
    expect(job.taskId).toMatch(/^c-/);
    expect(job.initialState).toBe("working");
    expect(server.envelopes).toHaveLength(1);
  });

  it("returns A2AJob with terminal initial state when producer responds immediately", async () => {
    server = await startServer(() => ({
      status: { state: "completed" },
      artifacts: [{ parts: [{ type: "text", text: '{"x":1}' }] }],
    }));
    const client = new A2AClient({ url: server.url, skillId: "x" });
    const job = await client.submit({ role: "user", parts: [] });
    expect(job.initialState).toBe("completed");
  });
});

describe("A2AClient.tasksCancel", () => {
  let server: TestServer;
  afterEach(async () => {
    await server?.close();
  });

  it("succeeds against a producer that returns {jsonrpc,id} (no result, no error)", async () => {
    server = await startServer(({ method }) => {
      if (method === "tasks/send") return { status: { state: "working" } };
      if (method === "tasks/cancel") return "__NO_RESULT_NO_ERROR__";
      return { status: { state: "working" } };
    });
    const client = new A2AClient({ url: server.url, skillId: "x" });
    const job = await client.submit({ role: "user", parts: [] });
    // Should not throw — tasks/cancel uses result-or-error mode.
    await expect(job.cancel("ok")).resolves.toBeUndefined();
    expect(server.envelopes.some((e) => e.method === "tasks/cancel")).toBe(true);
  });
});

describe("A2AClient JSON-RPC id uniqueness", () => {
  let server: TestServer;
  afterEach(async () => {
    await server?.close();
  });

  it("emits a unique JSON-RPC id per request (per-instance monotonic counter)", async () => {
    let pollCount = 0;
    const ids: number[] = [];
    server = await startServer(({ method, rpcId }) => {
      ids.push(rpcId);
      if (method === "tasks/send") return { status: { state: "working" } };
      if (method === "tasks/get") {
        pollCount += 1;
        if (pollCount < 3) return { status: { state: "working" } };
        return {
          status: { state: "completed" },
          artifacts: [{ parts: [{ type: "text", text: "ok" }] }],
        };
      }
      return null;
    });
    const client = new A2AClient({
      url: server.url,
      skillId: "x",
      pollIntervalMs: 5,
      pollIntervalMaxMs: 20,
    });
    await client.send({ role: "user", parts: [] });
    // Send + 3 polls = 4 envelopes, all with distinct ids.
    expect(ids).toHaveLength(4);
    expect(new Set(ids).size).toBe(4);
  });
});

describe("A2AClient construction", () => {
  it("throws on empty url", () => {
    expect(() => new A2AClient({ url: "", skillId: "x" })).toThrow(A2AError);
  });
  it("throws on non-positive timeoutMs", () => {
    expect(
      () => new A2AClient({ url: "http://x", skillId: "x", timeoutMs: 0 }),
    ).toThrow(A2AError);
    expect(
      () => new A2AClient({ url: "http://x", skillId: "x", timeoutMs: -1 }),
    ).toThrow(A2AError);
  });
});
