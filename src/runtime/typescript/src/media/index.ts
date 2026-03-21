/**
 * Media module — public API for multimodal content storage and helpers.
 */

export {
  type MediaStore,
  LocalMediaStore,
  S3MediaStore,
  getMediaStore,
  guessMimeType,
  _resetMediaStore,
} from "./media-store.js";

export {
  resolveResourceLinks,
  resolveResourceLinksForToolMessage,
  resolveMediaAsUserMessage,
  hasResourceLink,
  TOOL_IMAGE_UNSUPPORTED_VENDORS,
  type ResolvedContent,
} from "./resolver.js";

import { getMediaStore } from "./media-store.js";
import type { ResourceLink } from "fastmcp";

/**
 * Upload binary data to the configured media store.
 *
 * @returns URI pointing to the stored blob (e.g. `file://...` or `s3://...`).
 */
export async function uploadMedia(
  data: Buffer,
  filename: string,
  mimeType: string
): Promise<string> {
  const store = getMediaStore();
  return store.upload(data, filename, mimeType);
}

/**
 * Build an MCP `resource_link` content item.
 *
 * This is the standard way for tools to return references to binary media
 * (images, audio, PDFs, etc.) rather than embedding them inline.
 *
 * Returns a proper MCP ResourceLink that FastMCP sends as a `resource_link`
 * content type in the MCP protocol response (not serialized as JSON text).
 */
export function mediaResult(
  uri: string,
  name: string,
  mimeType: string,
  description?: string,
  size?: number
): ResourceLink {
  const result: ResourceLink = { type: "resource_link", uri, name, mimeType };
  if (description !== undefined) result.description = description;
  if (size !== undefined) result._meta = { size };

  return result;
}
