/**
 * Gemini SDK-managed multi-step loop — end-to-end regression test for #1160.
 *
 * Uses the REAL `ai` module (generateText + stopWhen + tool execution) with a
 * `MockLanguageModelV3` (from `ai/test`) injected via a mocked
 * `@ai-sdk/google` provider. The model emits a tool call on step 1 and text
 * on step 2.
 *
 * With the broken `maxSteps` wiring (removed in AI SDK v6), generateText
 * defaulted to `stopWhen: stepCountIs(1)`: the loop stopped right after the
 * tool-call step, `result.text` was empty, and since the tools carried
 * `_mesh_endpoint` the provider also stripped tool_calls — consumers received
 * an empty assistant message. With `stopWhen: stepCountIs(n)` the loop does
 * the follow-up generation and the final text is non-empty.
 *
 * Tool execution goes through the provider's execute functions →
 * `callMcpTool`, which is mocked here to return a canned tool result.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

// Per-step model results, controllable per test. vi.hoisted so the
// vi.mock("@ai-sdk/google") factory can reference it.
const modelHarness = vi.hoisted(() => ({
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  results: [] as any[],
  calls: 0,
}));

const callMcpToolMock = vi.hoisted(() => vi.fn());

vi.mock("@ai-sdk/google", async () => {
  const { MockLanguageModelV3 } = await import("ai/test");
  return {
    google: (modelId: string) =>
      new MockLanguageModelV3({
        modelId,
        // Function form (not the array form: MockLanguageModelV3 indexes the
        // array AFTER pushing the call, skipping element 0).
        doGenerate: async () => {
          const result = modelHarness.results[modelHarness.calls];
          modelHarness.calls++;
          if (!result) {
            throw new Error(`MockLanguageModelV3: no scripted result for step ${modelHarness.calls}`);
          }
          return result;
        },
      }),
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

const TEXT_STEP = {
  content: [{ type: "text", text: "It is sunny in Paris." }],
  finishReason: "stop",
  usage: { inputTokens: 20, outputTokens: 8, totalTokens: 28 },
  warnings: [],
};

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
            _mesh_endpoint: "http://weather-agent.local:9100",
          },
        },
      ],
      model_params: { ...modelParams },
    },
  };
}

describe("Gemini multi-step loop with real generateText (#1160)", () => {
  beforeEach(() => {
    modelHarness.results = [TOOL_CALL_STEP, TEXT_STEP];
    modelHarness.calls = 0;
    callMcpToolMock.mockReset();
    callMcpToolMock.mockResolvedValue(
      JSON.stringify({ temperature_c: 21, condition: "sunny" })
    );
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("executes the tool on step 1 and returns the follow-up text from step 2", async () => {
    const tool = llmProvider({ model: "gemini/gemini-2.5-flash", capability: "llm" });
    const raw = await tool.execute(meshToolRequest({ max_iterations: 3 }) as never);
    const response = JSON.parse(raw) as Record<string, unknown>;

    // The model was called twice: tool-call step + follow-up generation.
    expect(modelHarness.calls).toBe(2);

    // The tool was executed provider-side via its _mesh_endpoint.
    expect(callMcpToolMock).toHaveBeenCalledTimes(1);
    const [endpoint, toolName, toolArgs] = callMcpToolMock.mock.calls[0];
    expect(endpoint).toBe("http://weather-agent.local:9100");
    expect(toolName).toBe("get_weather");
    expect(toolArgs).toEqual({ city: "Paris" });

    // #1160: the assistant message must carry the step-2 text, not be empty.
    expect(response.content).toBe("It is sunny in Paris.");

    // Tools were executed provider-side — no tool_calls leak to the consumer.
    expect(response.tool_calls).toBeUndefined();
  });

  it("logs no [multi_content] for a null tool result and still completes (#1250)", async () => {
    // A tool returning empty content now surfaces as null. The provider's
    // object branch is guarded against null, so it must NOT log a bogus
    // [multi_content] line; the loop still runs the follow-up generation.
    const prev = process.env.MCP_MESH_DEBUG_MODE;
    process.env.MCP_MESH_DEBUG_MODE = "true";
    const logSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    try {
      modelHarness.results = [TOOL_CALL_STEP, TEXT_STEP];
      modelHarness.calls = 0;
      callMcpToolMock.mockReset();
      callMcpToolMock.mockResolvedValue(null);

      const tool = llmProvider({ model: "gemini/gemini-2.5-flash", capability: "llm" });
      const raw = await tool.execute(meshToolRequest({ max_iterations: 3 }) as never);
      const response = JSON.parse(raw) as Record<string, unknown>;

      expect(callMcpToolMock).toHaveBeenCalledTimes(1);

      const multiContentLogged = logSpy.mock.calls.some((args) =>
        args.some((a) => typeof a === "string" && a.includes("[multi_content]"))
      );
      expect(multiContentLogged).toBe(false);

      expect(response.content).toBe("It is sunny in Paris.");
    } finally {
      logSpy.mockRestore();
      if (prev === undefined) {
        delete process.env.MCP_MESH_DEBUG_MODE;
      } else {
        process.env.MCP_MESH_DEBUG_MODE = prev;
      }
    }
  });

  it("honors the forwarded cap: max_iterations=1 stops after the tool-call step", async () => {
    const tool = llmProvider({ model: "gemini/gemini-2.5-flash", capability: "llm" });
    const raw = await tool.execute(meshToolRequest({ max_iterations: 1 }) as never);
    const response = JSON.parse(raw) as Record<string, unknown>;

    // stopWhen=stepCountIs(1): the tool still executes within step 1, but no
    // follow-up generation happens — proving the cap actually drives the loop.
    expect(modelHarness.calls).toBe(1);
    expect(callMcpToolMock).toHaveBeenCalledTimes(1);
    expect(response.content).toBe("");
    expect(response.tool_calls).toBeUndefined();
  });
});
