/**
 * Issue #1619: a set-but-empty env var (empty Helm value, `docker run -e VAR`,
 * `export VAR="$UNSET"`) means "not set" and must not shadow the fallback.
 */
import { describe, it, expect, afterEach } from "vitest";
import { envLlmModel } from "../llm-agent.js";
import { resolveProducerRegistryUrl } from "../a2a/producer/mount.js";

const saved = {
  MESH_LLM_MODEL: process.env.MESH_LLM_MODEL,
  MCP_MESH_REGISTRY_URL: process.env.MCP_MESH_REGISTRY_URL,
};

afterEach(() => {
  for (const [k, v] of Object.entries(saved)) {
    if (v === undefined) delete process.env[k];
    else process.env[k] = v;
  }
});

describe("MESH_LLM_MODEL", () => {
  it("is undefined when unset", () => {
    delete process.env.MESH_LLM_MODEL;
    expect(envLlmModel()).toBeUndefined();
  });

  for (const blank of ["", "   "]) {
    it(`is undefined when blank ('${blank}') so the configured model applies`, () => {
      process.env.MESH_LLM_MODEL = blank;
      expect(envLlmModel()).toBeUndefined();
      expect(envLlmModel() ?? "configured-model").toBe("configured-model");
    });
  }

  it("returns a set value, trimmed", () => {
    process.env.MESH_LLM_MODEL = " openai/gpt-4o ";
    expect(envLlmModel()).toBe("openai/gpt-4o");
  });
});

describe("A2A producer registry URL (MCP_MESH_REGISTRY_URL)", () => {
  it("defaults when unset", () => {
    delete process.env.MCP_MESH_REGISTRY_URL;
    expect(resolveProducerRegistryUrl()).toBe("http://localhost:8000");
  });

  it("defaults when set but empty", () => {
    process.env.MCP_MESH_REGISTRY_URL = "";
    expect(resolveProducerRegistryUrl()).toBe("http://localhost:8000");
  });

  it("uses a set value", () => {
    process.env.MCP_MESH_REGISTRY_URL = "http://registry.mesh:8000";
    expect(resolveProducerRegistryUrl()).toBe("http://registry.mesh:8000");
  });
});
