#!/usr/bin/env npx tsx
/**
 * structured-consumer-ts - Cross-Runtime Structured Output Consumer
 *
 * Tests that a TypeScript consumer with Zod structured output receives
 * proper structured JSON from a Python Claude provider.
 *
 * Validates cross-runtime structured output works for non-Python consumers.
 */

import { FastMCP, mesh } from "@mcpmesh/sdk";
import { z } from "zod";

const server = new FastMCP({
  name: "Structured Consumer TS",
  version: "1.0.0",
});

// Structured output schema
const CountryInfo = z.object({
  name: z.string().describe("Name of the country"),
  capital: z.string().describe("Capital city"),
  population: z.string().describe("Approximate population"),
  continent: z.string().describe("Continent the country is in"),
});

// LLM-powered tool with structured output via Zod schema
const getCountryInfo = mesh.llm({
  name: "get_country_info",
  capability: "get_country_info",
  description: "Get structured country information using LLM",
  tags: ["structured", "claude", "cross-runtime", "typescript"],
  version: "1.0.0",

  // LLM Configuration - mesh delegation to Python Claude provider
  provider: { capability: "llm", tags: ["+claude"] },
  maxIterations: 1,

  // Structured output via Zod schema
  returns: CountryInfo,

  // Input schema
  parameters: z.object({
    ctx: z.object({
      country: z.string().describe("Country to get info about"),
    }),
  }),

  contextParam: "ctx",

  // Handler
  execute: async ({ ctx }, { llm }) => {
    return await llm(`Provide information about ${ctx.country}`);
  },
});

server.addTool(getCountryInfo);

const agent = mesh(server, {
  name: "structured-consumer-ts",
  version: "1.0.0",
  description: "TypeScript consumer testing cross-runtime structured output",
  httpPort: 9041,
});

console.log("structured-consumer-ts agent initialized. Waiting for mesh connections...");
