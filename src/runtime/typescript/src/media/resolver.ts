/**
 * Resolve resource_link URIs to provider-native multimodal content.
 *
 * When an LLM provider calls a tool that returns a resource_link (e.g., an image URI),
 * the LLM currently sees just a JSON string. This module resolves the URI to base64
 * media in provider-native format so the LLM can actually "see" the image.
 *
 * Based on Python's resolver:
 * src/runtime/python/_mcp_mesh/media/resolver.py
 */

import { createDebug } from "../debug.js";
import { getMediaStore } from "./media-store.js";

const debug = createDebug("media-resolver");

const IMAGE_MIME_TYPES = new Set(["image/png", "image/jpeg", "image/gif", "image/webp"]);

export interface ResolvedContent {
  type: string;
  [key: string]: unknown;
}

function formatForClaude(b64: string, mimeType: string): ResolvedContent {
  return {
    type: "image",
    source: {
      type: "base64",
      media_type: mimeType,
      data: b64,
    },
  };
}

function formatForOpenai(b64: string, mimeType: string): ResolvedContent {
  return {
    type: "image_url",
    image_url: {
      url: `data:${mimeType};base64,${b64}`,
      detail: "high",
    },
  };
}

function formatForGemini(b64: string, mimeType: string): ResolvedContent {
  // Vercel AI SDK handles Gemini images via OpenAI-compatible format
  return formatForOpenai(b64, mimeType);
}

const VENDOR_FORMATTERS: Record<string, (b64: string, mimeType: string) => ResolvedContent> = {
  anthropic: formatForClaude,
  openai: formatForOpenai,
  gemini: formatForGemini,
  google: formatForGemini,
};

/**
 * Resolve a single resource_link dict to a provider-native content part.
 *
 * @param resourceLink - Dict with type "resource_link" and either flat or nested resource fields
 * @param vendor - One of "anthropic", "openai", "gemini", "google"
 * @returns Provider-native content dict (image block or text fallback)
 */
async function resolveSingleResourceLink(
  resourceLink: Record<string, unknown>,
  vendor: string
): Promise<ResolvedContent> {
  // Support both flat format and nested resource sub-object
  const resource = (resourceLink.resource ?? {}) as Record<string, unknown>;
  const uri = (resource.uri ?? resourceLink.uri ?? "") as string;
  const mimeType = (resource.mimeType ?? resourceLink.mimeType ?? "") as string;
  const name = (resource.name ?? resourceLink.name ?? uri) as string;

  if (!IMAGE_MIME_TYPES.has(mimeType)) {
    return {
      type: "text",
      text: `[resource_link: ${name} (${mimeType || "unknown"}) at ${uri}]`,
    };
  }

  try {
    const store = getMediaStore();
    const { data, mimeType: fetchedMime } = await store.fetch(uri);
    const b64 = data.toString("base64");

    const formatter = VENDOR_FORMATTERS[vendor] ?? formatForOpenai;
    const result = formatter(b64, mimeType || fetchedMime);
    debug(`Resolved resource_link ${name} to ${vendor} image block (${data.length} bytes)`);
    return result;
  } catch (err) {
    const errMsg = err instanceof Error ? err.message : String(err);
    debug(`Failed to fetch resource_link ${uri}: ${errMsg}`);
    return {
      type: "text",
      text: `[resource_link: ${name} (${mimeType || "unknown"}) at ${uri} (fetch failed)]`,
    };
  }
}

/**
 * Scan tool result for resource_link items and resolve to provider-native format.
 *
 * Returns a list of content parts for the LLM message.
 * - For image resource_links: fetches bytes, base64 encodes, formats per vendor
 * - For non-image or non-resource_link: wraps in text content
 *
 * @param toolResult - The raw tool result (could be object, string, etc.)
 * @param vendor - One of "anthropic", "openai", "gemini", "google"
 * @returns List of content dicts suitable for provider-specific message content arrays
 */
export async function resolveResourceLinks(
  toolResult: unknown,
  vendor: string
): Promise<ResolvedContent[]> {
  // resource_link dict
  if (
    toolResult &&
    typeof toolResult === "object" &&
    (toolResult as Record<string, unknown>).type === "resource_link"
  ) {
    const part = await resolveSingleResourceLink(
      toolResult as Record<string, unknown>,
      vendor
    );
    return [part];
  }

  // multi_content dict (from extractContent in proxy.ts)
  if (
    toolResult &&
    typeof toolResult === "object" &&
    (toolResult as Record<string, unknown>).type === "multi_content"
  ) {
    const obj = toolResult as Record<string, unknown>;
    const items = (obj.items ?? obj.content ?? []) as unknown[];
    const parts: ResolvedContent[] = [];

    for (const item of items) {
      if (
        item &&
        typeof item === "object" &&
        (item as Record<string, unknown>).type === "resource_link"
      ) {
        parts.push(
          await resolveSingleResourceLink(item as Record<string, unknown>, vendor)
        );
      } else if (typeof item === "string") {
        parts.push({ type: "text", text: item });
      } else if (item && typeof item === "object") {
        // Non-resource_link objects (e.g., text items) — preserve or serialize
        const itemObj = item as Record<string, unknown>;
        if (itemObj.type === "text" && typeof itemObj.text === "string") {
          parts.push({ type: "text", text: itemObj.text });
        } else {
          parts.push({ type: "text", text: JSON.stringify(item) });
        }
      } else {
        parts.push({ type: "text", text: String(item) });
      }
    }

    return parts;
  }

  // Plain string
  if (typeof toolResult === "string") {
    return [{ type: "text", text: toolResult }];
  }

  // Anything else (dict without resource_link type, number, etc.)
  try {
    const text = JSON.stringify(toolResult);
    return [{ type: "text", text }];
  } catch {
    return [{ type: "text", text: String(toolResult) }];
  }
}

/** Vendors that do NOT support images in tool/function result messages. */
const TOOL_IMAGE_UNSUPPORTED_VENDORS = new Set(["openai", "gemini"]);

/**
 * Resolve resource_links for inclusion in a tool result message.
 *
 * For vendors that support images in tool messages (Anthropic/Claude),
 * returns the full multimodal content (text + image parts).
 *
 * For vendors that do NOT support images in tool messages (OpenAI, Gemini),
 * returns text-only content with descriptive placeholders. The actual image
 * should be injected via a separate user message using
 * `resolveMediaAsUserMessage()`.
 *
 * @param toolResult - Raw tool result
 * @param vendor - e.g. "anthropic", "openai", "gemini"
 * @returns Content parts suitable for a tool result message
 */
export async function resolveResourceLinksForToolMessage(
  toolResult: unknown,
  vendor: string
): Promise<ResolvedContent[]> {
  if (!TOOL_IMAGE_UNSUPPORTED_VENDORS.has(vendor)) {
    return resolveResourceLinks(toolResult, vendor);
  }

  const parts = await resolveResourceLinks(toolResult, vendor);
  return parts.map((part) => {
    if (part.type === "image" || part.type === "image_url") {
      return { type: "text", text: "[Image content — see next message]" };
    }
    return part;
  });
}

/**
 * Return a user message containing resolved images from a tool result.
 *
 * For vendors that do NOT support images in tool messages (OpenAI, Gemini),
 * resolves resource_link items and packages the image parts into a
 * `role: "user"` message that can be appended after the tool result message.
 *
 * For vendors that support images in tool messages (Anthropic), returns null.
 *
 * @param toolResult - Raw tool result
 * @param vendor - e.g. "anthropic", "openai", "gemini"
 * @returns A user message object with image content, or null
 */
export async function resolveMediaAsUserMessage(
  toolResult: unknown,
  vendor: string
): Promise<Record<string, unknown> | null> {
  if (!TOOL_IMAGE_UNSUPPORTED_VENDORS.has(vendor)) {
    return null;
  }

  const parts = await resolveResourceLinks(toolResult, vendor);
  const imageParts = parts.filter(
    (p) => p.type === "image" || p.type === "image_url"
  );
  if (imageParts.length === 0) {
    return null;
  }

  return {
    role: "user",
    content: [
      { type: "text", text: "The tool returned this image:" },
      ...imageParts,
    ],
  };
}

/**
 * Quick check whether a tool result contains any resource_link items.
 *
 * This is a lightweight synchronous check used to decide whether the
 * more expensive async resolution is needed.
 */
export function hasResourceLink(toolResult: unknown): boolean {
  if (!toolResult || typeof toolResult !== "object") {
    return false;
  }

  const obj = toolResult as Record<string, unknown>;

  if (obj.type === "resource_link") {
    return true;
  }

  if (obj.type === "multi_content") {
    const items = (obj.items ?? obj.content ?? []) as unknown[];
    return items.some(
      (i) =>
        i && typeof i === "object" && (i as Record<string, unknown>).type === "resource_link"
    );
  }

  return false;
}
