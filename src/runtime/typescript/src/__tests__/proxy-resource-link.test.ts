/**
 * Unit tests for extractContent mixed-content handling in proxy.ts
 *
 * Tests backward compatibility (text-only returns string) and
 * new multi-content support (resource_link, image, etc.).
 */

import { describe, it, expect } from "vitest";
import { extractContent, type MultiContentResult } from "../proxy.js";

describe("extractContent", () => {
  describe("backward compatibility — text-only content", () => {
    it("should return a string for direct string input", () => {
      const result = extractContent("hello world");
      expect(result).toBe("hello world");
    });

    it("should join multiple text items into a single string", () => {
      const result = extractContent({
        content: [
          { type: "text", text: "Hello " },
          { type: "text", text: "World" },
        ],
      });
      expect(result).toBe("Hello World");
    });

    it("should handle plain string items in content array", () => {
      const result = extractContent({
        content: ["foo", "bar"],
      });
      expect(result).toBe("foobar");
    });

    it("should parse JSON text content", () => {
      const result = extractContent({
        content: [{ type: "text", text: '{"key":"value"}' }],
      });
      expect(result).toBe('{"key":"value"}');
    });

    it("should return string for content string shorthand", () => {
      const result = extractContent({ content: "direct string" });
      expect(result).toBe("direct string");
    });

    it("should stringify non-content objects", () => {
      const result = extractContent({ foo: "bar" });
      expect(result).toBe('{"foo":"bar"}');
    });

    it("should convert non-string/non-object to string", () => {
      expect(extractContent(42)).toBe("42");
      expect(extractContent(true)).toBe("true");
      expect(extractContent(null)).toBe("null");
    });
  });

  describe("mixed content — resource_link and others", () => {
    it("should return MultiContentResult for resource_link items", () => {
      const result = extractContent({
        content: [
          { type: "text", text: "Here is the image:" },
          {
            type: "resource_link",
            resource: {
              uri: "file:///tmp/image.png",
              name: "image.png",
              mimeType: "image/png",
            },
          },
        ],
      });

      expect(typeof result).toBe("object");
      const multi = result as MultiContentResult;
      expect(multi.type).toBe("multi_content");
      expect(multi.content).toHaveLength(2);
      expect(multi.content[0]).toEqual({
        type: "text",
        text: "Here is the image:",
      });
      expect(multi.content[1]).toEqual({
        type: "resource_link",
        resource: {
          uri: "file:///tmp/image.png",
          name: "image.png",
          mimeType: "image/png",
        },
      });
    });

    it("should return MultiContentResult for image items", () => {
      const result = extractContent({
        content: [
          { type: "image", data: "base64data==", mimeType: "image/png" },
        ],
      });

      expect(typeof result).toBe("object");
      const multi = result as MultiContentResult;
      expect(multi.type).toBe("multi_content");
      expect(multi.content).toHaveLength(1);
      expect(multi.content[0]).toEqual({
        type: "image",
        data: "base64data==",
        mimeType: "image/png",
      });
    });

    it("should return MultiContentResult for embedded_resource items", () => {
      const result = extractContent({
        content: [
          {
            type: "embedded_resource",
            resource: {
              uri: "s3://bucket/file.pdf",
              mimeType: "application/pdf",
              blob: "base64blob==",
            },
          },
        ],
      });

      expect(typeof result).toBe("object");
      const multi = result as MultiContentResult;
      expect(multi.type).toBe("multi_content");
      expect(multi.content[0].type).toBe("embedded_resource");
    });

    it("should handle mix of text and multiple resource_links", () => {
      const result = extractContent({
        content: [
          { type: "text", text: "Generated files:" },
          {
            type: "resource_link",
            resource: { uri: "file:///a.png", name: "a.png", mimeType: "image/png" },
          },
          {
            type: "resource_link",
            resource: { uri: "file:///b.pdf", name: "b.pdf", mimeType: "application/pdf" },
          },
        ],
      });

      const multi = result as MultiContentResult;
      expect(multi.type).toBe("multi_content");
      expect(multi.content).toHaveLength(3);
      expect(multi.content[0]).toEqual({ type: "text", text: "Generated files:" });
      expect(multi.content[1].type).toBe("resource_link");
      expect(multi.content[2].type).toBe("resource_link");
    });

    it("should wrap plain string items as text in multi-content", () => {
      const result = extractContent({
        content: [
          "plain string",
          { type: "resource_link", resource: { uri: "file:///x", name: "x", mimeType: "text/plain" } },
        ],
      });

      const multi = result as MultiContentResult;
      expect(multi.type).toBe("multi_content");
      expect(multi.content[0]).toEqual({ type: "text", text: "plain string" });
    });
  });

  describe("edge cases", () => {
    it("should return string for empty content array", () => {
      const result = extractContent({ content: [] });
      expect(result).toBe("");
    });

    it("should return string for single text item", () => {
      const result = extractContent({
        content: [{ type: "text", text: "only text" }],
      });
      expect(result).toBe("only text");
    });

    it("should return MultiContentResult for single resource_link item", () => {
      const result = extractContent({
        content: [
          {
            type: "resource_link",
            resource: { uri: "file:///x", name: "x", mimeType: "text/plain" },
          },
        ],
      });

      const multi = result as MultiContentResult;
      expect(multi.type).toBe("multi_content");
      expect(multi.content).toHaveLength(1);
    });
  });
});
