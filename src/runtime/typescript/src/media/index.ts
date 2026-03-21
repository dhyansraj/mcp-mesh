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
  formatForOpenai,
  resolveResourceLinks,
  resolveResourceLinksForToolMessage,
  resolveMediaAsUserMessage,
  hasResourceLink,
  TOOL_IMAGE_UNSUPPORTED_VENDORS,
  type ResolvedContent,
} from "./resolver.js";

import { getMediaStore } from "./media-store.js";
import { formatForOpenai, type ResolvedContent } from "./resolver.js";
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

// ---------------------------------------------------------------------------
// MediaResult class — upload + ResourceLink in one step
// ---------------------------------------------------------------------------

/**
 * Convenience class: upload bytes and return a ResourceLink in one step.
 *
 * Usage:
 *   const link = await new MediaResult(pngBytes, "chart.png", "image/png").toResourceLink();
 *   // or use the standalone function:
 *   const link = await createMediaResult(pngBytes, "chart.png", "image/png");
 */
export class MediaResult {
  constructor(
    public readonly data: Buffer,
    public readonly filename: string,
    public readonly mimeType: string,
    public readonly name?: string,
    public readonly description?: string,
  ) {}

  async toResourceLink(): Promise<ResourceLink> {
    const uri = await uploadMedia(this.data, this.filename, this.mimeType);
    return mediaResult(uri, this.name ?? this.filename, this.mimeType, this.description, this.data.length);
  }
}

/**
 * Upload bytes and return a ResourceLink in one step.
 */
export async function createMediaResult(
  data: Buffer,
  filename: string,
  mimeType: string,
  name?: string,
  description?: string,
): Promise<ResourceLink> {
  return new MediaResult(data, filename, mimeType, name, description).toResourceLink();
}

// ---------------------------------------------------------------------------
// saveUpload — save file uploads to MediaStore
// ---------------------------------------------------------------------------

/**
 * Result of saving an upload to MediaStore.
 */
export interface MediaUploadResult {
  uri: string;
  name: string;
  mimeType: string;
  size: number;
}

/**
 * Save a file upload (e.g., from multer) to MediaStore and return the URI.
 *
 * Accepts objects with buffer/originalname/mimetype properties (multer format)
 * or any object with data/name/mimeType properties.
 */
export async function saveUpload(
  file: { buffer: Buffer; originalname: string; mimetype: string }
      | { data: Buffer; name: string; mimeType: string },
  options?: { filename?: string; mimeType?: string },
): Promise<string> {
  const data = 'buffer' in file ? file.buffer : file.data;
  const filename = options?.filename ?? ('originalname' in file ? file.originalname : file.name);
  const mime = options?.mimeType ?? ('mimetype' in file ? file.mimetype : file.mimeType);

  const store = getMediaStore();
  return store.upload(data, filename, mime);
}

/**
 * Save a file upload and return full metadata.
 */
export async function saveUploadResult(
  file: { buffer: Buffer; originalname: string; mimetype: string }
      | { data: Buffer; name: string; mimeType: string },
  options?: { filename?: string; mimeType?: string },
): Promise<MediaUploadResult> {
  const data = 'buffer' in file ? file.buffer : file.data;
  const filename = options?.filename ?? ('originalname' in file ? file.originalname : file.name);
  const mime = options?.mimeType ?? ('mimetype' in file ? file.mimetype : file.mimeType);

  const store = getMediaStore();
  const uri = await store.upload(data, filename, mime);
  return { uri, name: filename, mimeType: mime, size: data.length };
}

// ---------------------------------------------------------------------------
// resolveMediaInputs — resolve media URIs/buffers to OpenAI-compatible parts
// ---------------------------------------------------------------------------

/**
 * Resolve an array of media inputs to OpenAI-compatible image_url content parts.
 *
 * Each item is either:
 * - A URI string (resolved via MediaStore.fetch())
 * - An inline `{ data: Buffer; mimeType: string }` object
 *
 * Returns an array of ResolvedContent parts in OpenAI image_url format,
 * which Vercel AI SDK converts to each vendor's native format.
 *
 * @param media - Array of URI strings or inline media objects
 * @returns Array of OpenAI-compatible image_url content parts
 */
export async function resolveMediaInputs(
  media: Array<string | { data: Buffer; mimeType: string }>
): Promise<ResolvedContent[]> {
  const store = getMediaStore();
  const parts: ResolvedContent[] = [];

  for (const item of media) {
    let data: Buffer;
    let mimeType: string;

    if (typeof item === "string") {
      const result = await store.fetch(item);
      data = result.data;
      mimeType = result.mimeType;
    } else {
      data = item.data;
      mimeType = item.mimeType;
    }

    const b64 = data.toString("base64");
    parts.push(formatForOpenai(b64, mimeType));
  }

  return parts;
}
