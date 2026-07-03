/**
 * Consumer-side recovery + honest diagnostics for the mesh provider's
 * ``{ role, content }`` reply envelope (llm-agent.ts).
 *
 * Providers should send the answer as a string. Two malformed-but-recoverable
 * shapes occur in the field:
 *   1. ``content`` is a raw object — the structured answer leaked unserialized.
 *      ``complete()`` serializes it so downstream schema parsing sees JSON.
 *   2. the map carries neither ``content`` nor ``role`` — a bare structured
 *      answer without the envelope; the whole map is treated as the answer.
 *
 * When content resolves to empty under a response schema, ``run()`` blames the
 * empty reply and surfaces the raw payload — not an opaque "could not extract
 * JSON".
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { z } from "zod";

vi.mock("@mcpmesh/core", () => ({
  generateTraceId: () => "trace-mock",
  generateSpanId: () => "span-mock",
  injectTraceContext: (argsJson: string) => argsJson,
  publishSpan: vi.fn(async () => false),
  parseSseResponse: (s: string) => s,
  parseSseResponseToObject: (s: string) => JSON.parse(s),
  extractJson: (s: string) => s,
}));

vi.mock("../http-pool.js", () => ({
  getDispatcher: () => undefined,
}));

import { MeshDelegatedProvider, MeshLlmAgent } from "../llm-agent.js";
import { ResponseParseError } from "../errors.js";
import type { LlmMessage } from "../types.js";

const ENDPOINT = "http://provider.local:9001";
const FN_BUFFERED = "process_chat";

function mcpJsonResponse(payload: object): Response {
  const envelope = {
    jsonrpc: "2.0",
    id: 1,
    result: {
      content: [{ type: "text", text: JSON.stringify(payload) }],
    },
  };
  return {
    ok: true,
    status: 200,
    statusText: "OK",
    headers: {
      get: (name: string) =>
        name.toLowerCase() === "content-type" ? "application/json" : null,
    },
    text: async () => JSON.stringify(envelope),
    json: async () => envelope,
  } as unknown as Response;
}

describe("MeshDelegatedProvider.complete() — content normalization", () => {
  let originalFetch: typeof fetch;

  beforeEach(() => {
    originalFetch = globalThis.fetch;
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  function stub(payload: object) {
    globalThis.fetch = vi.fn(
      async () => mcpJsonResponse(payload)
    ) as unknown as typeof fetch;
  }

  async function completeWith(payload: object): Promise<string | undefined> {
    stub(payload);
    const provider = new MeshDelegatedProvider(ENDPOINT, FN_BUFFERED, false);
    const messages: LlmMessage[] = [{ role: "user", content: "hi" }];
    const res = await provider.complete("anthropic/claude-sonnet-4-5", messages);
    return res.choices[0]?.message.content as string | undefined;
  }

  it("string content passes through unchanged (regression)", async () => {
    expect(await completeWith({ role: "assistant", content: "ok" })).toBe("ok");
  });

  it("object content is serialized to a JSON string", async () => {
    const answer = { count: 5, name: "x" };
    expect(await completeWith({ role: "assistant", content: answer })).toBe(
      JSON.stringify(answer)
    );
  });

  it("bare map without content/role keys is serialized whole", async () => {
    const bare = { verdict: "BLOCK", reason: "policy" };
    expect(await completeWith(bare)).toBe(JSON.stringify(bare));
  });

  it("error map is NOT treated as a bare answer (stays empty)", async () => {
    expect(await completeWith({ error: "rate limited by vendor" })).toBe("");
  });

  it("empty MCP content → throws but still captures the raw payload (#1250)", async () => {
    // A delegated provider reply with an EMPTY content array now surfaces as
    // null. The type guard throws, but _lastRawResponse must be set FIRST so the
    // run() diagnostic isn't left stale — a regression vs the old JSON.parse("")
    // path that recorded the payload before throwing.
    const emptyEnvelope = { jsonrpc: "2.0", id: 1, result: { content: [] } };
    globalThis.fetch = vi.fn(async () => ({
      ok: true,
      status: 200,
      statusText: "OK",
      headers: {
        get: (name: string) =>
          name.toLowerCase() === "content-type" ? "application/json" : null,
      },
      text: async () => JSON.stringify(emptyEnvelope),
      json: async () => emptyEnvelope,
    })) as unknown as typeof fetch;

    const provider = new MeshDelegatedProvider(ENDPOINT, FN_BUFFERED, false);
    const messages: LlmMessage[] = [{ role: "user", content: "hi" }];
    await expect(
      provider.complete("anthropic/claude-sonnet-4-5", messages)
    ).rejects.toThrow("Invalid response from mesh provider");
    expect(provider.lastRawResponse).toBe("null");
  });

  it("bare answer with a null error field is still recovered", async () => {
    const payload = { data: "ok", error: null, verdict: "PASS" };
    expect(await completeWith(payload)).toBe(JSON.stringify(payload));
  });

  it("tool_calls-only map is NOT treated as a bare answer (stays empty)", async () => {
    const payload = {
      tool_calls: [
        { id: "call_1", type: "function", function: { name: "f", arguments: "{}" } },
      ],
    };
    expect(await completeWith(payload)).toBe("");
  });

  it("_mesh_usage-only map is NOT treated as a bare answer (stays empty)", async () => {
    expect(
      await completeWith({ _mesh_usage: { prompt_tokens: 1, completion_tokens: 2 } })
    ).toBe("");
  });

  it("empty-string content in a real envelope stays empty", async () => {
    expect(await completeWith({ role: "assistant", content: "" })).toBe("");
  });

  it("null content in a real envelope stays empty (legal, e.g. tool calls)", async () => {
    expect(
      await completeWith({ role: "assistant", content: null })
    ).toBe("");
  });
});

describe("MeshLlmAgent.run() — empty-content diagnostic", () => {
  let originalFetch: typeof fetch;

  beforeEach(() => {
    originalFetch = globalThis.fetch;
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  const schema = z.object({ answer: z.string() });

  function makeAgent() {
    return new MeshLlmAgent({
      functionId: "test.recovery",
      provider: { capability: "llm" },
      maxIterations: 5,
      returnSchema: schema,
    });
  }

  function stub(payload: object) {
    globalThis.fetch = vi.fn(
      async () => mcpJsonResponse(payload)
    ) as unknown as typeof fetch;
  }

  it("empty content under a response schema → ResponseParseError with raw payload", async () => {
    stub({ role: "assistant", content: "" });
    const agent = makeAgent();
    await expect(
      agent.run("hi", {
        tools: [],
        meshProvider: { endpoint: ENDPOINT, functionName: FN_BUFFERED },
      })
    ).rejects.toMatchObject({
      name: "ResponseParseError",
    });

    stub({ role: "assistant", content: "" });
    const agent2 = makeAgent();
    const err = await agent2
      .run("hi", {
        tools: [],
        meshProvider: { endpoint: ENDPOINT, functionName: FN_BUFFERED },
      })
      .catch((e) => e);
    expect(err).toBeInstanceOf(ResponseParseError);
    expect(err.message).toContain("empty content");
    expect(err.message).toContain("Raw response payload:");
  });

  it("object content under a response schema → parses instead of failing", async () => {
    stub({ role: "assistant", content: { answer: "structured" } });
    const agent = makeAgent();
    const result = await agent.run("hi", {
      tools: [],
      meshProvider: { endpoint: ENDPOINT, functionName: FN_BUFFERED },
    });
    expect(result).toEqual({ answer: "structured" });
  });

  it("genuine bare answer under a response schema → recovered (not an error)", async () => {
    stub({ answer: "bare" });
    const agent = makeAgent();
    const result = await agent.run("hi", {
      tools: [],
      meshProvider: { endpoint: ENDPOINT, functionName: FN_BUFFERED },
    });
    expect(result).toEqual({ answer: "bare" });
  });

  it("error map → diagnostic surfaces the error payload, not a schema failure", async () => {
    stub({ error: "rate limited by vendor" });
    const agent = makeAgent();
    const err = await agent
      .run("hi", {
        tools: [],
        meshProvider: { endpoint: ENDPOINT, functionName: FN_BUFFERED },
      })
      .catch((e) => e);
    expect(err).toBeInstanceOf(ResponseParseError);
    expect(err.message).toContain("empty content");
    expect(err.message).toContain("rate limited by vendor");
  });
});
