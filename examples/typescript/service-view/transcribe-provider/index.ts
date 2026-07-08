/**
 * transcribe-provider — MCP Mesh agent (TypeScript).
 *
 * Publishes the dotted capability `media.transcribe`, declared EXPLICITLY via
 * `agent.addTool({ capability, ... })` — the third slice of the shared `media.*`
 * namespace, served by its own agent.
 *
 * Cross-runtime: parameter names (`assetId`, `text`) and the capability match
 * the Java and Python providers, so any-runtime gateways are interchangeable.
 *
 * Run:
 *   cd examples/typescript/service-view/transcribe-provider
 *   npm install
 *   npx tsx index.ts
 */

import { mesh, FastMCP } from "@mcpmesh/sdk";
import { z } from "zod";

const server = new FastMCP({
  name: "Transcribe Provider Service",
  version: "1.0.0",
});

const agent = mesh(server, {
  name: "transcribe-provider",
  httpPort: 8132,
  description: "Publishes media.transcribe into the shared media.* namespace",
});

agent.addTool({
  name: "transcribe",
  capability: "media.transcribe",
  parameters: z.object({
    assetId: z.string().describe("Media asset identifier"),
    text: z.string().describe("Source audio text"),
  }),
  execute: async (args) => {
    const { assetId, text } = args as { assetId: string; text: string };
    const stripped = text.trim();
    const wordCount = stripped ? stripped.split(/\s+/).length : 0;
    return {
      assetId,
      transcript: `[${assetId}] ${stripped.toUpperCase()}`,
      wordCount,
      provider: "transcribe-provider",
    };
  },
});

// The SDK auto-starts after module loading completes.
console.log("transcribe-provider defined — publishes media.transcribe. Waiting for auto-start...");
