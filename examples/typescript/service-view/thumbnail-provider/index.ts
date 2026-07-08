/**
 * thumbnail-provider — MCP Mesh agent (TypeScript).
 *
 * Publishes the dotted capability `media.thumbnail`, declared EXPLICITLY via
 * `agent.addTool({ capability, ... })` — a second slice of the shared `media.*`
 * namespace, served by a DIFFERENT agent than caption/transcribe.
 *
 * Cross-runtime: parameter names (`assetId`, `width`) and the capability match
 * the Java and Python providers, so any-runtime gateways are interchangeable.
 *
 * Run:
 *   cd examples/typescript/service-view/thumbnail-provider
 *   npm install
 *   npx tsx index.ts
 */

import { mesh, FastMCP } from "@mcpmesh/sdk";
import { z } from "zod";

const server = new FastMCP({
  name: "Thumbnail Provider Service",
  version: "1.0.0",
});

const agent = mesh(server, {
  name: "thumbnail-provider",
  httpPort: 8131,
  description: "Publishes media.thumbnail into the shared media.* namespace",
});

agent.addTool({
  name: "thumbnail",
  capability: "media.thumbnail",
  parameters: z.object({
    assetId: z.string().describe("Media asset identifier"),
    width: z.number().int().positive().describe("Requested thumbnail width in pixels"),
  }),
  execute: async (args) => {
    const { assetId, width } = args as { assetId: string; width: number };
    const w = width && width > 0 ? width : 128;
    const h = Math.max(1, Math.floor((w * 9) / 16));
    return {
      assetId,
      uri: `thumb://${assetId}?w=${w}&h=${h}`,
      size: `${w}x${h}`,
      provider: "thumbnail-provider",
    };
  },
});

// The SDK auto-starts after module loading completes.
console.log("thumbnail-provider defined — publishes media.thumbnail. Waiting for auto-start...");
