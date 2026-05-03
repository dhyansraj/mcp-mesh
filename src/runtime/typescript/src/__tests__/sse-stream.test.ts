/**
 * Unit tests for sse-stream.ts (mesh.sseStream).
 *
 * Verifies the SSE wire format mirrors the Python ``mesh.route`` adapter:
 * - ``data: <chunk>\n\n`` per item
 * - ``data: [DONE]\n\n`` terminator on normal completion
 * - ``event: error\ndata: <json>\n\n`` on per-chunk error
 * - Standard headers (Content-Type, Cache-Control, Connection, X-Accel-Buffering)
 * - Idempotent end()
 */

import { describe, it, expect, vi } from "vitest";
import type { Response } from "express";
import { sseStream } from "../sse-stream.js";

interface FakeRes {
  headersSent: boolean;
  writableEnded: boolean;
  destroyed: boolean;
  setHeader: ReturnType<typeof vi.fn>;
  write: ReturnType<typeof vi.fn>;
  end: ReturnType<typeof vi.fn>;
  flushHeaders: ReturnType<typeof vi.fn>;
  _written: string[];
}

function makeFakeRes(): FakeRes {
  const res: FakeRes = {
    headersSent: false,
    writableEnded: false,
    destroyed: false,
    setHeader: vi.fn(),
    write: vi.fn((data: string) => {
      res._written.push(data);
      return true;
    }),
    end: vi.fn(() => {
      res.writableEnded = true;
    }),
    flushHeaders: vi.fn(() => {
      res.headersSent = true;
    }),
    _written: [],
  };
  return res;
}

async function* asyncIter<T>(items: T[]): AsyncGenerator<T, void, void> {
  for (const item of items) {
    yield item;
  }
}

describe("sseStream", () => {
  it("sets the standard SSE headers", async () => {
    const res = makeFakeRes();
    await sseStream(res as unknown as Response, asyncIter(["a"]));

    const setHeaderCalls = Object.fromEntries(
      res.setHeader.mock.calls.map((c) => [c[0], c[1]])
    );
    expect(setHeaderCalls["Content-Type"]).toBe("text/event-stream");
    expect(setHeaderCalls["Cache-Control"]).toBe("no-cache");
    expect(setHeaderCalls["Connection"]).toBe("keep-alive");
    expect(setHeaderCalls["X-Accel-Buffering"]).toBe("no");
    expect(res.flushHeaders).toHaveBeenCalledTimes(1);
  });

  it("writes data: <chunk>\\n\\n per item then data: [DONE]\\n\\n and ends once", async () => {
    const res = makeFakeRes();
    await sseStream(res as unknown as Response, asyncIter(["a", "b", "c"]));

    expect(res._written).toEqual([
      "data: a\n\n",
      "data: b\n\n",
      "data: c\n\n",
      "data: [DONE]\n\n",
    ]);
    expect(res.end).toHaveBeenCalledTimes(1);
  });

  it("does not double-end on already-completed response", async () => {
    const res = makeFakeRes();
    await sseStream(res as unknown as Response, asyncIter([]));
    // No items: should still write [DONE] and end exactly once
    expect(res._written).toEqual(["data: [DONE]\n\n"]);
    expect(res.end).toHaveBeenCalledTimes(1);
  });

  it("emits one data: line per newline in a multi-line chunk", async () => {
    const res = makeFakeRes();
    await sseStream(res as unknown as Response, asyncIter(["line1\nline2\nline3"]));

    // Per SSE spec, multi-line data is multiple data: prefixes inside one event
    expect(res._written[0]).toBe("data: line1\ndata: line2\ndata: line3\n\n");
    expect(res._written[1]).toBe("data: [DONE]\n\n");
    expect(res.end).toHaveBeenCalledTimes(1);
  });

  it("emits a heartbeat-style empty data line for empty chunks", async () => {
    const res = makeFakeRes();
    await sseStream(res as unknown as Response, asyncIter([""]));

    expect(res._written[0]).toBe("data: \n\n");
    expect(res._written[1]).toBe("data: [DONE]\n\n");
  });

  it("writes event: error on iterator throw and ends without sending [DONE]", async () => {
    const res = makeFakeRes();

    async function* throwing(): AsyncGenerator<string, void, void> {
      yield "first";
      throw new Error("upstream blew up");
    }

    await sseStream(res as unknown as Response, throwing());

    expect(res._written[0]).toBe("data: first\n\n");
    // Last frame is the error; [DONE] should NOT have been sent
    expect(res._written.at(-1)).toMatch(/^event: error\ndata: /);
    const errFrame = res._written.at(-1)!;
    const payloadJson = errFrame.replace(/^event: error\ndata: /, "").replace(/\n\n$/, "");
    const payload = JSON.parse(payloadJson);
    expect(payload.error).toBe("upstream blew up");
    expect(payload.type).toBe("Error");
    // No [DONE] anywhere
    expect(res._written.some((s) => s === "data: [DONE]\n\n")).toBe(false);
    expect(res.end).toHaveBeenCalledTimes(1);
  });

  it("writes event: error and stops on non-string chunks (TypeError)", async () => {
    const res = makeFakeRes();

    // Iterator yields a non-string — should be rejected with a structured error
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    async function* bad(): AsyncGenerator<any, void, void> {
      yield "ok";
      yield 42 as unknown as string;
      yield "never-reached";
    }

    await sseStream(res as unknown as Response, bad() as AsyncIterable<string>);

    expect(res._written[0]).toBe("data: ok\n\n");
    expect(res._written[1]).toMatch(/^event: error\ndata: /);
    const payloadJson = res._written[1].replace(/^event: error\ndata: /, "").replace(/\n\n$/, "");
    const payload = JSON.parse(payloadJson);
    expect(payload.type).toBe("TypeError");
    expect(payload.error).toMatch(/expected string chunk/);
    expect(res.end).toHaveBeenCalledTimes(1);
  });

  it("stops iterating and calls return() on consumer disconnect (write returns false)", async () => {
    const res = makeFakeRes();
    let returnCalled = false;
    let yielded = 0;

    const iter: AsyncIterable<string> = {
      [Symbol.asyncIterator]() {
        return {
          async next() {
            yielded += 1;
            if (yielded > 5) return { value: undefined, done: true };
            return { value: `chunk${yielded}`, done: false };
          },
          async return() {
            returnCalled = true;
            return { value: undefined, done: true };
          },
        };
      },
    };

    // After first write, simulate disconnect
    res.write = vi.fn(() => {
      res._written.push("first-write");
      res.writableEnded = true; // Simulate consumer disconnect
      return false;
    });

    await sseStream(res as unknown as Response, iter);

    expect(returnCalled).toBe(true);
    // Only one chunk was attempted, then disconnect detected
    expect(yielded).toBe(1);
    // [DONE] was NOT written
    expect(res._written).not.toContain("data: [DONE]\n\n");
  });

  it("does not set headers if headersSent is already true", async () => {
    const res = makeFakeRes();
    res.headersSent = true;

    await sseStream(res as unknown as Response, asyncIter(["a"]));

    expect(res.setHeader).not.toHaveBeenCalled();
    expect(res.flushHeaders).not.toHaveBeenCalled();
    // Still writes data + [DONE]
    expect(res._written).toEqual(["data: a\n\n", "data: [DONE]\n\n"]);
  });

  it("handles synchronous res.write throwing without crashing", async () => {
    const res = makeFakeRes();
    res.write = vi.fn(() => {
      throw new Error("socket closed");
    });

    // Should not throw out of sseStream — it swallows write errors and ends
    await expect(
      sseStream(res as unknown as Response, asyncIter(["a", "b"]))
    ).resolves.toBeUndefined();
    expect(res.end).toHaveBeenCalledTimes(1);
  });
});
