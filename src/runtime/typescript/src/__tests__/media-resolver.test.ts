/**
 * Unit tests for media/resolver.ts
 *
 * Tests resolveResourceLinks() and hasResourceLink() for converting
 * resource_link items to provider-native multimodal content.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";

// Mock @mcpmesh/core before importing
vi.mock("@mcpmesh/core", () => ({
  resolveConfig: vi.fn((_key: string, _value: string | null) => ""),
  resolveConfigInt: vi.fn((_key: string, _value: number | null) => null),
  getDefault: vi.fn((_key: string) => null),
}));

// Mock the media store
const mockFetch = vi.fn();
vi.mock("../media/media-store.js", () => ({
  getMediaStore: vi.fn(() => ({
    fetch: mockFetch,
    upload: vi.fn(),
    exists: vi.fn(),
  })),
}));

import { resolveResourceLinks, hasResourceLink } from "../media/resolver.js";

describe("resolveResourceLinks", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe("image resource_link resolution", () => {
    it("resolves image resource_link for claude (anthropic)", async () => {
      const imageData = Buffer.from("fake-png-data");
      mockFetch.mockResolvedValue({ data: imageData, mimeType: "image/png" });

      const result = await resolveResourceLinks(
        {
          type: "resource_link",
          resource: {
            uri: "file:///tmp/photo.png",
            name: "photo.png",
            mimeType: "image/png",
          },
        },
        "anthropic"
      );

      expect(result).toHaveLength(1);
      expect(result[0]).toEqual({
        type: "image",
        source: {
          type: "base64",
          media_type: "image/png",
          data: imageData.toString("base64"),
        },
      });
      expect(mockFetch).toHaveBeenCalledWith("file:///tmp/photo.png");
    });

    it("resolves image resource_link for openai", async () => {
      const imageData = Buffer.from("fake-jpeg-data");
      mockFetch.mockResolvedValue({ data: imageData, mimeType: "image/jpeg" });

      const result = await resolveResourceLinks(
        {
          type: "resource_link",
          resource: {
            uri: "file:///tmp/photo.jpg",
            name: "photo.jpg",
            mimeType: "image/jpeg",
          },
        },
        "openai"
      );

      expect(result).toHaveLength(1);
      expect(result[0]).toEqual({
        type: "image_url",
        image_url: {
          url: `data:image/jpeg;base64,${imageData.toString("base64")}`,
          detail: "high",
        },
      });
    });

    it("resolves image resource_link for gemini (uses openai format)", async () => {
      const imageData = Buffer.from("fake-webp-data");
      mockFetch.mockResolvedValue({ data: imageData, mimeType: "image/webp" });

      const result = await resolveResourceLinks(
        {
          type: "resource_link",
          resource: {
            uri: "s3://bucket/img.webp",
            name: "img.webp",
            mimeType: "image/webp",
          },
        },
        "gemini"
      );

      expect(result).toHaveLength(1);
      expect(result[0].type).toBe("image_url");
      expect((result[0] as Record<string, unknown>).image_url).toBeDefined();
    });

    it("resolves image resource_link with flat format (no nested resource)", async () => {
      const imageData = Buffer.from("flat-format-data");
      mockFetch.mockResolvedValue({ data: imageData, mimeType: "image/png" });

      const result = await resolveResourceLinks(
        {
          type: "resource_link",
          uri: "file:///tmp/flat.png",
          name: "flat.png",
          mimeType: "image/png",
        },
        "anthropic"
      );

      expect(result).toHaveLength(1);
      expect(result[0].type).toBe("image");
      expect(mockFetch).toHaveBeenCalledWith("file:///tmp/flat.png");
    });
  });

  describe("non-image resource_links", () => {
    it("passes through non-image resource_links as text", async () => {
      const result = await resolveResourceLinks(
        {
          type: "resource_link",
          resource: {
            uri: "file:///tmp/data.csv",
            name: "data.csv",
            mimeType: "text/csv",
          },
        },
        "anthropic"
      );

      expect(result).toHaveLength(1);
      expect(result[0].type).toBe("text");
      expect(result[0].text).toContain("data.csv");
      // Text files are now fetched and content included inline
      expect(mockFetch).toHaveBeenCalledWith("file:///tmp/data.csv");
    });

    it("passes through PDF resource_links as text", async () => {
      const result = await resolveResourceLinks(
        {
          type: "resource_link",
          resource: {
            uri: "file:///tmp/report.pdf",
            name: "report.pdf",
            mimeType: "application/pdf",
          },
        },
        "openai"
      );

      expect(result).toHaveLength(1);
      expect(result[0].type).toBe("text");
      expect(result[0].text).toContain("report.pdf");
    });
  });

  describe("plain string results", () => {
    it("handles plain string results unchanged", async () => {
      const result = await resolveResourceLinks("Hello, world!", "anthropic");

      expect(result).toHaveLength(1);
      expect(result[0]).toEqual({ type: "text", text: "Hello, world!" });
    });

    it("handles JSON string results", async () => {
      const result = await resolveResourceLinks('{"key":"value"}', "openai");

      expect(result).toHaveLength(1);
      expect(result[0]).toEqual({ type: "text", text: '{"key":"value"}' });
    });
  });

  describe("multi_content with mixed types", () => {
    it("handles multi_content with text and image resource_links", async () => {
      const imageData = Buffer.from("multi-image-data");
      mockFetch.mockResolvedValue({ data: imageData, mimeType: "image/png" });

      const result = await resolveResourceLinks(
        {
          type: "multi_content",
          content: [
            { type: "text", text: "Here is the image:" },
            {
              type: "resource_link",
              resource: {
                uri: "file:///tmp/img.png",
                name: "img.png",
                mimeType: "image/png",
              },
            },
          ],
        },
        "anthropic"
      );

      expect(result).toHaveLength(2);
      expect(result[0]).toEqual({ type: "text", text: "Here is the image:" });
      expect(result[1].type).toBe("image");
      expect((result[1] as Record<string, unknown>).source).toBeDefined();
    });

    it("handles multi_content with items key (alternative format)", async () => {
      const imageData = Buffer.from("items-format-data");
      mockFetch.mockResolvedValue({ data: imageData, mimeType: "image/jpeg" });

      const result = await resolveResourceLinks(
        {
          type: "multi_content",
          items: [
            {
              type: "resource_link",
              resource: {
                uri: "file:///tmp/photo.jpg",
                name: "photo.jpg",
                mimeType: "image/jpeg",
              },
            },
          ],
        },
        "openai"
      );

      expect(result).toHaveLength(1);
      expect(result[0].type).toBe("image_url");
    });

    it("handles multi_content with non-image resource_links", async () => {
      const result = await resolveResourceLinks(
        {
          type: "multi_content",
          content: [
            { type: "text", text: "Generated files:" },
            {
              type: "resource_link",
              resource: {
                uri: "file:///tmp/a.pdf",
                name: "a.pdf",
                mimeType: "application/pdf",
              },
            },
          ],
        },
        "anthropic"
      );

      expect(result).toHaveLength(2);
      expect(result[0]).toEqual({ type: "text", text: "Generated files:" });
      // Claude gets native document type for PDFs
      expect(result[1].type).toBe("document");
      expect(mockFetch).toHaveBeenCalledWith("file:///tmp/a.pdf");
    });

    it("handles multi_content with plain string items", async () => {
      const result = await resolveResourceLinks(
        {
          type: "multi_content",
          content: ["plain string item"],
        },
        "anthropic"
      );

      expect(result).toHaveLength(1);
      expect(result[0]).toEqual({ type: "text", text: "plain string item" });
    });
  });

  describe("error handling", () => {
    it("gracefully handles fetch failure — falls back to text", async () => {
      mockFetch.mockRejectedValue(new Error("File not found"));

      const result = await resolveResourceLinks(
        {
          type: "resource_link",
          resource: {
            uri: "file:///tmp/missing.png",
            name: "missing.png",
            mimeType: "image/png",
          },
        },
        "anthropic"
      );

      expect(result).toHaveLength(1);
      expect(result[0].type).toBe("text");
      expect(result[0].text).toContain("missing.png");
      expect(result[0].text).toContain("fetch failed");
    });
  });

  describe("other result types", () => {
    it("handles null result", async () => {
      const result = await resolveResourceLinks(null, "anthropic");

      expect(result).toHaveLength(1);
      expect(result[0].type).toBe("text");
      expect(result[0].text).toBe("null");
    });

    it("handles number result", async () => {
      const result = await resolveResourceLinks(42, "openai");

      expect(result).toHaveLength(1);
      expect(result[0]).toEqual({ type: "text", text: "42" });
    });

    it("handles plain object result (no resource_link type)", async () => {
      const result = await resolveResourceLinks({ key: "value" }, "anthropic");

      expect(result).toHaveLength(1);
      expect(result[0]).toEqual({ type: "text", text: '{"key":"value"}' });
    });
  });
});

describe("hasResourceLink", () => {
  it("returns true for resource_link object", () => {
    expect(hasResourceLink({
      type: "resource_link",
      resource: { uri: "file:///x", name: "x", mimeType: "image/png" },
    })).toBe(true);
  });

  it("returns true for multi_content with resource_link items", () => {
    expect(hasResourceLink({
      type: "multi_content",
      content: [
        { type: "text", text: "hello" },
        { type: "resource_link", resource: { uri: "file:///x" } },
      ],
    })).toBe(true);
  });

  it("returns false for multi_content without resource_link items", () => {
    expect(hasResourceLink({
      type: "multi_content",
      content: [
        { type: "text", text: "hello" },
      ],
    })).toBe(false);
  });

  it("returns false for plain string", () => {
    expect(hasResourceLink("hello")).toBe(false);
  });

  it("returns false for null", () => {
    expect(hasResourceLink(null)).toBe(false);
  });

  it("returns false for undefined", () => {
    expect(hasResourceLink(undefined)).toBe(false);
  });

  it("returns false for number", () => {
    expect(hasResourceLink(42)).toBe(false);
  });

  it("returns false for plain object", () => {
    expect(hasResourceLink({ type: "text", text: "hello" })).toBe(false);
  });

  it("returns true for multi_content with items key", () => {
    expect(hasResourceLink({
      type: "multi_content",
      items: [
        { type: "resource_link", resource: { uri: "file:///x" } },
      ],
    })).toBe(true);
  });
});
