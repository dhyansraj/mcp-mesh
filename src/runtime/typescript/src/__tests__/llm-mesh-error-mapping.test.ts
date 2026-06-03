/**
 * Unit tests for #1116 item-2 regression fixes: routing TS LLM calls through
 * the shared callMcpTool must preserve the behavior the hand-rolled paths had.
 *
 * Covered:
 *  - Fix 1: MeshDelegatedProvider.complete() maps a timeout to LLMAPIError(408).
 *           callMcpTool re-throws the AbortError as a plain Error ("MCP call
 *           timed out after <N>ms"), so complete() now matches on the message.
 *  - Fix 2: callMcpTool surfaces a tool-level isError result by throwing, so
 *           complete() re-wraps it into LLMAPIError and createLlmToolProxy into
 *           ToolExecutionError instead of returning the error text as success.
 *  - Fix 3: createLlmToolProxy returns null (not "") when the tool returns no
 *           content.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { MeshDelegatedProvider, createLlmToolProxy } from "../llm-agent.js";
import { LLMAPIError, ToolExecutionError } from "../errors.js";

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

const ENDPOINT = "http://provider.local:9000";
const FUNCTION = "mesh_complete";

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

describe("MeshDelegatedProvider.complete() error mapping (#1116 item-2)", () => {
  let originalFetch: typeof fetch;

  beforeEach(() => {
    originalFetch = globalThis.fetch;
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    vi.restoreAllMocks();
    delete process.env.MESH_PROVIDER_TIMEOUT_MS;
  });

  it("Fix 1: maps a timeout to LLMAPIError with status 408", async () => {
    process.env.MESH_PROVIDER_TIMEOUT_MS = "10";
    // fetch hangs until aborted; reject with AbortError when the signal fires.
    const fetchMock = vi.fn((_url: string, init: RequestInit) => {
      const signal = init.signal as AbortSignal;
      return new Promise<Response>((_resolve, reject) => {
        signal.addEventListener("abort", () => {
          const err = new Error("aborted");
          err.name = "AbortError";
          reject(err);
        });
      });
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const provider = new MeshDelegatedProvider(ENDPOINT, FUNCTION);
    const err = await provider
      .complete("mesh-delegated", [{ role: "user", content: "hi" }])
      .then(() => null)
      .catch((e) => e);

    expect(err).toBeInstanceOf(LLMAPIError);
    expect((err as LLMAPIError).statusCode).toBe(408);
    expect((err as LLMAPIError).message).toMatch(/timed out/i);
  });

  it("Fix 2: maps a tool-level isError result to LLMAPIError(0)", async () => {
    const fetchMock = vi.fn(async () =>
      jsonResponse({
        isError: true,
        content: [{ type: "text", text: "provider blew up" }],
      })
    );
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const provider = new MeshDelegatedProvider(ENDPOINT, FUNCTION);
    const err = await provider
      .complete("mesh-delegated", [{ role: "user", content: "hi" }])
      .then(() => null)
      .catch((e) => e);

    expect(err).toBeInstanceOf(LLMAPIError);
    expect((err as LLMAPIError).statusCode).toBe(0);
    expect((err as LLMAPIError).message).toContain("provider blew up");
  });
});

describe("createLlmToolProxy error/empty mapping (#1116 item-2)", () => {
  let originalFetch: typeof fetch;

  const toolInfo = {
    functionName: "do_thing",
    capability: "doer",
    endpoint: ENDPOINT,
    agentId: "agent-1",
  };

  beforeEach(() => {
    originalFetch = globalThis.fetch;
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it("Fix 2: maps a tool-level isError result to ToolExecutionError", async () => {
    const fetchMock = vi.fn(async () =>
      jsonResponse({
        isError: true,
        content: [{ type: "text", text: "tool failed" }],
      })
    );
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const proxy = createLlmToolProxy(toolInfo);
    const err = await proxy({}).then(() => null).catch((e) => e);

    expect(err).toBeInstanceOf(ToolExecutionError);
    expect((err as Error).message).toContain("tool failed");
  });

  it("Fix 3: returns null when the tool returns no content", async () => {
    const fetchMock = vi.fn(async () => jsonResponse({ content: [] }));
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const proxy = createLlmToolProxy(toolInfo);
    const result = await proxy({});

    expect(result).toBeNull();
  });

  it("returns parsed JSON for non-empty content", async () => {
    const fetchMock = vi.fn(async () =>
      jsonResponse({ content: [{ type: "text", text: '{"ok":true}' }] })
    );
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const proxy = createLlmToolProxy(toolInfo);
    const result = await proxy({});

    expect(result).toEqual({ ok: true });
  });
});
