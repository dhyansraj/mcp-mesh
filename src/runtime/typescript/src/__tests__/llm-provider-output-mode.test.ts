/**
 * Provider-side honoring of the consumer-supplied output_mode override — #1112.
 *
 * The provider's effective output mode is:
 *   effective = (model_params.output_mode is one of strict/hint/text)
 *                 ? that override
 *                 : handler.determineOutputMode(outputSchema)   // today's auto
 *
 * Observability seam: the strict path drives `generateObject()` while
 * hint/text drive `generateText()` (useStructuredOutput === outputMode ===
 * "strict"). For an OpenAI provider WITH a schema and NO tools, auto-selection
 * is "strict" → generateObject. A "hint"/"text" override flips it to
 * generateText. An absent/invalid override leaves auto (strict) intact.
 *
 * Also asserts output_mode is stripped from the params before they reach the
 * vendor SDK call (generateObject/generateText options).
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
}));

// Keep tracing inert/deterministic (publishTraceSpan is best-effort anyway).
vi.mock("../tracing.js", () => ({
  generateTraceId: () => "trace-mock",
  generateSpanId: () => "span-mock",
  publishTraceSpan: vi.fn(async () => {}),
  matchesPropagateHeader: () => false,
}));

import { llmProvider } from "../llm-provider.js";

const SCHEMA = {
  type: "object",
  properties: { answer: { type: "string" } },
  required: ["answer"],
};

function makeProvider() {
  // OpenAI vendor: auto-selects "strict" when a schema is present.
  return llmProvider({ model: "openai/gpt-4o", capability: "llm" });
}

function baseRequest(modelParams: Record<string, unknown>) {
  return {
    request: {
      messages: [
        { role: "system", content: "You are helpful." },
        { role: "user", content: "hi" },
      ],
      model_params: {
        output_schema: SCHEMA,
        output_type_name: "Answer",
        ...modelParams,
      },
    },
  };
}

describe("provider output_mode override (#1112)", () => {
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
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("auto-selects strict (generateObject) when no override is present — byte-identical to today", async () => {
    const tool = makeProvider();
    await tool.execute(baseRequest({}) as never);

    expect(generateObjectMock).toHaveBeenCalledTimes(1);
    expect(generateTextMock).not.toHaveBeenCalled();
  });

  it("honors a 'hint' override where it would auto-select strict (uses generateText)", async () => {
    const tool = makeProvider();
    await tool.execute(baseRequest({ output_mode: "hint" }) as never);

    expect(generateTextMock).toHaveBeenCalledTimes(1);
    expect(generateObjectMock).not.toHaveBeenCalled();
  });

  it("honors a 'text' override (uses generateText)", async () => {
    const tool = makeProvider();
    await tool.execute(baseRequest({ output_mode: "text" }) as never);

    expect(generateTextMock).toHaveBeenCalledTimes(1);
    expect(generateObjectMock).not.toHaveBeenCalled();
  });

  it("ignores an invalid override and falls back to auto (strict → generateObject)", async () => {
    const tool = makeProvider();
    await tool.execute(baseRequest({ output_mode: "bogus" }) as never);

    expect(generateObjectMock).toHaveBeenCalledTimes(1);
    expect(generateTextMock).not.toHaveBeenCalled();
  });

  it("strips output_mode from the params reaching the vendor SDK call", async () => {
    const tool = makeProvider();
    await tool.execute(baseRequest({ output_mode: "hint" }) as never);

    // hint → generateText; assert the options object carries no output_mode.
    expect(generateTextMock).toHaveBeenCalledTimes(1);
    const opts = generateTextMock.mock.calls[0][0] as Record<string, unknown>;
    expect("output_mode" in opts).toBe(false);
    // Nested guard: output_mode must not leak via providerOptions either.
    expect(JSON.stringify(opts)).not.toContain("output_mode");
  });
});
