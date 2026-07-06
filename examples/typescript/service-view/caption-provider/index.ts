/**
 * caption-provider — MCP Mesh agent (TypeScript).
 *
 * Publishes ONE slice of the shared `media.*` namespace via producer sugar
 * (RFC #1280). `agent.addService("media", { caption })` publishes the `caption`
 * entry as a mesh tool under the capability `media.caption` (prefix + method
 * name). The `"media"` prefix is entirely user-chosen — nothing is hard-coded.
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

const server = new FastMCP({
  name: "Caption Provider Service",
  version: "1.0.0",
});

const agent = mesh(server, {
  name: "caption-provider",
  httpPort: 8130,
  description: "Publishes media.caption into the shared media.* namespace",
});

agent.addService("media", {
  caption: async (args: { assetId: string; text: string }) => ({
    assetId: args.assetId,
    caption: `A scene showing ${args.text.trim().toLowerCase()}.`,
    provider: "caption-provider",
  }),
});

// The SDK auto-starts after module loading completes.
console.log("caption-provider defined — publishes media.caption. Waiting for auto-start...");
