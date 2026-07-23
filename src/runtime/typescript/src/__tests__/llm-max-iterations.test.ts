/**
 * Unit tests for the configurable provider-managed agentic-loop cap — issue #1116.
 *
 * Two surfaces are covered:
 *
 *  1. Provider resolution (`resolveMaxIterations`): precedence of the
 *     consumer-forwarded `model_params.max_iterations` over the
 *     `MESH_LLM_MAX_ITERATIONS` env, the default of 10 when neither is set,
 *     and the sanitization of invalid inputs.
 *
 *  2. Consumer forwarding (`MeshDelegatedProvider.complete()`): when the caller
 *     passes `options.maxIterations`, it surfaces on the wire request as
 *     `model_params.max_iterations`; when absent, no such key leaks.
 *
 * Issue #1355: exhaustion is now a STRUCTURAL signal, byte-identical to the
 * Python reference. The provider marks it with a `_mesh_stop_reason:
 * "max_iterations"` sibling field (buffered) or a typed terminal `end` frame
 * (streaming) — NEVER an English marker in `content` / the token stream. The
 * delegating consumer reads the signal and raises the typed `MaxIterationsError`.
 * Coverage below asserts the structured marker on every channel.
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
  resolveMaxIterations,
  envMaxIterations,
  sanitizeMaxIterations,
} from "../llm-provider.js";
import { MeshDelegatedProvider, MeshLlmAgent } from "../llm-agent.js";
import { MaxIterationsError } from "../errors.js";
import {
  STOP_REASON_KEY,
  STOP_REASON_MAX_ITERATIONS,
  FRAME_KEY,
  FRAME_CHUNK,
  FRAME_END,
  encodeChunk,
  encodeEnd,
  parseStreamFrame,
} from "../llm-stop-reason.js";
import type { LlmMessage } from "../types.js";

// ----------------------------------------------------------------------------
// resolveMaxIterations — provider-side precedence + sanitization
// ----------------------------------------------------------------------------

describe("resolveMaxIterations — provider loop cap resolution", () => {
  const ORIGINAL_ENV = process.env.MESH_LLM_MAX_ITERATIONS;

  afterEach(() => {
    if (ORIGINAL_ENV === undefined) {
      delete process.env.MESH_LLM_MAX_ITERATIONS;
    } else {
      process.env.MESH_LLM_MAX_ITERATIONS = ORIGINAL_ENV;
    }
  });

  it("model_params override wins over env", () => {
    process.env.MESH_LLM_MAX_ITERATIONS = "7";
    expect(resolveMaxIterations(25)).toBe(25);
  });

  it("falls back to env when the param is absent", () => {
    process.env.MESH_LLM_MAX_ITERATIONS = "15";
    expect(resolveMaxIterations(undefined)).toBe(15);
  });

  it("defaults to 10 when neither param nor env is set", () => {
    delete process.env.MESH_LLM_MAX_ITERATIONS;
    expect(resolveMaxIterations(undefined)).toBe(10);
  });

  it("accepts a numeric string from the env", () => {
    delete process.env.MESH_LLM_MAX_ITERATIONS;
    process.env.MESH_LLM_MAX_ITERATIONS = "3";
    expect(resolveMaxIterations(undefined)).toBe(3);
  });

  it("floors a fractional value to an integer", () => {
    delete process.env.MESH_LLM_MAX_ITERATIONS;
    expect(resolveMaxIterations(4.9)).toBe(4);
  });

  // #1116 fractional hole: floor-BEFORE-validate. 0.5 floors to 0, which is
  // not > 0, so it must fall back to the default — NOT return a zero cap that
  // would disable the loop.
  it("falls back to 10 for a fractional value that floors to zero (0.5)", () => {
    delete process.env.MESH_LLM_MAX_ITERATIONS;
    expect(resolveMaxIterations(0.5)).toBe(10);
  });

  it("falls back to 10 for a fractional value that floors to zero (0.9)", () => {
    delete process.env.MESH_LLM_MAX_ITERATIONS;
    expect(resolveMaxIterations(0.9)).toBe(10);
  });

  it.each([
    ["zero", 0],
    ["negative", -5],
    ["NaN", NaN],
    ["non-numeric string", "abc" as unknown as number],
    ["null", null as unknown as number],
    ["object", {} as unknown as number],
  ])("falls back to 10 for an invalid value (%s)", (_label, value) => {
    delete process.env.MESH_LLM_MAX_ITERATIONS;
    expect(resolveMaxIterations(value)).toBe(10);
  });

  it("an invalid env falls back to 10", () => {
    process.env.MESH_LLM_MAX_ITERATIONS = "not-a-number";
    expect(resolveMaxIterations(undefined)).toBe(10);
  });

  // Parity (#1116/#1160): the Gemini AI-SDK-managed loop wires
  // `stopWhen: stepCountIs(resolvedMaxIterations)` — AI SDK v6 removed
  // `maxSteps`, whose default-stepCountIs(1) replacement caused the empty
  // assistant message regression (#1160). The actual generateText option
  // wiring is asserted in llm-provider-stopwhen.test.ts, and the multi-step
  // loop behavior (tool call → follow-up text) in
  // llm-provider-multistep.test.ts. Here we only assert the resolution the
  // Gemini path consumes.
  it("Gemini stopWhen path consumes the forwarded resolved cap", () => {
    delete process.env.MESH_LLM_MAX_ITERATIONS;
    expect(resolveMaxIterations(25)).toBe(25);
  });

  it("Gemini stopWhen path falls back to 10 when the cap is absent", () => {
    delete process.env.MESH_LLM_MAX_ITERATIONS;
    expect(resolveMaxIterations(undefined)).toBe(10);
  });
});

// ----------------------------------------------------------------------------
// envMaxIterations — single source of truth for env parsing
// ----------------------------------------------------------------------------

describe("envMaxIterations — env parse + validation", () => {
  const ORIGINAL_ENV = process.env.MESH_LLM_MAX_ITERATIONS;

  afterEach(() => {
    if (ORIGINAL_ENV === undefined) {
      delete process.env.MESH_LLM_MAX_ITERATIONS;
    } else {
      process.env.MESH_LLM_MAX_ITERATIONS = ORIGINAL_ENV;
    }
  });

  it("returns undefined when the env is unset", () => {
    delete process.env.MESH_LLM_MAX_ITERATIONS;
    expect(envMaxIterations()).toBeUndefined();
  });

  it.each([
    ["zero", "0", undefined],
    ["empty string", "", undefined],
    ["non-numeric", "abc", undefined],
    ["fractional below one", "0.5", undefined],
    ["positive integer", "15", 15],
    ["fractional floors down", "4.9", 4],
    ["scientific notation (Number semantics)", "1e2", 100],
  ])("parses %s → %s", (_label, raw, expected) => {
    process.env.MESH_LLM_MAX_ITERATIONS = raw;
    expect(envMaxIterations()).toBe(expected);
  });
});

// ----------------------------------------------------------------------------
// sanitizeMaxIterations — single source of truth for cap normalization
// ----------------------------------------------------------------------------

describe("sanitizeMaxIterations — value normalization", () => {
  it.each([
    ["positive integer", 5, 5],
    ["fractional floors down", 4.9, 4],
    ["numeric string", "15", 15],
    ["scientific notation (Number semantics)", "1e2", 100],
  ])("normalizes a valid value (%s) → %s", (_label, value, expected) => {
    expect(sanitizeMaxIterations(value)).toBe(expected);
  });

  it.each([
    ["undefined", undefined],
    ["null", null],
    ["zero", 0],
    ["negative", -3],
    ["fractional below one", 0.5],
    ["NaN", NaN],
    ["non-numeric string", "abc"],
    ["empty string", ""],
    ["object", {}],
  ])("rejects an invalid value (%s) → undefined", (_label, value) => {
    expect(sanitizeMaxIterations(value)).toBeUndefined();
  });
});

// ----------------------------------------------------------------------------
// MeshDelegatedProvider.complete() — consumer forwards maxIterations
// ----------------------------------------------------------------------------

const ENDPOINT = "http://provider.local:9001";
const FN_BUFFERED = "process_chat";

describe("MeshDelegatedProvider.complete() — maxIterations forwarding", () => {
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

  const STUB_COMPLETION = { role: "assistant", content: "ok" };

  it("forwards options.maxIterations as model_params.max_iterations", async () => {
    let capturedBody: string | undefined;
    const fetchMock = vi.fn(async (_url: string, init: RequestInit) => {
      capturedBody = init.body as string;
      return mockJsonResponse(mcpToolResponse(STUB_COMPLETION));
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const provider = new MeshDelegatedProvider(ENDPOINT, FN_BUFFERED, false);
    const messages: LlmMessage[] = [{ role: "user", content: "hi" }];

    await provider.complete("anthropic/claude-sonnet-4-5", messages, undefined, {
      maxIterations: 25,
    });

    const body = JSON.parse(capturedBody!);
    const modelParams = body.params.arguments.request.model_params as Record<string, unknown>;
    expect(modelParams.max_iterations).toBe(25);
  });

  it("typed maxIterations wins over an escape-hatch modelParams.max_iterations", async () => {
    let capturedBody: string | undefined;
    const fetchMock = vi.fn(async (_url: string, init: RequestInit) => {
      capturedBody = init.body as string;
      return mockJsonResponse(mcpToolResponse(STUB_COMPLETION));
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const provider = new MeshDelegatedProvider(ENDPOINT, FN_BUFFERED, false);
    const messages: LlmMessage[] = [{ role: "user", content: "hi" }];

    await provider.complete("anthropic/claude-sonnet-4-5", messages, undefined, {
      maxIterations: 25,
      modelParams: { max_iterations: 3 },
    });

    const body = JSON.parse(capturedBody!);
    const modelParams = body.params.arguments.request.model_params as Record<string, unknown>;
    expect(modelParams.max_iterations).toBe(25);
  });

  it("does not emit max_iterations when maxIterations is absent", async () => {
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
    });

    const body = JSON.parse(capturedBody!);
    const modelParams = body.params.arguments.request.model_params as Record<string, unknown>;
    expect(modelParams.max_iterations).toBeUndefined();
  });
});

// ----------------------------------------------------------------------------
// Issue #1360: consumer-level forwarding through MeshLlmAgent.run().
//
// The complete()-level tests above prove the wire guard omits the key when the
// caller passes no maxIterations. These assert the END-TO-END consumer path:
// run() resolves the cap, and only an EXPLICITLY configured one (runtime option
// / consumer env / user-supplied config) reaches the wire. A consumer that
// configured NOTHING must send no max_iterations key so the provider's own
// MESH_LLM_MAX_ITERATIONS governs — mirroring the Python/Java tests from #1356.
//
// The consumer's OWN loop cap must still default to 10 when unset (the #1355
// exhaustion path), which the last test asserts via the raised error's cap.
// ----------------------------------------------------------------------------

describe("MeshLlmAgent forwarding — explicit vs unset (issue #1360)", () => {
  let originalFetch: typeof fetch;
  const ORIGINAL_ENV = process.env.MESH_LLM_MAX_ITERATIONS;

  beforeEach(() => {
    originalFetch = globalThis.fetch;
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    vi.restoreAllMocks();
    if (ORIGINAL_ENV === undefined) {
      delete process.env.MESH_LLM_MAX_ITERATIONS;
    } else {
      process.env.MESH_LLM_MAX_ITERATIONS = ORIGINAL_ENV;
    }
  });

  /**
   * Run the agent through a fetch mock returning a normal completion, and
   * return the wire request's model_params (undefined when the request carried
   * no model_params block at all — e.g. a consumer that configured nothing).
   */
  async function captureRunModelParams(
    agent: MeshLlmAgent,
    options?: { maxIterations?: number },
  ): Promise<Record<string, unknown> | undefined> {
    let capturedBody: string | undefined;
    globalThis.fetch = vi.fn(async (_url: string, init: RequestInit) => {
      capturedBody = init.body as string;
      return mockJsonResponse(mcpToolResponse({ role: "assistant", content: "ok" }));
    }) as unknown as typeof fetch;

    await agent.run("hi", {
      tools: [],
      meshProvider: { endpoint: ENDPOINT, functionName: FN_BUFFERED },
      options,
    });

    const body = JSON.parse(capturedBody!);
    return body.params.arguments.request.model_params as
      | Record<string, unknown>
      | undefined;
  }

  function unsetAgent(): MeshLlmAgent {
    // No maxIterations configured at all — the crux of #1360.
    return new MeshLlmAgent({
      functionId: "test.1360.unset",
      provider: { capability: "llm", tags: ["+claude"] },
    });
  }

  it("omits max_iterations when the consumer configured nothing (provider env governs)", async () => {
    delete process.env.MESH_LLM_MAX_ITERATIONS;
    const modelParams = await captureRunModelParams(unsetAgent());
    expect(modelParams?.max_iterations).toBeUndefined();
  });

  it("forwards an explicit runtime option", async () => {
    delete process.env.MESH_LLM_MAX_ITERATIONS;
    const modelParams = await captureRunModelParams(unsetAgent(), {
      maxIterations: 25,
    });
    expect(modelParams?.max_iterations).toBe(25);
  });

  it("forwards the consumer-side MESH_LLM_MAX_ITERATIONS env", async () => {
    process.env.MESH_LLM_MAX_ITERATIONS = "15";
    const modelParams = await captureRunModelParams(unsetAgent());
    expect(modelParams?.max_iterations).toBe(15);
  });

  it("forwards an explicit user-supplied config value", async () => {
    delete process.env.MESH_LLM_MAX_ITERATIONS;
    const agent = new MeshLlmAgent({
      functionId: "test.1360.explicit-config",
      provider: { capability: "llm", tags: ["+claude"] },
      maxIterations: 8,
    });
    const modelParams = await captureRunModelParams(agent);
    expect(modelParams?.max_iterations).toBe(8);
  });

  it("still caps the consumer's own loop at 10 when unset (default local cap preserved)", async () => {
    delete process.env.MESH_LLM_MAX_ITERATIONS;
    // Provider signals exhaustion structurally; the raised error must carry the
    // default local cap of 10, proving the consumer loop is still bounded even
    // though nothing is forwarded to the provider.
    globalThis.fetch = vi.fn(async () =>
      mockJsonResponse(
        mcpToolResponse({
          role: "assistant",
          content: "",
          _mesh_stop_reason: "max_iterations",
        }),
      ),
    ) as unknown as typeof fetch;

    try {
      await unsetAgent().run("hi", {
        tools: [],
        meshProvider: { endpoint: ENDPOINT, functionName: FN_BUFFERED },
      });
      throw new Error("expected MaxIterationsError");
    } catch (err) {
      expect(err).toBeInstanceOf(MaxIterationsError);
      expect((err as MaxIterationsError).iterations).toBe(10);
    }
  });
});

// ----------------------------------------------------------------------------
// Issue #1355: shared exhaustion vocabulary — encode/parse frame helpers.
// These must be byte-identical to Python's llm_stop_reason.py so a TS consumer
// interoperates with a Python provider (and vice versa).
// ----------------------------------------------------------------------------

describe("llm-stop-reason vocabulary — frame encode/parse (cross-runtime shapes)", () => {
  it("exposes the constants byte-identical to the Python reference", () => {
    expect(STOP_REASON_KEY).toBe("_mesh_stop_reason");
    expect(STOP_REASON_MAX_ITERATIONS).toBe("max_iterations");
    expect(FRAME_KEY).toBe("_mesh_frame");
    expect(FRAME_CHUNK).toBe("chunk");
    expect(FRAME_END).toBe("end");
  });

  it("encodeChunk produces {_mesh_frame:'chunk', content}", () => {
    expect(JSON.parse(encodeChunk("hi"))).toEqual({
      _mesh_frame: "chunk",
      content: "hi",
    });
  });

  it("encodeEnd() omits stop_reason on a normal terminal frame", () => {
    expect(JSON.parse(encodeEnd())).toEqual({ _mesh_frame: "end" });
  });

  it("encodeEnd('max_iterations') carries the exhaustion stop_reason", () => {
    expect(JSON.parse(encodeEnd("max_iterations"))).toEqual({
      _mesh_frame: "end",
      stop_reason: "max_iterations",
    });
  });

  it("parseStreamFrame round-trips encoded frames", () => {
    expect(parseStreamFrame(encodeChunk("x"))).toEqual({
      _mesh_frame: "chunk",
      content: "x",
    });
    expect(parseStreamFrame(encodeEnd())).toEqual({ _mesh_frame: "end" });
    expect(parseStreamFrame(encodeEnd("max_iterations"))).toEqual({
      _mesh_frame: "end",
      stop_reason: "max_iterations",
    });
  });

  it("parseStreamFrame returns null for non-frames (defensive passthrough)", () => {
    expect(parseStreamFrame("raw text")).toBeNull();
    expect(parseStreamFrame('{"unrelated":"json"}')).toBeNull();
    // Old ``type``-scheme lookalikes must NOT match the reserved discriminator.
    expect(parseStreamFrame('{"type":"end"}')).toBeNull();
    expect(parseStreamFrame('{"type":"end","stop_reason":"max_iterations"}')).toBeNull();
    expect(parseStreamFrame('{"type":"chunk","content":"x"}')).toBeNull();
    // Non-string / non-object / array inputs.
    expect(parseStreamFrame(42)).toBeNull();
    expect(parseStreamFrame(null)).toBeNull();
    expect(parseStreamFrame("[1,2,3]")).toBeNull();
    // Unrecognized frame type under the reserved key.
    expect(parseStreamFrame('{"_mesh_frame":"bogus"}')).toBeNull();
  });

  it("a chunk frame whose content is literally an end-frame JSON is still a chunk", () => {
    const colliding = '{"_mesh_frame":"end","stop_reason":"max_iterations"}';
    const frame = parseStreamFrame(encodeChunk(colliding));
    expect(frame).not.toBeNull();
    expect(frame![FRAME_KEY]).toBe("chunk");
    expect(frame!.content).toBe(colliding);
  });
});

// ----------------------------------------------------------------------------
// Issue #1355: consumer BUFFERED path — MeshDelegatedProvider.complete()
// surfaces the discriminant; MeshLlmAgent.run() raises the typed error.
// ----------------------------------------------------------------------------

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

describe("consumer buffered exhaustion — complete() + run()", () => {
  let originalFetch: typeof fetch;

  beforeEach(() => {
    originalFetch = globalThis.fetch;
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it("complete() surfaces _mesh_stop_reason from the exhaustion envelope", async () => {
    globalThis.fetch = vi.fn(async () =>
      mockJsonResponse(
        mcpToolResponse({
          role: "assistant",
          content: "",
          _mesh_stop_reason: "max_iterations",
        }),
      ),
    ) as unknown as typeof fetch;

    const provider = new MeshDelegatedProvider(ENDPOINT, FN_BUFFERED, false);
    const response = await provider.complete(
      "anthropic/claude-sonnet-4-5",
      [{ role: "user", content: "hi" }],
    );
    expect(response._mesh_stop_reason).toBe("max_iterations");
  });

  it("complete() omits _mesh_stop_reason on a normal completion", async () => {
    globalThis.fetch = vi.fn(async () =>
      mockJsonResponse(mcpToolResponse({ role: "assistant", content: "the answer" })),
    ) as unknown as typeof fetch;

    const provider = new MeshDelegatedProvider(ENDPOINT, FN_BUFFERED, false);
    const response = await provider.complete(
      "anthropic/claude-sonnet-4-5",
      [{ role: "user", content: "hi" }],
    );
    expect(response._mesh_stop_reason).toBeUndefined();
    expect(response.choices[0].message.content).toBe("the answer");
  });

  it("complete() does NOT mis-parse an exhaustion envelope as a bare answer", async () => {
    // Empty content + _mesh_stop_reason must be recognized as a reserved-key
    // envelope, NOT treated as a bare structured answer (the whole map).
    globalThis.fetch = vi.fn(async () =>
      mockJsonResponse(
        mcpToolResponse({
          role: "assistant",
          content: "",
          _mesh_stop_reason: "max_iterations",
        }),
      ),
    ) as unknown as typeof fetch;

    const provider = new MeshDelegatedProvider(ENDPOINT, FN_BUFFERED, false);
    const response = await provider.complete(
      "anthropic/claude-sonnet-4-5",
      [{ role: "user", content: "hi" }],
    );
    // Content stays empty (not the JSON-stringified envelope).
    expect(response.choices[0].message.content).toBe("");
  });

  it("run() raises MaxIterationsError on the exhaustion envelope (iteration 1)", async () => {
    globalThis.fetch = vi.fn(async () =>
      mockJsonResponse(
        mcpToolResponse({
          role: "assistant",
          content: "",
          _mesh_stop_reason: "max_iterations",
        }),
      ),
    ) as unknown as typeof fetch;

    const agent = new MeshLlmAgent({
      functionId: "test.buffered.exhaustion",
      provider: { capability: "llm", tags: ["+claude"] },
      maxIterations: 7,
    });

    await expect(
      agent.run("hi", {
        tools: [],
        meshProvider: { endpoint: ENDPOINT, functionName: FN_BUFFERED },
      }),
    ).rejects.toBeInstanceOf(MaxIterationsError);
  });

  it("run() carries the resolved cap on the raised error", async () => {
    globalThis.fetch = vi.fn(async () =>
      mockJsonResponse(
        mcpToolResponse({
          role: "assistant",
          content: "partial reasoning so far...",
          _mesh_stop_reason: "max_iterations",
        }),
      ),
    ) as unknown as typeof fetch;

    const agent = new MeshLlmAgent({
      functionId: "test.buffered.exhaustion.cap",
      provider: { capability: "llm", tags: ["+claude"] },
      maxIterations: 3,
    });

    try {
      await agent.run("hi", {
        tools: [],
        meshProvider: { endpoint: ENDPOINT, functionName: FN_BUFFERED },
      });
      throw new Error("expected MaxIterationsError");
    } catch (err) {
      expect(err).toBeInstanceOf(MaxIterationsError);
      expect((err as MaxIterationsError).iterations).toBe(3);
    }
  });

  it("run() returns the answer on a normal completion (no discriminant)", async () => {
    globalThis.fetch = vi.fn(async () =>
      mockJsonResponse(mcpToolResponse({ role: "assistant", content: "the answer" })),
    ) as unknown as typeof fetch;

    const agent = new MeshLlmAgent({
      functionId: "test.buffered.normal",
      provider: { capability: "llm", tags: ["+claude"] },
      maxIterations: 3,
    });

    const result = await agent.run("hi", {
      tools: [],
      meshProvider: { endpoint: ENDPOINT, functionName: FN_BUFFERED },
    });
    expect(result).toBe("the answer");
  });
});

// ----------------------------------------------------------------------------
// Issue #1355: consumer STREAMING path — MeshLlmAgent.stream() unwraps
// _mesh_frame frames, raises on exhaustion, never forwards a control frame.
// Frames ride the SSE progress-notification ``message`` field, exactly as a
// Python @mesh.llm_provider streaming tool emits them (cross-runtime interop).
// ----------------------------------------------------------------------------

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

function makeSseResponse(blocks: string[]): Response {
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

/**
 * Build an SSE fetch mock whose progress notifications carry ``frames`` (the
 * wire strings a provider emits), terminated by a JSON-RPC result event.
 */
function frameStreamFetch(frames: string[]) {
  return vi.fn(async (_url: string, init: RequestInit) => {
    const body = JSON.parse(init.body as string);
    const token = body.params._meta.progressToken as string;
    const reqId = body.id as string;
    const events = frames.map((f, idx) =>
      sseEvent({
        jsonrpc: "2.0",
        method: "notifications/progress",
        params: { progressToken: token, progress: idx + 1, message: f },
      }),
    );
    events.push(sseEvent({ jsonrpc: "2.0", id: reqId, result: {} }));
    return makeSseResponse(events);
  });
}

const STREAM_TOOL = "process_chat_stream";

function makeStreamAgent(maxIterations = 5): MeshLlmAgent {
  return new MeshLlmAgent({
    functionId: "test.stream.exhaustion",
    provider: { capability: "llm", tags: ["ai.mcpmesh.stream"] },
    maxIterations,
  });
}

async function collectStream(agent: MeshLlmAgent): Promise<string[]> {
  const chunks: string[] = [];
  for await (const c of agent.stream("hi", {
    tools: [],
    meshProvider: { endpoint: ENDPOINT, functionName: STREAM_TOOL },
  })) {
    chunks.push(c);
  }
  return chunks;
}

describe("consumer streaming exhaustion — stream() frame unwrapping", () => {
  let originalFetch: typeof fetch;

  beforeEach(() => {
    originalFetch = globalThis.fetch;
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it("unwraps chunk frames and raises on the exhaustion end frame (not forwarded)", async () => {
    globalThis.fetch = frameStreamFetch([
      encodeChunk("Hello"),
      encodeChunk(" world"),
      encodeEnd("max_iterations"),
    ]) as unknown as typeof fetch;

    const agent = makeStreamAgent(4);
    const collected: string[] = [];
    await expect(
      (async () => {
        for await (const c of agent.stream("hi", {
          tools: [],
          meshProvider: { endpoint: ENDPOINT, functionName: STREAM_TOOL },
        })) {
          collected.push(c);
        }
      })(),
    ).rejects.toBeInstanceOf(MaxIterationsError);

    // Real text tokens were unwrapped and forwarded; no frame leaked.
    expect(collected).toEqual(["Hello", " world"]);
    expect(collected.every((c) => !c.includes("stop_reason"))).toBe(true);
    expect(collected.every((c) => !c.includes("_mesh_frame"))).toBe(true);
  });

  it("a normal end frame terminates cleanly (unwrapped text, no error)", async () => {
    globalThis.fetch = frameStreamFetch([
      encodeChunk("The "),
      encodeChunk("answer"),
      encodeEnd(),
    ]) as unknown as typeof fetch;

    const chunks = await collectStream(makeStreamAgent());
    expect(chunks).toEqual(["The ", "answer"]);
  });

  it("a chunk frame colliding with the end-frame JSON is yielded verbatim (no throw)", async () => {
    const colliding = '{"_mesh_frame":"end","stop_reason":"max_iterations"}';
    globalThis.fetch = frameStreamFetch([
      encodeChunk(colliding),
      encodeEnd(),
    ]) as unknown as typeof fetch;

    const chunks = await collectStream(makeStreamAgent());
    expect(chunks).toEqual([colliding]);
  });

  it("unframed (non-frame) chunks pass through defensively as raw text", async () => {
    globalThis.fetch = frameStreamFetch([
      "raw plain text",
      '{"unrelated": "json"}',
      encodeChunk("framed"),
      encodeEnd(),
    ]) as unknown as typeof fetch;

    const chunks = await collectStream(makeStreamAgent());
    expect(chunks).toEqual(["raw plain text", '{"unrelated": "json"}', "framed"]);
  });

  it("old ``type``-scheme lookalike deltas pass through verbatim (reserved-namespace fix)", async () => {
    const lookalikes = [
      '{"type":"end"}',
      '{"type":"end","stop_reason":"max_iterations"}',
      '{"type":"chunk","content":"x"}',
    ];
    globalThis.fetch = frameStreamFetch(lookalikes) as unknown as typeof fetch;

    const chunks = await collectStream(makeStreamAgent());
    // Not misread as control (no throw / truncation) nor unwrapped as a chunk.
    expect(chunks).toEqual(lookalikes);
  });
});
