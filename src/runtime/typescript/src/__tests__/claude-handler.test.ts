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
      expect(capabilities.promptCaching).toBe(false); // Disabled for AI SDK v6
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

    it("should always return 'hint' for any schema (Claude strategy)", () => {
      // Claude always uses "hint" mode because generateObject() has issues with Anthropic
      // and native structured output is slow. Prompt-based JSON is fast and reliable.
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

    it("should return 'hint' for complex schemas (Claude always uses hint)", () => {
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

      // Claude always uses hint mode regardless of complexity
      const mode = handler.determineOutputMode(complexSchema);
      expect(mode).toBe("hint");
    });

    it("should return 'hint' for schemas with nested objects (Claude always uses hint)", () => {
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

      // Claude always uses hint mode regardless of nesting
      const mode = handler.determineOutputMode(nestedSchema);
      expect(mode).toBe("hint");
    });

    it("should return 'hint' for schemas with $defs (Claude always uses hint)", () => {
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

      // Claude always uses hint mode regardless of $defs
      const mode = handler.determineOutputMode(schemaWithDefs);
      expect(mode).toBe("hint");
    });

    it("should return 'hint' for schemas with $ref (Claude always uses hint)", () => {
      const schemaWithRef: OutputSchema = {
        name: "SchemaWithRef",
        schema: {
          type: "object",
          properties: {
            address: { $ref: "#/$defs/Address" },
          },
        },
      };

      // Claude always uses hint mode regardless of $ref
      const mode = handler.determineOutputMode(schemaWithRef);
      expect(mode).toBe("hint");
    });

    it("should return 'hint' regardless of pre-computed fieldCount", () => {
      const schemaWithFieldCount: OutputSchema = {
        name: "SchemaWithFieldCount",
        schema: { type: "object" },
        fieldCount: 10,
      };

      // Claude always uses hint mode regardless of field count
      const mode = handler.determineOutputMode(schemaWithFieldCount);
      expect(mode).toBe("hint");
    });

    it("should return 'hint' regardless of pre-computed hasNestedObjects", () => {
      const schemaWithFlag: OutputSchema = {
        name: "SchemaWithFlag",
        schema: { type: "object", properties: { a: { type: "string" } } },
        fieldCount: 1,
        hasNestedObjects: false,
      };

      // Claude always uses hint mode regardless of flags
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

    it("should keep system messages as strings (prompt caching disabled for AI SDK v6)", () => {
      const messages: LlmMessage[] = [
        { role: "system", content: "You are a helpful assistant." },
        { role: "user", content: "Hello" },
      ];

      const request = handler.prepareRequest(messages, null, null);

      // System message should remain as string content (AI SDK v6 requires string, not array)
      // Prompt caching is disabled to maintain compatibility with AI SDK v6
      const systemMsg = request.messages[0];
      expect(systemMsg.role).toBe("system");
      expect(typeof systemMsg.content).toBe("string");
      expect(systemMsg.content).toBe("You are a helpful assistant.");
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

    it("should not include response_format by default (Claude uses hint mode)", () => {
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

      // Claude always uses hint mode by default, so no responseFormat
      const request = handler.prepareRequest(messages, null, outputSchema);

      expect(request.responseFormat).toBeUndefined();
    });

    it("should include response_format when outputMode: strict is explicitly set", () => {
      const messages: LlmMessage[] = [{ role: "user", content: "Hello" }];
      const outputSchema: OutputSchema = {
        name: "Response",
        schema: {
          type: "object",
          properties: {
            field1: { type: "string" },
          },
        },
      };

      // Explicitly set strict mode to get responseFormat
      const request = handler.prepareRequest(messages, null, outputSchema, { outputMode: "strict" });

      expect(request.responseFormat).toBeDefined();
      expect(request.responseFormat?.type).toBe("json_schema");
      expect(request.responseFormat?.jsonSchema.name).toBe("Response");
    });

    it("should not include response_format in hint mode (any schema)", () => {
      const messages: LlmMessage[] = [{ role: "user", content: "Hello" }];
      const simpleSchema: OutputSchema = {
        name: "Simple",
        schema: {
          type: "object",
          properties: { name: { type: "string" } },
        },
      };

      const request = handler.prepareRequest(messages, null, simpleSchema);

      // Claude always uses hint mode, no response_format
      expect(request.responseFormat).toBeUndefined();
    });

    it("should not include response_format in text mode", () => {
      const messages: LlmMessage[] = [{ role: "user", content: "Hello" }];

      const request = handler.prepareRequest(messages, null, null, { outputMode: "text" });

      expect(request.responseFormat).toBeUndefined();
    });

    it("should add additionalProperties:false to schema when explicit strict mode is set", () => {
      const messages: LlmMessage[] = [{ role: "user", content: "Hello" }];
      const outputSchema: OutputSchema = {
        name: "Test",
        schema: {
          type: "object",
          properties: {
            field1: { type: "string" },
          },
        },
      };

      // Must explicitly use strict mode for Claude to include responseFormat
      const request = handler.prepareRequest(messages, null, outputSchema, { outputMode: "strict" });

      expect(request.responseFormat?.jsonSchema.schema.additionalProperties).toBe(false);
    });

    it("should pass through temperature, maxOutputTokens, and topP", () => {
      const messages: LlmMessage[] = [{ role: "user", content: "Hello" }];

      const request = handler.prepareRequest(messages, null, null, {
        temperature: 0.7,
        maxOutputTokens: 1000,
        topP: 0.9,
      });

      expect(request.temperature).toBe(0.7);
      expect(request.maxOutputTokens).toBe(1000);
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
      const content = assistantMsg.content as unknown as Array<{ type: string; toolCallId?: string; toolName?: string; input?: unknown }>;
      expect(content[0].type).toBe("tool-call");
      expect(content[0].toolCallId).toBe("call_123");
      expect(content[0].toolName).toBe("get_weather");
      expect(content[0].input).toEqual({ city: "NYC" });
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
      const content = toolMsg.content as unknown as Array<{ type: string; toolCallId: string; toolName: string; output: { type: string; value: unknown } }>;
      expect(content[0].type).toBe("tool-result");
      expect(content[0].toolCallId).toBe("call_123");
      expect(content[0].toolName).toBe("get_weather");
      // AI SDK v6 expects output as { type: 'text' | 'json', value: ... }
      expect(content[0].output.type).toBe("text");
      expect(content[0].output.value).toBe("Sunny, 75°F");
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
      const content = assistantMsg.content as unknown as Array<{ input: unknown }>;
      // Should fallback to empty object (AI SDK v6 uses 'input' instead of 'args')
      expect(content[0].input).toEqual({});
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

    it("should add detailed JSON schema for any schema (Claude uses hint mode by default)", () => {
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

      // Claude always uses hint mode, so detailed JSON instructions are added
      const result = handler.formatSystemPrompt(basePrompt, null, complexSchema);

      expect(result).toContain("RESPONSE FORMAT:");
      expect(result).toContain("CRITICAL: Your response must be ONLY the raw JSON object");
    });

    it("should add brief JSON note when explicit strict mode is set", () => {
      const basePrompt = "You are a helpful assistant.";
      const schema: OutputSchema = {
        name: "StrictOutput",
        schema: {
          type: "object",
          properties: {
            a: { type: "string" },
          },
        },
      };

      // Only with explicit "strict" mode override
      const result = handler.formatSystemPrompt(basePrompt, null, schema, "strict");

      expect(result).toContain("StrictOutput format");
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
      expect(result).toContain("CRITICAL: Your response must be ONLY the raw JSON object");
    });

    it("should not add JSON instructions in text mode", () => {
      const basePrompt = "You are a helpful assistant.";

      const result = handler.formatSystemPrompt(basePrompt, null, null, "text");

      expect(result).toBe(basePrompt);
      expect(result).not.toContain("JSON");
    });
  });

  describe("schema strictness (makeSchemaStrict) - only in explicit strict mode", () => {
    // These tests verify that when outputMode: "strict" is explicitly set,
    // the schema is properly modified with additionalProperties: false
    it("should add additionalProperties:false to nested objects in strict mode", () => {
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
          },
        },
      };

      // Must explicitly use strict mode for Claude to include responseFormat
      const request = handler.prepareRequest(messages, null, nestedSchema, { outputMode: "strict" });

      const schema = request.responseFormat?.jsonSchema.schema as Record<string, unknown>;
      expect(schema.additionalProperties).toBe(false);

      const properties = schema.properties as Record<string, Record<string, unknown>>;
      expect(properties.user.additionalProperties).toBe(false);
    });

    it("should add additionalProperties:false to $defs in strict mode", () => {
      const messages: LlmMessage[] = [{ role: "user", content: "Hello" }];
      const schemaWithDefs: OutputSchema = {
        name: "WithDefs",
        schema: {
          type: "object",
          properties: {
            a: { type: "string" },
          },
          $defs: {
            Address: {
              type: "object",
              properties: { city: { type: "string" } },
            },
          },
        },
      };

      // Must explicitly use strict mode for Claude to include responseFormat
      const request = handler.prepareRequest(messages, null, schemaWithDefs, { outputMode: "strict" });

      const schema = request.responseFormat?.jsonSchema.schema as Record<string, unknown>;
      const defs = schema.$defs as Record<string, Record<string, unknown>>;
      expect(defs.Address.additionalProperties).toBe(false);
    });

    it("should add additionalProperties:false to array items in strict mode", () => {
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
          },
        },
      };

      // Must explicitly use strict mode for Claude to include responseFormat
      const request = handler.prepareRequest(messages, null, arraySchema, { outputMode: "strict" });

      const schema = request.responseFormat?.jsonSchema.schema as Record<string, unknown>;
      const properties = schema.properties as Record<string, Record<string, unknown>>;
      const items = properties.items.items as Record<string, unknown>;
      expect(items.additionalProperties).toBe(false);
    });
  });
});
