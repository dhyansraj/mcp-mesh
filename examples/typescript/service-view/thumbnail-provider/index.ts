/**
 * thumbnail-provider — MCP Mesh agent (TypeScript).
 *
 * Publishes `media.thumbnail` via producer sugar (RFC #1280):
 * `agent.addService("media", { thumbnail })` publishes the `thumbnail` entry as
 * the dotted capability `media.thumbnail` — a second slice of the shared
 * `media.*` namespace, served by a DIFFERENT agent than caption/transcribe.
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

const server = new FastMCP({
  name: "Thumbnail Provider Service",
  version: "1.0.0",
});

const agent = mesh(server, {
  name: "thumbnail-provider",
  httpPort: 8131,
  description: "Publishes media.thumbnail into the shared media.* namespace",
});

agent.addService("media", {
  thumbnail: async (args: { assetId: string; width: number }) => {
    const w = args.width && args.width > 0 ? args.width : 128;
    const h = Math.max(1, Math.floor((w * 9) / 16));
    return {
      assetId: args.assetId,
      uri: `thumb://${args.assetId}?w=${w}&h=${h}`,
      size: `${w}x${h}`,
      provider: "thumbnail-provider",
    };
  },
});

// The SDK auto-starts after module loading completes.
console.log("thumbnail-provider defined — publishes media.thumbnail. Waiting for auto-start...");
