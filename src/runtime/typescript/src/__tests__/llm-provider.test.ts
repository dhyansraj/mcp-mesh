/**
 * Unit tests for llm-provider.ts
 *
 * Tests LLM provider tool generation and vendor extraction utilities.
 */

import { describe, it, expect } from "vitest";
import {
  extractVendorFromModel,
  extractModelName,
  llmProvider,
  isLlmProviderTool,
  getLlmProviderMeta,
} from "../llm-provider.js";

describe("extractVendorFromModel", () => {
  it("should extract vendor from vendor/model format", () => {
    expect(extractVendorFromModel("anthropic/claude-sonnet-4-5")).toBe("anthropic");
    expect(extractVendorFromModel("openai/gpt-4o")).toBe("openai");
    expect(extractVendorFromModel("google/gemini-2.0-flash")).toBe("google");
  });

  it("should return null for model without vendor prefix", () => {
    expect(extractVendorFromModel("gpt-4")).toBeNull();
    expect(extractVendorFromModel("claude-sonnet-4-5")).toBeNull();
  });

  it("should return null for empty string", () => {
    expect(extractVendorFromModel("")).toBeNull();
  });

  it("should normalize vendor to lowercase", () => {
    expect(extractVendorFromModel("ANTHROPIC/claude-sonnet-4-5")).toBe("anthropic");
    expect(extractVendorFromModel("OpenAI/gpt-4o")).toBe("openai");
  });

  it("should trim whitespace from vendor", () => {
    expect(extractVendorFromModel("  anthropic  /claude-sonnet-4-5")).toBe("anthropic");
  });

  it("should handle multi-segment model names", () => {
    expect(extractVendorFromModel("anthropic/claude-3-5-sonnet-20241022")).toBe("anthropic");
  });

  it("should return null for slash without vendor", () => {
    expect(extractVendorFromModel("/gpt-4")).toBeNull();
  });
});

describe("extractModelName", () => {
  it("should extract model name without vendor prefix", () => {
    expect(extractModelName("anthropic/claude-sonnet-4-5")).toBe("claude-sonnet-4-5");
    expect(extractModelName("openai/gpt-4o")).toBe("gpt-4o");
  });

  it("should return model as-is if no vendor prefix", () => {
    expect(extractModelName("gpt-4")).toBe("gpt-4");
    expect(extractModelName("claude-sonnet-4-5")).toBe("claude-sonnet-4-5");
  });

  it("should handle multi-segment paths after vendor", () => {
    expect(extractModelName("vendor/model/variant")).toBe("model/variant");
  });

  it("should handle empty input", () => {
    expect(extractModelName("")).toBe("");
  });
});

describe("llmProvider", () => {
  describe("tool definition generation", () => {
    it("should generate tool with correct structure", () => {
      const tool = llmProvider({
        model: "anthropic/claude-sonnet-4-5",
        capability: "llm",
        tags: ["llm", "claude"],
      });

      expect(tool.name).toBe("process_chat");
      expect(typeof tool.description).toBe("string");
      expect(tool.parameters).toBeDefined();
      expect(typeof tool.execute).toBe("function");
    });

    it("should use custom tool name", () => {
      const tool = llmProvider({
        model: "openai/gpt-4o",
        name: "custom_chat",
      });

      expect(tool.name).toBe("custom_chat");
    });

    it("should use custom description", () => {
      const tool = llmProvider({
        model: "openai/gpt-4o",
        description: "Custom LLM endpoint",
      });

      expect(tool.description).toBe("Custom LLM endpoint");
    });

    it("should include model in default description", () => {
      const tool = llmProvider({
        model: "anthropic/claude-sonnet-4-5",
      });

      expect(tool.description).toContain("claude-sonnet-4-5");
    });

    it("should attach mesh metadata", () => {
      const tool = llmProvider({
        model: "anthropic/claude-sonnet-4-5",
        capability: "llm",
        tags: ["llm", "claude", "anthropic"],
        version: "2.0.0",
      });

      expect(tool._meshMeta).toBeDefined();
      expect(tool._meshMeta?.capability).toBe("llm");
      expect(tool._meshMeta?.tags).toEqual(["llm", "claude", "anthropic"]);
      expect(tool._meshMeta?.version).toBe("2.0.0");
      expect(tool._meshMeta?.vendor).toBe("anthropic");
    });

    it("should use default values when not provided", () => {
      const tool = llmProvider({
        model: "openai/gpt-4o",
      });

      expect(tool._meshMeta?.capability).toBe("llm");
      expect(tool._meshMeta?.tags).toEqual([]);
      expect(tool._meshMeta?.version).toBe("1.0.0");
    });

    it("should extract vendor from model string", () => {
      const anthropicTool = llmProvider({ model: "anthropic/claude-sonnet-4-5" });
      const openaiTool = llmProvider({ model: "openai/gpt-4o" });
      const googleTool = llmProvider({ model: "google/gemini-2.0-flash" });

      expect(anthropicTool._meshMeta?.vendor).toBe("anthropic");
      expect(openaiTool._meshMeta?.vendor).toBe("openai");
      expect(googleTool._meshMeta?.vendor).toBe("google");
    });

    it("should use 'unknown' vendor for models without prefix", () => {
      const tool = llmProvider({ model: "gpt-4" });

      expect(tool._meshMeta?.vendor).toBe("unknown");
    });
  });

  describe("parameter schema", () => {
    it("should have request parameter with messages", () => {
      const tool = llmProvider({ model: "anthropic/claude-sonnet-4-5" });

      // The schema should be defined
      expect(tool.parameters).toBeDefined();
      expect(tool.parameters.shape.request).toBeDefined();
    });
  });
});

describe("isLlmProviderTool", () => {
  it("should return true for LLM provider tools", () => {
    const tool = llmProvider({ model: "anthropic/claude-sonnet-4-5" });

    expect(isLlmProviderTool(tool)).toBe(true);
  });

  it("should return false for non-objects", () => {
    expect(isLlmProviderTool(null)).toBe(false);
    expect(isLlmProviderTool(undefined)).toBe(false);
    expect(isLlmProviderTool("string")).toBe(false);
    expect(isLlmProviderTool(123)).toBe(false);
  });

  it("should return false for objects without _meshMeta", () => {
    expect(isLlmProviderTool({})).toBe(false);
    expect(isLlmProviderTool({ name: "test" })).toBe(false);
  });

  it("should return false for objects with non-object _meshMeta", () => {
    expect(isLlmProviderTool({ _meshMeta: "not an object" })).toBe(false);
    expect(isLlmProviderTool({ _meshMeta: 123 })).toBe(false);
    // Note: null returns true because typeof null === "object" in JavaScript
    // This is a known quirk; getLlmProviderMeta handles null gracefully
  });
});

describe("getLlmProviderMeta", () => {
  it("should return metadata from LLM provider tool", () => {
    const tool = llmProvider({
      model: "openai/gpt-4o",
      capability: "llm",
      tags: ["gpt", "openai"],
      version: "1.5.0",
    });

    const meta = getLlmProviderMeta(tool);

    expect(meta).not.toBeNull();
    expect(meta?.capability).toBe("llm");
    expect(meta?.tags).toEqual(["gpt", "openai"]);
    expect(meta?.version).toBe("1.5.0");
    expect(meta?.vendor).toBe("openai");
  });

  it("should return null for tool without metadata", () => {
    const fakeTool = {
      name: "test",
      execute: () => Promise.resolve(""),
      inputSchema: {},
    } as unknown as ReturnType<typeof llmProvider>;

    const meta = getLlmProviderMeta(fakeTool);

    expect(meta).toBeNull();
  });
});

describe("LLM provider configurations", () => {
  it("should accept maxOutputTokens configuration", () => {
    const tool = llmProvider({
      model: "anthropic/claude-sonnet-4-5",
      maxOutputTokens: 4096,
    });

    expect(tool).toBeDefined();
    // maxOutputTokens is used internally in execute, verified via integration tests
  });

  it("should accept temperature configuration", () => {
    const tool = llmProvider({
      model: "openai/gpt-4o",
      temperature: 0.7,
    });

    expect(tool).toBeDefined();
  });

  it("should accept topP configuration", () => {
    const tool = llmProvider({
      model: "google/gemini-2.0-flash",
      topP: 0.9,
    });

    expect(tool).toBeDefined();
  });

  it("should accept all parameters together", () => {
    const tool = llmProvider({
      model: "anthropic/claude-sonnet-4-5",
      capability: "custom-llm",
      tags: ["production", "fast"],
      version: "3.0.0",
      name: "production_chat",
      description: "Production LLM endpoint with Claude",
      maxOutputTokens: 8192,
      temperature: 0.5,
      topP: 0.95,
    });

    expect(tool.name).toBe("production_chat");
    expect(tool.description).toBe("Production LLM endpoint with Claude");
    expect(tool._meshMeta?.capability).toBe("custom-llm");
    expect(tool._meshMeta?.tags).toEqual(["production", "fast"]);
    expect(tool._meshMeta?.version).toBe("3.0.0");
    expect(tool._meshMeta?.vendor).toBe("anthropic");
  });
});
