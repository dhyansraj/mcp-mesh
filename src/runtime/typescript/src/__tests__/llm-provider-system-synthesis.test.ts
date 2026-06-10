/**
 * Provider synthesizes a system message when the consumer supplies none but
 * structured-output (hint mode) instructions still need to reach the model —
 * #1112 finding 6.
 *
 * Root cause: the request.messages transform only augmented an EXISTING system
 * message with the schema/JSON hint instructions. A mesh-delegated consumer
 * with a typed schema and NO systemPrompt produced no system message, so the
 * hint instructions were silently dropped. In hint mode there is no native
 * response_format backstop (strict-only), so the model returned prose and the
 * consumer's ResponseParser threw "Could not extract JSON from response."
 *
 * Fix: when NO system message exists AND mode !== "text" AND a schema is
 * present, synthesize a system message via formatSystemPrompt("", ...) and
 * prepend it.
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

interface Msg {
  role: string;
  content: unknown;
}

function systemMessages(opts: Record<string, unknown>): Msg[] {
  return (opts.messages as Msg[]).filter((m) => m.role === "system");
}

beforeEach(() => {
  generateObjectMock.mockReset();
  generateTextMock.mockReset();
  generateObjectMock.mockResolvedValue({
    object: { answer: "ok" },
    usage: { inputTokens: 1, outputTokens: 1 },
    finishReason: "stop",
  });
  generateTextMock.mockResolvedValue({
    text: '{"answer":"ok"}',
    toolCalls: [],
    usage: { inputTokens: 1, outputTokens: 1 },
    finishReason: "stop",
  });
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("provider system-message synthesis (#1112 finding 6)", () => {
  it("synthesizes a system message with schema/JSON hint instructions when none exists (hint + schema)", async () => {
    const tool = makeProvider();
    await tool.execute({
      request: {
        // NO system message — only a user turn.
        messages: [{ role: "user", content: "hi" }],
        model_params: {
          output_schema: SCHEMA,
          output_type_name: "Answer",
          output_mode: "hint",
        },
      },
    } as never);

    // hint → generateText.
    expect(generateTextMock).toHaveBeenCalledTimes(1);
    const opts = generateTextMock.mock.calls[0][0] as Record<string, unknown>;
    const systems = systemMessages(opts);

    // A system message was synthesized and prepended.
    expect(systems).toHaveLength(1);
    expect((opts.messages as Msg[])[0].role).toBe("system");

    const content = systems[0].content as string;
    // Carries the hint-mode JSON instructions + schema field.
    expect(content).toContain("OUTPUT FORMAT:");
    expect(content).toContain("ONLY valid JSON");
    expect(content).toContain("answer");
  });

  it("augments an EXISTING system message (hint + schema) without double-adding", async () => {
    const tool = makeProvider();
    await tool.execute({
      request: {
        messages: [
          { role: "system", content: "You are helpful." },
          { role: "user", content: "hi" },
        ],
        model_params: {
          output_schema: SCHEMA,
          output_type_name: "Answer",
          output_mode: "hint",
        },
      },
    } as never);

    expect(generateTextMock).toHaveBeenCalledTimes(1);
    const opts = generateTextMock.mock.calls[0][0] as Record<string, unknown>;
    const systems = systemMessages(opts);

    // Exactly one system message — the original, augmented (not double-added).
    expect(systems).toHaveLength(1);
    const content = systems[0].content as string;
    expect(content).toContain("You are helpful.");
    expect(content).toContain("OUTPUT FORMAT:");
    expect(content).toContain("answer");
  });

  it("does NOT synthesize for strict mode with no system message (native response_format backstop)", async () => {
    const tool = makeProvider();
    await tool.execute({
      request: {
        messages: [{ role: "user", content: "hi" }],
        model_params: {
          output_schema: SCHEMA,
          output_type_name: "Answer",
          // No override → OpenAI auto-selects strict (no tools, has schema).
        },
      },
    } as never);

    // strict + schema + no tools → generateObject (structured output intact).
    expect(generateObjectMock).toHaveBeenCalledTimes(1);
    expect(generateTextMock).not.toHaveBeenCalled();

    const opts = generateObjectMock.mock.calls[0][0] as Record<string, unknown>;
    // No system message was synthesized — strict relies on response_format.
    expect(systemMessages(opts)).toHaveLength(0);
  });

  it("does NOT synthesize for text mode with no system message", async () => {
    const tool = makeProvider();
    await tool.execute({
      request: {
        messages: [{ role: "user", content: "hi" }],
        model_params: {
          output_schema: SCHEMA,
          output_type_name: "Answer",
          output_mode: "text",
        },
      },
    } as never);

    expect(generateTextMock).toHaveBeenCalledTimes(1);
    const opts = generateTextMock.mock.calls[0][0] as Record<string, unknown>;
    expect(systemMessages(opts)).toHaveLength(0);
  });

  it("does NOT synthesize when there is no schema (hint mode, no system message)", async () => {
    const tool = makeProvider();
    await tool.execute({
      request: {
        messages: [{ role: "user", content: "hi" }],
        model_params: {
          output_mode: "hint",
        },
      },
    } as never);

    expect(generateTextMock).toHaveBeenCalledTimes(1);
    const opts = generateTextMock.mock.calls[0][0] as Record<string, unknown>;
    expect(systemMessages(opts)).toHaveLength(0);
  });
});
