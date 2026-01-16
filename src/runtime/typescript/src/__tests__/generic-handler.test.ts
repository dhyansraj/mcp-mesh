/**
 * Unit tests for generic-handler.ts
 *
 * Tests the GenericHandler fallback provider for unknown vendors.
 */

import { describe, it, expect, beforeEach } from "vitest";
import { GenericHandler } from "../provider-handlers/generic-handler.js";
import type { OutputSchema, ToolSchema } from "../provider-handlers/provider-handler.js";
import type { LlmMessage } from "../types.js";

describe("GenericHandler", () => {
  let handler: GenericHandler;

  beforeEach(() => {
    handler = new GenericHandler();
  });

  describe("vendor", () => {
    it("should default to 'unknown' vendor", () => {
      expect(handler.vendor).toBe("unknown");
    });

    it("should accept custom vendor name in constructor", () => {
      const customHandler = new GenericHandler("custom-vendor");
      expect(customHandler.vendor).toBe("custom-vendor");
    });
  });

  describe("getCapabilities", () => {
    it("should return conservative capabilities", () => {
      const capabilities = handler.getCapabilities();

      // Conservative approach for unknown vendors
      expect(capabilities.nativeToolCalling).toBe(true);
      expect(capabilities.structuredOutput).toBe(false);
      expect(capabilities.streaming).toBe(false);
      expect(capabilities.vision).toBe(false);
      expect(capabilities.jsonMode).toBe(false);
    });
  });

  describe("determineOutputMode", () => {
    it("should return 'text' when no schema provided", () => {
      const mode = handler.determineOutputMode(null);
      expect(mode).toBe("text");
    });

    it("should return override mode when specified", () => {
      const schema: OutputSchema = {
        name: "Test",
        schema: { type: "object", properties: { a: { type: "string" } } },
      };

      expect(handler.determineOutputMode(schema, "strict")).toBe("strict");
      expect(handler.determineOutputMode(schema, "text")).toBe("text");
    });

    it("should always return 'hint' for schemas (conservative approach)", () => {
      // Generic handler uses hint mode since we can't assume structured output support
      const simpleSchema: OutputSchema = {
        name: "Simple",
        schema: { type: "object", properties: { name: { type: "string" } } },
      };

      const mode = handler.determineOutputMode(simpleSchema);
      expect(mode).toBe("hint");
    });

    it("should return 'hint' even for complex schemas", () => {
      const complexSchema: OutputSchema = {
        name: "Complex",
        schema: {
          type: "object",
          properties: {
            a: { type: "string" },
            b: { type: "string" },
            c: { type: "string" },
            d: { type: "string" },
            e: { type: "string" },
            f: { type: "string" },
          },
        },
      };

      const mode = handler.determineOutputMode(complexSchema);
      // Generic handler always uses hint, not strict
      expect(mode).toBe("hint");
    });
  });

  describe("prepareRequest", () => {
    it("should pass messages through unchanged", () => {
      const messages: LlmMessage[] = [
        { role: "system", content: "You are helpful." },
        { role: "user", content: "Hello" },
        { role: "assistant", content: "Hi!" },
      ];

      const request = handler.prepareRequest(messages, null, null);

      expect(request.messages).toHaveLength(3);
      expect(request.messages[0].content).toBe("You are helpful.");
      expect(request.messages[1].content).toBe("Hello");
      expect(request.messages[2].content).toBe("Hi!");
    });

    it("should NOT convert tool_calls (unlike Claude/OpenAI handlers)", () => {
      const messages: LlmMessage[] = [
        {
          role: "assistant",
          content: "",
          tool_calls: [
            {
              id: "call_123",
              type: "function",
              function: { name: "test", arguments: "{}" },
            },
          ],
        },
      ];

      const request = handler.prepareRequest(messages, null, null);

      // Generic handler passes messages as-is (Vercel AI SDK normalizes)
      expect(request.messages[0].tool_calls).toEqual(messages[0].tool_calls);
    });

    it("should include tools when provided", () => {
      const messages: LlmMessage[] = [{ role: "user", content: "Hello" }];
      const tools: ToolSchema[] = [
        { type: "function", function: { name: "test", description: "Test tool" } },
      ];

      const request = handler.prepareRequest(messages, tools, null);

      expect(request.tools).toEqual(tools);
    });

    it("should NOT include response_format (not all vendors support it)", () => {
      const messages: LlmMessage[] = [{ role: "user", content: "Hello" }];
      const schema: OutputSchema = {
        name: "Test",
        schema: { type: "object", properties: { value: { type: "string" } } },
      };

      const request = handler.prepareRequest(messages, null, schema);

      // Generic handler relies on prompt-based instructions, not response_format
      expect(request.responseFormat).toBeUndefined();
    });

    it("should pass through temperature, maxOutputTokens, and topP", () => {
      const messages: LlmMessage[] = [{ role: "user", content: "Hello" }];

      const request = handler.prepareRequest(messages, null, null, {
        temperature: 0.8,
        maxOutputTokens: 500,
        topP: 0.9,
      });

      expect(request.temperature).toBe(0.8);
      expect(request.maxOutputTokens).toBe(500);
      expect(request.topP).toBe(0.9);
    });

    it("should pass through additional options", () => {
      const messages: LlmMessage[] = [{ role: "user", content: "Hello" }];

      const request = handler.prepareRequest(messages, null, null, {
        customOption: "value",
        anotherOption: 123,
      });

      expect(request.customOption).toBe("value");
      expect(request.anotherOption).toBe(123);
    });
  });

  describe("formatSystemPrompt", () => {
    it("should return base prompt as-is when no tools or schema", () => {
      const basePrompt = "You are a helpful assistant.";
      const result = handler.formatSystemPrompt(basePrompt, null, null);

      expect(result).toBe(basePrompt);
    });

    it("should add tool calling rules when tools provided", () => {
      const basePrompt = "You are a helpful assistant.";
      const tools: ToolSchema[] = [
        { type: "function", function: { name: "test" } },
      ];

      const result = handler.formatSystemPrompt(basePrompt, tools, null);

      expect(result).toContain("TOOL CALLING RULES:");
      expect(result).toContain("Make one tool call at a time");
      expect(result).toContain("standard JSON function calling format");
    });

    it("should add explicit JSON schema instructions when schema provided", () => {
      const basePrompt = "You are a helpful assistant.";
      const schema: OutputSchema = {
        name: "Response",
        schema: {
          type: "object",
          properties: {
            message: { type: "string" },
            count: { type: "number" },
          },
        },
      };

      const result = handler.formatSystemPrompt(basePrompt, null, schema);

      // Generic handler adds full schema to prompt (can't rely on response_format)
      expect(result).toContain("IMPORTANT: Return your final response as valid JSON");
      expect(result).toContain('"type": "object"');
      expect(result).toContain('"message"');
      expect(result).toContain('"count"');
      expect(result).toContain("Return ONLY the JSON object");
      expect(result).toContain("no markdown");
    });

    it("should not add JSON instructions in text mode", () => {
      const basePrompt = "You are a helpful assistant.";
      const schema: OutputSchema = {
        name: "Unused",
        schema: { type: "object", properties: {} },
      };

      const result = handler.formatSystemPrompt(basePrompt, null, schema, "text");

      expect(result).toBe(basePrompt);
      expect(result).not.toContain("JSON");
    });

    it("should combine tool rules and JSON schema when both provided", () => {
      const basePrompt = "You are a helpful assistant.";
      const tools: ToolSchema[] = [
        { type: "function", function: { name: "get_data" } },
      ];
      const schema: OutputSchema = {
        name: "Output",
        schema: { type: "object", properties: { result: { type: "string" } } },
      };

      const result = handler.formatSystemPrompt(basePrompt, tools, schema);

      expect(result).toContain("TOOL CALLING RULES:");
      expect(result).toContain("Return your final response as valid JSON");
    });
  });

  describe("fallback behavior", () => {
    it("should work with any vendor name", () => {
      const vendors = ["cohere", "together", "replicate", "ollama", "local"];

      for (const vendor of vendors) {
        const h = new GenericHandler(vendor);
        expect(h.vendor).toBe(vendor);

        const caps = h.getCapabilities();
        // All should have same conservative capabilities
        expect(caps.structuredOutput).toBe(false);
        expect(caps.jsonMode).toBe(false);
      }
    });

    it("should produce usable prompts for any model", () => {
      const basePrompt = "You are a coding assistant.";
      const tools: ToolSchema[] = [
        { type: "function", function: { name: "run_code", description: "Execute code" } },
      ];
      const schema: OutputSchema = {
        name: "CodeResult",
        schema: {
          type: "object",
          properties: {
            success: { type: "boolean" },
            output: { type: "string" },
          },
        },
      };

      const prompt = handler.formatSystemPrompt(basePrompt, tools, schema);

      // Prompt should be comprehensive enough for any model
      expect(prompt).toContain("You are a coding assistant.");
      expect(prompt).toContain("TOOL CALLING RULES:");
      expect(prompt).toContain("JSON");
      expect(prompt).toContain("success");
      expect(prompt).toContain("output");
    });
  });
});
