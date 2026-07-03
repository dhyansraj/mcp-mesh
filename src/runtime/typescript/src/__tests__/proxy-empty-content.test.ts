/**
 * Unit tests for empty-content handling in extractContent (#1250).
 *
 * A provider returning None or an empty collection serializes to an MCP result
 * with an EMPTY content array. Typed returns carry the value in
 * structuredContent (FastMCP wraps non-object values as {"result": X} and tags
 * the wrapping with a fastmcp.wrap_result meta marker); untyped/None returns
 * carry no structuredContent at all.
 *
 * Before the fix, extractContent joined the empty array to "" and callers
 * JSON.parse("")-threw or returned a bare "". Now: recover from
 * structuredContent when present (unwrapping only when the marker is set),
 * otherwise return null.
 */

import { describe, it, expect } from "vitest";
import { extractContent } from "../proxy.js";

describe("extractContent — empty content array (#1250)", () => {
  it("recovers an empty list from wrapped structuredContent {result: []}", () => {
    const result = extractContent({
      content: [],
      structuredContent: { result: [] },
      _meta: { fastmcp: { wrap_result: true } },
    });
    expect(result).toEqual([]);
    expect(Array.isArray(result)).toBe(true);
  });

  it("recovers a wrapped scalar value when the marker is present", () => {
    const result = extractContent({
      content: [],
      structuredContent: { result: 42 },
      _meta: { fastmcp: { wrap_result: true } },
    });
    expect(result).toBe(42);
  });

  it("also honors the marker under the `meta` (non-alias) key", () => {
    const result = extractContent({
      content: [],
      structuredContent: { result: [] },
      meta: { fastmcp: { wrap_result: true } },
    });
    expect(result).toEqual([]);
  });

  it("uses structuredContent as-is when no wrap marker is present", () => {
    const structured = { result: [] };
    const result = extractContent({
      content: [],
      structuredContent: structured,
    });
    // No marker → do NOT unwrap the single-key result dict.
    expect(result).toEqual({ result: [] });
  });

  it("uses a non-result structuredContent object as-is", () => {
    const result = extractContent({
      content: [],
      structuredContent: { items: [1, 2, 3], count: 3 },
      _meta: { fastmcp: { wrap_result: true } },
    });
    // Marker present but no `result` key → structuredContent as-is.
    expect(result).toEqual({ items: [1, 2, 3], count: 3 });
  });

  it("does NOT unwrap when a sibling key accompanies `result`, even with the marker", () => {
    const result = extractContent({
      content: [],
      structuredContent: { result: 1, extra: 2 },
      _meta: { fastmcp: { wrap_result: true } },
    });
    // Exact-keys rule: keys must be exactly {"result"} to unwrap.
    expect(result).toEqual({ result: 1, extra: 2 });
  });

  it("returns a non-object (scalar) structuredContent as-is, not null", () => {
    const result = extractContent({
      content: [],
      structuredContent: "hello" as unknown as Record<string, unknown>,
    });
    expect(result).toBe("hello");
  });

  it("falls back to `meta` when `_meta` is present but null", () => {
    const result = extractContent({
      content: [],
      structuredContent: { result: [] },
      _meta: null,
      meta: { fastmcp: { wrap_result: true } },
    });
    expect(result).toEqual([]);
  });

  it("returns null when content is empty and there is no structuredContent", () => {
    const result = extractContent({ content: [] });
    expect(result).toBeNull();
  });

  it("returns null when structuredContent is explicitly null", () => {
    const result = extractContent({ content: [], structuredContent: null });
    expect(result).toBeNull();
  });
});

describe("extractContent — regression: non-empty content unchanged", () => {
  it("returns the JSON string '[]' for a single '[]' text block", () => {
    const result = extractContent({ content: [{ type: "text", text: "[]" }] });
    expect(result).toBe("[]");
  });

  it("returns the JSON string '{}' for a single '{}' text block", () => {
    const result = extractContent({ content: [{ type: "text", text: "{}" }] });
    expect(result).toBe("{}");
  });

  it("returns the string 'null' for a single 'null' text block", () => {
    const result = extractContent({ content: [{ type: "text", text: "null" }] });
    expect(result).toBe("null");
  });

  it("returns normal text payloads verbatim", () => {
    const result = extractContent({
      content: [{ type: "text", text: "hello world" }],
    });
    expect(result).toBe("hello world");
  });

  it("still returns a MultiContentResult for mixed content", () => {
    const result = extractContent({
      content: [
        { type: "text", text: "see file" },
        { type: "resource_link", uri: "file:///x.png" },
      ],
    });
    expect(result).toMatchObject({ type: "multi_content" });
  });
});
