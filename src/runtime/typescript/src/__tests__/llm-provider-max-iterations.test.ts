/**
 * Provider-side max_iterations exhaustion signal — issue #1355 (Phase 2, TS).
 *
 * The provider-managed agentic loop must mark exhaustion STRUCTURALLY via a
 * `_mesh_stop_reason: "max_iterations"` sibling field on the reply envelope —
 * never an English marker in `content`. Two provider loops are exercised here
 * with the REAL `ai` module (generateText + stopWhen + tool execution) driven
 * by a `MockLanguageModelV3`:
 *
 *  1. Manual loop (Claude/OpenAI): iterates generateText itself. On exhaustion
 *     it sets `content` to the last genuine assistant text (or "") and adds the
 *     `_mesh_stop_reason` sibling. The old `"Maximum tool call iterations
 *     reached"` marker is gone from the wire.
 *
 *  2. Gemini SDK-managed loop (stopWhen = stepCountIs(n)): the AI SDK owns the
 *     loop. Step-cap exhaustion is detected post-call via
 *     `finishReason === "tool-calls"` at the step cap — the last step still
 *     wanted to call tools but the loop was cut off. A normal completion within
 *     the cap ends with `finishReason === "stop"` and carries NO discriminant.
 *
 * Tool execution goes through the provider's execute path → `callMcpTool`,
 * mocked here to return a canned tool result.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

// Per-step model results, controllable per test. vi.hoisted so the provider
// mock factories can reference it.
const modelHarness = vi.hoisted(() => ({
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  results: [] as any[],
  calls: 0,
}));

const callMcpToolMock = vi.hoisted(() => vi.fn());

// Shared doGenerate: return the scripted result for the current call, or the
// last scripted result if the loop runs past the script (the manual loop keeps
// calling until its own cap, so an exhaustion script only needs one repeated
// tool-call step). vi.hoisted so both mock factories can reference it; it closes
// over the hoisted `modelHarness` (both are hoisted together).
const doGenerate = vi.hoisted(() => async () => {
  const idx = Math.min(modelHarness.calls, modelHarness.results.length - 1);
  const result = modelHarness.results[idx];
  modelHarness.calls++;
  if (!result) {
    throw new Error(
      `MockLanguageModelV3: no scripted result for call ${modelHarness.calls}`,
    );
  }
  return result;
});

vi.mock("@ai-sdk/anthropic", async () => {
  const { MockLanguageModelV3 } = await import("ai/test");
  return {
    anthropic: (modelId: string) => new MockLanguageModelV3({ modelId, doGenerate }),
  };
});

vi.mock("@ai-sdk/google", async () => {
  const { MockLanguageModelV3 } = await import("ai/test");
  return {
    google: (modelId: string) => new MockLanguageModelV3({ modelId, doGenerate }),
  };
});

// Replace only callMcpTool — keep runWithTraceContext etc. real.
vi.mock("../proxy.js", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../proxy.js")>();
  return { ...actual, callMcpTool: callMcpToolMock };
});

// Keep tracing inert (publishTraceSpan is best-effort fire-and-forget).
vi.mock("../tracing.js", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../tracing.js")>();
  return { ...actual, publishTraceSpan: vi.fn(async () => false) };
});

import { llmProvider } from "../llm-provider.js";

// Tool-call step WITHOUT preamble text (Gemini path).
const TOOL_CALL_STEP = {
  content: [
    {
      type: "tool-call",
      toolCallId: "call-1",
      toolName: "get_weather",
      input: JSON.stringify({ city: "Paris" }),
    },
  ],
  finishReason: "tool-calls",
  usage: { inputTokens: 10, outputTokens: 5, totalTokens: 15 },
  warnings: [],
};

// Tool-call step WITH preamble prose (manual loop — proves `content` carries the
// last genuine assistant text on exhaustion, never an English marker).
const TOOL_CALL_STEP_WITH_TEXT = {
  content: [
    { type: "text", text: "still gathering data..." },
    {
      type: "tool-call",
      toolCallId: "call-1",
      toolName: "get_weather",
      input: JSON.stringify({ city: "Paris" }),
    },
  ],
  finishReason: "tool-calls",
  usage: { inputTokens: 10, outputTokens: 5, totalTokens: 15 },
  warnings: [],
};

const TEXT_STEP = {
  content: [{ type: "text", text: "It is sunny in Paris." }],
  finishReason: "stop",
  usage: { inputTokens: 20, outputTokens: 8, totalTokens: 28 },
  warnings: [],
};

function meshToolRequest(model: string, modelParams: Record<string, unknown>) {
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
            _mesh_endpoint: "http://weather-agent.local:9100",
          },
        },
      ],
      model_params: { ...modelParams, model },
    },
  };
}

beforeEach(() => {
  modelHarness.results = [];
  modelHarness.calls = 0;
  callMcpToolMock.mockReset();
  callMcpToolMock.mockResolvedValue(
    JSON.stringify({ temperature_c: 21, condition: "sunny" }),
  );
  process.env.ANTHROPIC_API_KEY = "test-key";
  process.env.GOOGLE_GENERATIVE_AI_API_KEY = "test-key";
  delete process.env.MESH_LLM_MAX_ITERATIONS;
});

afterEach(() => {
  delete process.env.ANTHROPIC_API_KEY;
  delete process.env.GOOGLE_GENERATIVE_AI_API_KEY;
  vi.restoreAllMocks();
});

describe("manual provider loop (Claude) — buffered exhaustion signal", () => {
  it("marks exhaustion with _mesh_stop_reason and NOT an English marker", async () => {
    // The model keeps requesting tools; the loop exhausts its cap (2).
    modelHarness.results = [TOOL_CALL_STEP_WITH_TEXT];

    const tool = llmProvider({ model: "anthropic/claude-sonnet-4-5", capability: "llm" });
    const raw = await tool.execute(
      meshToolRequest("anthropic/claude-sonnet-4-5", { max_iterations: 2 }) as never,
    );
    const response = JSON.parse(raw) as Record<string, unknown>;

    // The loop ran exactly the cap number of generations.
    expect(modelHarness.calls).toBe(2);

    // Structural discriminant present; content is the last genuine assistant
    // text, NOT the removed "Maximum tool call iterations reached" marker.
    expect(response._mesh_stop_reason).toBe("max_iterations");
    expect(response.content).toBe("still gathering data...");
    expect(response.content).not.toBe("Maximum tool call iterations reached");
  });

  it("exhaustion content is empty when no assistant preamble text was produced", async () => {
    modelHarness.results = [TOOL_CALL_STEP]; // no text parts

    const tool = llmProvider({ model: "anthropic/claude-sonnet-4-5", capability: "llm" });
    const raw = await tool.execute(
      meshToolRequest("anthropic/claude-sonnet-4-5", { max_iterations: 2 }) as never,
    );
    const response = JSON.parse(raw) as Record<string, unknown>;

    expect(response._mesh_stop_reason).toBe("max_iterations");
    expect(response.content).toBe("");
  });

  it("a normal completion carries NO discriminant", async () => {
    // Tool call on step 1, final text on step 2 — completes within the cap.
    modelHarness.results = [TOOL_CALL_STEP_WITH_TEXT, TEXT_STEP];

    const tool = llmProvider({ model: "anthropic/claude-sonnet-4-5", capability: "llm" });
    const raw = await tool.execute(
      meshToolRequest("anthropic/claude-sonnet-4-5", { max_iterations: 5 }) as never,
    );
    const response = JSON.parse(raw) as Record<string, unknown>;

    expect(response.content).toBe("It is sunny in Paris.");
    expect(response._mesh_stop_reason).toBeUndefined();
  });
});

describe("Gemini SDK-managed loop (stopWhen) — buffered exhaustion signal (T3)", () => {
  it("detects step-cap exhaustion via finishReason=tool-calls at the cap", async () => {
    // stopWhen = stepCountIs(1): the AI SDK executes the tool-call step then
    // stops — the model still wanted to call tools (finishReason tool-calls).
    modelHarness.results = [TOOL_CALL_STEP];

    const tool = llmProvider({ model: "gemini/gemini-2.5-flash", capability: "llm" });
    const raw = await tool.execute(
      meshToolRequest("gemini/gemini-2.5-flash", { max_iterations: 1 }) as never,
    );
    const response = JSON.parse(raw) as Record<string, unknown>;

    // The tool executed on step 1, but no follow-up generation happened.
    expect(callMcpToolMock).toHaveBeenCalledTimes(1);
    expect(response._mesh_stop_reason).toBe("max_iterations");
    // Tools were executed provider-side — no tool_calls leak to the consumer.
    expect(response.tool_calls).toBeUndefined();
  });

  it("a normal Gemini completion (finishReason=stop) carries NO discriminant", async () => {
    // Tool call on step 1, follow-up text on step 2 — completes within the cap.
    modelHarness.results = [TOOL_CALL_STEP, TEXT_STEP];

    const tool = llmProvider({ model: "gemini/gemini-2.5-flash", capability: "llm" });
    const raw = await tool.execute(
      meshToolRequest("gemini/gemini-2.5-flash", { max_iterations: 3 }) as never,
    );
    const response = JSON.parse(raw) as Record<string, unknown>;

    expect(response.content).toBe("It is sunny in Paris.");
    expect(response._mesh_stop_reason).toBeUndefined();
  });

  it("a natural completion landing EXACTLY at the cap carries NO discriminant", async () => {
    // Boundary case that discriminates last-step vs true-aggregate semantics.
    // stopWhen = stepCountIs(2): tool call on step 1, final text on step 2 — the
    // model stops NATURALLY on the text step, landing exactly at the cap (2==2).
    // The step-cap check (stepCount >= resolvedMaxIterations) now PASSES, so
    // correctness rests entirely on the last-step clause: the LAST step is a text
    // answer (empty `toolCalls`, finishReason "stop"), so NO discriminant. A
    // true-aggregate reading of `toolCalls`/`finishReason` (which would see the
    // step-1 tool call) would FALSELY mark this as exhaustion — this test would
    // then fail, catching that regression.
    modelHarness.results = [TOOL_CALL_STEP, TEXT_STEP];

    const tool = llmProvider({ model: "gemini/gemini-2.5-flash", capability: "llm" });
    const raw = await tool.execute(
      meshToolRequest("gemini/gemini-2.5-flash", { max_iterations: 2 }) as never,
    );
    const response = JSON.parse(raw) as Record<string, unknown>;

    expect(response.content).toBe("It is sunny in Paris.");
    expect(response._mesh_stop_reason).toBeUndefined();
  });
});
