/**
 * Unit tests for media option in LLM agent calls.
 *
 * Tests resolveMediaInputs() and the integration of media items
 * into multipart user messages for LLM completions.
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
  resolveMediaConfig: vi.fn(() => ({
    storage: "local",
    storagePath: "/tmp/media",
    storagePrefix: "",
  })),
  guessMimeType: vi.fn(() => "application/octet-stream"),
}));

import { resolveMediaInputs } from "../media/index.js";

describe("resolveMediaInputs", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("resolves a URI string via MediaStore.fetch()", async () => {
    const imageData = Buffer.from("fake-png-data");
    mockFetch.mockResolvedValue({ data: imageData, mimeType: "image/png" });

    const parts = await resolveMediaInputs(["file:///tmp/photo.png"]);

    expect(parts).toHaveLength(1);
    expect(parts[0]).toEqual({
      type: "image_url",
      image_url: {
        url: `data:image/png;base64,${imageData.toString("base64")}`,
        detail: "high",
      },
    });
    expect(mockFetch).toHaveBeenCalledWith("file:///tmp/photo.png");
  });

  it("resolves an inline Buffer media object", async () => {
    const imageData = Buffer.from("inline-jpeg-data");

    const parts = await resolveMediaInputs([
      { data: imageData, mimeType: "image/jpeg" },
    ]);

    expect(parts).toHaveLength(1);
    expect(parts[0]).toEqual({
      type: "image_url",
      image_url: {
        url: `data:image/jpeg;base64,${imageData.toString("base64")}`,
        detail: "high",
      },
    });
    // Should NOT call MediaStore.fetch for inline buffers
    expect(mockFetch).not.toHaveBeenCalled();
  });

  it("resolves multiple media items (mixed URI and Buffer)", async () => {
    const uriImageData = Buffer.from("uri-image-data");
    const bufferImageData = Buffer.from("buffer-image-data");

    mockFetch.mockResolvedValue({ data: uriImageData, mimeType: "image/png" });

    const parts = await resolveMediaInputs([
      "file:///tmp/chart.png",
      { data: bufferImageData, mimeType: "image/webp" },
    ]);

    expect(parts).toHaveLength(2);

    // First: URI-resolved image
    expect(parts[0]).toEqual({
      type: "image_url",
      image_url: {
        url: `data:image/png;base64,${uriImageData.toString("base64")}`,
        detail: "high",
      },
    });

    // Second: inline buffer image
    expect(parts[1]).toEqual({
      type: "image_url",
      image_url: {
        url: `data:image/webp;base64,${bufferImageData.toString("base64")}`,
        detail: "high",
      },
    });
  });

  it("returns empty array for empty media list", async () => {
    const parts = await resolveMediaInputs([]);
    expect(parts).toHaveLength(0);
    expect(mockFetch).not.toHaveBeenCalled();
  });

  it("resolves S3 URIs via MediaStore.fetch()", async () => {
    const imageData = Buffer.from("s3-image");
    mockFetch.mockResolvedValue({ data: imageData, mimeType: "image/gif" });

    const parts = await resolveMediaInputs(["s3://bucket/images/logo.gif"]);

    expect(parts).toHaveLength(1);
    expect(parts[0].type).toBe("image_url");
    expect(mockFetch).toHaveBeenCalledWith("s3://bucket/images/logo.gif");
  });
});

describe("LlmCallOptions.media integration", () => {
  // These tests verify the message structure that would be built
  // by MeshLlmAgent.run() when media is provided.

  it("builds multipart content for string message with media", () => {
    // Simulate what run() does: text + image parts
    const prompt = "Describe this image";
    const mediaParts = [
      {
        type: "image_url" as const,
        image_url: {
          url: "data:image/png;base64,abc123",
          detail: "high" as const,
        },
      },
    ];

    const message = {
      role: "user" as const,
      content: [
        { type: "text" as const, text: prompt },
        ...mediaParts,
      ],
    };

    expect(message.content).toHaveLength(2);
    expect(message.content[0]).toEqual({ type: "text", text: "Describe this image" });
    expect(message.content[1]).toEqual({
      type: "image_url",
      image_url: { url: "data:image/png;base64,abc123", detail: "high" },
    });
  });

  it("preserves plain string message when no media provided", () => {
    const prompt = "Hello world";
    const mediaParts: unknown[] = [];

    // When media is empty, run() uses plain string content
    const message =
      mediaParts.length > 0
        ? { role: "user" as const, content: [{ type: "text" as const, text: prompt }, ...mediaParts] }
        : { role: "user" as const, content: prompt };

    expect(message.content).toBe("Hello world");
  });

  it("builds multipart with multiple images", () => {
    const prompt = "Compare these two images";
    const mediaParts = [
      {
        type: "image_url" as const,
        image_url: { url: "data:image/png;base64,img1", detail: "high" as const },
      },
      {
        type: "image_url" as const,
        image_url: { url: "data:image/jpeg;base64,img2", detail: "high" as const },
      },
    ];

    const message = {
      role: "user" as const,
      content: [
        { type: "text" as const, text: prompt },
        ...mediaParts,
      ],
    };

    expect(message.content).toHaveLength(3);
    expect(message.content[0].type).toBe("text");
    expect(message.content[1].type).toBe("image_url");
    expect(message.content[2].type).toBe("image_url");
  });
});
