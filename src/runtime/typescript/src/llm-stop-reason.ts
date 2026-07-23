/**
 * Shared vocabulary for the LLM exhaustion signal (issue #1355).
 *
 * When a provider-managed agentic loop hits `max_iterations` it must make the
 * exhaustion *structurally* distinguishable so the delegating consumer can raise
 * a typed error instead of returning a fabricated answer. Per the #1247 envelope
 * contract, `content` is always the answer string — the discriminant never
 * lives inside it.
 *
 * Two channels carry the signal. Interop with Python's
 * `_mcp_mesh/engine/llm_stop_reason.py` is PARSE-BASED (whitespace-insensitive):
 * the CONSTANT VALUES and the parsed frame STRUCTURE match across runtimes, so a
 * TS consumer interoperates with a Python provider and vice versa. The raw
 * encoder output is NOT byte-identical — Python's `json.dumps` emits spaces
 * (`{"_mesh_frame": "chunk", ...}`) while JS `JSON.stringify` does not — so never
 * assert raw-string equality against the Python bytes:
 *
 * - **Buffered** reply envelope: a namespaced sibling field
 *   `_mesh_stop_reason: "max_iterations"` (sibling of `content` / `_mesh_usage`).
 *   Absent on normal completion.
 * - **Streaming**: the MCP stream channel is strictly stringly-typed (FastMCP
 *   progress notifications carry `str` chunks), so a structured object cannot
 *   ride it directly. We adopt the Anthropic Messages API streaming discipline:
 *   the discriminator is the frame *type*, never the text content. EVERY chunk
 *   is a typed frame — a JSON *string* keyed by a RESERVED `_mesh_`-namespaced
 *   discriminator — so text can never be misread as a control signal:
 *
 *   - text delta            → `{"_mesh_frame":"chunk","content":"<delta>"}`
 *   - terminal, normal      → `{"_mesh_frame":"end"}`
 *   - terminal, exhaustion  → `{"_mesh_frame":"end","stop_reason":"max_iterations"}`
 *
 *   The discriminator lives under the reserved `_mesh_frame` key, not the common
 *   `type` token, so two collision surfaces close:
 *
 *   1. A framed text delta whose `content` is literally an end-frame JSON string
 *      still arrives as `{"_mesh_frame":"chunk","content":"..."}` — parsed as a
 *      `chunk`, its content yielded verbatim; no control collision.
 *   2. An UNFRAMED raw model delta from a non-framing provider that happens to
 *      read like `{"type":"end"}` does NOT carry `_mesh_frame` →
 *      `parseStreamFrame` returns `null` and the consumer passes it through as
 *      raw text (defensive fallback).
 */

// Shared vocabulary token (kept identical to Python's STOP_REASON_MAX_ITERATIONS).
export const STOP_REASON_MAX_ITERATIONS = "max_iterations";

// Reserved sibling key on the buffered reply envelope.
export const STOP_REASON_KEY = "_mesh_stop_reason";

// Typed stream-envelope frame vocabulary. The discriminator is a RESERVED
// `_mesh_`-namespaced key so raw model text can never satisfy the frame check
// (the common `type` token would be a far wider collision surface).
export const FRAME_KEY = "_mesh_frame";
export const FRAME_CHUNK = "chunk";
export const FRAME_END = "end";

/** A parsed stream-envelope frame. */
export interface StreamFrame {
  [FRAME_KEY]: string;
  content?: unknown;
  stop_reason?: string;
  [key: string]: unknown;
}

/** Serialize a text delta as a typed `chunk` frame string. */
export function encodeChunk(text: string): string {
  return JSON.stringify({ [FRAME_KEY]: FRAME_CHUNK, content: text });
}

/**
 * Serialize a terminal `end` frame string.
 *
 * `stopReason` is included only when set (e.g. `"max_iterations"` on
 * exhaustion); a normal completion emits `{"_mesh_frame":"end"}`.
 */
export function encodeEnd(stopReason?: string): string {
  const frame: Record<string, string> = { [FRAME_KEY]: FRAME_END };
  if (stopReason !== undefined && stopReason !== null) {
    frame.stop_reason = stopReason;
  }
  return JSON.stringify(frame);
}

/**
 * Parse a stream chunk into a typed frame object, or `null`.
 *
 * A well-formed frame is a JSON object carrying the reserved `_mesh_frame`
 * discriminator set to a recognized frame type (`"chunk"` or `"end"`). Anything
 * else — a non-string, invalid JSON, a JSON value that isn't an object, an
 * object missing `_mesh_frame`, or one whose `_mesh_frame` is unrecognized —
 * returns `null` so the consumer can apply a defensive passthrough fallback.
 * Because the discriminator is `_mesh_`-namespaced, an UNFRAMED raw model delta
 * that merely looks frame-ish (e.g. a literal `{"type":"end"}` in the model's
 * own text) does NOT match and is passed through verbatim rather than misread
 * as a control/text frame.
 */
export function parseStreamFrame(chunk: unknown): StreamFrame | null {
  if (typeof chunk !== "string") {
    return null;
  }
  let obj: unknown;
  try {
    obj = JSON.parse(chunk);
  } catch {
    return null;
  }
  if (obj === null || typeof obj !== "object" || Array.isArray(obj)) {
    return null;
  }
  const frameType = (obj as Record<string, unknown>)[FRAME_KEY];
  if (frameType !== FRAME_CHUNK && frameType !== FRAME_END) {
    return null;
  }
  return obj as StreamFrame;
}
