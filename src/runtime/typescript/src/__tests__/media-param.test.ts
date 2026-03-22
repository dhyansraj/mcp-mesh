/**
 * Unit tests for mediaParam() helper and enrichSchemaWithMediaTypes().
 *
 * Tests the [media:TYPE] description convention and JSON Schema enrichment.
 */

import { describe, it, expect, vi } from "vitest";

// Mock @mcpmesh/core before importing
vi.mock("@mcpmesh/core", () => ({
  resolveConfig: vi.fn((_key: string, _value: string | null) => ""),
  resolveConfigInt: vi.fn((_key: string, _value: number | null) => null),
  getDefault: vi.fn((_key: string) => null),
}));

import { mediaParam } from "../types.js";
import { enrichSchemaWithMediaTypes } from "../media-param.js";

describe("mediaParam", () => {
  it("creates optional string schema", () => {
    const schema = mediaParam("image/*");
    expect(schema.isOptional()).toBe(true);
  });

  it("includes media type in description", () => {
    const schema = mediaParam("image/*");
    expect(schema.description).toContain("[media:image/*]");
  });

  it("defaults to */* when no media type specified", () => {
    const schema = mediaParam();
    expect(schema.description).toContain("[media:*/*]");
  });

  it("accepts specific MIME types", () => {
    const schema = mediaParam("audio/wav");
    expect(schema.description).toContain("[media:audio/wav]");
  });
});

describe("enrichSchemaWithMediaTypes", () => {
  it("adds x-media-type from description convention", () => {
    const schema: Record<string, unknown> = {
      properties: {
        image: {
          type: "string",
          description: "[media:image/*] Media URI for this parameter",
        },
      },
    };
    enrichSchemaWithMediaTypes(schema);
    const props = schema.properties as Record<string, Record<string, unknown>>;
    expect(props.image["x-media-type"]).toBe("image/*");
    expect(props.image.description).toContain("accepts media URI");
    expect(props.image.description).not.toContain("[media:");
  });

  it("leaves non-media params unchanged", () => {
    const schema: Record<string, unknown> = {
      properties: {
        question: { type: "string", description: "A question" },
      },
    };
    enrichSchemaWithMediaTypes(schema);
    const props = schema.properties as Record<string, Record<string, unknown>>;
    expect(props.question["x-media-type"]).toBeUndefined();
    expect(props.question.description).toBe("A question");
  });

  it("handles schema with no properties", () => {
    const schema: Record<string, unknown> = { type: "object" };
    // Should not throw
    enrichSchemaWithMediaTypes(schema);
    expect(schema.type).toBe("object");
  });

  it("handles mixed media and non-media params", () => {
    const schema: Record<string, unknown> = {
      properties: {
        question: { type: "string", description: "User question" },
        image: {
          type: "string",
          description: "[media:image/*] Media URI for this parameter",
        },
        audio: {
          type: "string",
          description: "[media:audio/wav] Media URI for this parameter",
        },
      },
    };
    enrichSchemaWithMediaTypes(schema);
    const props = schema.properties as Record<string, Record<string, unknown>>;

    expect(props.question["x-media-type"]).toBeUndefined();
    expect(props.question.description).toBe("User question");

    expect(props.image["x-media-type"]).toBe("image/*");
    expect(props.image.description).toContain("accepts media URI: image/*");

    expect(props.audio["x-media-type"]).toBe("audio/wav");
    expect(props.audio.description).toContain("accepts media URI: audio/wav");
  });

  it("cleans [media:...] prefix from description", () => {
    const schema: Record<string, unknown> = {
      properties: {
        photo: {
          type: "string",
          description: "[media:image/png] Upload a photo",
        },
      },
    };
    enrichSchemaWithMediaTypes(schema);
    const props = schema.properties as Record<string, Record<string, unknown>>;
    expect(props.photo.description).toBe("Upload a photo (accepts media URI: image/png)");
    expect(props.photo["x-media-type"]).toBe("image/png");
  });
});
