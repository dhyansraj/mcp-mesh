/**
 * Issue #547 Phase 4: unit tests for the schema verdict policy helpers in
 * `schema-normalize.ts`.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

// Mock @mcpmesh/core so we don't load the napi binding for these unit tests.
vi.mock("@mcpmesh/core", () => ({
  normalizeSchema: vi.fn(),
}));

import * as core from "@mcpmesh/core";
import {
  clusterStrictEnabled,
  normalizeSchemaWithPolicy,
  shouldRefuseStartup,
} from "../schema-normalize.js";

describe("shouldRefuseStartup", () => {
  it("OK never refuses regardless of flags", () => {
    expect(shouldRefuseStartup("OK", false, true)).toBe(false);
    expect(shouldRefuseStartup("OK", true, true)).toBe(false);
    expect(shouldRefuseStartup("OK", true, false)).toBe(false);
  });

  it("BLOCK with default tool_strict refuses", () => {
    expect(shouldRefuseStartup("BLOCK", false, true)).toBe(true);
  });

  it("BLOCK with per-tool override does not refuse", () => {
    expect(shouldRefuseStartup("BLOCK", false, false)).toBe(false);
  });

  it("WARN with defaults does not refuse", () => {
    expect(shouldRefuseStartup("WARN", false, true)).toBe(false);
  });

  it("WARN with cluster strict refuses", () => {
    expect(shouldRefuseStartup("WARN", true, true)).toBe(true);
  });

  it("per-tool override wins over cluster strict", () => {
    expect(shouldRefuseStartup("BLOCK", true, false)).toBe(false);
    expect(shouldRefuseStartup("WARN", true, false)).toBe(false);
  });
});

describe("clusterStrictEnabled", () => {
  const originalEnv = process.env.MCP_MESH_SCHEMA_STRICT;

  afterEach(() => {
    if (originalEnv === undefined) {
      delete process.env.MCP_MESH_SCHEMA_STRICT;
    } else {
      process.env.MCP_MESH_SCHEMA_STRICT = originalEnv;
    }
  });

  it.each(["1", "true", "TRUE", "True", "yes", "YES"])(
    "truthy value %s -> true",
    (v) => {
      process.env.MCP_MESH_SCHEMA_STRICT = v;
      expect(clusterStrictEnabled()).toBe(true);
    }
  );

  it.each(["", "0", "false", "no", "off", "anything-else"])(
    "falsy value %s -> false",
    (v) => {
      process.env.MCP_MESH_SCHEMA_STRICT = v;
      expect(clusterStrictEnabled()).toBe(false);
    }
  );

  it("unset -> false", () => {
    delete process.env.MCP_MESH_SCHEMA_STRICT;
    expect(clusterStrictEnabled()).toBe(false);
  });
});

describe("normalizeSchemaWithPolicy", () => {
  const mockNormalize = core.normalizeSchema as unknown as ReturnType<
    typeof vi.fn
  >;
  let warnSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    mockNormalize.mockReset();
    warnSpy = vi.spyOn(console, "warn").mockImplementation(() => undefined);
  });

  afterEach(() => {
    warnSpy.mockRestore();
  });

  it("OK passes through with canonical+hash", () => {
    mockNormalize.mockReturnValue(
      JSON.stringify({
        canonical: { type: "string" },
        hash: "sha256:deadbeef",
        verdict: "OK",
        warnings: [],
      })
    );
    const r = normalizeSchemaWithPolicy({}, "ctx", false, true);
    expect(r.verdict).toBe("OK");
    expect(r.canonicalJson).toBe('{"type":"string"}');
    expect(r.hash).toBe("sha256:deadbeef");
    expect(r.warnings).toEqual([]);
  });

  it("BLOCK with toolStrict=true throws", () => {
    mockNormalize.mockReturnValue(
      JSON.stringify({ verdict: "BLOCK", warnings: ["unsupported keyword"] })
    );
    expect(() => normalizeSchemaWithPolicy({}, "ctx", false, true)).toThrow(
      /BLOCK for ctx.*unsupported keyword.*Cannot start agent/
    );
  });

  it("BLOCK with toolStrict=false does not throw, tags warnings", () => {
    mockNormalize.mockReturnValue(
      JSON.stringify({
        canonical: { type: "string" },
        hash: "sha256:abc",
        verdict: "BLOCK",
        warnings: ["something bad"],
      })
    );
    const r = normalizeSchemaWithPolicy({}, "ctx", false, false);
    expect(r.verdict).toBe("BLOCK");
    expect(r.warnings).toEqual(["[demoted from BLOCK] something bad"]);
    expect(r.canonicalJson).toBe('{"type":"string"}');
    expect(warnSpy).toHaveBeenCalled();
  });

  it("WARN with cluster strict + tool strict throws (promoted)", () => {
    mockNormalize.mockReturnValue(
      JSON.stringify({ verdict: "WARN", warnings: ["soft issue"] })
    );
    expect(() => normalizeSchemaWithPolicy({}, "ctx", true, true)).toThrow(
      /WARN for ctx \(MCP_MESH_SCHEMA_STRICT=true upgraded WARN.*soft issue/
    );
  });

  it("WARN with cluster strict + tool override does not throw", () => {
    mockNormalize.mockReturnValue(
      JSON.stringify({
        canonical: { type: "string" },
        hash: "sha256:abc",
        verdict: "WARN",
        warnings: ["soft issue"],
      })
    );
    const r = normalizeSchemaWithPolicy({}, "ctx", true, false);
    expect(r.verdict).toBe("WARN");
    expect(r.warnings).toEqual(["soft issue"]);
  });

  it("WARN without cluster strict logs and continues", () => {
    mockNormalize.mockReturnValue(
      JSON.stringify({
        canonical: { type: "string" },
        hash: "sha256:abc",
        verdict: "WARN",
        warnings: ["soft issue"],
      })
    );
    const r = normalizeSchemaWithPolicy({}, "ctx", false, true);
    expect(r.verdict).toBe("WARN");
    expect(r.warnings).toEqual(["soft issue"]);
    expect(warnSpy).toHaveBeenCalled();
  });
});
