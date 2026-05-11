/**
 * Tests for A2AStream + A2AClient.subscribe (issue #917).
 *
 * Spins up a tiny SSE producer over node:http that pushes a sequence
 * of `data: { ... }` frames (status + artifact + final) so we exercise
 * the full SSE line parser + JobController bridge.
 */
import { describe, it, expect, afterEach, vi } from "vitest";
import * as http from "node:http";
import { AddressInfo } from "node:net";
import { A2AClient } from "../../a2a/a2a-client.js";
import {
  A2AJobCanceledError,
  A2AJobFailedError,
} from "../../a2a/errors.js";

interface SseServer {
  url: string;
  close: () => Promise<void>;
}

function startSseServer(frames: string[][]): Promise<SseServer> {
  return new Promise((resolve) => {
    const server = http.createServer((_req, res) => {
      res.setHeader("Content-Type", "text/event-stream");
      res.setHeader("Cache-Control", "no-cache");
      // Push frames one at a time with small gaps so the consumer sees
      // a true streaming response (not a single buffered write).
      let i = 0;
      const writeNext = () => {
        if (i >= frames.length) {
          res.end();
          return;
        }
        const lines = frames[i++];
        for (const l of lines) {
          res.write(l + "\n");
        }
        res.write("\n"); // event boundary
        setTimeout(writeNext, 5);
      };
      writeNext();
    });
    server.listen(0, "127.0.0.1", () => {
      const port = (server.address() as AddressInfo).port;
      resolve({
        url: `http://127.0.0.1:${port}/agents/test`,
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

const sse = (envelope: object) =>
  `data: ${JSON.stringify(envelope)}`;

describe("A2AStream iterator", () => {
  let server: SseServer;
  afterEach(async () => {
    await server?.close();
  });

  it("yields parsed status and artifact events", async () => {
    server = await startSseServer([
      [
        sse({
          jsonrpc: "2.0",
          id: 1,
          result: {
            status: {
              state: "working",
              message: { parts: [{ text: "warming up" }] },
            },
            metadata: { progress: 0.1 },
          },
        }),
      ],
      [
        sse({
          jsonrpc: "2.0",
          id: 1,
          result: {
            artifact: { parts: [{ text: '{"x":1}' }] },
          },
        }),
      ],
      [
        sse({
          jsonrpc: "2.0",
          id: 1,
          result: {
            status: { state: "completed" },
            final: true,
          },
        }),
      ],
    ]);
    const client = new A2AClient({ url: server.url, skillId: "x" });
    const stream = await client.subscribe({ role: "user", parts: [] });
    const events: Array<{
      kind: string;
      state?: string;
      progress?: number;
      message?: string;
      artifactText?: string;
      final: boolean;
    }> = [];
    for await (const e of stream) {
      events.push({
        kind: e.kind,
        state: e.state,
        progress: e.progress,
        message: e.message,
        artifactText: e.artifactText,
        final: e.final,
      });
    }
    expect(events.map((e) => e.kind)).toEqual([
      "status",
      "artifact",
      "status",
    ]);
    expect(events[0].progress).toBe(0.1);
    expect(events[0].message).toBe("warming up");
    expect(events[1].artifactText).toBe('{"x":1}');
    expect(events[2].state).toBe("completed");
    expect(events[2].final).toBe(true);
  });

  it("ignores SSE comment + non-data lines", async () => {
    server = await startSseServer([
      [": keepalive", "id: 1", "event: message"],
      [
        sse({
          jsonrpc: "2.0",
          id: 1,
          result: {
            status: { state: "completed" },
            final: true,
          },
        }),
      ],
    ]);
    const client = new A2AClient({ url: server.url, skillId: "x" });
    const stream = await client.subscribe({ role: "user", parts: [] });
    const events = [];
    for await (const e of stream) events.push(e);
    expect(events).toHaveLength(1);
    expect(events[0].state).toBe("completed");
  });
});

describe("A2AStream.bridge", () => {
  let server: SseServer;
  afterEach(async () => {
    await server?.close();
  });

  it("mirrors progress + returns the artifact value", async () => {
    server = await startSseServer([
      [
        sse({
          jsonrpc: "2.0",
          id: 1,
          result: {
            status: {
              state: "working",
              message: { parts: [{ text: "step1" }] },
            },
            metadata: { progress: 0.25 },
          },
        }),
      ],
      [
        sse({
          jsonrpc: "2.0",
          id: 1,
          result: {
            status: {
              state: "working",
              message: { parts: [{ text: "step2" }] },
            },
            metadata: { progress: 0.75 },
          },
        }),
      ],
      [
        sse({
          jsonrpc: "2.0",
          id: 1,
          result: {
            artifact: { parts: [{ text: '{"sections":["a","b"]}' }] },
          },
        }),
      ],
      [
        sse({
          jsonrpc: "2.0",
          id: 1,
          result: { status: { state: "completed" }, final: true },
        }),
      ],
    ]);
    const client = new A2AClient({ url: server.url, skillId: "x" });
    const stream = await client.subscribe({ role: "user", parts: [] });
    const ctrl = makeMockController();
    const value = await stream.bridge(ctrl);
    expect(value).toEqual({ sections: ["a", "b"] });
    expect(
      (ctrl as unknown as { updateProgress: ReturnType<typeof vi.fn> })
        .updateProgress.mock.calls.length,
    ).toBeGreaterThanOrEqual(2);
  });

  it("throws A2AJobFailedError when terminal state is failed", async () => {
    server = await startSseServer([
      [
        sse({
          jsonrpc: "2.0",
          id: 1,
          result: {
            status: {
              state: "failed",
              message: { parts: [{ text: "boom" }] },
            },
            final: true,
          },
        }),
      ],
    ]);
    const client = new A2AClient({ url: server.url, skillId: "x" });
    const stream = await client.subscribe({ role: "user", parts: [] });
    await expect(stream.bridge(makeMockController())).rejects.toBeInstanceOf(
      A2AJobFailedError,
    );
  });

  it("throws A2AJobCanceledError when terminal state is canceled", async () => {
    server = await startSseServer([
      [
        sse({
          jsonrpc: "2.0",
          id: 1,
          result: {
            status: {
              state: "canceled",
              message: { parts: [{ text: "user cancel" }] },
            },
            final: true,
          },
        }),
      ],
    ]);
    const client = new A2AClient({ url: server.url, skillId: "x" });
    const stream = await client.subscribe({ role: "user", parts: [] });
    await expect(stream.bridge(makeMockController())).rejects.toBeInstanceOf(
      A2AJobCanceledError,
    );
  });

  it("returns empty string on terminal completed with no artifact (parity with A2AJob)", async () => {
    server = await startSseServer([
      [
        sse({
          jsonrpc: "2.0",
          id: 1,
          result: {
            status: { state: "completed" },
            final: true,
          },
        }),
      ],
    ]);
    const client = new A2AClient({ url: server.url, skillId: "x" });
    const stream = await client.subscribe({ role: "user", parts: [] });
    const value = await stream.bridge(makeMockController());
    expect(value).toBe("");
  });

  it("throws A2AJobFailedError when stream ends with no terminal state and no artifact", async () => {
    server = await startSseServer([
      [
        sse({
          jsonrpc: "2.0",
          id: 1,
          result: {
            status: {
              state: "working",
              message: { parts: [{ text: "still going" }] },
            },
            metadata: { progress: 0.1 },
          },
        }),
      ],
    ]);
    const client = new A2AClient({ url: server.url, skillId: "x" });
    const stream = await client.subscribe({ role: "user", parts: [] });
    await expect(stream.bridge(makeMockController())).rejects.toThrow(
      /ended without artifact/,
    );
  });
});
