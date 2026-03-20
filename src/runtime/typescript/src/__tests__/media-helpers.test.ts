/**
 * Unit tests for media/index.ts helper functions.
 *
 * Tests mediaResult() and uploadMedia() convenience functions.
 */

import { describe, it, expect, vi } from "vitest";

// Mock @mcpmesh/core before importing
vi.mock("@mcpmesh/core", () => ({
  resolveConfig: vi.fn((_key: string, _value: string | null) => ""),
  resolveConfigInt: vi.fn((_key: string, _value: number | null) => null),
  getDefault: vi.fn((_key: string) => null),
}));

import { mediaResult } from "../media/index.js";

describe("mediaResult", () => {
  it("should build a proper MCP ResourceLink content item", () => {
    const result = mediaResult(
      "file:///tmp/image.png",
      "image.png",
      "image/png"
    );

    expect(result).toEqual({
      type: "resource_link",
      uri: "file:///tmp/image.png",
      name: "image.png",
      mimeType: "image/png",
    });
  });

  it("should include description when provided", () => {
    const result = mediaResult(
      "s3://bucket/photo.jpg",
      "photo.jpg",
      "image/jpeg",
      "A vacation photo"
    );

    expect(result).toEqual({
      type: "resource_link",
      uri: "s3://bucket/photo.jpg",
      name: "photo.jpg",
      mimeType: "image/jpeg",
      description: "A vacation photo",
    });
  });

  it("should include size in _meta when provided", () => {
    const result = mediaResult(
      "file:///data.csv",
      "data.csv",
      "text/csv",
      undefined,
      1024
    );

    expect(result).toEqual({
      type: "resource_link",
      uri: "file:///data.csv",
      name: "data.csv",
      mimeType: "text/csv",
      _meta: { size: 1024 },
    });
  });

  it("should include both description and size when provided", () => {
    const result = mediaResult(
      "file:///report.pdf",
      "report.pdf",
      "application/pdf",
      "Quarterly report",
      204800
    );

    expect(result).toEqual({
      type: "resource_link",
      uri: "file:///report.pdf",
      name: "report.pdf",
      mimeType: "application/pdf",
      description: "Quarterly report",
      _meta: { size: 204800 },
    });
  });

  it("should handle size of 0 correctly", () => {
    const result = mediaResult(
      "file:///empty.txt",
      "empty.txt",
      "text/plain",
      undefined,
      0
    );

    expect(result._meta).toEqual({ size: 0 });
  });
});
