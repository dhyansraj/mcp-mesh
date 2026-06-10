/**
 * Gemini SDK-managed agentic loop wiring — issue #1160.
 *
 * AI SDK v6 removed `maxSteps` from generateText; loop control is now
 * `stopWhen` with a default of `stepCountIs(1)`. The provider previously set
 * `requestOptions.maxSteps`, which landed in the `...settings` rest and was
 * silently ignored — Gemini executed the tool-call step but never did the
 * follow-up generation, returning an empty assistant message.
 *
 * These tests mock `generateText` (keeping the REAL `stepCountIs`/`tool`/
 * `jsonSchema` via importOriginal) and assert the options object that reaches
 * the AI SDK:
 *
 *  - Gemini + `_mesh_endpoint` tools: `stopWhen` is set to the result of
 *    `stepCountIs(resolvedMaxIterations)`. `stepCountIs(n)` returns a
 *    predicate `({ steps }) => steps.length === n`, so we assert the
 *    predicate's behavior at the boundary (true at n steps, false at n-1).
 *  - The removed `maxSteps` key is NOT present (regression guard).
 *  - Non-Gemini vendors (manual provider-managed loop) do NOT set `stopWhen`.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

const generateTextMock = vi.fn();
const generateObjectMock = vi.fn();

vi.mock("ai", async (importOriginal) => {
  const actual = await importOriginal<typeof import("ai")>();
  return {
    ...actual,
    generateText: (opts: unknown) => generateTextMock(opts),
    generateObject: (opts: unknown) => generateObjectMock(opts),
  };
});

// Keep tracing inert/deterministic (publishTraceSpan is best-effort anyway).
vi.mock("../tracing.js", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../tracing.js")>();
  return {
    ...actual,
    generateTraceId: () => "trace-mock",
    generateSpanId: () => "span-mock",
    publishTraceSpan: vi.fn(async () => false),
    matchesPropagateHeader: () => false,
  };
});

import { llmProvider } from "../llm-provider.js";

type StopWhenPredicate = (options: { steps: unknown[] }) => boolean | PromiseLike<boolean>;

function meshToolRequest(modelParams: Record<string, unknown>) {
  return {
    request: {
      messages: [{ role: "user", content: "What's the weather in Paris?" }],
      tools: [
        {
          type: "function",
          function: {
            name: "get_weather",
            description: "Get the current weather for a city",
            parameters: {
              type: "object",
              properties: { city: { type: "string" } },
              required: ["city"],
            },
            // Mesh-enriched endpoint → provider-managed tool execution
            _mesh_endpoint: "http://weather-agent.local:9100",
          },
        },
      ],
      model_params: { ...modelParams },
    },
  };
}

async function stepsAtCount(stopWhen: StopWhenPredicate, count: number): Promise<boolean> {
  return await stopWhen({ steps: new Array(count).fill({}) });
}

describe("Gemini SDK-managed loop wires stopWhen (#1160)", () => {
  beforeEach(() => {
    generateTextMock.mockReset();
    generateObjectMock.mockReset();
    generateTextMock.mockResolvedValue({
      text: "It is sunny in Paris.",
      toolCalls: [],
      usage: { inputTokens: 1, outputTokens: 1 },
      finishReason: "stop",
    });
    // Model creation must not depend on real credentials at request time
    // (generateText is mocked), but keep keys set for construction safety.
    process.env.GOOGLE_GENERATIVE_AI_API_KEY = "test-key";
    process.env.ANTHROPIC_API_KEY = "test-key";
  });

  afterEach(() => {
    delete process.env.GOOGLE_GENERATIVE_AI_API_KEY;
    delete process.env.ANTHROPIC_API_KEY;
    vi.restoreAllMocks();
  });

  it("sets stopWhen=stepCountIs(max_iterations) and never the removed maxSteps", async () => {
    const tool = llmProvider({ model: "gemini/gemini-2.5-flash", capability: "llm" });
    await tool.execute(meshToolRequest({ max_iterations: 25 }) as never);

    expect(generateTextMock).toHaveBeenCalledTimes(1);
    const opts = generateTextMock.mock.calls[0][0] as Record<string, unknown>;

    // AI SDK v6 removed maxSteps — it must not be passed at all.
    expect("maxSteps" in opts).toBe(false);

    // stopWhen must be the stepCountIs(25) predicate: stops exactly when the
    // step count reaches the resolved cap.
    const stopWhen = opts.stopWhen as StopWhenPredicate;
    expect(typeof stopWhen).toBe("function");
    expect(await stepsAtCount(stopWhen, 25)).toBe(true);
    expect(await stepsAtCount(stopWhen, 24)).toBe(false);
    expect(await stepsAtCount(stopWhen, 1)).toBe(false);
  });

  it("defaults stopWhen to stepCountIs(10) when no cap is forwarded", async () => {
    delete process.env.MESH_LLM_MAX_ITERATIONS;
    const tool = llmProvider({ model: "gemini/gemini-2.5-flash", capability: "llm" });
    await tool.execute(meshToolRequest({}) as never);

    expect(generateTextMock).toHaveBeenCalledTimes(1);
    const opts = generateTextMock.mock.calls[0][0] as Record<string, unknown>;
    expect("maxSteps" in opts).toBe(false);

    const stopWhen = opts.stopWhen as StopWhenPredicate;
    expect(typeof stopWhen).toBe("function");
    expect(await stepsAtCount(stopWhen, 10)).toBe(true);
    expect(await stepsAtCount(stopWhen, 9)).toBe(false);
  });

  it("non-Gemini vendors keep the manual loop: no stopWhen, no maxSteps", async () => {
    const tool = llmProvider({ model: "anthropic/claude-sonnet-4-5", capability: "llm" });
    await tool.execute(meshToolRequest({ max_iterations: 25 }) as never);

    expect(generateTextMock).toHaveBeenCalledTimes(1);
    const opts = generateTextMock.mock.calls[0][0] as Record<string, unknown>;
    expect(opts.stopWhen).toBeUndefined();
    expect("maxSteps" in opts).toBe(false);
  });
});
