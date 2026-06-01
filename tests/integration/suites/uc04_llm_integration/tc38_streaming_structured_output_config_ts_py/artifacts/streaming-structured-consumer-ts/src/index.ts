#!/usr/bin/env npx tsx
/**
 * streaming-structured-consumer-ts - RFC #1100 validation consumer.
 *
 * Drives the STREAMING + STRUCTURED-OUTPUT combination against a Python
 * Claude provider on a capable model (anthropic/claude-sonnet-4-5):
 *
 *   - provider tags include "ai.mcpmesh.stream" → the registry resolver
 *     hands back the provider's auto-generated process_chat_stream tool.
 *   - `returns` is a Zod object → the TS MeshLlmAgent.stream() path forwards
 *     `output_schema` in model_params (TS, unlike Python, does NOT gate
 *     stream() on str output_type — see src/runtime/typescript/src/llm-agent.ts).
 *   - `filter: [{ capability: "calculator" }]` wires a real mesh tool so the
 *     provider runs its NATIVE streaming agentic loop (process_chat_stream's
 *     tool-endpoints branch → anthropic_native.complete_stream →
 *     _build_create_kwargs), which is the exact code path RFC #1100 changed.
 *     (A no-tools consumer would hit the LiteLLM no-tools branch instead and
 *     never exercise the native output_config adapter.)
 *
 * The handler consumes llm.stream() chunk-by-chunk, accumulates the
 * text_delta chunks into a single string, parses it as JSON, validates
 * against the schema, and returns the structured object. It also echoes
 * diagnostics (chunk count, raw accumulated text) so the test can assert
 * the stream actually chunked and the JSON parsed cleanly.
 */

import { FastMCP, mesh } from "@mcpmesh/sdk";
import { z } from "zod";

const server = new FastMCP({
  name: "Streaming Structured Consumer TS",
  version: "1.0.0",
});

// Structured output schema the model must emit as streamed JSON.
const CalcReport = z.object({
  expression: z.string().describe("The arithmetic expression that was computed"),
  result: z.number().describe("The numeric result"),
  explanation: z.string().describe("One short sentence explaining the calculation"),
});

const streamingCalc = mesh.llm({
  name: "streaming_calc_report",
  capability: "streaming_calc_report",
  description:
    "Compute an arithmetic expression using mesh calculator tools and return " +
    "a structured report — streamed token-by-token from a Claude provider.",
  tags: ["structured", "streaming", "claude", "cross-runtime", "typescript"],
  version: "1.0.0",

  // Mesh delegation to the Python Claude provider. The ai.mcpmesh.stream tag
  // opt-in is REQUIRED in TS to resolve the streaming provider variant.
  provider: { capability: "llm", tags: ["+claude", "ai.mcpmesh.stream"] },

  // Wire the real calculator mesh tools so the provider runs its NATIVE
  // streaming agentic loop (forces the anthropic_native output_config path).
  filter: [{ capability: "calculator" }],
  filterMode: "all",
  maxIterations: 5,

  // Structured output via Zod schema → drives output_schema in model_params.
  returns: CalcReport,

  parameters: z.object({
    ctx: z.object({
      a: z.number().describe("First operand"),
      b: z.number().describe("Second operand"),
    }),
  }),
  contextParam: "ctx",

  execute: async ({ ctx }, { llm }) => {
    const prompt =
      `Use the calculator tools to multiply ${ctx.a} by ${ctx.b}, then add ${ctx.a}. ` +
      `Report the final arithmetic expression, the numeric result, and a one-sentence explanation.`;

    // Consume the streaming provider chunk-by-chunk. With RFC #1100 these
    // are Anthropic text_delta chunks carrying the structured JSON.
    const chunks: string[] = [];
    for await (const chunk of llm.stream(prompt)) {
      chunks.push(chunk);
    }
    const accumulated = chunks.join("");

    // The streamed text_delta chunks accumulate into the final JSON object.
    // Parse + validate against the schema (this is what proves the streamed
    // JSON is well-formed and schema-valid — no thinking text leaked in).
    let parsedOk = false;
    let parseError = "";
    let report: z.infer<typeof CalcReport> | null = null;
    try {
      const obj = JSON.parse(accumulated.trim());
      report = CalcReport.parse(obj);
      parsedOk = true;
    } catch (e) {
      parseError = String(e);
    }

    // Surface diagnostics in the returned object so the test can assert on
    // streaming behavior AND the structured result in one tool call.
    return {
      expression: report?.expression ?? "",
      result: report?.result ?? 0,
      explanation: report?.explanation ?? "",
      // Diagnostics (extra keys are fine — returns schema is for the model,
      // the tool return is serialized as-is to the caller).
      _diag_chunk_count: chunks.length,
      _diag_accumulated: accumulated,
      _diag_parsed_ok: parsedOk,
      _diag_parse_error: parseError,
    } as unknown as z.infer<typeof CalcReport>;
  },
});

server.addTool(streamingCalc);

const agent = mesh(server, {
  name: "streaming-structured-consumer-ts",
  version: "1.0.0",
  description: "TS consumer driving streaming + structured output (RFC #1100)",
  httpPort: 9042,
});

console.log(
  "streaming-structured-consumer-ts initialized. Waiting for mesh connections..."
);
