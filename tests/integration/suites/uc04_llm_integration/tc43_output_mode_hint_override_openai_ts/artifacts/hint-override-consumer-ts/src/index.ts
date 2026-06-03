#!/usr/bin/env npx tsx
/**
 * hint-override-consumer-ts - TS consumer that FORCES outputMode: "hint".
 *
 * Issue #1112 finding #6: a mesh.llm consumer can set outputMode to override the
 * provider's auto-selected structured-output mode. OpenAI auto-selects strict
 * (native responseFormat); this consumer forces "hint" so the provider must embed
 * the schema in the prompt and DROP responseFormat while still producing valid
 * structured output.
 *
 * Mirrors tc32's structured-consumer-openai-ts (same simple CountryInfo Zod
 * schema). The get_country_info_hint tool is ADDITIVE — the default
 * get_country_info (auto mode) is kept for parity.
 *
 * Provider runtime under test: TypeScript OpenAI provider (openai-provider-ts).
 */

import { FastMCP, mesh } from "@mcpmesh/sdk";
import { z } from "zod";

const server = new FastMCP({
  name: "Hint Override Consumer OpenAI TS",
  version: "1.0.0",
});

const CountryInfo = z.object({
  name: z.string().describe("Name of the country"),
  capital: z.string().describe("Capital city"),
  population: z.string().describe("Approximate population"),
  continent: z.string().describe("Continent the country is in"),
});

// Default (auto / unset outputMode) — kept for parity with tc32.
const getCountryInfo = mesh.llm({
  name: "get_country_info",
  capability: "get_country_info",
  description: "Get structured country information using LLM (auto mode)",
  tags: ["structured", "openai", "typescript"],
  version: "1.0.0",
  provider: { capability: "llm", tags: ["+openai"] },
  maxIterations: 1,
  returns: CountryInfo,
  parameters: z.object({
    ctx: z.object({
      country: z.string().describe("Country to get info about"),
    }),
  }),
  contextParam: "ctx",
  execute: async ({ ctx }, { llm }) => {
    return await llm(`Provide information about ${ctx.country}`);
  },
});

// OVERRIDE: outputMode: "hint" (Issue #1112 finding #6).
const getCountryInfoHint = mesh.llm({
  name: "get_country_info_hint",
  capability: "get_country_info_hint",
  description: "Get structured country information using LLM with forced HINT mode",
  tags: ["structured", "openai", "typescript", "hint-override"],
  version: "1.0.0",
  provider: { capability: "llm", tags: ["+openai"] },
  maxIterations: 1,
  // Force HINT: overrides the OpenAI provider's auto-selected STRICT.
  outputMode: "hint",
  returns: CountryInfo,
  parameters: z.object({
    ctx: z.object({
      country: z.string().describe("Country to get info about"),
    }),
  }),
  contextParam: "ctx",
  execute: async ({ ctx }, { llm }) => {
    return await llm(`Provide information about ${ctx.country}`);
  },
});

server.addTool(getCountryInfo);
server.addTool(getCountryInfoHint);

const agent = mesh(server, {
  name: "hint-override-consumer-ts",
  version: "1.0.0",
  description: "TypeScript consumer forcing outputMode=hint against an OpenAI provider",
  httpPort: 9043,
});

console.log("hint-override-consumer-ts agent initialized. Waiting for mesh connections...");
