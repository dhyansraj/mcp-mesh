/**
 * Unit tests for openai-handler.ts
 *
 * Tests the OpenAIHandler provider for OpenAI models (GPT-4, etc.).
 */

import { describe, it, expect, beforeEach } from "vitest";
import { OpenAIHandler } from "../provider-handlers/openai-handler.js";
import type { OutputSchema, ToolSchema } from "../provider-handlers/provider-handler.js";
import type { LlmMessage } from "../types.js";

describe("OpenAIHandler", () => {
  let handler: OpenAIHandler;

  beforeEach(() => {
    handler = new OpenAIHandler();
  });

  describe("vendor", () => {
    it("should have vendor set to 'openai'", () => {
      expect(handler.vendor).toBe("openai");
    });
  });

  describe("getCapabilities", () => {
    it("should return OpenAI capabilities", () => {
      const capabilities = handler.getCapabilities();

      expect(capabilities.nativeToolCalling).toBe(true);
      expect(capabilities.structuredOutput).toBe(true);
      expect(capabilities.streaming).toBe(true);
      expect(capabilities.vision).toBe(true);
      expect(capabilities.jsonMode).toBe(true);
      // OpenAI doesn't have promptCaching
      expect(capabilities.promptCaching).toBeUndefined();
    });
  });

  describe("determineOutputMode", () => {
    it("should return 'text' when no schema provided", () => {
      const mode = handler.determineOutputMode(null);
      expect(mode).toBe("text");
    });

    it("should return override mode when specified", () => {
      const schema: OutputSchema = {
        name: "TestSchema",
        schema: { type: "object", properties: { a: { type: "string" } } },
      };

      expect(handler.determineOutputMode(schema, "hint")).toBe("hint");
      expect(handler.determineOutputMode(schema, "strict")).toBe("strict");
      expect(handler.determineOutputMode(schema, "text")).toBe("text");
    });

    it("should always return 'strict' for schemas (unlike Claude)", () => {
      // OpenAI has excellent structured output, so always use strict
      const simpleSchema: OutputSchema = {
        name: "Simple",
        schema: { type: "object", properties: { name: { type: "string" } } },
      };

      const mode = handler.determineOutputMode(simpleSchema);
      expect(mode).toBe("strict");
    });
  });

  describe("prepareRequest", () => {
    it("should convert messages to Vercel format", () => {
      const messages: LlmMessage[] = [
        { role: "system", content: "You are helpful." },
        { role: "user", content: "Hello" },
        { role: "assistant", content: "Hi there!" },
      ];

      const request = handler.prepareRequest(messages, null, null);

      expect(request.messages).toHaveLength(3);
      expect(request.messages[0].role).toBe("system");
      expect(request.messages[0].content).toBe("You are helpful.");
    });

    it("should NOT apply prompt caching (unlike Claude)", () => {
      const messages: LlmMessage[] = [
        { role: "system", content: "You are a helpful assistant." },
      ];

      const request = handler.prepareRequest(messages, null, null);

      // System message should remain as plain string (no cache_control)
      expect(request.messages[0].content).toBe("You are a helpful assistant.");
    });

    it("should include tools when provided", () => {
      const messages: LlmMessage[] = [{ role: "user", content: "Hello" }];
      const tools: ToolSchema[] = [
        {
          type: "function",
          function: { name: "get_weather", description: "Get weather info" },
        },
      ];

      const request = handler.prepareRequest(messages, tools, null);

      expect(request.tools).toEqual(tools);
    });

    it("should include response_format for any schema (always strict)", () => {
      const messages: LlmMessage[] = [{ role: "user", content: "Hello" }];
      const simpleSchema: OutputSchema = {
        name: "Simple",
        schema: { type: "object", properties: { name: { type: "string" } } },
      };

      const request = handler.prepareRequest(messages, null, simpleSchema);

      // OpenAI always uses response_format for schemas
      expect(request.responseFormat).toBeDefined();
      expect(request.responseFormat?.type).toBe("json_schema");
      expect(request.responseFormat?.jsonSchema.name).toBe("Simple");
      expect(request.responseFormat?.jsonSchema.strict).toBe(true);
    });

    it("should NOT include response_format in text mode", () => {
      const messages: LlmMessage[] = [{ role: "user", content: "Hello" }];

      const request = handler.prepareRequest(messages, null, null, { outputMode: "text" });

      expect(request.responseFormat).toBeUndefined();
    });

    it("should NOT include response_format when no schema", () => {
      const messages: LlmMessage[] = [{ role: "user", content: "Hello" }];

      const request = handler.prepareRequest(messages, null, null);

      expect(request.responseFormat).toBeUndefined();
    });

    it("should pass through temperature, maxTokens, and topP", () => {
      const messages: LlmMessage[] = [{ role: "user", content: "Hello" }];

      const request = handler.prepareRequest(messages, null, null, {
        temperature: 0.5,
        maxTokens: 2000,
        topP: 0.95,
      });

      expect(request.temperature).toBe(0.5);
      expect(request.maxTokens).toBe(2000);
      expect(request.topP).toBe(0.95);
    });

    it("should convert assistant tool_calls to Vercel format", () => {
      const messages: LlmMessage[] = [
        {
          role: "assistant",
          content: "Let me check the weather.",
          tool_calls: [
            {
              id: "call_abc",
              type: "function",
              function: { name: "get_weather", arguments: '{"location":"London"}' },
            },
          ],
        },
      ];

      const request = handler.prepareRequest(messages, null, null);

      const assistantMsg = request.messages[0];
      expect(Array.isArray(assistantMsg.content)).toBe(true);
      const content = assistantMsg.content as unknown as Array<{ type: string; text?: string; toolCallId?: string }>;

      // Should have text part and tool-call part
      expect(content[0].type).toBe("text");
      expect(content[0].text).toBe("Let me check the weather.");
      expect(content[1].type).toBe("tool-call");
      expect(content[1].toolCallId).toBe("call_abc");
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

      expect(result).toContain("IMPORTANT TOOL CALLING RULES:");
      expect(result).toContain("Make ONE tool call at a time");
      // OpenAI doesn't need anti-XML instructions
      expect(result).not.toContain("XML");
    });

    it("should add brief JSON note when schema provided", () => {
      const basePrompt = "You are a helpful assistant.";
      const schema: OutputSchema = {
        name: "TestOutput",
        schema: { type: "object", properties: { value: { type: "string" } } },
      };

      const result = handler.formatSystemPrompt(basePrompt, null, schema);

      expect(result).toContain("TestOutput format");
    });

    it("should NOT add detailed JSON schema (response_format handles this)", () => {
      const basePrompt = "You are a helpful assistant.";
      const schema: OutputSchema = {
        name: "Response",
        schema: {
          type: "object",
          properties: { data: { type: "string" } },
        },
      };

      const result = handler.formatSystemPrompt(basePrompt, null, schema);

      // OpenAI relies on response_format, not prompt-based JSON instructions
      expect(result).not.toContain("RESPONSE FORMAT:");
      expect(result).not.toContain('"type": "object"');
    });

    it("should not add JSON note in text mode", () => {
      const basePrompt = "You are a helpful assistant.";

      const result = handler.formatSystemPrompt(basePrompt, null, null, "text");

      expect(result).toBe(basePrompt);
    });
  });

  describe("schema strictness (addAdditionalPropertiesFalse)", () => {
    it("should add additionalProperties:false to root object", () => {
      const messages: LlmMessage[] = [{ role: "user", content: "Hello" }];
      const schema: OutputSchema = {
        name: "Test",
        schema: {
          type: "object",
          properties: { name: { type: "string" } },
        },
      };

      const request = handler.prepareRequest(messages, null, schema);

      const resultSchema = request.responseFormat?.jsonSchema.schema as Record<string, unknown>;
      expect(resultSchema.additionalProperties).toBe(false);
    });

    it("should make all properties required for OpenAI strict mode", () => {
      const messages: LlmMessage[] = [{ role: "user", content: "Hello" }];
      const schema: OutputSchema = {
        name: "Test",
        schema: {
          type: "object",
          properties: {
            name: { type: "string" },
            age: { type: "number" },
            active: { type: "boolean" },
          },
        },
      };

      const request = handler.prepareRequest(messages, null, schema);

      const resultSchema = request.responseFormat?.jsonSchema.schema as Record<string, unknown>;
      expect(resultSchema.required).toEqual(["name", "age", "active"]);
    });

    it("should add additionalProperties:false to nested objects", () => {
      const messages: LlmMessage[] = [{ role: "user", content: "Hello" }];
      const nestedSchema: OutputSchema = {
        name: "Nested",
        schema: {
          type: "object",
          properties: {
            user: {
              type: "object",
              properties: { name: { type: "string" } },
            },
          },
        },
      };

      const request = handler.prepareRequest(messages, null, nestedSchema);

      const schema = request.responseFormat?.jsonSchema.schema as Record<string, unknown>;
      const properties = schema.properties as Record<string, Record<string, unknown>>;
      expect(properties.user.additionalProperties).toBe(false);
      expect(properties.user.required).toEqual(["name"]);
    });

    it("should process $defs for nested models", () => {
      const messages: LlmMessage[] = [{ role: "user", content: "Hello" }];
      const schemaWithDefs: OutputSchema = {
        name: "WithDefs",
        schema: {
          type: "object",
          properties: {
            data: { $ref: "#/$defs/Data" },
          },
          $defs: {
            Data: {
              type: "object",
              properties: { value: { type: "string" } },
            },
          },
        },
      };

      const request = handler.prepareRequest(messages, null, schemaWithDefs);

      const schema = request.responseFormat?.jsonSchema.schema as Record<string, unknown>;
      const defs = schema.$defs as Record<string, Record<string, unknown>>;
      expect(defs.Data.additionalProperties).toBe(false);
      expect(defs.Data.required).toEqual(["value"]);
    });

    it("should process array items", () => {
      const messages: LlmMessage[] = [{ role: "user", content: "Hello" }];
      const arraySchema: OutputSchema = {
        name: "ArraySchema",
        schema: {
          type: "object",
          properties: {
            items: {
              type: "array",
              items: {
                type: "object",
                properties: { id: { type: "number" } },
              },
            },
          },
        },
      };

      const request = handler.prepareRequest(messages, null, arraySchema);

      const schema = request.responseFormat?.jsonSchema.schema as Record<string, unknown>;
      const properties = schema.properties as Record<string, Record<string, unknown>>;
      const items = properties.items.items as Record<string, unknown>;
      expect(items.additionalProperties).toBe(false);
      expect(items.required).toEqual(["id"]);
    });

    it("should process anyOf, oneOf, allOf schemas", () => {
      const messages: LlmMessage[] = [{ role: "user", content: "Hello" }];
      const unionSchema: OutputSchema = {
        name: "Union",
        schema: {
          type: "object",
          properties: {
            value: {
              anyOf: [
                { type: "object", properties: { str: { type: "string" } } },
                { type: "object", properties: { num: { type: "number" } } },
              ],
            },
          },
        },
      };

      const request = handler.prepareRequest(messages, null, unionSchema);

      const schema = request.responseFormat?.jsonSchema.schema as Record<string, unknown>;
      const properties = schema.properties as Record<string, Record<string, unknown>>;
      const anyOf = properties.value.anyOf as Array<Record<string, unknown>>;

      expect(anyOf[0].additionalProperties).toBe(false);
      expect(anyOf[1].additionalProperties).toBe(false);
    });
  });
});
