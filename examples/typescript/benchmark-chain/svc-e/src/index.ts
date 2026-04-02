#!/usr/bin/env npx tsx
/**
 * svc-e - MCP Mesh Agent
 *
 * Terminal service - generates response payload
 */

import { FastMCP, mesh } from "@mcpmesh/sdk";
import { z } from "zod";

const server = new FastMCP({
  name: "SvcE Service",
  version: "1.0.0",
});

const agent = mesh(server, {
  name: "svc-e",
  httpPort: 8080,
});

const PAYLOAD_SIZES: Record<string, number> = {
  "1kb": 1024,
  "10kb": 10240,
  "100kb": 102400,
  "1mb": 1048576,
};

function generatePayload(sizeKey: string): string {
  const targetBytes = PAYLOAD_SIZES[sizeKey] ?? 1024;
  const pattern = "abcdefghijklmnopqrstuvwxyz0123456789";
  const envelopeOverhead = '{"data":""}'.length;
  const dataLen = Math.max(targetBytes - envelopeOverhead, 0);
  const repetitions = Math.floor(dataLen / pattern.length) + 1;
  const data = pattern.repeat(repetitions).slice(0, dataLen);
  return JSON.stringify({ data });
}

agent.addTool({
  name: "generate_response",
  capability: "generate_response",
  description: "Terminal service that generates benchmark response",
  tags: ["benchmark", "chain", "terminal"],
  parameters: z.object({
    mode: z.string().default("baseline"),
    payload: z.string().default(""),
    payload_size: z.string().default("1kb"),
  }),
  execute: async (args) => {
    if (args.mode === "baseline") {
      return "Hello World";
    }
    return generatePayload(args.payload_size);
  },
});

console.log("svc-e agent defined. Waiting for auto-start...");
