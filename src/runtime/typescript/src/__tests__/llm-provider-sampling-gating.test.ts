/**
 * Mesh-level OpenAI sampling-param gating (cross-runtime parity with Java
 * `OpenAiHandler.restrictsSamplingParams` and Python `restricts_sampling_params`).
 *
 * OpenAI o-series (o1/o3/o4) and gpt-5 (except gpt-5-chat) reject non-default
 * `temperature`/`top_p` with HTTP 400. This is version-independent HARDENING:
 * mesh omits temperature/topP for restricted models BEFORE handing off to the
 * SDK (rather than silently relying on @ai-sdk/openai to strip them) and logs
 * its own warning. maxOutputTokens is intentionally NOT touched.
 *
 * Two layers:
 *  - the `restrictsSamplingParams` classifier truth table, and
 *  - behavioral: the options reaching the mocked vendor call (generateText /
 *    generateObject) carry NO temperature/topP for a restricted model, while a
 *    non-restricted model (gpt-4o) keeps them.
 *
 * The Vercel `ai` module is mocked — no real LLM is invoked.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

const generateObjectMock = vi.fn();
const generateTextMock = vi.fn();

vi.mock("ai", () => ({
  generateText: (opts: unknown) => generateTextMock(opts),
  generateObject: (opts: unknown) => generateObjectMock(opts),
  jsonSchema: (schema: Record<string, unknown>) => schema,
  tool: (config: unknown) => config,
  stepCountIs: (n: number) => ({ steps }: { steps: unknown[] }) => steps.length === n,
}));

// Keep tracing inert/deterministic (publishTraceSpan is best-effort anyway).
vi.mock("../tracing.js", () => ({
  generateTraceId: () => "trace-mock",
  generateSpanId: () => "span-mock",
  publishTraceSpan: vi.fn(async () => {}),
  matchesPropagateHeader: () => false,
}));

import {
  llmProvider,
  restrictsAnthropicSamplingParams,
  restrictsSamplingParams,
} from "../llm-provider.js";

// ----------------------------------------------------------------------------
// Classifier truth table
// ----------------------------------------------------------------------------

describe("restrictsSamplingParams truth table", () => {
  it.each([
    "o1",
    "o3-mini",
    "o4-mini",
    "gpt-5",
    "gpt-5-mini",
    "gpt-5-nano",
    // #1332 — version-agnostic: gpt-5 point releases stay restricted.
    "gpt-5.6",
    "gpt-5-6",
    "openai/gpt-5.6",
    "openai/o3-mini",
    "openai/gpt-5",
    "O3-MINI", // case-insensitive
  ])("restricts %s", (model) => {
    expect(restrictsSamplingParams(model)).toBe(true);
  });

  it.each([
    "gpt-4o",
    "gpt-4.1",
    "gpt-5-chat",
    "gpt-5-chat-latest",
    // #1332 — version-agnostic chat exclusion covers versioned chat ids.
    "gpt-5.6-chat",
    "gpt-5.6-chat-latest",
    "openai/gpt-4o",
    "gemini/gemini-2.0-flash",
    "anthropic/claude-sonnet-4-5",
    "o5", // not an o1/o3/o4 series
    undefined,
    null,
    "",
  ])("does not restrict %s", (model) => {
    expect(restrictsSamplingParams(model as string | undefined | null)).toBe(false);
  });
});

// ----------------------------------------------------------------------------
// Behavioral — the options reaching the vendor SDK call
// ----------------------------------------------------------------------------

const SCHEMA = {
  type: "object",
  properties: { answer: { type: "string" } },
  required: ["answer"],
};

function baseRequest(
  modelParams: Record<string, unknown>,
  opts: { withSchema?: boolean } = {},
) {
  const mp: Record<string, unknown> = { ...modelParams };
  if (opts.withSchema) {
    mp.output_schema = SCHEMA;
    mp.output_type_name = "Answer";
  }
  return {
    request: {
      messages: [
        { role: "system", content: "You are helpful." },
        { role: "user", content: "hi" },
      ],
      model_params: mp,
    },
  };
}

describe("OpenAI sampling-param gating — vendor call options", () => {
  let warnSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    generateObjectMock.mockReset();
    generateTextMock.mockReset();
    generateObjectMock.mockResolvedValue({
      object: { answer: "ok" },
      usage: { inputTokens: 1, outputTokens: 1 },
      finishReason: "stop",
    });
    generateTextMock.mockResolvedValue({
      text: "ok",
      toolCalls: [],
      usage: { inputTokens: 1, outputTokens: 1 },
      finishReason: "stop",
    });
    warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  // --- generateText (plain / no schema) path ---

  it("omits temperature/topP for a restricted model (o3-mini) — generateText", async () => {
    const tool = llmProvider({
      model: "openai/o3-mini",
      capability: "llm",
      temperature: 0.7,
      topP: 0.9,
    });
    await tool.execute(baseRequest({}) as never);

    expect(generateTextMock).toHaveBeenCalledTimes(1);
    const opts = generateTextMock.mock.calls[0][0] as Record<string, unknown>;
    expect("temperature" in opts).toBe(false);
    expect("topP" in opts).toBe(false);
    // mesh surfaces its own warning (one per omitted param).
    expect(warnSpy).toHaveBeenCalledTimes(2);
  });

  it("keeps temperature/topP for a non-restricted model (gpt-4o) — generateText", async () => {
    const tool = llmProvider({
      model: "openai/gpt-4o",
      capability: "llm",
      temperature: 0.7,
      topP: 0.9,
    });
    await tool.execute(baseRequest({}) as never);

    expect(generateTextMock).toHaveBeenCalledTimes(1);
    const opts = generateTextMock.mock.calls[0][0] as Record<string, unknown>;
    expect(opts.temperature).toBe(0.7);
    expect(opts.topP).toBe(0.9);
    expect(warnSpy).not.toHaveBeenCalled();
  });

  it("omits temperature/topP supplied via model_params for a restricted model", async () => {
    const tool = llmProvider({ model: "openai/gpt-5", capability: "llm" });
    await tool.execute(
      baseRequest({ temperature: 0.3, top_p: 0.5 }) as never,
    );

    expect(generateTextMock).toHaveBeenCalledTimes(1);
    const opts = generateTextMock.mock.calls[0][0] as Record<string, unknown>;
    expect("temperature" in opts).toBe(false);
    expect("topP" in opts).toBe(false);
  });

  it("omits temperature/topP for a gpt-5 point release (gpt-5.6) — generateText", async () => {
    // #1332 — a gpt-5 point release is restricted like the base model.
    const tool = llmProvider({
      model: "openai/gpt-5.6",
      capability: "llm",
      temperature: 0.7,
      topP: 0.9,
    });
    await tool.execute(baseRequest({}) as never);

    expect(generateTextMock).toHaveBeenCalledTimes(1);
    const opts = generateTextMock.mock.calls[0][0] as Record<string, unknown>;
    expect("temperature" in opts).toBe(false);
    expect("topP" in opts).toBe(false);
  });

  it("does not touch maxOutputTokens for a restricted model", async () => {
    const tool = llmProvider({
      model: "openai/o3-mini",
      capability: "llm",
      maxOutputTokens: 4096,
      temperature: 0.7,
    });
    await tool.execute(baseRequest({}) as never);

    const opts = generateTextMock.mock.calls[0][0] as Record<string, unknown>;
    expect(opts.maxOutputTokens).toBe(4096);
    expect("temperature" in opts).toBe(false);
  });

  // --- generateObject (structured output) path ---

  it("omits temperature/topP for a restricted model (o3-mini) — generateObject", async () => {
    const tool = llmProvider({
      model: "openai/o3-mini",
      capability: "llm",
      temperature: 0.7,
      topP: 0.9,
    });
    await tool.execute(baseRequest({}, { withSchema: true }) as never);

    expect(generateObjectMock).toHaveBeenCalledTimes(1);
    const opts = generateObjectMock.mock.calls[0][0] as Record<string, unknown>;
    expect("temperature" in opts).toBe(false);
    expect("topP" in opts).toBe(false);
  });

  it("keeps temperature/topP for a non-restricted model (gpt-4o) — generateObject", async () => {
    const tool = llmProvider({
      model: "openai/gpt-4o",
      capability: "llm",
      temperature: 0.7,
      topP: 0.9,
    });
    await tool.execute(baseRequest({}, { withSchema: true }) as never);

    expect(generateObjectMock).toHaveBeenCalledTimes(1);
    const opts = generateObjectMock.mock.calls[0][0] as Record<string, unknown>;
    expect(opts.temperature).toBe(0.7);
    expect(opts.topP).toBe(0.9);
  });
});

// ----------------------------------------------------------------------------
// Anthropic classifier truth table (#1344)
// ----------------------------------------------------------------------------
// Anthropic REMOVED temperature/top_p/top_k on the Opus 4.7+ / Sonnet 5 /
// Fable 5 families — presence is a hard HTTP 400. Narrower than the native
// structured-output model set: opus-4-6 / sonnet-4-6 / haiku-4-5 still accept
// sampling params and must NOT be caught. Mirrors Python
// `restricts_anthropic_sampling_params` / Java
// `AnthropicHandler.restrictsSamplingParams`.

describe("restrictsAnthropicSamplingParams truth table", () => {
  it.each([
    "claude-sonnet-5",
    "claude-opus-4-7",
    "claude-opus-4-8",
    "claude-fable-5",
    "anthropic/claude-sonnet-5",
    "anthropic/claude-opus-4-7",
    "anthropic/claude-opus-4-8",
    "anthropic/claude-fable-5",
    "bedrock/anthropic.claude-opus-4-8-20260101-v1:0",
    "databricks/anthropic.claude-sonnet-5",
    "anthropic/claude-opus-4.7",
    "anthropic/claude-opus-4.8",
    "claude-sonnet-5-20260201",
    "ANTHROPIC/CLAUDE-OPUS-4-8", // case-insensitive
  ])("restricts %s", (model) => {
    expect(restrictsAnthropicSamplingParams(model)).toBe(true);
    expect(restrictsSamplingParams(model)).toBe(true);
  });

  it.each([
    "anthropic/claude-opus-4-6",
    "anthropic/claude-sonnet-4-6",
    "anthropic/claude-haiku-4-5",
    "anthropic/claude-sonnet-4-5",
    "anthropic/claude-opus-4-5",
    "anthropic/claude-opus-4-1",
    "claude-3-5-sonnet-20241022",
    "bedrock/anthropic.claude-3-5-sonnet-20241022-v2:0",
    // Boundary guard: a hypothetical future minor version must NOT match the
    // shorter pattern.
    "anthropic/claude-opus-4-70",
    "anthropic/claude-opus-4-80",
    "anthropic/claude-sonnet-50",
    "anthropic/claude-fable-50",
    // Leading-digit guard.
    "anthropic/claude-opus-14-7",
    "openai/gpt-4o",
    "gemini/gemini-2.5-flash",
    undefined,
    null,
    "",
  ])("does not restrict %s", (model) => {
    expect(
      restrictsAnthropicSamplingParams(model as string | undefined | null),
    ).toBe(false);
  });
});

// ----------------------------------------------------------------------------
// Behavioral — Anthropic (#1344)
// ----------------------------------------------------------------------------

describe("Anthropic sampling-param gating — vendor call options", () => {
  let warnSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    process.env.ANTHROPIC_API_KEY = "sk-test";
    generateObjectMock.mockReset();
    generateTextMock.mockReset();
    generateObjectMock.mockResolvedValue({
      object: { answer: "ok" },
      usage: { inputTokens: 1, outputTokens: 1 },
      finishReason: "stop",
    });
    generateTextMock.mockResolvedValue({
      text: "ok",
      toolCalls: [],
      usage: { inputTokens: 1, outputTokens: 1 },
      finishReason: "stop",
    });
    warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it.each([
    "anthropic/claude-opus-4-8",
    "anthropic/claude-opus-4-7",
    "anthropic/claude-sonnet-5",
    "anthropic/claude-fable-5",
  ])("omits temperature/topP for a restricted model (%s)", async (model) => {
    const tool = llmProvider({
      model,
      capability: "llm",
      temperature: 0.7,
      topP: 0.9,
    });
    await tool.execute(baseRequest({}) as never);

    expect(generateTextMock).toHaveBeenCalledTimes(1);
    const opts = generateTextMock.mock.calls[0][0] as Record<string, unknown>;
    expect("temperature" in opts).toBe(false);
    expect("topP" in opts).toBe(false);
    // mesh surfaces its own warning (one per omitted param).
    expect(warnSpy).toHaveBeenCalledTimes(2);
  });

  it.each([
    "anthropic/claude-opus-4-6",
    "anthropic/claude-sonnet-4-6",
    "anthropic/claude-haiku-4-5",
    "anthropic/claude-opus-4-70",
  ])("keeps temperature/topP for an unrestricted model (%s)", async (model) => {
    const tool = llmProvider({
      model,
      capability: "llm",
      temperature: 0.7,
      topP: 0.9,
    });
    await tool.execute(baseRequest({}) as never);

    const opts = generateTextMock.mock.calls[0][0] as Record<string, unknown>;
    expect(opts.temperature).toBe(0.7);
    expect(opts.topP).toBe(0.9);
    expect(warnSpy).not.toHaveBeenCalled();
  });

  it("omits temperature/topP supplied via model_params for a restricted model", async () => {
    const tool = llmProvider({
      model: "anthropic/claude-opus-4-8",
      capability: "llm",
    });
    await tool.execute(baseRequest({ temperature: 0.3, top_p: 0.5 }) as never);

    const opts = generateTextMock.mock.calls[0][0] as Record<string, unknown>;
    expect("temperature" in opts).toBe(false);
    expect("topP" in opts).toBe(false);
  });

  it("does not touch maxOutputTokens for a restricted model", async () => {
    // Anthropic REQUIRES max_tokens — the gate must never strip it.
    const tool = llmProvider({
      model: "anthropic/claude-opus-4-8",
      capability: "llm",
      maxOutputTokens: 4096,
      temperature: 0.7,
    });
    await tool.execute(baseRequest({}) as never);

    const opts = generateTextMock.mock.calls[0][0] as Record<string, unknown>;
    expect(opts.maxOutputTokens).toBe(4096);
    expect("temperature" in opts).toBe(false);
  });
});
