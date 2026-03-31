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
      expect(capabilities.structuredOutput).toBe(true); // Native response_format in mesh delegation
      expect(capabilities.streaming).toBe(true);
      expect(capabilities.vision).toBe(true);
      expect(capabilities.jsonMode).toBe(false); // No native JSON mode used
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

    it("should return 'strict' for schemas (native response_format)", () => {
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
      expect(mode).toBe("strict");
    });

    it("should return 'strict' for complex schemas", () => {
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

    it("should return 'strict' regardless of pre-computed fieldCount", () => {
      const schemaWithFieldCount: OutputSchema = {
        name: "SchemaWithFieldCount",
        schema: { type: "object" },
        fieldCount: 10,
      };

      const mode = handler.determineOutputMode(schemaWithFieldCount);
      expect(mode).toBe("strict");
    });

    it("should return 'strict' regardless of pre-computed hasNestedObjects", () => {
      const schemaWithFlag: OutputSchema = {
        name: "SchemaWithFlag",
        schema: { type: "object", properties: { a: { type: "string" } } },
        fieldCount: 1,
        hasNestedObjects: false,
      };

      const mode = handler.determineOutputMode(schemaWithFlag);
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

    it("should set responseFormat with strict schema by default for schemas", () => {
      const messages: LlmMessage[] = [{ role: "user", content: "Hello" }];
      const outputSchema: OutputSchema = {
        name: "Response",
        schema: {
          type: "object",
          properties: {
            field1: { type: "string" },
            field2: { type: "string" },
          },
        },
      };

      // Default mode is strict, so responseFormat should be set
      const request = handler.prepareRequest(messages, null, outputSchema);

      expect(request.responseFormat).toBeDefined();
      expect(request.responseFormat?.type).toBe("json_schema");
      expect(request.responseFormat?.jsonSchema.name).toBe("Response");
      expect(request.responseFormat?.jsonSchema.strict).toBe(true);
    });

    it("should set responseFormat with strict schema when outputMode: strict is explicitly set", () => {
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

      const request = handler.prepareRequest(messages, null, outputSchema, { outputMode: "strict" });

      expect(request.responseFormat).toBeDefined();
      expect(request.responseFormat?.type).toBe("json_schema");
      expect(request.responseFormat?.jsonSchema.name).toBe("Response");
      expect(request.responseFormat?.jsonSchema.strict).toBe(true);
      // Strict schema should have additionalProperties: false and all required
      expect(request.responseFormat?.jsonSchema.schema.additionalProperties).toBe(false);
      expect(request.responseFormat?.jsonSchema.schema.required).toEqual(["field1"]);
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

      // Explicitly force hint mode
      const request = handler.prepareRequest(messages, null, simpleSchema, { outputMode: "hint" });

      expect(request.responseFormat).toBeUndefined();
    });

    it("should not include response_format in text mode", () => {
      const messages: LlmMessage[] = [{ role: "user", content: "Hello" }];

      const request = handler.prepareRequest(messages, null, null, { outputMode: "text" });

      expect(request.responseFormat).toBeUndefined();
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
          content: "Sunny, 75\u00b0F",
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
      expect(content[0].output.value).toBe("Sunny, 75\u00b0F");
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

    it("should add brief JSON note in strict mode (default for schemas)", () => {
      const basePrompt = "You are a helpful assistant.";
      const schema: OutputSchema = {
        name: "ComplexOutput",
        schema: {
          type: "object",
          properties: {
            a: { type: "string" },
            b: { type: "string" },
          },
        },
      };

      // Default mode is strict, so brief note should be added
      const result = handler.formatSystemPrompt(basePrompt, null, schema);

      expect(result).toContain("structured as JSON matching the ComplexOutput format");
      expect(result).not.toContain("RESPONSE FORMAT:");
      expect(result).not.toContain("CRITICAL:");
    });

    it("should add brief JSON note in explicit strict mode", () => {
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

      const result = handler.formatSystemPrompt(basePrompt, null, schema, "strict");

      expect(result).toContain("structured as JSON matching the StrictOutput format");
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

      const result = handler.formatSystemPrompt(basePrompt, null, simpleSchema, "hint");

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

    it("should add DECISION GUIDE in hint mode with tools", () => {
      const basePrompt = "You are a helpful assistant.";
      const tools: ToolSchema[] = [
        { type: "function", function: { name: "get_weather" } },
      ];
      const schema: OutputSchema = {
        name: "Output",
        schema: {
          type: "object",
          properties: { result: { type: "string" } },
        },
      };

      const result = handler.formatSystemPrompt(basePrompt, tools, schema, "hint");

      expect(result).toContain("DECISION GUIDE:");
      expect(result).toContain("RESPONSE FORMAT:");
    });

    it("should add brief JSON note in strict mode with tools (no DECISION GUIDE)", () => {
      const basePrompt = "You are a helpful assistant.";
      const tools: ToolSchema[] = [
        { type: "function", function: { name: "get_weather" } },
      ];
      const schema: OutputSchema = {
        name: "Output",
        schema: {
          type: "object",
          properties: { result: { type: "string" } },
        },
      };

      const result = handler.formatSystemPrompt(basePrompt, tools, schema, "strict");

      // Rust core does not add DECISION GUIDE in strict mode
      expect(result).toContain("structured as JSON matching the Output format");
    });

    it("should NOT add DECISION GUIDE in strict mode without tools", () => {
      const basePrompt = "You are a helpful assistant.";
      const schema: OutputSchema = {
        name: "Output",
        schema: {
          type: "object",
          properties: { result: { type: "string" } },
        },
      };

      const result = handler.formatSystemPrompt(basePrompt, null, schema, "strict");

      expect(result).not.toContain("DECISION GUIDE:");
      expect(result).toContain("structured as JSON matching the Output format");
    });
  });

  describe("schema strictness in prepareRequest", () => {
    it("should apply makeSchemaStrict with additionalProperties and required in strict mode", () => {
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

      const request = handler.prepareRequest(messages, null, nestedSchema, { outputMode: "strict" });

      expect(request.responseFormat).toBeDefined();
      expect(request.responseFormat?.jsonSchema.schema.additionalProperties).toBe(false);
      // Rust core sorts property keys alphabetically
      const requiredArr = request.responseFormat?.jsonSchema.schema.required as string[];
      expect(requiredArr.sort()).toEqual(["a", "user"]);
      // Nested objects should also have strict constraints
      const userSchema = (request.responseFormat?.jsonSchema.schema.properties as Record<string, Record<string, unknown>>)?.user;
      expect(userSchema?.additionalProperties).toBe(false);
      expect(userSchema?.required).toEqual(["name"]);
    });

    it("should sanitize validation keywords from schema", () => {
      const messages: LlmMessage[] = [{ role: "user", content: "Hello" }];
      const schemaWithValidation: OutputSchema = {
        name: "Validated",
        schema: {
          type: "object",
          properties: {
            age: { type: "number", minimum: 0, maximum: 150 },
            name: { type: "string", minLength: 1, maxLength: 100 },
          },
        },
      };

      const request = handler.prepareRequest(messages, null, schemaWithValidation);

      expect(request.responseFormat).toBeDefined();
      // Validation keywords should be stripped
      const props = request.responseFormat?.jsonSchema.schema.properties as Record<string, Record<string, unknown>>;
      expect(props.age.minimum).toBeUndefined();
      expect(props.age.maximum).toBeUndefined();
      expect(props.name.minLength).toBeUndefined();
      expect(props.name.maxLength).toBeUndefined();
    });
  });
});
