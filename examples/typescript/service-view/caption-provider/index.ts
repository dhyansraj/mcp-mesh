/**
 * caption-provider — MCP Mesh agent (TypeScript).
 *
 * Publishes ONE slice of the shared `media.*` namespace. The dotted capability
 * `media.caption` is declared EXPLICITLY via `agent.addTool({ capability, ... })`
 * — the `media.*` namespace is entirely user-chosen, nothing is hard-coded.
 *
 * Cross-runtime: the parameter names (`assetId`, `text`) and the `media.caption`
 * capability match the Java and Python providers exactly, so a gateway in ANY
 * runtime can consume this provider.
 *
 * Run:
 *   cd examples/typescript/service-view/caption-provider
 *   npm install
 *   npx tsx index.ts
 */

import { mesh, FastMCP } from "@mcpmesh/sdk";
import { z } from "zod";

const server = new FastMCP({
  name: "Caption Provider Service",
  version: "1.0.0",
});

const agent = mesh(server, {
  name: "caption-provider",
  httpPort: 8130,
  description: "Publishes media.caption into the shared media.* namespace",
});

agent.addTool({
  name: "caption",
  capability: "media.caption",
  parameters: z.object({
    assetId: z.string().describe("Media asset identifier"),
    text: z.string().describe("Source description text"),
  }),
  execute: async (args) => {
    const { assetId, text } = args as { assetId: string; text: string };
    return {
      assetId,
      caption: `A scene showing ${text.trim().toLowerCase()}.`,
      provider: "caption-provider",
    };
  },
});

// The SDK auto-starts after module loading completes.
console.log("caption-provider defined — publishes media.caption. Waiting for auto-start...");
