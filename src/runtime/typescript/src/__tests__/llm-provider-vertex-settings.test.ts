/**
 * Vertex AI provider settings resolution — issue #1181.
 *
 * The mesh contract (#834) is GOOGLE_CLOUD_PROJECT / GOOGLE_CLOUD_LOCATION
 * (honored by the Python runtime). @ai-sdk/google-vertex's default `vertex`
 * instance only reads GOOGLE_VERTEX_PROJECT / GOOGLE_VERTEX_LOCATION at call
 * time, so identically-configured environments worked on Python and threw
 * `AI_LoadSettingError` on TS.
 *
 * loadProvider("vertex_ai") must now ALWAYS construct the provider via
 * createVertex() with explicitly resolved settings:
 *  - mesh-standard names map through,
 *  - the vendor-specific GOOGLE_VERTEX_* name wins when both are set,
 *  - settings that resolve to nothing are OMITTED (the SDK surfaces its own
 *    clear error), and the debug warn mentions BOTH accepted names.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

const createVertexMock = vi.fn(
  (options?: { project?: string; location?: string }) => {
    // Mimic the real factory: returns a callable provider that resolves models.
    return (modelId: string) => ({ modelId, options });
  }
);

vi.mock("@ai-sdk/google-vertex", () => ({
  createVertex: (options?: { project?: string; location?: string }) =>
    createVertexMock(options),
  // The default instance reads GOOGLE_VERTEX_* env vars at call time and must
  // never be used by the mesh provider path (#1181 regression guard).
  vertex: () => {
    throw new Error("default `vertex` instance must not be used");
  },
}));

import { loadProvider, resolveVertexSettings } from "../llm-provider.js";

const ENV_KEYS = [
  "GOOGLE_VERTEX_PROJECT",
  "GOOGLE_VERTEX_LOCATION",
  "GOOGLE_CLOUD_PROJECT",
  "GOOGLE_CLOUD_LOCATION",
  "MCP_MESH_DEBUG_MODE",
  "MCP_MESH_LOG_LEVEL",
] as const;

describe("vertex_ai provider settings resolution (#1181)", () => {
  let savedEnv: Record<string, string | undefined>;

  beforeEach(() => {
    createVertexMock.mockClear();
    // Capture-and-restore: save current values, clear for a clean slate.
    savedEnv = {};
    for (const key of ENV_KEYS) {
      savedEnv[key] = process.env[key];
      delete process.env[key];
    }
  });

  afterEach(() => {
    for (const key of ENV_KEYS) {
      if (savedEnv[key] === undefined) {
        delete process.env[key];
      } else {
        process.env[key] = savedEnv[key];
      }
    }
    vi.restoreAllMocks();
  });

  it("maps mesh-standard GOOGLE_CLOUD_PROJECT/GOOGLE_CLOUD_LOCATION through to createVertex", async () => {
    process.env.GOOGLE_CLOUD_PROJECT = "mesh-project";
    process.env.GOOGLE_CLOUD_LOCATION = "us-central1";

    const provider = await loadProvider("vertex_ai");

    expect(createVertexMock).toHaveBeenCalledTimes(1);
    expect(createVertexMock).toHaveBeenCalledWith({
      project: "mesh-project",
      location: "us-central1",
    });

    // The swap must be seamless: loadProvider returns the factory's provider,
    // which resolves model IDs exactly like the previous default instance.
    expect(typeof provider).toBe("function");
    const model = provider!("gemini-2.5-flash") as {
      modelId: string;
      options?: { project?: string; location?: string };
    };
    expect(model.modelId).toBe("gemini-2.5-flash");
    expect(model.options).toEqual({
      project: "mesh-project",
      location: "us-central1",
    });
  });

  it("prefers vendor-specific GOOGLE_VERTEX_* when both names are set", async () => {
    process.env.GOOGLE_VERTEX_PROJECT = "vertex-project";
    process.env.GOOGLE_VERTEX_LOCATION = "europe-west4";
    process.env.GOOGLE_CLOUD_PROJECT = "cloud-project";
    process.env.GOOGLE_CLOUD_LOCATION = "us-central1";

    await loadProvider("vertex_ai");

    expect(createVertexMock).toHaveBeenCalledWith({
      project: "vertex-project",
      location: "europe-west4",
    });
  });

  it("resolves each setting independently (mixed naming)", async () => {
    process.env.GOOGLE_VERTEX_PROJECT = "vertex-project";
    process.env.GOOGLE_CLOUD_LOCATION = "us-east1";

    await loadProvider("vertex_ai");

    expect(createVertexMock).toHaveBeenCalledWith({
      project: "vertex-project",
      location: "us-east1",
    });
  });

  it("omits unresolved settings and warns mentioning BOTH accepted names", async () => {
    process.env.MCP_MESH_DEBUG_MODE = "true";
    const logSpy = vi.spyOn(console, "log").mockImplementation(() => {});

    await loadProvider("vertex_ai");

    // Factory still called (single code path), but without project/location
    // keys — the SDK throws its own clear LoadSettingError at call time.
    expect(createVertexMock).toHaveBeenCalledTimes(1);
    const opts = createVertexMock.mock.calls[0][0] as Record<string, unknown>;
    expect(opts).not.toHaveProperty("project");
    expect(opts).not.toHaveProperty("location");

    const logged = logSpy.mock.calls.map((call) => call.join(" ")).join("\n");
    expect(logged).toContain("GOOGLE_VERTEX_PROJECT");
    expect(logged).toContain("GOOGLE_CLOUD_PROJECT");
    expect(logged).toContain("GOOGLE_VERTEX_LOCATION");
    expect(logged).toContain("GOOGLE_CLOUD_LOCATION");
  });

  it("resolveVertexSettings treats empty string as unset (falls through, never blank)", () => {
    process.env.GOOGLE_VERTEX_PROJECT = "";
    process.env.GOOGLE_CLOUD_PROJECT = "cloud-project";
    process.env.GOOGLE_VERTEX_LOCATION = "";

    const settings = resolveVertexSettings();

    // An empty vendor-specific name must not shadow-and-blank the setting: it
    // falls through to the mesh-standard name, and a setting with no non-empty
    // source is omitted entirely.
    expect(settings).toEqual({ project: "cloud-project" });
    expect(settings).not.toHaveProperty("location");
  });
});
