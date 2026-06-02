/**
 * Unit test for the buffered-path effective-timeout guard in callMcpTool.
 *
 * PR-B (#1116) item 1 hardening: the streaming path already fell back to a
 * positive default when the resolved timeout was non-positive; the buffered
 * path did not. After extracting the shared `buildMcpRequest`, BOTH paths apply
 * the guard. This test asserts callMcpTool no longer aborts-immediately when a
 * caller passes a zero/negative timeout (a setTimeout(…, 0) would otherwise fire
 * on the next tick and abort the in-flight fetch).
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { callMcpTool, DEFAULT_CALL_OPTIONS, type CallOptions } from "../proxy.js";

vi.mock("@mcpmesh/core", () => ({
  generateTraceId: () => "trace-mock",
  generateSpanId: () => "span-mock",
  injectTraceContext: (argsJson: string) => argsJson,
  publishSpan: vi.fn(async () => false),
  parseSseResponse: (s: string) => s,
  parseSseResponseToObject: (s: string) => JSON.parse(s),
  awaitJobCancel: vi.fn(() => new Promise<void>(() => {})),
  matchesPropagateHeader: () => false,
}));

vi.mock("../http-pool.js", () => ({
  getDispatcher: () => undefined,
}));

const ENDPOINT = "http://producer.local:9000";
const TOOL = "echo";
const CAPABILITY = "echoer";

function jsonResponse(result: unknown): Response {
  const body = JSON.stringify({ jsonrpc: "2.0", id: "x", result });
  return {
    ok: true,
    status: 200,
    statusText: "OK",
    text: async () => body,
    headers: {
      get: (name: string) =>
        name.toLowerCase() === "content-type" ? "application/json" : null,
    },
  } as unknown as Response;
}

describe("callMcpTool effective-timeout guard (buffered path)", () => {
  let originalFetch: typeof fetch;

  beforeEach(() => {
    originalFetch = globalThis.fetch;
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it("does not abort-immediately when timeout is 0 (falls back to default)", async () => {
    let aborted = false;
    const fetchMock = vi.fn(async (_url: string, init: RequestInit) => {
      const signal = init.signal as AbortSignal | undefined;
      // Yield a couple of microtasks + a macrotask so any setTimeout(…, 0)
      // abort would have had a chance to fire before we resolve.
      await new Promise((resolve) => setTimeout(resolve, 5));
      if (signal?.aborted) {
        aborted = true;
      }
      return jsonResponse({ content: [{ type: "text", text: "ok" }] });
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const options: CallOptions = { ...DEFAULT_CALL_OPTIONS, timeout: 0 };
    const result = await callMcpTool(ENDPOINT, TOOL, { foo: 1 }, options, CAPABILITY);

    expect(aborted).toBe(false);
    expect(result).toBe("ok");
  });

  it("does not abort-immediately when timeout is negative", async () => {
    let aborted = false;
    const fetchMock = vi.fn(async (_url: string, init: RequestInit) => {
      const signal = init.signal as AbortSignal | undefined;
      await new Promise((resolve) => setTimeout(resolve, 5));
      if (signal?.aborted) {
        aborted = true;
      }
      return jsonResponse({ content: [{ type: "text", text: "ok" }] });
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const options: CallOptions = { ...DEFAULT_CALL_OPTIONS, timeout: -100 };
    const result = await callMcpTool(ENDPOINT, TOOL, { foo: 1 }, options, CAPABILITY);

    expect(aborted).toBe(false);
    expect(result).toBe("ok");
  });
});
