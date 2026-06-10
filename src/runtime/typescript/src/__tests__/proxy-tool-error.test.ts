/**
 * Unit tests for transport-symmetric tool-error surfacing in callMcpTool (#1161).
 *
 * FastMCP streamable-HTTP commonly answers ``tools/call`` with
 * ``text/event-stream``, so SSE is the hot path for TS→TS agent calls. A
 * producer tool that throws returns a CallToolResult with ``isError: true``;
 * BOTH the JSON and SSE response paths must throw the same
 * ``MCP tool error: …`` shape instead of returning the error text as a
 * successful result (which would poison LLM tool-execution loops and record
 * success spans).
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { callMcpTool, DEFAULT_CALL_OPTIONS, runWithTraceContext } from "../proxy.js";
import { publishTraceSpan } from "../tracing.js";

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

// Spy on publishTraceSpan so span-accounting tests can count emitted spans.
// The real implementation gates on initTracing() module state, which unit
// tests can't reach; everything else in tracing.js stays real.
vi.mock("../tracing.js", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../tracing.js")>();
  return {
    ...actual,
    publishTraceSpan: vi.fn(async () => true),
  };
});

vi.mock("../http-pool.js", () => ({
  getDispatcher: () => undefined,
}));

const ENDPOINT = "http://producer.local:9000";
const TOOL = "explode";
const CAPABILITY = "exploder";

function jsonResponse(envelope: object): Response {
  const body = JSON.stringify({ jsonrpc: "2.0", id: "x", ...envelope });
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

/** Build a Response whose body is a ReadableStream emitting SSE event blocks. */
function sseResponse(envelopes: object[]): Response {
  const encoder = new TextEncoder();
  const blocks = envelopes.map(
    (e) => `event: message\ndata: ${JSON.stringify({ jsonrpc: "2.0", id: "x", ...e })}\n\n`
  );
  let i = 0;
  const stream = new ReadableStream<Uint8Array>({
    pull(controller) {
      if (i < blocks.length) {
        controller.enqueue(encoder.encode(blocks[i]));
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

/**
 * Build a Response whose SSE body errors mid-read with the given error —
 * models a job-cancel or timeout firing `controller.abort()` while the
 * body is being consumed.
 */
function sseAbortingResponse(err: unknown): Response {
  const encoder = new TextEncoder();
  let pulled = false;
  const stream = new ReadableStream<Uint8Array>({
    pull(controller) {
      if (!pulled) {
        pulled = true;
        controller.enqueue(encoder.encode("event: message\n"));
      } else {
        controller.error(err);
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

function mockFetch(makeResponse: () => Response): void {
  // Fresh Response per call so retries don't reuse a consumed SSE body.
  const fetchMock = vi.fn(async () => makeResponse());
  globalThis.fetch = fetchMock as unknown as typeof fetch;
}

const TOOL_ERROR_RESULT = {
  isError: true,
  content: [{ type: "text", text: "boom: division by zero" }],
};

describe("callMcpTool tool-level error surfacing (isError)", () => {
  let originalFetch: typeof fetch;

  beforeEach(() => {
    originalFetch = globalThis.fetch;
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it("rejects on SSE response with isError: true (same shape as JSON path)", async () => {
    mockFetch(() => sseResponse([{ result: TOOL_ERROR_RESULT }]));

    await expect(
      callMcpTool(ENDPOINT, TOOL, { a: 1 }, DEFAULT_CALL_OPTIONS, CAPABILITY)
    ).rejects.toThrow("MCP tool error: boom: division by zero");
  });

  it("rejects on JSON response with isError: true (regression guard)", async () => {
    mockFetch(() => jsonResponse({ result: TOOL_ERROR_RESULT }));

    await expect(
      callMcpTool(ENDPOINT, TOOL, { a: 1 }, DEFAULT_CALL_OPTIONS, CAPABILITY)
    ).rejects.toThrow("MCP tool error: boom: division by zero");
  });

  it("rejects on SSE response carrying a JSON-RPC protocol error", async () => {
    mockFetch(() =>
      sseResponse([{ error: { code: -32603, message: "internal failure" } }])
    );

    await expect(
      callMcpTool(ENDPOINT, TOOL, { a: 1 }, DEFAULT_CALL_OPTIONS, CAPABILITY)
    ).rejects.toThrow("MCP error: internal failure");
  });

  it("resolves a legitimately falsy SSE result identically to the JSON path", async () => {
    // JSON-RPC permits any `result` value, including falsy ones; a truthiness
    // check would silently drop them. Verify SSE and JSON agree.
    mockFetch(() => sseResponse([{ result: 0 }]));
    const sseValue = await callMcpTool(
      ENDPOINT, TOOL, { a: 1 }, DEFAULT_CALL_OPTIONS, CAPABILITY
    );

    mockFetch(() => jsonResponse({ result: 0 }));
    const jsonValue = await callMcpTool(
      ENDPOINT, TOOL, { a: 1 }, DEFAULT_CALL_OPTIONS, CAPABILITY
    );

    expect(sseValue).toBe(jsonValue);
    expect(sseValue).toBe("0");
  });

  it("resolves an empty-content SSE result as empty string", async () => {
    mockFetch(() => sseResponse([{ result: { content: [] } }]));

    const value = await callMcpTool(
      ENDPOINT, TOOL, { a: 1 }, DEFAULT_CALL_OPTIONS, CAPABILITY
    );
    expect(value).toBe("");
  });

  it("still resolves successful SSE results (sanity)", async () => {
    mockFetch(() =>
      sseResponse([{ result: { content: [{ type: "text", text: "fine" }] } }])
    );

    const value = await callMcpTool(
      ENDPOINT, TOOL, { a: 1 }, DEFAULT_CALL_OPTIONS, CAPABILITY
    );
    expect(value).toBe("fine");
  });
});

describe("callMcpTool abort mid-SSE-read span accounting", () => {
  let originalFetch: typeof fetch;

  beforeEach(() => {
    originalFetch = globalThis.fetch;
    vi.mocked(publishTraceSpan).mockClear();
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it("publishes exactly one error span (the outer timeout one) when the body read aborts", async () => {
    // An abort (timeout or job-cancel) surfaces from reader.read() as an
    // AbortError. The SSE catch must NOT publish a span for it — the outer
    // catch owns abort accounting; both publishing would emit two spans
    // with the same spanId, the second mislabeled "timeout".
    const abortErr = new DOMException("This operation was aborted", "AbortError");
    mockFetch(() => sseAbortingResponse(abortErr));

    await expect(
      runWithTraceContext({ traceId: "trace-abort", parentSpanId: null }, () =>
        callMcpTool(ENDPOINT, TOOL, { a: 1 }, DEFAULT_CALL_OPTIONS, CAPABILITY)
      )
    ).rejects.toThrow(`MCP call timed out after ${DEFAULT_CALL_OPTIONS.timeout}ms`);

    expect(publishTraceSpan).toHaveBeenCalledTimes(1);
    expect(vi.mocked(publishTraceSpan).mock.calls[0][0]).toMatchObject({
      success: false,
      error: "timeout",
    });
  });

  it("still publishes the SSE-reader error span for genuine tool errors", async () => {
    // Counterpart guard: the abort fix must not stop non-abort SSE-reader
    // errors from publishing their error span. The first published span
    // carries the precise tool-error message, and nothing is mislabeled
    // "timeout". (A generic post-loop span on exhausted retries is
    // pre-existing JSON-path behavior, deliberately not asserted on.)
    mockFetch(() => sseResponse([{ result: TOOL_ERROR_RESULT }]));

    await expect(
      runWithTraceContext({ traceId: "trace-toolerr", parentSpanId: null }, () =>
        callMcpTool(ENDPOINT, TOOL, { a: 1 }, DEFAULT_CALL_OPTIONS, CAPABILITY)
      )
    ).rejects.toThrow("MCP tool error: boom: division by zero");

    const calls = vi.mocked(publishTraceSpan).mock.calls;
    expect(calls.length).toBeGreaterThanOrEqual(1);
    expect(calls[0][0]).toMatchObject({
      success: false,
      error: "MCP tool error: boom: division by zero",
    });
    expect(calls.some((c) => c[0].error === "timeout")).toBe(false);
  });
});
