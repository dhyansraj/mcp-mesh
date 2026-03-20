/**
 * Unit tests for media/media-store.ts
 *
 * Tests the MediaStore abstraction: LocalMediaStore, getMediaStore, helpers.
 */

import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { join } from "node:path";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";

// Mock @mcpmesh/core before importing modules that use it
vi.mock("@mcpmesh/core", () => ({
  resolveConfig: vi.fn((_key: string, _value: string | null) => ""),
  resolveConfigInt: vi.fn((_key: string, _value: number | null) => null),
  getDefault: vi.fn((_key: string) => null),
}));

import {
  LocalMediaStore,
  getMediaStore,
  guessMimeType,
  _resetMediaStore,
} from "../media/index.js";

describe("guessMimeType", () => {
  it("should return correct MIME for common extensions", () => {
    expect(guessMimeType("photo.png")).toBe("image/png");
    expect(guessMimeType("photo.jpg")).toBe("image/jpeg");
    expect(guessMimeType("photo.jpeg")).toBe("image/jpeg");
    expect(guessMimeType("animation.gif")).toBe("image/gif");
    expect(guessMimeType("doc.pdf")).toBe("application/pdf");
    expect(guessMimeType("data.json")).toBe("application/json");
    expect(guessMimeType("song.mp3")).toBe("audio/mpeg");
  });

  it("should be case-insensitive", () => {
    expect(guessMimeType("PHOTO.PNG")).toBe("image/png");
    expect(guessMimeType("Doc.PDF")).toBe("application/pdf");
  });

  it("should fall back to application/octet-stream for unknown extensions", () => {
    expect(guessMimeType("file.xyz")).toBe("application/octet-stream");
    expect(guessMimeType("noext")).toBe("application/octet-stream");
  });
});

describe("LocalMediaStore", () => {
  let tmpDir: string;
  let store: LocalMediaStore;

  beforeEach(async () => {
    tmpDir = await mkdtemp(join(tmpdir(), "mcp-mesh-media-test-"));
    store = new LocalMediaStore(tmpDir, "test/");
  });

  afterEach(async () => {
    await rm(tmpDir, { recursive: true, force: true });
  });

  it("should upload and fetch a file round-trip", async () => {
    const data = Buffer.from("hello world");
    const uri = await store.upload(data, "hello.txt", "text/plain");

    expect(uri).toMatch(/^file:\/\//);
    expect(uri).toContain("hello.txt");

    const result = await store.fetch(uri);
    expect(result.data.toString()).toBe("hello world");
    expect(result.mimeType).toBe("text/plain");
  });

  it("should upload binary data correctly", async () => {
    const data = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);
    const uri = await store.upload(data, "image.png", "image/png");

    const result = await store.fetch(uri);
    expect(Buffer.compare(result.data, data)).toBe(0);
    expect(result.mimeType).toBe("image/png");
  });

  it("should return true for exists() after upload", async () => {
    const data = Buffer.from("test");
    const uri = await store.upload(data, "exists-test.txt", "text/plain");

    expect(await store.exists(uri)).toBe(true);
  });

  it("should return false for exists() before upload", async () => {
    const fakeUri = `file://${join(tmpDir, "test", "does-not-exist.txt")}`;
    expect(await store.exists(fakeUri)).toBe(false);
  });

  it("should create nested directories automatically", async () => {
    const data = Buffer.from("nested");
    const uri = await store.upload(data, "deep-file.txt", "text/plain");

    expect(await store.exists(uri)).toBe(true);
    const result = await store.fetch(uri);
    expect(result.data.toString()).toBe("nested");
  });
});

describe("getMediaStore", () => {
  beforeEach(() => {
    _resetMediaStore();
  });

  afterEach(() => {
    _resetMediaStore();
  });

  it("should return a LocalMediaStore by default", () => {
    const store = getMediaStore();
    expect(store).toBeInstanceOf(LocalMediaStore);
  });

  it("should return the same instance on repeated calls", () => {
    const store1 = getMediaStore();
    const store2 = getMediaStore();
    expect(store1).toBe(store2);
  });

  it("should return a fresh instance after reset", () => {
    const store1 = getMediaStore();
    _resetMediaStore();
    const store2 = getMediaStore();
    expect(store1).not.toBe(store2);
  });
});
