/**
 * Unit tests for MeshLlmAgent.stream() — Stage 3 of issue #854.
 *
 * Covers:
 * - Mesh-delegate path: chunks come through from a mocked process_chat_stream
 * - The {request: <MeshLlmRequest>} body shape is preserved
 * - Direct providers throw a clear error pointing the user at mesh-delegate
 * - The createCallable's .stream() exposes the same iterable
 * - Tag-based discrimination: provider tags (including ai.mcpmesh.stream) are
 *   forwarded verbatim to buildLlmAgentSpecs() so the registry resolver can
 *   pick the streaming variant.
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

import {
  MeshLlmAgent,
  MeshDelegatedProvider,
} from "../llm-agent.js";
import type { LlmMessage } from "../types.js";
import { LlmToolRegistry, buildLlmAgentSpecs } from "../llm.js";
import { z } from "zod";

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
const STREAM_TOOL = "process_chat_stream";

describe("MeshDelegatedProvider.streamComplete()", () => {
  let originalFetch: typeof fetch;

  beforeEach(() => {
    originalFetch = globalThis.fetch;
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it("yields each progress chunk and wraps args in {request: <MeshLlmRequest>}", async () => {
    let capturedBody: string | undefined;
    const fetchMock = vi.fn(async (_url: string, init: RequestInit) => {
      capturedBody = init.body as string;
      const body = JSON.parse(capturedBody);
      const token = body.params._meta.progressToken as string;
      const reqId = body.id as string;
      return makeMockResponse([
        sseEvent({
          jsonrpc: "2.0",
          method: "notifications/progress",
          params: { progressToken: token, progress: 1, message: "Hello" },
        }),
        sseEvent({
          jsonrpc: "2.0",
          method: "notifications/progress",
          params: { progressToken: token, progress: 2, message: ", " },
        }),
        sseEvent({
          jsonrpc: "2.0",
          method: "notifications/progress",
          params: { progressToken: token, progress: 3, message: "world!" },
        }),
        sseEvent({
          jsonrpc: "2.0",
          id: reqId,
          result: { content: [{ type: "text", text: "Hello, world!" }] },
        }),
      ]);
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const provider = new MeshDelegatedProvider(ENDPOINT, STREAM_TOOL, false);
    const messages: LlmMessage[] = [{ role: "user", content: "say hi" }];

    const chunks: string[] = [];
    for await (const c of provider.streamComplete("anthropic/claude-sonnet-4-5", messages, undefined, {
      maxOutputTokens: 256,
      temperature: 0.7,
    })) {
      chunks.push(c);
    }

    expect(chunks).toEqual(["Hello", ", ", "world!"]);
    expect(fetchMock).toHaveBeenCalledTimes(1);

    // Wire-format check: body should be tools/call -> process_chat_stream
    // with a {request: {messages, model_params}} arguments object.
    const body = JSON.parse(capturedBody!);
    expect(body.method).toBe("tools/call");
    expect(body.params.name).toBe(STREAM_TOOL);
    expect(typeof body.params._meta.progressToken).toBe("string");

    const args = body.params.arguments as Record<string, unknown>;
    expect(args.request).toBeDefined();
    const request = args.request as Record<string, unknown>;
    expect(request.messages).toEqual(messages);
    const modelParams = request.model_params as Record<string, unknown>;
    expect(modelParams.model).toBe("anthropic/claude-sonnet-4-5");
    expect(modelParams.max_tokens).toBe(256);
    expect(modelParams.temperature).toBe(0.7);
  });

  it("does not emit model_params when no model/options provided", async () => {
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

    const provider = new MeshDelegatedProvider(ENDPOINT, STREAM_TOOL, false);
    const messages: LlmMessage[] = [{ role: "user", content: "hi" }];

    const out: string[] = [];
    for await (const c of provider.streamComplete("default", messages)) {
      out.push(c);
    }
    expect(out).toEqual([]);

    const body = JSON.parse(capturedBody!);
    const args = body.params.arguments as Record<string, unknown>;
    const request = args.request as Record<string, unknown>;
    // model="default" + no options -> no model_params at all
    expect(request.model_params).toBeUndefined();
  });

  it("forwards tools when present and includes parallel_tool_calls when enabled", async () => {
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

    const provider = new MeshDelegatedProvider(ENDPOINT, STREAM_TOOL, true);
    const messages: LlmMessage[] = [{ role: "user", content: "hi" }];
    const tools = [
      {
        type: "function" as const,
        function: { name: "calc", description: "calc", parameters: { type: "object", properties: {} } },
      },
    ];

    const out: string[] = [];
    for await (const c of provider.streamComplete("anthropic/claude-sonnet-4-5", messages, tools)) {
      out.push(c);
    }

    const body = JSON.parse(capturedBody!);
    const request = body.params.arguments.request as Record<string, unknown>;
    expect(request.tools).toEqual(tools);
    expect((request.model_params as Record<string, unknown>).parallel_tool_calls).toBe(true);
  });
});

describe("MeshLlmAgent.stream()", () => {
  let originalFetch: typeof fetch;

  beforeEach(() => {
    originalFetch = globalThis.fetch;
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it("streams chunks from a mesh-delegated provider", async () => {
    const fetchMock = vi.fn(async (_url: string, init: RequestInit) => {
      const body = JSON.parse(init.body as string);
      const token = body.params._meta.progressToken as string;
      const reqId = body.id as string;
      return makeMockResponse([
        sseEvent({
          jsonrpc: "2.0",
          method: "notifications/progress",
          params: { progressToken: token, progress: 1, message: "alpha " },
        }),
        sseEvent({
          jsonrpc: "2.0",
          method: "notifications/progress",
          params: { progressToken: token, progress: 2, message: "beta" },
        }),
        sseEvent({
          jsonrpc: "2.0",
          id: reqId,
          result: { content: [{ type: "text", text: "alpha beta" }] },
        }),
      ]);
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const agent = new MeshLlmAgent({
      functionId: "test.stream",
      provider: { capability: "llm", tags: ["ai.mcpmesh.stream"] },
      maxIterations: 1,
    });

    const chunks: string[] = [];
    for await (const c of agent.stream("hi", {
      tools: [],
      meshProvider: { endpoint: ENDPOINT, functionName: STREAM_TOOL },
    })) {
      chunks.push(c);
    }

    expect(chunks).toEqual(["alpha ", "beta"]);
  });

  it("throws when called on an agent without a meshProvider (direct mode)", async () => {
    const agent = new MeshLlmAgent({
      functionId: "test.direct",
      provider: "claude",
      maxIterations: 1,
    });

    const collect = async () => {
      const out: string[] = [];
      for await (const c of agent.stream("hi", { tools: [] })) {
        out.push(c);
      }
      return out;
    };

    await expect(collect()).rejects.toThrow(/MeshLlmAgent\.stream\(\) requires a mesh-delegated provider/);
    await expect(collect()).rejects.toThrow(/ai\.mcpmesh\.stream/);
  });

  it("createCallable exposes a stream() method that delegates correctly", async () => {
    const fetchMock = vi.fn(async (_url: string, init: RequestInit) => {
      const body = JSON.parse(init.body as string);
      const token = body.params._meta.progressToken as string;
      const reqId = body.id as string;
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
        sseEvent({ jsonrpc: "2.0", id: reqId, result: {} }),
      ]);
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const agent = new MeshLlmAgent({
      functionId: "test.callable",
      provider: { capability: "llm", tags: ["ai.mcpmesh.stream"] },
      maxIterations: 1,
    });
    const callable = agent.createCallable({
      tools: [],
      meshProvider: { endpoint: ENDPOINT, functionName: STREAM_TOOL },
    });

    expect(typeof callable.stream).toBe("function");

    const out: string[] = [];
    for await (const c of callable.stream("ping")) {
      out.push(c);
    }
    expect(out).toEqual(["x", "y"]);
  });

  it("system prompt template is rendered and pushed as the first message", async () => {
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

    const agent = new MeshLlmAgent({
      functionId: "test.sys",
      provider: { capability: "llm", tags: ["ai.mcpmesh.stream"] },
      maxIterations: 1,
      systemPrompt: "You are {{role}}.",
    });

    const out: string[] = [];
    for await (const c of agent.stream("hi", {
      tools: [],
      meshProvider: { endpoint: ENDPOINT, functionName: STREAM_TOOL },
      templateContext: { role: "concise" },
    })) {
      out.push(c);
    }
    expect(out).toEqual([]);

    const body = JSON.parse(capturedBody!);
    const request = body.params.arguments.request as Record<string, unknown>;
    const messages = request.messages as Array<{ role: string; content: string }>;
    expect(messages[0]).toEqual({ role: "system", content: "You are concise." });
    expect(messages[1]).toEqual({ role: "user", content: "hi" });
  });
});

describe("Tag-based discrimination flows through to buildLlmAgentSpecs", () => {
  beforeEach(() => {
    LlmToolRegistry.reset();
  });

  it("forwards provider.tags (including ai.mcpmesh.stream) verbatim in the agent spec", () => {
    const registry = LlmToolRegistry.getInstance();
    registry.register("user.chat_stream", {
      functionId: "user.chat_stream",
      name: "chat_stream",
      capability: "chat_stream",
      description: "stream test",
      version: "1.0.0",
      tags: [],
      provider: { capability: "llm", tags: ["+claude", "ai.mcpmesh.stream"] },
      maxIterations: 1,
      filterMode: "all",
      inputSchema: JSON.stringify({ type: "object" }),
      outputMode: "hint",
      parallelToolCalls: false,
      execute: async () => "ok",
    });

    const specs = buildLlmAgentSpecs();
    expect(specs).toHaveLength(1);
    const parsed = JSON.parse(specs[0].provider);
    // Mesh-delegate object spec is serialized as-is (no `direct` wrapper)
    expect(parsed.capability).toBe("llm");
    expect(parsed.tags).toEqual(["+claude", "ai.mcpmesh.stream"]);
  });

  it("string provider goes through the direct: wrapper (no tag flow path)", () => {
    const registry = LlmToolRegistry.getInstance();
    registry.register("user.chat", {
      functionId: "user.chat",
      name: "chat",
      capability: "chat",
      description: "buffered test",
      version: "1.0.0",
      tags: [],
      provider: "claude",
      maxIterations: 1,
      filterMode: "all",
      inputSchema: JSON.stringify({ type: "object" }),
      outputMode: "hint",
      parallelToolCalls: false,
      execute: async () => "ok",
    });

    const specs = buildLlmAgentSpecs();
    const parsed = JSON.parse(specs[0].provider);
    expect(parsed).toEqual({ direct: "claude" });
  });
});

// Small helper so the unused-import lint doesn't trigger if z grows unused
void z;
