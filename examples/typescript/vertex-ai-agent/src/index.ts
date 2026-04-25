/**
 * vertex-ai-agent (TypeScript) — Minimal Gemini-via-Vertex-AI agent
 *
 * Demonstrates calling Google Gemini through Vertex AI (IAM auth) instead of
 * AI Studio, using the Vercel AI SDK's @ai-sdk/google-vertex provider.
 *
 * The only differences from a Gemini AI Studio agent are:
 *   - model prefix:   "vertex_ai/<model>"   (vs "gemini/<model>")
 *   - auth env vars:  GOOGLE_VERTEX_PROJECT + GOOGLE_VERTEX_LOCATION + ADC
 *                     (vs GOOGLE_GENERATIVE_AI_API_KEY)
 *
 * Mesh-side prompt shaping (HINT-mode for tool calls, STRICT-mode for
 * tool-free structured output) is identical for both backends — the same
 * GeminiHandler is selected for vendor "vertex_ai".
 */

import { FastMCP, mesh } from "@mcpmesh/sdk";
import { z } from "zod";

const server = new FastMCP({
  name: "Vertex AI Agent (TS)",
  version: "1.0.0",
});

const agent = mesh(server, {
  name: "vertex-ai-agent-ts",
  version: "1.0.0",
  description: "Gemini via Vertex AI (IAM auth) demo agent — TypeScript",
  httpPort: 9041,
});

// Zero-code Vertex AI provider — selected via the vertex_ai/* model prefix.
agent.addLlmProvider({
  name: "vertex_chat",
  model: "vertex_ai/gemini-2.0-flash",
  capability: "llm",
  tags: ["llm", "gemini", "vertex", "provider"],
  version: "1.0.0",
});

// Structured-output tool: returns a CapitalInfo object.
const CapitalInfo = z.object({
  name: z.string().describe("The country name"),
  capital: z.string().describe("The capital city"),
});

const capitalOfTool = mesh.llm({
  name: "capital_of",
  capability: "capital_lookup",
  description: "Return the capital of a country as a structured CapitalInfo object",
  tags: ["geography", "llm"],
  version: "1.0.0",

  // Mesh delegation — find any LLM provider tagged "vertex".
  provider: { capability: "llm", tags: ["+vertex"] },
  systemPrompt:
    "You answer geography questions concisely. " +
    "Return the country name and its capital as structured JSON.",

  // Input schema for the tool.
  parameters: z.object({
    country: z.string().describe("Country to look up"),
  }),

  // Output schema — triggers HINT-mode prompt shaping when combined with tools.
  returns: CapitalInfo,

  execute: async ({ country }, { llm }) => {
    return await llm(`What is the capital of ${country}?`);
  },
});

server.addTool(capitalOfTool);

console.log("vertex-ai-agent-ts initialized. Waiting for auto-start...");
