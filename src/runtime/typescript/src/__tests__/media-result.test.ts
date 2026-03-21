/**
 * Unit tests for MediaResult class, createMediaResult, saveUpload, saveUploadResult.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";

// Mock @mcpmesh/core before importing
vi.mock("@mcpmesh/core", () => ({
  resolveConfig: vi.fn((_key: string, _value: string | null) => ""),
  resolveConfigInt: vi.fn((_key: string, _value: number | null) => null),
  getDefault: vi.fn((_key: string) => null),
}));

// Mock the media store
const mockUpload = vi.fn();
vi.mock("../media/media-store.js", () => ({
  getMediaStore: vi.fn(() => ({
    upload: mockUpload,
    fetch: vi.fn(),
    exists: vi.fn(),
  })),
}));

import {
  MediaResult,
  createMediaResult,
  saveUpload,
  saveUploadResult,
} from "../media/index.js";

describe("MediaResult", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("uploads and returns ResourceLink", async () => {
    const data = Buffer.from("fake-png-data");
    mockUpload.mockResolvedValue("file:///tmp/media/chart.png");

    const mr = new MediaResult(data, "chart.png", "image/png");
    const link = await mr.toResourceLink();

    expect(mockUpload).toHaveBeenCalledWith(data, "chart.png", "image/png");
    expect(link).toEqual({
      type: "resource_link",
      uri: "file:///tmp/media/chart.png",
      name: "chart.png",
      mimeType: "image/png",
      _meta: { size: data.length },
    });
  });

  it("defaults name to filename", async () => {
    const data = Buffer.from("hello");
    mockUpload.mockResolvedValue("file:///tmp/media/output.csv");

    const mr = new MediaResult(data, "output.csv", "text/csv");
    const link = await mr.toResourceLink();

    expect(link.name).toBe("output.csv");
  });

  it("uses custom name when provided", async () => {
    const data = Buffer.from("hello");
    mockUpload.mockResolvedValue("file:///tmp/media/output.csv");

    const mr = new MediaResult(data, "output.csv", "text/csv", "Sales Data");
    const link = await mr.toResourceLink();

    expect(link.name).toBe("Sales Data");
  });

  it("includes description when provided", async () => {
    const data = Buffer.from("pdf-bytes");
    mockUpload.mockResolvedValue("file:///tmp/media/report.pdf");

    const mr = new MediaResult(data, "report.pdf", "application/pdf", undefined, "Quarterly report");
    const link = await mr.toResourceLink();

    expect(link.description).toBe("Quarterly report");
  });

  it("includes size in result", async () => {
    const data = Buffer.from("x".repeat(1024));
    mockUpload.mockResolvedValue("file:///tmp/media/big.bin");

    const mr = new MediaResult(data, "big.bin", "application/octet-stream");
    const link = await mr.toResourceLink();

    expect(link._meta).toEqual({ size: 1024 });
  });
});

describe("createMediaResult", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("one-liner convenience", async () => {
    const data = Buffer.from("image-data");
    mockUpload.mockResolvedValue("file:///tmp/media/photo.jpg");

    const link = await createMediaResult(data, "photo.jpg", "image/jpeg");

    expect(mockUpload).toHaveBeenCalledWith(data, "photo.jpg", "image/jpeg");
    expect(link).toEqual({
      type: "resource_link",
      uri: "file:///tmp/media/photo.jpg",
      name: "photo.jpg",
      mimeType: "image/jpeg",
      _meta: { size: data.length },
    });
  });

  it("passes name and description through", async () => {
    const data = Buffer.from("wav-data");
    mockUpload.mockResolvedValue("file:///tmp/media/clip.wav");

    const link = await createMediaResult(data, "clip.wav", "audio/wav", "Audio Clip", "Recording from meeting");

    expect(link.name).toBe("Audio Clip");
    expect(link.description).toBe("Recording from meeting");
  });
});

describe("saveUpload", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("saves multer file and returns URI", async () => {
    const buffer = Buffer.from("multer-data");
    mockUpload.mockResolvedValue("file:///tmp/media/upload.png");

    const uri = await saveUpload({
      buffer,
      originalname: "upload.png",
      mimetype: "image/png",
    });

    expect(mockUpload).toHaveBeenCalledWith(buffer, "upload.png", "image/png");
    expect(uri).toBe("file:///tmp/media/upload.png");
  });

  it("saves generic file and returns URI", async () => {
    const data = Buffer.from("generic-data");
    mockUpload.mockResolvedValue("file:///tmp/media/doc.pdf");

    const uri = await saveUpload({
      data,
      name: "doc.pdf",
      mimeType: "application/pdf",
    });

    expect(mockUpload).toHaveBeenCalledWith(data, "doc.pdf", "application/pdf");
    expect(uri).toBe("file:///tmp/media/doc.pdf");
  });

  it("allows filename override", async () => {
    const buffer = Buffer.from("data");
    mockUpload.mockResolvedValue("file:///tmp/media/custom.txt");

    const uri = await saveUpload(
      { buffer, originalname: "original.txt", mimetype: "text/plain" },
      { filename: "custom.txt" },
    );

    expect(mockUpload).toHaveBeenCalledWith(buffer, "custom.txt", "text/plain");
    expect(uri).toBe("file:///tmp/media/custom.txt");
  });

  it("allows mimeType override", async () => {
    const data = Buffer.from("data");
    mockUpload.mockResolvedValue("file:///tmp/media/file.bin");

    await saveUpload(
      { data, name: "file.bin", mimeType: "application/octet-stream" },
      { mimeType: "application/x-custom" },
    );

    expect(mockUpload).toHaveBeenCalledWith(data, "file.bin", "application/x-custom");
  });
});

describe("saveUploadResult", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("returns full metadata for multer file", async () => {
    const buffer = Buffer.from("result-data");
    mockUpload.mockResolvedValue("file:///tmp/media/result.png");

    const result = await saveUploadResult({
      buffer,
      originalname: "result.png",
      mimetype: "image/png",
    });

    expect(result).toEqual({
      uri: "file:///tmp/media/result.png",
      name: "result.png",
      mimeType: "image/png",
      size: buffer.length,
    });
  });

  it("returns full metadata for generic file", async () => {
    const data = Buffer.from("generic-result");
    mockUpload.mockResolvedValue("s3://bucket/report.pdf");

    const result = await saveUploadResult({
      data,
      name: "report.pdf",
      mimeType: "application/pdf",
    });

    expect(result).toEqual({
      uri: "s3://bucket/report.pdf",
      name: "report.pdf",
      mimeType: "application/pdf",
      size: data.length,
    });
  });

  it("respects filename and mimeType overrides", async () => {
    const buffer = Buffer.from("override-data");
    mockUpload.mockResolvedValue("file:///tmp/media/renamed.csv");

    const result = await saveUploadResult(
      { buffer, originalname: "original.txt", mimetype: "text/plain" },
      { filename: "renamed.csv", mimeType: "text/csv" },
    );

    expect(mockUpload).toHaveBeenCalledWith(buffer, "renamed.csv", "text/csv");
    expect(result).toEqual({
      uri: "file:///tmp/media/renamed.csv",
      name: "renamed.csv",
      mimeType: "text/csv",
      size: buffer.length,
    });
  });
});
