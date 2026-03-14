#!/usr/bin/env npx tsx
/**
 * structured-consumer-openai-ts - Cross-Runtime Structured Output Consumer (OpenAI)
 *
 * Tests that a TypeScript consumer with Zod structured output receives
 * proper structured JSON from a Python OpenAI provider.
 */

import { FastMCP, mesh } from "@mcpmesh/sdk";
import { z } from "zod";

const server = new FastMCP({
  name: "Structured Consumer OpenAI TS",
  version: "1.0.0",
});

const CountryInfo = z.object({
  name: z.string().describe("Name of the country"),
  capital: z.string().describe("Capital city"),
  population: z.string().describe("Approximate population"),
  continent: z.string().describe("Continent the country is in"),
});

const getCountryInfo = mesh.llm({
  name: "get_country_info",
  capability: "get_country_info",
  description: "Get structured country information using LLM",
  tags: ["structured", "openai", "cross-runtime", "typescript"],
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

server.addTool(getCountryInfo);

const agent = mesh(server, {
  name: "structured-consumer-openai-ts",
  version: "1.0.0",
  description: "TypeScript consumer testing cross-runtime structured output with OpenAI",
  httpPort: 9048,
});

console.log("structured-consumer-openai-ts agent initialized. Waiting for mesh connections...");
