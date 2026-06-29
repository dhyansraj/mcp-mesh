/**
 * Consumer-span LLM token telemetry — regression test for #1228.
 *
 * The dashboard aggregates per-agent / per-model token usage from `mesh:trace`
 * span fields `llm_input_tokens` / `llm_output_tokens` / `llm_total_tokens` /
 * `llm_model`. Python already stamps the consumer's own execution span (via the
 * `set_llm_metadata` contextvar read in ExecutionTracer); this asserts the TS
 * `@mesh.llm` consumer span reaches parity.
 *
 * The mesh-delegated provider is reached through `callMcpTool`, mocked here to
 * return the canned provider response JSON (incl. `_mesh_usage`). The agentic
 * loop in MeshLlmAgent parses `_mesh_usage`, accumulates totals across
 * iterations, finalizes `_meta`, and the `@mesh.llm` consumer span published in
 * llm.ts stamps the llm_* SpanData fields from it.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { z } from "zod";

const callMcpToolMock = vi.hoisted(() => vi.fn());
const publishTraceSpanMock = vi.hoisted(() => vi.fn(async () => true));

// Replace only callMcpTool — keep runWithTraceContext etc. real so the
// consumer span's trace context propagation behaves normally.
vi.mock("../proxy.js", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../proxy.js")>();
  return { ...actual, callMcpTool: callMcpToolMock };
});

// Capture published spans; keep everything else real.
vi.mock("../tracing.js", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../tracing.js")>();
  return { ...actual, publishTraceSpan: publishTraceSpanMock };
});

import { llm, LlmToolRegistry } from "../llm.js";
import { createLlmToolProxy } from "../llm-agent.js";
import type { SpanData } from "../tracing.js";

const FUNCTION_ID = "summarize";
const PROVIDER_ENDPOINT = "http://llm-provider.local:9200";

/** Provider response carrying token usage and (optionally) a tool call. */
function providerResponse(opts: {
  content: string;
  inputTokens: number;
  outputTokens: number;
  toolCall?: { id: string; name: string; args: string };
}): string {
  return JSON.stringify({
    role: "assistant",
    content: opts.content,
    ...(opts.toolCall
      ? {
          tool_calls: [
            {
              id: opts.toolCall.id,
              type: "function",
              function: { name: opts.toolCall.name, arguments: opts.toolCall.args },
            },
          ],
        }
      : {}),
    _mesh_usage: {
      prompt_tokens: opts.inputTokens,
      completion_tokens: opts.outputTokens,
    },
  });
}

/** The consumer's own `@mesh.llm` execution span (function_name === FUNCTION_ID). */
function consumerSpan(): SpanData | undefined {
  const calls = publishTraceSpanMock.mock.calls as unknown as Array<[SpanData]>;
  return calls.map((c) => c[0]).find((s) => s.functionName === FUNCTION_ID);
}

describe("consumer-span LLM token telemetry (#1228)", () => {
  beforeEach(() => {
    LlmToolRegistry.reset();
    callMcpToolMock.mockReset();
    publishTraceSpanMock.mockClear();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("stamps llm_* token fields on the consumer span for a single-iteration call", async () => {
    const tool = llm({
      name: FUNCTION_ID,
      provider: { capability: "llm-service" },
      parameters: z.object({}),
      execute: async (_args: unknown, { llm: llmCallable }: { llm: (m: string) => Promise<string> }) => {
        return llmCallable("Summarize the doc");
      },
    });

    LlmToolRegistry.getInstance().setResolvedProvider(FUNCTION_ID, {
      endpoint: PROVIDER_ENDPOINT,
      functionName: "process_chat",
      model: "claude-sonnet-4",
      agentId: "provider-agent",
    });

    callMcpToolMock.mockResolvedValue(
      providerResponse({ content: "A short summary.", inputTokens: 100, outputTokens: 40 })
    );

    await tool.execute({} as never);

    const span = consumerSpan();
    expect(span).toBeDefined();
    expect(span!.llmInputTokens).toBe(100);
    expect(span!.llmOutputTokens).toBe(40);
    expect(span!.llmTotalTokens).toBe(140);
    expect(span!.llmModel).toBe("claude-sonnet-4");
    expect(span!.llmProvider).toBe(`mesh:${PROVIDER_ENDPOINT}`);
  });

  it("accumulates token usage across a multi-iteration agentic loop", async () => {
    const tool = llm({
      name: FUNCTION_ID,
      provider: { capability: "llm-service" },
      parameters: z.object({}),
      execute: async (_args: unknown, { llm: llmCallable }: { llm: (m: string) => Promise<string> }) => {
        return llmCallable("Look something up then answer");
      },
    });

    LlmToolRegistry.getInstance().setResolvedProvider(FUNCTION_ID, {
      endpoint: PROVIDER_ENDPOINT,
      functionName: "process_chat",
      model: "claude-sonnet-4",
      agentId: "provider-agent",
    });

    // Register a resolved tool so the loop has a tool to call on iteration 1.
    // The proxy routes through the mocked callMcpTool for its result.
    LlmToolRegistry.getInstance().setResolvedTools(FUNCTION_ID, [
      createLlmToolProxy(
        {
          functionName: "lookup",
          capability: "lookup",
          endpoint: "http://tool-agent.local:9300",
          agentId: "tool-agent",
        },
        "Look up a value"
      ),
    ]);

    // Iteration 1: provider asks for a tool call (usage 50/20).
    // Tool result returned by the proxy/callMcpTool.
    // Iteration 2: provider returns final text (usage 70/30).
    callMcpToolMock
      .mockResolvedValueOnce(
        providerResponse({
          content: "",
          inputTokens: 50,
          outputTokens: 20,
          toolCall: { id: "call-1", name: "lookup", args: "{}" },
        })
      )
      .mockResolvedValueOnce(JSON.stringify({ value: 42 })) // tool result
      .mockResolvedValueOnce(
        providerResponse({ content: "The answer is 42.", inputTokens: 70, outputTokens: 30 })
      );

    await tool.execute({} as never);

    const span = consumerSpan();
    expect(span).toBeDefined();
    // Accumulated across both provider calls: 50+70 input, 20+30 output.
    expect(span!.llmInputTokens).toBe(120);
    expect(span!.llmOutputTokens).toBe(50);
    expect(span!.llmTotalTokens).toBe(170);
    expect(span!.llmModel).toBe("claude-sonnet-4");
  });

  it("stamps llm_* token fields when the handler throws AFTER an LLM call recorded usage", async () => {
    const boom = new Error("handler failed after LLM call");
    const tool = llm({
      name: FUNCTION_ID,
      provider: { capability: "llm-service" },
      parameters: z.object({}),
      execute: async (_args: unknown, { llm: llmCallable }: { llm: (m: string) => Promise<string> }) => {
        // Real LLM call records usage, THEN the handler fails.
        await llmCallable("Summarize the doc");
        throw boom;
      },
    });

    LlmToolRegistry.getInstance().setResolvedProvider(FUNCTION_ID, {
      endpoint: PROVIDER_ENDPOINT,
      functionName: "process_chat",
      model: "claude-sonnet-4",
      agentId: "provider-agent",
    });

    callMcpToolMock.mockResolvedValue(
      providerResponse({ content: "A short summary.", inputTokens: 100, outputTokens: 40 })
    );

    // The handler's exception must still propagate.
    await expect(tool.execute({} as never)).rejects.toThrow("handler failed after LLM call");

    const span = consumerSpan();
    expect(span).toBeDefined();
    expect(span!.success).toBe(false);
    // Accumulated usage from the LLM call before the throw is preserved.
    expect(span!.llmInputTokens).toBe(100);
    expect(span!.llmOutputTokens).toBe(40);
    expect(span!.llmTotalTokens).toBe(140);
    expect(span!.llmModel).toBe("claude-sonnet-4");
    expect(span!.llmProvider).toBe(`mesh:${PROVIDER_ENDPOINT}`);
  });

  it("publishes the consumer span WITHOUT llm_* fields when execute never calls the llm", async () => {
    const tool = llm({
      name: FUNCTION_ID,
      provider: { capability: "llm-service" },
      parameters: z.object({}),
      // Non-LLM path through the same wrapper: returns directly, no llm() call.
      execute: async () => "static result",
    });

    LlmToolRegistry.getInstance().setResolvedProvider(FUNCTION_ID, {
      endpoint: PROVIDER_ENDPOINT,
      functionName: "process_chat",
      model: "claude-sonnet-4",
      agentId: "provider-agent",
    });

    await tool.execute({} as never);

    const span = consumerSpan();
    expect(span).toBeDefined();
    expect(span!.llmInputTokens).toBeUndefined();
    expect(span!.llmOutputTokens).toBeUndefined();
    expect(span!.llmTotalTokens).toBeUndefined();
    expect(span!.llmModel).toBeUndefined();
    expect(span!.llmProvider).toBeUndefined();
    // callMcpTool must not have been invoked on this non-LLM path.
    expect(callMcpToolMock).not.toHaveBeenCalled();
  });
});
