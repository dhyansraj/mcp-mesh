#!/usr/bin/env npx tsx
/**
 * header-echo-ts - Returns propagated headers as JSON
 */

import { FastMCP, mesh, getCurrentPropagatedHeaders } from "@mcpmesh/sdk";
import { z } from "zod";

const server = new FastMCP({
  name: "Header Echo TS",
  version: "1.0.0",
});

const agent = mesh(server, {
  name: "header-echo-ts",
  httpPort: 0,
});

agent.addTool({
  name: "echo_headers",
  capability: "echo_headers",
  description: "Return propagated headers",
  parameters: z.object({}),
  execute: async () => {
    const headers = getCurrentPropagatedHeaders();
    return JSON.stringify(headers);
  },
});

console.log("header-echo-ts agent defined. Waiting for auto-start...");
