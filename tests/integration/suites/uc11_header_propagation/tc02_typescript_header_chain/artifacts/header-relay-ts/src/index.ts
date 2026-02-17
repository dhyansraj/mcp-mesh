#!/usr/bin/env npx tsx
/**
 * header-relay-ts - Calls echo_headers dependency and returns result
 */

import { FastMCP, mesh, McpMeshTool } from "@mcpmesh/sdk";
import { z } from "zod";

const server = new FastMCP({
  name: "Header Relay TS",
  version: "1.0.0",
});

const agent = mesh(server, {
  name: "header-relay-ts",
  httpPort: 0,
});

agent.addTool({
  name: "relay_headers",
  capability: "relay_headers",
  description: "Call echo_headers and return result",
  dependencies: ["echo_headers"],
  parameters: z.object({}),
  execute: async (
    args: {},
    echoSvc: McpMeshTool | null = null
  ): Promise<string> => {
    if (!echoSvc) return '{"error": "echo_headers not available"}';
    const result = await echoSvc({});
    return JSON.stringify(result);
  },
});

console.log("header-relay-ts agent defined. Waiting for auto-start...");
