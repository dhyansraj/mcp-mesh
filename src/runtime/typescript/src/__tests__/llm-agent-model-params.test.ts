/**
 * Unit tests for the `modelParams` escape-hatch — issue #1019.
 *
 * The TS SDK exposes a typed option surface (`maxOutputTokens`, `temperature`,
 * `topP`, `stop`) that maps to wire `model_params` keys. For vendor-specific
 * kwargs that the typed surface doesn't expose (e.g., Gemini `thinking_config`,
 * Anthropic `output_config`, OpenAI `reasoning_effort`) callers can pass an
 * arbitrary dict via `options.modelParams`. The dict is merged into the wire
 * `model_params` BEFORE typed fields, so typed options always win on collision
 * (keeping the typed surface authoritative).
 *
 * Covers both the buffered (`complete()`) and the streaming (`streamComplete()`)
 * paths since both build `model_params` independently.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

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

import { MeshDelegatedProvider } from "../llm-agent.js";
import type { LlmMessage } from "../types.js";

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

function makeMockResponse(blocks: string[]): Response {
  return {
    ok: true,
    status: 200,
    statusText: "OK",
    body: makeSseStream(blocks),
    headers: {
      get: (name: string) =>
        name.toLowerCase() === "content-type" ? "text/event-stream" : null,
    },
  } as unknown as Response;
}

const ENDPOINT = "http://provider.local:9001";
const FN_BUFFERED = "process_chat";
const FN_STREAM = "process_chat_stream";

// ----------------------------------------------------------------------------
// complete() — buffered path
// ----------------------------------------------------------------------------

describe("MeshDelegatedProvider.complete() — modelParams escape hatch", () => {
  let originalFetch: typeof fetch;

  beforeEach(() => {
    originalFetch = globalThis.fetch;
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  function mockJsonResponse(body: object): Response {
    return {
      ok: true,
      status: 200,
      statusText: "OK",
      headers: {
        get: (name: string) =>
          name.toLowerCase() === "content-type" ? "application/json" : null,
      },
      text: async () => JSON.stringify(body),
      json: async () => body,
    } as unknown as Response;
  }

  function mcpToolResponse(payload: object) {
    return {
      jsonrpc: "2.0",
      id: 1,
      result: {
        content: [{ type: "text", text: JSON.stringify(payload) }],
      },
    };
  }

  // complete() expects the MCP content[0].text payload to be the
  // mesh-provider shape: { role, content, tool_calls?, _mesh_usage? }
  const STUB_COMPLETION = { role: "assistant", content: "ok" };

  it("merges modelParams keys into the wire request's model_params", async () => {
    let capturedBody: string | undefined;
    const fetchMock = vi.fn(async (_url: string, init: RequestInit) => {
      capturedBody = init.body as string;
      return mockJsonResponse(mcpToolResponse(STUB_COMPLETION));
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const provider = new MeshDelegatedProvider(ENDPOINT, FN_BUFFERED, false);
    const messages: LlmMessage[] = [{ role: "user", content: "hi" }];

    await provider.complete("anthropic/claude-sonnet-4-5", messages, undefined, {
      maxOutputTokens: 256,
      modelParams: {
        thinking_config: { thinking_budget: 0 },
        reasoning_effort: "high",
      },
    });

    const body = JSON.parse(capturedBody!);
    const request = body.params.arguments.request as Record<string, unknown>;
    const modelParams = request.model_params as Record<string, unknown>;
    expect(modelParams.thinking_config).toEqual({ thinking_budget: 0 });
    expect(modelParams.reasoning_effort).toBe("high");
    // Typed fields still flow through
    expect(modelParams.max_tokens).toBe(256);
    expect(modelParams.model).toBe("anthropic/claude-sonnet-4-5");
  });

  it("typed options win over modelParams on collision", async () => {
    let capturedBody: string | undefined;
    const fetchMock = vi.fn(async (_url: string, init: RequestInit) => {
      capturedBody = init.body as string;
      return mockJsonResponse(mcpToolResponse(STUB_COMPLETION));
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const provider = new MeshDelegatedProvider(ENDPOINT, FN_BUFFERED, false);
    const messages: LlmMessage[] = [{ role: "user", content: "hi" }];

    await provider.complete("anthropic/claude-sonnet-4-5", messages, undefined, {
      temperature: 0.5,
      maxOutputTokens: 200,
      modelParams: {
        temperature: 0.9, // caller tried to set via escape hatch — typed wins
        max_tokens: 999,  // caller used the wire-name; typed maxOutputTokens wins
        thinking_config: { thinking_budget: 0 },
      },
    });

    const body = JSON.parse(capturedBody!);
    const modelParams = body.params.arguments.request.model_params as Record<string, unknown>;
    expect(modelParams.temperature).toBe(0.5);
    expect(modelParams.max_tokens).toBe(200);
    // Untouched vendor-specific keys flow through
    expect(modelParams.thinking_config).toEqual({ thinking_budget: 0 });
  });

  it("vendor-specific keys flow through untouched (no key translation)", async () => {
    let capturedBody: string | undefined;
    const fetchMock = vi.fn(async (_url: string, init: RequestInit) => {
      capturedBody = init.body as string;
      return mockJsonResponse(mcpToolResponse(STUB_COMPLETION));
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const provider = new MeshDelegatedProvider(ENDPOINT, FN_BUFFERED, false);
    const messages: LlmMessage[] = [{ role: "user", content: "hi" }];

    await provider.complete("anthropic/claude-sonnet-4-5", messages, undefined, {
      modelParams: {
        output_config: { format: { type: "json_schema", schema: { type: "object" } } },
        extra_headers: { "x-vendor-flag": "1" },
      },
    });

    const body = JSON.parse(capturedBody!);
    const modelParams = body.params.arguments.request.model_params as Record<string, unknown>;
    expect(modelParams.output_config).toEqual({
      format: { type: "json_schema", schema: { type: "object" } },
    });
    expect(modelParams.extra_headers).toEqual({ "x-vendor-flag": "1" });
  });

  it("absent modelParams → behavior unchanged (no model_params keys leak)", async () => {
    let capturedBody: string | undefined;
    const fetchMock = vi.fn(async (_url: string, init: RequestInit) => {
      capturedBody = init.body as string;
      return mockJsonResponse(mcpToolResponse(STUB_COMPLETION));
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const provider = new MeshDelegatedProvider(ENDPOINT, FN_BUFFERED, false);
    const messages: LlmMessage[] = [{ role: "user", content: "hi" }];

    // No options at all; model="default" so no model_params should be emitted.
    await provider.complete("default", messages);

    const body = JSON.parse(capturedBody!);
    const request = body.params.arguments.request as Record<string, unknown>;
    expect(request.model_params).toBeUndefined();
  });
});

// ----------------------------------------------------------------------------
// streamComplete() — streaming path
// ----------------------------------------------------------------------------

describe("MeshDelegatedProvider.streamComplete() — modelParams escape hatch", () => {
  let originalFetch: typeof fetch;

  beforeEach(() => {
    originalFetch = globalThis.fetch;
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  async function drain(gen: AsyncGenerator<string, void, void>): Promise<string[]> {
    const out: string[] = [];
    for await (const c of gen) out.push(c);
    return out;
  }

  it("merges modelParams into the streaming request and lets typed options win", async () => {
    let capturedBody: string | undefined;
    const fetchMock = vi.fn(async (_url: string, init: RequestInit) => {
      capturedBody = init.body as string;
      const body = JSON.parse(capturedBody);
      const reqId = body.id as string;
      return makeMockResponse([
        sseEvent({ jsonrpc: "2.0", id: reqId, result: { content: [{ type: "text", text: "" }] } }),
      ]);
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const provider = new MeshDelegatedProvider(ENDPOINT, FN_STREAM, false);
    const messages: LlmMessage[] = [{ role: "user", content: "hi" }];

    await drain(provider.streamComplete("anthropic/claude-sonnet-4-5", messages, undefined, {
      temperature: 0.4,
      modelParams: {
        temperature: 0.9, // typed wins
        thinking_config: { thinking_budget: 0 }, // flows through
      },
    }));

    const body = JSON.parse(capturedBody!);
    const modelParams = body.params.arguments.request.model_params as Record<string, unknown>;
    expect(modelParams.temperature).toBe(0.4);
    expect(modelParams.thinking_config).toEqual({ thinking_budget: 0 });
    expect(modelParams.model).toBe("anthropic/claude-sonnet-4-5");
  });
});

// ----------------------------------------------------------------------------
// output_mode override on the wire — issue #1112
// ----------------------------------------------------------------------------

describe("MeshDelegatedProvider — output_mode override on the wire (#1112)", () => {
  let originalFetch: typeof fetch;

  beforeEach(() => {
    originalFetch = globalThis.fetch;
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  function mockJsonResponse(body: object): Response {
    return {
      ok: true,
      status: 200,
      statusText: "OK",
      headers: {
        get: (name: string) =>
          name.toLowerCase() === "content-type" ? "application/json" : null,
      },
      text: async () => JSON.stringify(body),
      json: async () => body,
    } as unknown as Response;
  }

  function mcpToolResponse(payload: object) {
    return {
      jsonrpc: "2.0",
      id: 1,
      result: { content: [{ type: "text", text: JSON.stringify(payload) }] },
    };
  }

  const STUB_COMPLETION = { role: "assistant", content: "ok" };

  async function captureComplete(
    options: Parameters<MeshDelegatedProvider["complete"]>[3]
  ): Promise<Record<string, unknown> | undefined> {
    let capturedBody: string | undefined;
    const fetchMock = vi.fn(async (_url: string, init: RequestInit) => {
      capturedBody = init.body as string;
      return mockJsonResponse(mcpToolResponse(STUB_COMPLETION));
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const provider = new MeshDelegatedProvider(ENDPOINT, FN_BUFFERED, false);
    const messages: LlmMessage[] = [{ role: "user", content: "hi" }];
    await provider.complete("anthropic/claude-sonnet-4-5", messages, undefined, options);

    const body = JSON.parse(capturedBody!);
    return body.params.arguments.request.model_params as Record<string, unknown> | undefined;
  }

  it("includes model_params.output_mode when outputMode is explicitly set", async () => {
    const modelParams = await captureComplete({ outputMode: "strict" });
    expect(modelParams?.output_mode).toBe("strict");
  });

  it("omits model_params.output_mode when outputMode is unset (default path)", async () => {
    const modelParams = await captureComplete({ maxOutputTokens: 128 });
    expect(modelParams).toBeDefined();
    expect("output_mode" in (modelParams ?? {})).toBe(false);
  });

  it("typed outputMode beats escape-hatch modelParams.output_mode", async () => {
    const modelParams = await captureComplete({
      outputMode: "hint",
      modelParams: { output_mode: "strict" },
    });
    expect(modelParams?.output_mode).toBe("hint");
  });

  it("streamComplete includes output_mode when explicitly set", async () => {
    let capturedBody: string | undefined;
    const fetchMock = vi.fn(async (_url: string, init: RequestInit) => {
      capturedBody = init.body as string;
      const body = JSON.parse(capturedBody);
      const reqId = body.id as string;
      return makeMockResponse([
        sseEvent({ jsonrpc: "2.0", id: reqId, result: { content: [{ type: "text", text: "" }] } }),
      ]);
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const provider = new MeshDelegatedProvider(ENDPOINT, FN_STREAM, false);
    const messages: LlmMessage[] = [{ role: "user", content: "hi" }];
    const gen = provider.streamComplete("anthropic/claude-sonnet-4-5", messages, undefined, {
      outputMode: "text",
    });
    for await (const _ of gen) { /* drain */ }

    const body = JSON.parse(capturedBody!);
    const modelParams = body.params.arguments.request.model_params as Record<string, unknown>;
    expect(modelParams.output_mode).toBe("text");
  });
});
