/**
 * Unit tests for claude-handler.ts
 *
 * Tests the ClaudeHandler provider for Anthropic Claude models.
 */

import { describe, it, expect, beforeEach } from "vitest";
import { ClaudeHandler } from "../provider-handlers/claude-handler.js";
import type { OutputSchema, ToolSchema } from "../provider-handlers/provider-handler.js";
import type { LlmMessage } from "../types.js";

describe("ClaudeHandler", () => {
  let handler: ClaudeHandler;

  beforeEach(() => {
    handler = new ClaudeHandler();
  });

  describe("vendor", () => {
    it("should have vendor set to 'anthropic'", () => {
      expect(handler.vendor).toBe("anthropic");
    });
  });

  describe("getCapabilities", () => {
    it("should return Claude capabilities", () => {
      const capabilities = handler.getCapabilities();

      expect(capabilities.nativeToolCalling).toBe(true);
      expect(capabilities.structuredOutput).toBe(true);
      expect(capabilities.streaming).toBe(true);
      expect(capabilities.vision).toBe(true);
      expect(capabilities.jsonMode).toBe(true);
      expect(capabilities.promptCaching).toBe(true);
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

    it("should return 'hint' for simple schemas (< 5 fields)", () => {
      const simpleSchema: OutputSchema = {
        name: "SimpleSchema",
        schema: {
          type: "object",
          properties: {
            name: { type: "string" },
            age: { type: "number" },
          },
        },
      };

      const mode = handler.determineOutputMode(simpleSchema);
      expect(mode).toBe("hint");
    });

    it("should return 'strict' for complex schemas (>= 5 fields)", () => {
      const complexSchema: OutputSchema = {
        name: "ComplexSchema",
        schema: {
          type: "object",
          properties: {
            field1: { type: "string" },
            field2: { type: "string" },
            field3: { type: "string" },
            field4: { type: "string" },
            field5: { type: "string" },
          },
        },
      };

      const mode = handler.determineOutputMode(complexSchema);
      expect(mode).toBe("strict");
    });

    it("should return 'strict' for schemas with nested objects", () => {
      const nestedSchema: OutputSchema = {
        name: "NestedSchema",
        schema: {
          type: "object",
          properties: {
            name: { type: "string" },
            address: {
              type: "object",
              properties: {
                street: { type: "string" },
                city: { type: "string" },
              },
            },
          },
        },
      };

      const mode = handler.determineOutputMode(nestedSchema);
      expect(mode).toBe("strict");
    });

    it("should return 'strict' for schemas with $defs", () => {
      const schemaWithDefs: OutputSchema = {
        name: "SchemaWithDefs",
        schema: {
          type: "object",
          properties: {
            name: { type: "string" },
          },
          $defs: {
            Address: { type: "object", properties: { city: { type: "string" } } },
          },
        },
      };

      const mode = handler.determineOutputMode(schemaWithDefs);
      expect(mode).toBe("strict");
    });

    it("should return 'strict' for schemas with $ref", () => {
      const schemaWithRef: OutputSchema = {
        name: "SchemaWithRef",
        schema: {
          type: "object",
          properties: {
            address: { $ref: "#/$defs/Address" },
          },
        },
      };

      const mode = handler.determineOutputMode(schemaWithRef);
      expect(mode).toBe("strict");
    });

    it("should use pre-computed fieldCount if available", () => {
      const schemaWithFieldCount: OutputSchema = {
        name: "SchemaWithFieldCount",
        schema: { type: "object" },
        fieldCount: 10,
      };

      const mode = handler.determineOutputMode(schemaWithFieldCount);
      expect(mode).toBe("strict");
    });

    it("should use pre-computed hasNestedObjects if available", () => {
      const schemaWithFlag: OutputSchema = {
        name: "SchemaWithFlag",
        schema: { type: "object", properties: { a: { type: "string" } } },
        fieldCount: 1,
        hasNestedObjects: false,
      };

      const mode = handler.determineOutputMode(schemaWithFlag);
      expect(mode).toBe("hint");
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
    });

    it("should apply prompt caching to system messages", () => {
      const messages: LlmMessage[] = [
        { role: "system", content: "You are a helpful assistant." },
        { role: "user", content: "Hello" },
      ];

      const request = handler.prepareRequest(messages, null, null);

      // System message should be converted to cached format
      const systemMsg = request.messages[0];
      expect(systemMsg.role).toBe("system");
      // Content should be an array with cache_control
      expect(Array.isArray(systemMsg.content)).toBe(true);
      const content = systemMsg.content as unknown as Array<{ type: string; text: string; cache_control: { type: string } }>;
      expect(content[0].type).toBe("text");
      expect(content[0].cache_control.type).toBe("ephemeral");
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

    it("should include response_format in strict mode with schema", () => {
      const messages: LlmMessage[] = [{ role: "user", content: "Hello" }];
      const outputSchema: OutputSchema = {
        name: "Response",
        schema: {
          type: "object",
          properties: {
            field1: { type: "string" },
            field2: { type: "string" },
            field3: { type: "string" },
            field4: { type: "string" },
            field5: { type: "string" },
          },
        },
      };

      const request = handler.prepareRequest(messages, null, outputSchema);

      expect(request.responseFormat).toBeDefined();
      expect(request.responseFormat?.type).toBe("json_schema");
      expect(request.responseFormat?.jsonSchema.name).toBe("Response");
    });

    it("should not include response_format in hint mode", () => {
      const messages: LlmMessage[] = [{ role: "user", content: "Hello" }];
      const simpleSchema: OutputSchema = {
        name: "Simple",
        schema: {
          type: "object",
          properties: { name: { type: "string" } },
        },
      };

      const request = handler.prepareRequest(messages, null, simpleSchema);

      // Simple schema uses hint mode, no response_format
      expect(request.responseFormat).toBeUndefined();
    });

    it("should not include response_format in text mode", () => {
      const messages: LlmMessage[] = [{ role: "user", content: "Hello" }];

      const request = handler.prepareRequest(messages, null, null, { outputMode: "text" });

      expect(request.responseFormat).toBeUndefined();
    });

    it("should add additionalProperties:false to schema in strict mode", () => {
      const messages: LlmMessage[] = [{ role: "user", content: "Hello" }];
      const outputSchema: OutputSchema = {
        name: "Test",
        schema: {
          type: "object",
          properties: {
            field1: { type: "string" },
            field2: { type: "string" },
            field3: { type: "string" },
            field4: { type: "string" },
            field5: { type: "string" },
          },
        },
      };

      const request = handler.prepareRequest(messages, null, outputSchema);

      expect(request.responseFormat?.jsonSchema.schema.additionalProperties).toBe(false);
    });

    it("should pass through temperature, maxTokens, and topP", () => {
      const messages: LlmMessage[] = [{ role: "user", content: "Hello" }];

      const request = handler.prepareRequest(messages, null, null, {
        temperature: 0.7,
        maxTokens: 1000,
        topP: 0.9,
      });

      expect(request.temperature).toBe(0.7);
      expect(request.maxTokens).toBe(1000);
      expect(request.topP).toBe(0.9);
    });

    it("should convert assistant tool_calls to Vercel format", () => {
      const messages: LlmMessage[] = [
        { role: "user", content: "What's the weather?" },
        {
          role: "assistant",
          content: "",
          tool_calls: [
            {
              id: "call_123",
              type: "function",
              function: { name: "get_weather", arguments: '{"city":"NYC"}' },
            },
          ],
        },
      ];

      const request = handler.prepareRequest(messages, null, null);

      const assistantMsg = request.messages[1];
      expect(Array.isArray(assistantMsg.content)).toBe(true);
      const content = assistantMsg.content as unknown as Array<{ type: string; toolCallId?: string; toolName?: string; args?: unknown }>;
      expect(content[0].type).toBe("tool-call");
      expect(content[0].toolCallId).toBe("call_123");
      expect(content[0].toolName).toBe("get_weather");
      expect(content[0].args).toEqual({ city: "NYC" });
    });

    it("should convert tool result messages to Vercel format", () => {
      const messages: LlmMessage[] = [
        {
          role: "tool",
          content: "Sunny, 75°F",
          tool_call_id: "call_123",
          name: "get_weather",
        } as LlmMessage,
      ];

      const request = handler.prepareRequest(messages, null, null);

      const toolMsg = request.messages[0];
      expect(toolMsg.role).toBe("tool");
      expect(Array.isArray(toolMsg.content)).toBe(true);
      const content = toolMsg.content as unknown as Array<{ type: string; toolCallId: string; toolName: string; result: string }>;
      expect(content[0].type).toBe("tool-result");
      expect(content[0].toolCallId).toBe("call_123");
      expect(content[0].toolName).toBe("get_weather");
      expect(content[0].result).toBe("Sunny, 75°F");
    });

    it("should handle malformed tool_call arguments gracefully", () => {
      const messages: LlmMessage[] = [
        {
          role: "assistant",
          content: "",
          tool_calls: [
            {
              id: "call_456",
              type: "function",
              function: { name: "test_tool", arguments: "invalid json{" },
            },
          ],
        },
      ];

      // Should not throw
      const request = handler.prepareRequest(messages, null, null);

      const assistantMsg = request.messages[0];
      const content = assistantMsg.content as unknown as Array<{ args: unknown }>;
      // Should fallback to empty object
      expect(content[0].args).toEqual({});
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
      expect(result).toContain("NEVER use XML-style syntax");
    });

    it("should add brief JSON note in strict mode", () => {
      const basePrompt = "You are a helpful assistant.";
      const complexSchema: OutputSchema = {
        name: "ComplexOutput",
        schema: {
          type: "object",
          properties: {
            a: { type: "string" },
            b: { type: "string" },
            c: { type: "string" },
            d: { type: "string" },
            e: { type: "string" },
          },
        },
      };

      const result = handler.formatSystemPrompt(basePrompt, null, complexSchema);

      expect(result).toContain("ComplexOutput format");
      // Should NOT contain detailed schema (that's handled by response_format)
      expect(result).not.toContain("RESPONSE FORMAT:");
    });

    it("should add detailed JSON schema in hint mode", () => {
      const basePrompt = "You are a helpful assistant.";
      const simpleSchema: OutputSchema = {
        name: "SimpleOutput",
        schema: {
          type: "object",
          properties: {
            name: { type: "string", description: "The name" },
            age: { type: "number" },
          },
          required: ["name"],
        },
      };

      const result = handler.formatSystemPrompt(basePrompt, null, simpleSchema);

      expect(result).toContain("RESPONSE FORMAT:");
      expect(result).toContain("name: string (required)");
      expect(result).toContain("age: number (optional)");
      expect(result).toContain("Respond ONLY with valid JSON");
    });

    it("should not add JSON instructions in text mode", () => {
      const basePrompt = "You are a helpful assistant.";

      const result = handler.formatSystemPrompt(basePrompt, null, null, "text");

      expect(result).toBe(basePrompt);
      expect(result).not.toContain("JSON");
    });
  });

  describe("schema strictness (makeSchemaStrict)", () => {
    it("should add additionalProperties:false to nested objects", () => {
      const messages: LlmMessage[] = [{ role: "user", content: "Hello" }];
      const nestedSchema: OutputSchema = {
        name: "Nested",
        schema: {
          type: "object",
          properties: {
            user: {
              type: "object",
              properties: {
                name: { type: "string" },
              },
            },
            a: { type: "string" },
            b: { type: "string" },
            c: { type: "string" },
            d: { type: "string" },
          },
        },
      };

      const request = handler.prepareRequest(messages, null, nestedSchema);

      const schema = request.responseFormat?.jsonSchema.schema as Record<string, unknown>;
      expect(schema.additionalProperties).toBe(false);

      const properties = schema.properties as Record<string, Record<string, unknown>>;
      expect(properties.user.additionalProperties).toBe(false);
    });

    it("should add additionalProperties:false to $defs", () => {
      const messages: LlmMessage[] = [{ role: "user", content: "Hello" }];
      const schemaWithDefs: OutputSchema = {
        name: "WithDefs",
        schema: {
          type: "object",
          properties: {
            a: { type: "string" },
            b: { type: "string" },
            c: { type: "string" },
            d: { type: "string" },
            e: { type: "string" },
          },
          $defs: {
            Address: {
              type: "object",
              properties: { city: { type: "string" } },
            },
          },
        },
      };

      const request = handler.prepareRequest(messages, null, schemaWithDefs);

      const schema = request.responseFormat?.jsonSchema.schema as Record<string, unknown>;
      const defs = schema.$defs as Record<string, Record<string, unknown>>;
      expect(defs.Address.additionalProperties).toBe(false);
    });

    it("should add additionalProperties:false to array items", () => {
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
            a: { type: "string" },
            b: { type: "string" },
            c: { type: "string" },
            d: { type: "string" },
          },
        },
      };

      const request = handler.prepareRequest(messages, null, arraySchema);

      const schema = request.responseFormat?.jsonSchema.schema as Record<string, unknown>;
      const properties = schema.properties as Record<string, Record<string, unknown>>;
      const items = properties.items.items as Record<string, unknown>;
      expect(items.additionalProperties).toBe(false);
    });
  });
});
