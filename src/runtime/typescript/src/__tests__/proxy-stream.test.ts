/**
 * Unit tests for streamMcpTool / proxy.stream() in proxy.ts
 *
 * Mocks ``fetch`` to return a Response whose body is a ReadableStream emitting
 * hand-crafted SSE events (``notifications/progress`` followed by a final
 * ``result``). Verifies the wire-protocol contract documented in #854.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { createProxy, streamMcpTool, DEFAULT_CALL_OPTIONS } from "../proxy.js";

// Mock @mcpmesh/core so trace injection / dispatcher pieces don't need a Rust build
vi.mock("@mcpmesh/core", () => ({
  generateTraceId: () => "trace-mock",
  generateSpanId: () => "span-mock",
  injectTraceContext: (argsJson: string) => argsJson,
  publishSpan: vi.fn(async () => false),
  parseSseResponse: (s: string) => s,
  parseSseResponseToObject: (s: string) => JSON.parse(s),
}));

vi.mock("../http-pool.js", () => ({
  getDispatcher: () => undefined,
}));

/**
 * Build a ReadableStream<Uint8Array> that emits the given SSE event blocks
 * one chunk at a time. Each block should already include the trailing blank
 * line per SSE spec.
 */
function makeSseStream(blocks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  let i = 0;
  return new ReadableStream<Uint8Array>({
    pull(controller) {
      if (i < blocks.length) {
        controller.enqueue(encoder.encode(blocks[i]));
        i += 1;
      } else {
        controller.close();
      }
    },
  });
}

function sseEvent(payload: object): string {
  return `event: message\ndata: ${JSON.stringify(payload)}\n\n`;
}

function makeMockResponse(blocks: string[], opts: { ok?: boolean; status?: number } = {}): Response {
  return {
    ok: opts.ok ?? true,
    status: opts.status ?? 200,
    statusText: "OK",
    body: makeSseStream(blocks),
    headers: {
      get: (name: string) => (name.toLowerCase() === "content-type" ? "text/event-stream" : null),
    },
  } as unknown as Response;
}

const ENDPOINT = "http://producer.local:9000";
const TOOL = "stream_chunks";
const CAPABILITY = "streamer";

describe("streamMcpTool", () => {
  let originalFetch: typeof fetch;

  beforeEach(() => {
    originalFetch = globalThis.fetch;
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it("yields each progress chunk in order", async () => {
    let capturedBody: string | undefined;
    const fetchMock = vi.fn(async (_url: string, init: RequestInit) => {
      capturedBody = init.body as string;
      const reqId = JSON.parse(capturedBody).id as string;
      const token = JSON.parse(capturedBody).params._meta.progressToken as string;
      return makeMockResponse([
        sseEvent({
          jsonrpc: "2.0",
          method: "notifications/progress",
          params: { progressToken: token, progress: 1, message: "alpha" },
        }),
        sseEvent({
          jsonrpc: "2.0",
          method: "notifications/progress",
          params: { progressToken: token, progress: 2, message: "beta" },
        }),
        sseEvent({
          jsonrpc: "2.0",
          method: "notifications/progress",
          params: { progressToken: token, progress: 3, message: "gamma" },
        }),
        sseEvent({ jsonrpc: "2.0", id: reqId, result: { content: [{ type: "text", text: "alphabetagamma" }] } }),
      ]);
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const chunks: string[] = [];
    for await (const chunk of streamMcpTool(ENDPOINT, TOOL, { foo: 1 }, DEFAULT_CALL_OPTIONS, CAPABILITY)) {
      chunks.push(chunk);
    }

    expect(chunks).toEqual(["alpha", "beta", "gamma"]);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    // Verify the request body has _meta.progressToken
    const body = JSON.parse(capturedBody!);
    expect(body.method).toBe("tools/call");
    expect(body.params.name).toBe(TOOL);
    expect(typeof body.params._meta.progressToken).toBe("string");
    expect(body.params._meta.progressToken.length).toBeGreaterThan(0);
    // Verify Accept header
    const headers = (fetchMock.mock.calls[0][1] as RequestInit).headers as Record<string, string>;
    expect(headers["Accept"]).toBe("text/event-stream");
  });

  it("does not yield the final result message content", async () => {
    const fetchMock = vi.fn(async (_url: string, init: RequestInit) => {
      const body = JSON.parse(init.body as string);
      return makeMockResponse([
        sseEvent({
          jsonrpc: "2.0",
          method: "notifications/progress",
          params: { progressToken: body.params._meta.progressToken, progress: 1, message: "only-chunk" },
        }),
        // Final result with content that must NOT be yielded
        sseEvent({
          jsonrpc: "2.0",
          id: body.id,
          result: { content: [{ type: "text", text: "FINAL-RESULT-DO-NOT-YIELD" }] },
        }),
      ]);
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const chunks: string[] = [];
    for await (const chunk of streamMcpTool(ENDPOINT, TOOL, undefined, DEFAULT_CALL_OPTIONS, CAPABILITY)) {
      chunks.push(chunk);
    }

    expect(chunks).toEqual(["only-chunk"]);
    expect(chunks).not.toContain("FINAL-RESULT-DO-NOT-YIELD");
  });

  it("ignores progress notifications with a mismatched progressToken", async () => {
    const fetchMock = vi.fn(async (_url: string, init: RequestInit) => {
      const body = JSON.parse(init.body as string);
      return makeMockResponse([
        // Notification from a DIFFERENT in-flight call (unlikely but defensive)
        sseEvent({
          jsonrpc: "2.0",
          method: "notifications/progress",
          params: { progressToken: "some-other-token", progress: 1, message: "ignored" },
        }),
        sseEvent({
          jsonrpc: "2.0",
          method: "notifications/progress",
          params: { progressToken: body.params._meta.progressToken, progress: 1, message: "kept" },
        }),
        sseEvent({ jsonrpc: "2.0", id: body.id, result: {} }),
      ]);
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const chunks: string[] = [];
    for await (const chunk of streamMcpTool(ENDPOINT, TOOL, undefined, DEFAULT_CALL_OPTIONS, CAPABILITY)) {
      chunks.push(chunk);
    }

    expect(chunks).toEqual(["kept"]);
  });

  it("throws when the JSON-RPC final message contains an error", async () => {
    const fetchMock = vi.fn(async (_url: string, init: RequestInit) => {
      const body = JSON.parse(init.body as string);
      return makeMockResponse([
        sseEvent({
          jsonrpc: "2.0",
          method: "notifications/progress",
          params: { progressToken: body.params._meta.progressToken, progress: 1, message: "partial" },
        }),
        sseEvent({
          jsonrpc: "2.0",
          id: body.id,
          error: { code: -32000, message: "tool blew up" },
        }),
      ]);
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const collect = async () => {
      const out: string[] = [];
      for await (const chunk of streamMcpTool(ENDPOINT, TOOL, undefined, DEFAULT_CALL_OPTIONS, CAPABILITY)) {
        out.push(chunk);
      }
      return out;
    };

    await expect(collect()).rejects.toThrow(/tool blew up/);
  });

  it("throws on non-2xx HTTP response", async () => {
    const fetchMock = vi.fn(async () => {
      return {
        ok: false,
        status: 503,
        statusText: "Service Unavailable",
        body: makeSseStream([]),
        headers: { get: () => null },
      } as unknown as Response;
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const collect = async () => {
      for await (const _ of streamMcpTool(ENDPOINT, TOOL, undefined, DEFAULT_CALL_OPTIONS, CAPABILITY)) {
        // no-op
      }
    };

    await expect(collect()).rejects.toThrow(/503 Service Unavailable/);
  });

  it("releases the underlying reader when the consumer breaks early", async () => {
    let reader: ReadableStreamDefaultReader<Uint8Array> | undefined;
    const fetchMock = vi.fn(async (_url: string, init: RequestInit) => {
      const body = JSON.parse(init.body as string);
      const stream = makeSseStream([
        sseEvent({
          jsonrpc: "2.0",
          method: "notifications/progress",
          params: { progressToken: body.params._meta.progressToken, progress: 1, message: "first" },
        }),
        sseEvent({
          jsonrpc: "2.0",
          method: "notifications/progress",
          params: { progressToken: body.params._meta.progressToken, progress: 2, message: "second" },
        }),
        sseEvent({ jsonrpc: "2.0", id: body.id, result: {} }),
      ]);
      // Wrap stream so we can spy on the reader after getReader is called
      const origGetReader = stream.getReader.bind(stream);
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      (stream as any).getReader = function (...rargs: any[]) {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        reader = (origGetReader as any)(...rargs);
        return reader!;
      };
      return {
        ok: true,
        status: 200,
        statusText: "OK",
        body: stream,
        headers: { get: () => "text/event-stream" },
      } as unknown as Response;
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const iter = streamMcpTool(ENDPOINT, TOOL, undefined, DEFAULT_CALL_OPTIONS, CAPABILITY);
    const out: string[] = [];
    for await (const chunk of iter) {
      out.push(chunk);
      // Break on first chunk
      break;
    }

    expect(out).toEqual(["first"]);
    // Wait a tick so finally{} can run
    await new Promise((r) => setTimeout(r, 0));
    expect(reader).toBeDefined();
    // After cancel(), reads should resolve with done:true
    const post = await reader!.read();
    expect(post.done).toBe(true);
  });

  it("yields nothing when the producer emits no progress notifications (TS soft-fallback skipped)", async () => {
    // Per #854: TS Stage 1 does NOT implement Python's soft-fallback. If the
    // producer didn't emit progress, the iterable yields nothing.
    const fetchMock = vi.fn(async (_url: string, init: RequestInit) => {
      const body = JSON.parse(init.body as string);
      return makeMockResponse([
        sseEvent({
          jsonrpc: "2.0",
          id: body.id,
          result: { content: [{ type: "text", text: "buffered final" }] },
        }),
      ]);
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const out: string[] = [];
    for await (const chunk of streamMcpTool(ENDPOINT, TOOL, undefined, DEFAULT_CALL_OPTIONS, CAPABILITY)) {
      out.push(chunk);
    }
    expect(out).toEqual([]);
  });

  it("handles SSE events split across multiple network chunks", async () => {
    // Split a single SSE event in the middle of its payload to verify the
    // \n\n boundary parser correctly buffers partial reads.
    const fetchMock = vi.fn(async (_url: string, init: RequestInit) => {
      const body = JSON.parse(init.body as string);
      const ev1 = sseEvent({
        jsonrpc: "2.0",
        method: "notifications/progress",
        params: { progressToken: body.params._meta.progressToken, progress: 1, message: "one" },
      });
      const ev2 = sseEvent({
        jsonrpc: "2.0",
        method: "notifications/progress",
        params: { progressToken: body.params._meta.progressToken, progress: 2, message: "two" },
      });
      const final = sseEvent({ jsonrpc: "2.0", id: body.id, result: {} });
      const all = ev1 + ev2 + final;
      const mid = Math.floor(all.length / 2);
      return makeMockResponse([all.slice(0, mid), all.slice(mid)]);
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const out: string[] = [];
    for await (const chunk of streamMcpTool(ENDPOINT, TOOL, undefined, DEFAULT_CALL_OPTIONS, CAPABILITY)) {
      out.push(chunk);
    }
    expect(out).toEqual(["one", "two"]);
  });
});

describe("createProxy.stream() integration", () => {
  let originalFetch: typeof fetch;
  beforeEach(() => {
    originalFetch = globalThis.fetch;
  });
  afterEach(() => {
    globalThis.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it("attaches a non-enumerable stream method that yields progress chunks", async () => {
    const fetchMock = vi.fn(async (_url: string, init: RequestInit) => {
      const body = JSON.parse(init.body as string);
      const token = body.params._meta.progressToken as string;
      return makeMockResponse([
        sseEvent({
          jsonrpc: "2.0",
          method: "notifications/progress",
          params: { progressToken: token, progress: 1, message: "x" },
        }),
        sseEvent({
          jsonrpc: "2.0",
          method: "notifications/progress",
          params: { progressToken: token, progress: 2, message: "y" },
        }),
        sseEvent({ jsonrpc: "2.0", id: body.id, result: {} }),
      ]);
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const proxy = createProxy(ENDPOINT, CAPABILITY, TOOL);
    expect(typeof proxy.stream).toBe("function");

    // Non-enumerable: JSON.stringify on a function returns undefined entirely,
    // which is the strongest possible guarantee that no internal field leaks.
    // Also verify the property descriptor is non-enumerable explicitly.
    const json = JSON.stringify(proxy);
    expect(json).toBeUndefined();
    const desc = Object.getOwnPropertyDescriptor(proxy, "stream");
    expect(desc).toBeDefined();
    expect(desc?.enumerable).toBe(false);

    const chunks: string[] = [];
    for await (const chunk of proxy.stream({ foo: "bar" })) {
      chunks.push(chunk);
    }
    expect(chunks).toEqual(["x", "y"]);
  });
});
