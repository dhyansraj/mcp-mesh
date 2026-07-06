/**
 * media-gateway — MCP Mesh agent (TypeScript).
 *
 * Aggregates three independent capabilities behind ONE typed service view
 * (RFC #1280) and fans a single request out across them. Because each view
 * method binds its own capability, the `servedBy` fields in the result name
 * THREE different provider agents answering through one interface.
 *
 * Consumption style: `mesh.serviceView(...)` placed in a tool's `dependencies`
 * array occupies one positional slot but expands into N dependency edges on the
 * `process_media` tool. The `caption` method is `required`, so the mesh runtime
 * returns the structured `dependency_unavailable` refusal BEFORE the handler
 * runs whenever caption has no provider; the optional `thumbnail` / `transcribe`
 * methods throw when unresolved, which the handler catches for graceful
 * degradation.
 *
 * Cross-runtime: the `media.*` capabilities are identical across the Java,
 * Python, and TypeScript examples, so this gateway can consume the providers
 * from ANY runtime and vice versa.
 *
 * Run:
 *   cd examples/typescript/service-view/media-gateway
 *   npm install
 *   npx tsx index.ts
 */

import { mesh, FastMCP, type MeshServiceFacade } from "@mcpmesh/sdk";
import { z } from "zod";

const server = new FastMCP({
  name: "Media Gateway Service",
  version: "1.0.0",
});

const agent = mesh(server, {
  name: "media-gateway",
  httpPort: 8133,
  description: "Aggregates three media capabilities behind one typed service view",
});

// One typed view aggregating three capabilities. caption is required; thumbnail
// and transcribe are optional. Methods expand into edges NAME-SORTED.
const Media = mesh.serviceView({
  methods: {
    caption: { capability: "media.caption", required: true },
    thumbnail: "media.thumbnail",
    transcribe: "media.transcribe",
  },
});

type MediaFacade = MeshServiceFacade<typeof Media>;

/** One combined-result entry: the value plus the provider agent that served it. */
function entry(value: string, servedBy: string) {
  return { value, servedBy };
}

/** Shared fan-out: run one asset through all three view methods and combine. */
async function combine(media: MediaFacade, assetId: string, text: string) {
  const result: Record<string, unknown> = { assetId };

  // REQUIRED edge — a missing provider is refused before this handler runs.
  const caption = (await media.caption({ assetId, text })) as {
    caption: string;
    provider: string;
  };
  result.caption = entry(caption.caption, caption.provider);

  // OPTIONAL edge — degrade gracefully if no thumbnail provider is present.
  try {
    const thumb = (await media.thumbnail({ assetId, width: 320 })) as {
      uri: string;
      size: string;
      provider: string;
    };
    result.thumbnail = entry(`${thumb.uri} (${thumb.size})`, thumb.provider);
  } catch (e) {
    // An unresolved OPTIONAL edge throws when called; anything else (provider
    // bug, floor error) is a real failure and must propagate.
    if (!(e instanceof TypeError)) throw e;
    result.thumbnail = entry("(no thumbnail — provider offline)", "unavailable");
  }

  // OPTIONAL edge — degrade gracefully if no transcribe provider is present.
  try {
    const tx = (await media.transcribe({ assetId, text })) as {
      transcript: string;
      wordCount: number;
      provider: string;
    };
    result.transcript = entry(`${tx.transcript} [${tx.wordCount} words]`, tx.provider);
  } catch (e) {
    if (!(e instanceof TypeError)) throw e;
    result.transcript = entry("(no transcript — provider offline)", "unavailable");
  }

  return result;
}

agent.addTool({
  name: "process_media",
  capability: "process_media",
  description: "Runs an asset through caption, thumbnail and transcribe via one service view",
  tags: ["media", "gateway"],
  parameters: z.object({
    assetId: z.string().describe("Media asset identifier"),
    text: z.string().describe("Source description / audio text"),
  }),
  dependencies: [Media],
  // The view facade is injected at the [Media] slot. Its runtime shape is the
  // MediaFacade, but the execute dep slot is typed McpMeshTool | MeshJob | null,
  // so annotate `unknown` and narrow to the facade (same idiom as the SDK tests).
  execute: async ({ assetId, text }, media: unknown) =>
    combine(media as MediaFacade, assetId, text),
});

// The SDK auto-starts after module loading completes.
console.log("media-gateway defined — process_media over one MediaService view. Waiting for auto-start...");
