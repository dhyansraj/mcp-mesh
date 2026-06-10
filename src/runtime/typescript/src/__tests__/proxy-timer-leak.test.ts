/**
 * Regression tests for #1163 LOW-5 — callMcpTool's abort timer.
 *
 * Previously `clearTimeout(timeoutId)` ran only after `fetch` RESOLVED:
 *   (a) on fetch rejection the timer stayed armed until effectiveTimeout
 *       elapsed — one leaked timer per retry attempt;
 *   (b) because the timer cleared as soon as headers arrived, the body
 *       read (response.text() / SSE) was unbounded by the call timeout.
 *
 * The fix clears the timer in a per-attempt `finally`, keeping the
 * controller armed until the body is fully consumed — so an
 * over-deadline body read aborts and surfaces through the existing
 * isTimeoutError path ("MCP call timed out after Xms").
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

function abortError(): Error {
  const err = new Error("This operation was aborted");
  err.name = "AbortError";
  return err;
}

describe("callMcpTool abort-timer lifecycle (#1163 LOW-5)", () => {
  let originalFetch: typeof fetch;

  beforeEach(() => {
    originalFetch = globalThis.fetch;
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("clears the abort timer when fetch rejects (no leaked timer per attempt)", async () => {
    vi.useFakeTimers();

    const fetchMock = vi.fn(async () => {
      throw new TypeError("fetch failed: connection refused");
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const options: CallOptions = {
      ...DEFAULT_CALL_OPTIONS,
      timeout: 30_000,
      maxAttempts: 1,
    };

    await expect(
      callMcpTool(ENDPOINT, TOOL, { foo: 1 }, options, CAPABILITY),
    ).rejects.toThrow(/connection refused/);

    // Before the fix the 30s abort timer stayed armed after the
    // rejection; with the per-attempt finally it is cleared.
    expect(vi.getTimerCount()).toBe(0);
  });

  it("aborts an over-deadline body read and surfaces it as the timeout path", async () => {
    const fetchMock = vi.fn(async (_url: string, init: RequestInit) => {
      const signal = init.signal as AbortSignal | undefined;
      return {
        ok: true,
        status: 200,
        statusText: "OK",
        headers: {
          get: (name: string) =>
            name.toLowerCase() === "content-type" ? "application/json" : null,
        },
        // Body read never resolves on its own — only rejects when the
        // call-timeout abort fires (mirrors a stalled producer socket).
        text: () =>
          new Promise<string>((_resolve, reject) => {
            if (signal?.aborted) {
              reject(abortError());
              return;
            }
            signal?.addEventListener("abort", () => reject(abortError()));
          }),
      } as unknown as Response;
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const options: CallOptions = {
      ...DEFAULT_CALL_OPTIONS,
      timeout: 50,
      maxAttempts: 1,
    };

    // Must reject with the timeout message (isTimeoutError path), not
    // hang forever waiting on the body.
    await expect(
      callMcpTool(ENDPOINT, TOOL, { foo: 1 }, options, CAPABILITY),
    ).rejects.toThrow(/MCP call timed out after 50ms/);
    expect(fetchMock).toHaveBeenCalledTimes(1); // timeout is non-retryable
  });
});
