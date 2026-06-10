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
 * Parity note: the truncation marker stays the PLAIN content string
 * "Maximum tool call iterations reached" (matching Python `mesh/helpers.py`);
 * this PR does not introduce a structured marker.
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
import { MeshDelegatedProvider } from "../llm-agent.js";
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
