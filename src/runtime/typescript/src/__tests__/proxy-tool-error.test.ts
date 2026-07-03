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

  it("resolves an empty-content SSE result as null (#1250)", async () => {
    // Behavior change: an empty content array means "no value" (null), not "".
    mockFetch(() => sseResponse([{ result: { content: [] } }]));

    const value = await callMcpTool(
      ENDPOINT, TOOL, { a: 1 }, DEFAULT_CALL_OPTIONS, CAPABILITY
    );
    expect(value).toBeNull();
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

  it("still publishes exactly one error span for genuine SSE tool errors", async () => {
    // Counterpart guard: the abort fix must not stop non-abort SSE-reader
    // errors from being accounted. Since #1202, the post-loop aggregate is
    // the single publisher: one span, carrying the precise tool-error
    // message, nothing mislabeled "timeout".
    mockFetch(() => sseResponse([{ result: TOOL_ERROR_RESULT }]));

    await expect(
      runWithTraceContext({ traceId: "trace-toolerr", parentSpanId: null }, () =>
        callMcpTool(ENDPOINT, TOOL, { a: 1 }, DEFAULT_CALL_OPTIONS, CAPABILITY)
      )
    ).rejects.toThrow("MCP tool error: boom: division by zero");

    const calls = vi.mocked(publishTraceSpan).mock.calls;
    expect(calls.length).toBe(1);
    expect(calls[0][0]).toMatchObject({
      success: false,
      error: "MCP tool error: boom: division by zero",
    });
    expect(calls.some((c) => c[0].error === "timeout")).toBe(false);
  });
});

describe("callMcpTool per-call span accounting (#1202)", () => {
  let originalFetch: typeof fetch;

  beforeEach(() => {
    originalFetch = globalThis.fetch;
    vi.mocked(publishTraceSpan).mockClear();
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it("single failed call (maxAttempts=1) publishes exactly ONE error span", async () => {
    // Regression: the JSON-RPC error branch used to publish a per-attempt
    // error span AND the post-loop aggregate published a second one — two
    // span records sharing one spanId for a single failed call.
    mockFetch(() => jsonResponse({ error: { code: -32603, message: "internal failure" } }));

    await expect(
      runWithTraceContext({ traceId: "trace-1202-a", parentSpanId: null }, () =>
        callMcpTool(ENDPOINT, TOOL, { a: 1 }, DEFAULT_CALL_OPTIONS, CAPABILITY)
      )
    ).rejects.toThrow("MCP error: internal failure");

    expect(publishTraceSpan).toHaveBeenCalledTimes(1);
    const span = vi.mocked(publishTraceSpan).mock.calls[0][0];
    expect(span).toMatchObject({
      spanId: "span-mock",
      success: false,
      error: "MCP error: internal failure",
    });
    // Single-attempt spans don't carry attempts info
    expect(span.callAttempts).toBeUndefined();
    // The response body size (formerly only on the per-attempt span) is
    // folded into the aggregate.
    expect(span.responseBytes).toBeGreaterThan(0);
  });

  it("exhausted retries (maxAttempts=3) publish exactly ONE error span carrying attempts info", async () => {
    const fetchMock = vi.fn(async () => jsonResponse({ result: TOOL_ERROR_RESULT }));
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    await expect(
      runWithTraceContext({ traceId: "trace-1202-b", parentSpanId: null }, () =>
        callMcpTool(
          ENDPOINT,
          TOOL,
          { a: 1 },
          { ...DEFAULT_CALL_OPTIONS, maxAttempts: 3, retryDelay: 1 },
          CAPABILITY
        )
      )
    ).rejects.toThrow("MCP tool error: boom: division by zero");

    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(publishTraceSpan).toHaveBeenCalledTimes(1);
    expect(vi.mocked(publishTraceSpan).mock.calls[0][0]).toMatchObject({
      success: false,
      error: "MCP tool error: boom: division by zero",
      callAttempts: 3,
    });
  });

  it("success after retry publishes exactly ONE success span (attempts noted, no error spans)", async () => {
    let call = 0;
    const fetchMock = vi.fn(async () => {
      call += 1;
      return call === 1
        ? jsonResponse({ error: { code: -32603, message: "transient failure" } })
        : jsonResponse({ result: { content: [{ type: "text", text: "fine" }] } });
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const value = await runWithTraceContext(
      { traceId: "trace-1202-c", parentSpanId: null },
      () =>
        callMcpTool(
          ENDPOINT,
          TOOL,
          { a: 1 },
          { ...DEFAULT_CALL_OPTIONS, maxAttempts: 2, retryDelay: 1 },
          CAPABILITY
        )
    );

    expect(value).toBe("fine");
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(publishTraceSpan).toHaveBeenCalledTimes(1);
    expect(vi.mocked(publishTraceSpan).mock.calls[0][0]).toMatchObject({
      success: true,
      error: null,
      callAttempts: 2,
    });
  });

  it("first-attempt success publishes one success span without attempts info", async () => {
    mockFetch(() => jsonResponse({ result: { content: [{ type: "text", text: "fine" }] } }));

    const value = await runWithTraceContext(
      { traceId: "trace-1202-d", parentSpanId: null },
      () => callMcpTool(ENDPOINT, TOOL, { a: 1 }, DEFAULT_CALL_OPTIONS, CAPABILITY)
    );

    expect(value).toBe("fine");
    expect(publishTraceSpan).toHaveBeenCalledTimes(1);
    const span = vi.mocked(publishTraceSpan).mock.calls[0][0];
    expect(span).toMatchObject({ success: true, error: null });
    expect(span.callAttempts).toBeUndefined();
  });

  it("timeout on attempt 2 (after a retried generic failure) publishes ONE timeout span with callAttempts: 2", async () => {
    // The abort/timeout path is non-retryable and publishes immediately from
    // the catch — but when it strikes on a later attempt, its span must still
    // carry the total attempts the call burned, not look like a first-try
    // timeout.
    let call = 0;
    const fetchMock = vi.fn(async () => {
      call += 1;
      if (call === 1) {
        return jsonResponse({ error: { code: -32603, message: "transient failure" } });
      }
      throw new DOMException("This operation was aborted", "AbortError");
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    await expect(
      runWithTraceContext({ traceId: "trace-1202-e", parentSpanId: null }, () =>
        callMcpTool(
          ENDPOINT,
          TOOL,
          { a: 1 },
          { ...DEFAULT_CALL_OPTIONS, maxAttempts: 3, retryDelay: 1 },
          CAPABILITY
        )
      )
    ).rejects.toThrow(`MCP call timed out after ${DEFAULT_CALL_OPTIONS.timeout}ms`);

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(publishTraceSpan).toHaveBeenCalledTimes(1);
    expect(vi.mocked(publishTraceSpan).mock.calls[0][0]).toMatchObject({
      success: false,
      error: "timeout",
      callAttempts: 2,
    });
  });

  it("SSE success after retry publishes exactly ONE success span with callAttempts: 2", async () => {
    // The SSE success branch has its own publish site; it must carry the
    // same attempts accounting as the JSON branch.
    let call = 0;
    const fetchMock = vi.fn(async () => {
      call += 1;
      return call === 1
        ? jsonResponse({ error: { code: -32603, message: "transient failure" } })
        : sseResponse([{ result: { content: [{ type: "text", text: "fine" }] } }]);
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const value = await runWithTraceContext(
      { traceId: "trace-1202-f", parentSpanId: null },
      () =>
        callMcpTool(
          ENDPOINT,
          TOOL,
          { a: 1 },
          { ...DEFAULT_CALL_OPTIONS, maxAttempts: 2, retryDelay: 1 },
          CAPABILITY
        )
    );

    expect(value).toBe("fine");
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(publishTraceSpan).toHaveBeenCalledTimes(1);
    expect(vi.mocked(publishTraceSpan).mock.calls[0][0]).toMatchObject({
      success: true,
      error: null,
      callAttempts: 2,
    });
  });
});
