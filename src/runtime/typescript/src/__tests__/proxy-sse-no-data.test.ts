/**
 * Unit tests for SSE no-data/comment-only EOF handling in callMcpTool (#1201).
 *
 * When a producer holds a response past the proxy's X-Mesh-Timeout budget,
 * the registry proxy cuts the exchange with a clean EOF whose accumulated
 * body may be nothing but sse-starlette keepalive comment frames
 * (`: ping - <ts>`). Per the SSE spec, ":"-prefixed comment frames must be
 * ignored — and a stream that ends with ZERO result frames is a cut
 * exchange that must reject, never resolve as an empty-string success
 * (which would poison LLM tool loops and record success spans).
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { callMcpTool, DEFAULT_CALL_OPTIONS } from "../proxy.js";

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
const TOOL = "slow_tool";
const CAPABILITY = "slow_capability";

/** Build a Response streaming the given raw SSE chunks verbatim. */
function rawSseResponse(chunks: string[]): Response {
  const encoder = new TextEncoder();
  let i = 0;
  const stream = new ReadableStream<Uint8Array>({
    pull(controller) {
      if (i < chunks.length) {
        controller.enqueue(encoder.encode(chunks[i]));
        i += 1;
      } else {
        controller.close();
      }
    },
  });
  return {
    ok: true,
    status: 200,
    statusText: "OK",
    body: stream,
    headers: {
      get: (name: string) =>
        name.toLowerCase() === "content-type" ? "text/event-stream" : null,
    },
  } as unknown as Response;
}

function mockFetch(makeResponse: () => Response): ReturnType<typeof vi.fn> {
  // Fresh Response per call so retries don't reuse a consumed SSE body.
  const fetchMock = vi.fn(async () => makeResponse());
  globalThis.fetch = fetchMock as unknown as typeof fetch;
  return fetchMock;
}

const RESULT_FRAME = `event: message\ndata: ${JSON.stringify({
  jsonrpc: "2.0",
  id: "x",
  result: { content: [{ type: "text", text: "fine" }] },
})}\n\n`;

describe("callMcpTool SSE no-data EOF handling (#1201)", () => {
  let originalFetch: typeof fetch;

  beforeEach(() => {
    originalFetch = globalThis.fetch;
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it("rejects a comment-only stream (keepalive ping then proxy cut)", async () => {
    mockFetch(() => rawSseResponse([": ping - 2026-06-09 12:00:00+00:00\r\n\r\n"]));

    await expect(
      callMcpTool(ENDPOINT, TOOL, {}, DEFAULT_CALL_OPTIONS, CAPABILITY)
    ).rejects.toThrow("ended without a result frame");
  });

  it("rejects a fully empty stream (zero bytes before EOF)", async () => {
    mockFetch(() => rawSseResponse([]));

    await expect(
      callMcpTool(ENDPOINT, TOOL, {}, DEFAULT_CALL_OPTIONS, CAPABILITY)
    ).rejects.toThrow("ended without a result frame");
  });

  it("rejects a notifications-only stream that never delivers the result", async () => {
    const notification = `event: message\ndata: ${JSON.stringify({
      jsonrpc: "2.0",
      method: "notifications/progress",
      params: { progressToken: "t", message: "working..." },
    })}\n\n`;
    mockFetch(() => rawSseResponse([notification]));

    await expect(
      callMcpTool(ENDPOINT, TOOL, {}, DEFAULT_CALL_OPTIONS, CAPABILITY)
    ).rejects.toThrow("ended without a result frame");
  });

  it("ignores comment frames interleaved with a real result frame", async () => {
    mockFetch(() =>
      rawSseResponse([": ping - keepalive 1\r\n\r\n", RESULT_FRAME, ": ping - keepalive 2\r\n\r\n"])
    );

    const value = await callMcpTool(ENDPOINT, TOOL, {}, DEFAULT_CALL_OPTIONS, CAPABILITY);
    expect(value).toBe("fine");
  });

  it("still extracts a result frame whose final line lacks a trailing newline", async () => {
    // A proxy cut can drop the final newline; the leftover-buffer drain must
    // still parse a complete data line.
    mockFetch(() => rawSseResponse([RESULT_FRAME.trimEnd()]));

    const value = await callMcpTool(ENDPOINT, TOOL, {}, DEFAULT_CALL_OPTIONS, CAPABILITY);
    expect(value).toBe("fine");
  });

  it("normal SSE result path unchanged (sanity)", async () => {
    mockFetch(() => rawSseResponse([RESULT_FRAME]));

    const value = await callMcpTool(ENDPOINT, TOOL, {}, DEFAULT_CALL_OPTIONS, CAPABILITY);
    expect(value).toBe("fine");
  });

  it("proxy timeout marker + no result frame → timeout-classified, not retried", async () => {
    // The registry proxy's terminal `: mesh-proxy-timeout budget=<N>s`
    // comment frame (#1201) marks the X-Mesh-Timeout budget as spent.
    // Classification must match local abort-timeouts: a single attempt even
    // with retries configured (a retry would burn another full budget), and
    // a message naming the proxy budget.
    const fetchMock = mockFetch(() =>
      rawSseResponse([": ping - keepalive\r\n\r\n", ": mesh-proxy-timeout budget=30s\n\n"])
    );

    await expect(
      callMcpTool(ENDPOINT, TOOL, {}, { ...DEFAULT_CALL_OPTIONS, maxAttempts: 2 }, CAPABILITY)
    ).rejects.toThrow(/timed out: registry proxy X-Mesh-Timeout budget \(30s\)/);

    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("proxy timeout marker after a complete result frame → data wins", async () => {
    // A marker can only follow a complete frame on a pathological proxy, but
    // the contract stays: a delivered result is a success, marker or not.
    mockFetch(() =>
      rawSseResponse([RESULT_FRAME, ": mesh-proxy-timeout budget=30s\n\n"])
    );

    const value = await callMcpTool(ENDPOINT, TOOL, {}, DEFAULT_CALL_OPTIONS, CAPABILITY);
    expect(value).toBe("fine");
  });

  it("no marker → generic no-result error stays retryable", async () => {
    const fetchMock = mockFetch(() => rawSseResponse([": ping - keepalive\r\n\r\n"]));

    await expect(
      callMcpTool(ENDPOINT, TOOL, {}, { ...DEFAULT_CALL_OPTIONS, maxAttempts: 2, retryDelay: 1 }, CAPABILITY)
    ).rejects.toThrow("ended without a result frame");

    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});
