/**
 * Tests for A2AJob (issue #917).
 *
 * Avoids binding a real napi JobController — we mock @mcpmesh/core's
 * `awaitJobCancel` and pass a hand-rolled controller object whose
 * `updateProgress` we can spy on.
 */
import {
  describe,
  it,
  expect,
  beforeEach,
  afterEach,
  vi,
} from "vitest";
import * as http from "node:http";
import { AddressInfo } from "node:net";

// Mock @mcpmesh/core's awaitJobCancel so we can simulate cancel
// without binding a real napi cancel registry.
vi.mock("@mcpmesh/core", async () => {
  const actual = await vi.importActual<Record<string, unknown>>("@mcpmesh/core");
  return {
    ...actual,
    awaitJobCancel: vi.fn().mockReturnValue(new Promise(() => {})),
  };
});

import { awaitJobCancel } from "@mcpmesh/core";
import { A2AClient } from "../../a2a/a2a-client.js";
import {
  A2AJobCanceledError,
  A2AJobFailedError,
} from "../../a2a/errors.js";

const awaitJobCancelMock = awaitJobCancel as unknown as ReturnType<typeof vi.fn>;

interface TestServer {
  url: string;
  /** Per-method response queue. Each entry is consumed in order. */
  responses: Map<string, Array<unknown>>;
  /** All received envelopes — assert against this in tests. */
  envelopes: Array<{ method: string; params: unknown }>;
  close: () => Promise<void>;
}

function startServer(): Promise<TestServer> {
  return new Promise((resolve) => {
    const responses = new Map<string, Array<unknown>>();
    const envelopes: TestServer["envelopes"] = [];
    const server = http.createServer((req, res) => {
      let body = "";
      req.on("data", (chunk) => (body += chunk));
      req.on("end", () => {
        const env = JSON.parse(body);
        envelopes.push({ method: env.method, params: env.params });
        const queue = responses.get(env.method) ?? [];
        const next = queue.shift() ?? { status: { state: "working" } };
        res.setHeader("Content-Type", "application/json");
        res.end(JSON.stringify({ jsonrpc: "2.0", id: env.id, result: next }));
      });
    });
    server.listen(0, "127.0.0.1", () => {
      const port = (server.address() as AddressInfo).port;
      resolve({
        url: `http://127.0.0.1:${port}/agents/test`,
        responses,
        envelopes,
        close: () =>
          new Promise<void>((rs, rj) =>
            server.close((err) => (err ? rj(err) : rs())),
          ),
      });
    });
  });
}

function makeMockController(jobId = "job-test") {
  return {
    jobId,
    updateProgress: vi.fn().mockResolvedValue(undefined),
    complete: vi.fn().mockResolvedValue(undefined),
    fail: vi.fn().mockResolvedValue(undefined),
    isTerminal: vi.fn().mockResolvedValue(false),
    releaseLease: vi.fn().mockResolvedValue(undefined),
  } as unknown as import("@mcpmesh/core").JobController & {
    updateProgress: ReturnType<typeof vi.fn>;
  };
}

describe("A2AJob.bridge", () => {
  let server: TestServer;

  beforeEach(() => {
    awaitJobCancelMock.mockReset();
    awaitJobCancelMock.mockReturnValue(new Promise(() => {}));
  });
  afterEach(async () => {
    await server?.close();
  });

  it("polls until terminal then returns the parsed artifact", async () => {
    server = await startServer();
    server.responses.set("tasks/send", [{ status: { state: "working" } }]);
    server.responses.set("tasks/get", [
      {
        status: { state: "working" },
        metadata: { progress: 0.3 },
      },
      {
        status: { state: "completed" },
        artifacts: [{ parts: [{ text: '{"section":"intro"}' }] }],
      },
    ]);
    const client = new A2AClient({
      url: server.url,
      skillId: "x",
      pollIntervalMs: 5,
      pollIntervalMaxMs: 20,
    });
    const job = await client.submit({ role: "user", parts: [] });
    const ctrl = makeMockController();
    const value = await job.bridge(ctrl);
    expect(value).toEqual({ section: "intro" });
    expect(
      (ctrl as unknown as { updateProgress: ReturnType<typeof vi.fn> })
        .updateProgress,
    ).toHaveBeenCalledWith(0.3, null);
  });

  it("throws A2AJobFailedError on terminal failed", async () => {
    server = await startServer();
    server.responses.set("tasks/send", [
      {
        status: {
          state: "failed",
          message: { parts: [{ text: "boom" }] },
        },
      },
    ]);
    const client = new A2AClient({ url: server.url, skillId: "x" });
    const job = await client.submit({ role: "user", parts: [] });
    await expect(job.bridge(makeMockController())).rejects.toBeInstanceOf(
      A2AJobFailedError,
    );
  });

  it("throws A2AJobCanceledError on terminal canceled", async () => {
    server = await startServer();
    server.responses.set("tasks/send", [
      {
        status: {
          state: "canceled",
          message: { parts: [{ text: "user-cancel" }] },
        },
      },
    ]);
    const client = new A2AClient({ url: server.url, skillId: "x" });
    const job = await client.submit({ role: "user", parts: [] });
    await expect(job.bridge(makeMockController())).rejects.toBeInstanceOf(
      A2AJobCanceledError,
    );
  });

  it("propagates mesh-side cancel: POSTs tasks/cancel + throws A2AJobCanceledError", async () => {
    server = await startServer();
    server.responses.set("tasks/send", [{ status: { state: "working" } }]);
    server.responses.set("tasks/get", [
      { status: { state: "working" } },
      { status: { state: "working" } },
      { status: { state: "working" } },
    ]);
    server.responses.set("tasks/cancel", [{ status: { state: "canceled" } }]);

    // Resolver-controlled cancel — eliminates the previous timing-
    // sensitive setTimeout(30ms). We trigger it explicitly after the
    // bridge has had a chance to enter its poll loop (one tick).
    let cancelResolve!: () => void;
    const cancelPromise = new Promise<void>((r) => {
      cancelResolve = r;
    });
    awaitJobCancelMock.mockReturnValue(cancelPromise);

    const client = new A2AClient({
      url: server.url,
      skillId: "x",
      pollIntervalMs: 10,
      pollIntervalMaxMs: 20,
    });
    const job = await client.submit({ role: "user", parts: [] });
    const bridgePromise = job.bridge(makeMockController());
    // Yield once so bridge attaches its .then on cancelPromise + enters
    // the poll loop, then explicitly fire the cancel signal.
    await Promise.resolve();
    cancelResolve();
    await expect(bridgePromise).rejects.toBeInstanceOf(A2AJobCanceledError);
    // The bridge MUST have POSTed tasks/cancel upstream.
    expect(server.envelopes.some((e) => e.method === "tasks/cancel")).toBe(true);
  });

  it("surfaces transport failure as A2AJobFailedError + best-effort upstream cancel", async () => {
    server = await startServer();
    server.responses.set("tasks/send", [{ status: { state: "working" } }]);
    server.responses.set("tasks/cancel", [{ status: { state: "canceled" } }]);
    const client = new A2AClient({
      url: server.url,
      skillId: "x",
      pollIntervalMs: 5,
    });
    const job = await client.submit({ role: "user", parts: [] });
    await server.close(); // Force tasks/get to fail
    server = { ...server, close: async () => {} };
    await expect(job.bridge(makeMockController())).rejects.toBeInstanceOf(
      A2AJobFailedError,
    );
  });
});

describe("A2AJob.cancel", () => {
  let server: TestServer;
  afterEach(async () => {
    await server?.close();
  });

  it("POSTs tasks/cancel with the supplied reason", async () => {
    server = await startServer();
    server.responses.set("tasks/send", [{ status: { state: "working" } }]);
    server.responses.set("tasks/cancel", [{ status: { state: "canceled" } }]);
    const client = new A2AClient({ url: server.url, skillId: "x" });
    const job = await client.submit({ role: "user", parts: [] });
    await job.cancel("why");
    const cancelEnv = server.envelopes.find((e) => e.method === "tasks/cancel");
    expect(cancelEnv).toBeDefined();
    expect((cancelEnv?.params as { reason?: string }).reason).toBe("why");
  });

  it("swallows transport errors (best-effort)", async () => {
    server = await startServer();
    server.responses.set("tasks/send", [{ status: { state: "working" } }]);
    const client = new A2AClient({ url: server.url, skillId: "x" });
    const job = await client.submit({ role: "user", parts: [] });
    await server.close();
    server = { ...server, close: async () => {} };
    // Should not throw.
    await job.cancel("after-close");
  });
});

describe("A2AJob.wait", () => {
  let server: TestServer;
  afterEach(async () => {
    await server?.close();
  });

  it("returns A2AResponse on completed terminal", async () => {
    server = await startServer();
    server.responses.set("tasks/send", [{ status: { state: "working" } }]);
    server.responses.set("tasks/get", [
      {
        status: { state: "completed" },
        artifacts: [{ parts: [{ text: "ok" }] }],
      },
    ]);
    const client = new A2AClient({
      url: server.url,
      skillId: "x",
      pollIntervalMs: 5,
    });
    const job = await client.submit({ role: "user", parts: [] });
    const r = await job.wait();
    expect(r.state).toBe("completed");
    expect(r.artifactText).toBe("ok");
  });

  it("short-circuits on initial terminal state", async () => {
    server = await startServer();
    server.responses.set("tasks/send", [
      {
        status: { state: "completed" },
        artifacts: [{ parts: [{ text: "ok" }] }],
      },
    ]);
    const client = new A2AClient({ url: server.url, skillId: "x" });
    const job = await client.submit({ role: "user", parts: [] });
    const r = await job.wait();
    expect(r.state).toBe("completed");
    // Only the initial submit envelope — no tasks/get.
    expect(server.envelopes.filter((e) => e.method === "tasks/get")).toHaveLength(0);
  });
});

describe("A2AJob.status (raw envelope)", () => {
  let server: TestServer;
  afterEach(async () => {
    await server?.close();
  });

  it("returns the live envelope for the configured task", async () => {
    server = await startServer();
    server.responses.set("tasks/send", [{ status: { state: "working" } }]);
    server.responses.set("tasks/get", [
      { status: { state: "working" }, metadata: { progress: 0.5 } },
    ]);
    const client = new A2AClient({ url: server.url, skillId: "x" });
    const job = await client.submit({ role: "user", parts: [] });
    const result = await job.status();
    expect(
      ((result as Record<string, unknown>).status as { state: string }).state,
    ).toBe("working");
  });
});
