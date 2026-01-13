/**
 * Unit tests for response-parser.ts
 *
 * Tests JSON extraction and Zod schema validation from LLM responses.
 */

import { describe, it, expect } from "vitest";
import { z } from "zod";
import {
  extractJson,
  ResponseParser,
  createResponseParser,
  zodSchemaToPromptDescription,
  formatZodError,
  ResponseParseError,
} from "../response-parser.js";

describe("extractJson", () => {
  describe("markdown code blocks", () => {
    it("should extract JSON from ```json code block", () => {
      const content = `Here's the result:
\`\`\`json
{"name": "test", "value": 42}
\`\`\`
That's all.`;

      const result = extractJson(content);
      expect(result).toBe('{"name": "test", "value": 42}');
    });

    it("should extract JSON from plain ``` code block", () => {
      const content = `\`\`\`
{"items": [1, 2, 3]}
\`\`\``;

      const result = extractJson(content);
      expect(result).toBe('{"items": [1, 2, 3]}');
    });

    it("should handle multiline JSON in code block", () => {
      const content = `\`\`\`json
{
  "name": "test",
  "nested": {
    "value": 123
  }
}
\`\`\``;

      const result = extractJson(content);
      expect(result).toBeTruthy();
      expect(JSON.parse(result!)).toEqual({
        name: "test",
        nested: { value: 123 },
      });
    });
  });

  describe("raw JSON extraction", () => {
    it("should extract JSON object without code block", () => {
      const content = 'The answer is {"result": true}';

      const result = extractJson(content);
      expect(result).toBe('{"result": true}');
    });

    it("should extract JSON array without code block", () => {
      const content = "Here are the items: [1, 2, 3, 4, 5]";

      const result = extractJson(content);
      expect(result).toBe("[1, 2, 3, 4, 5]");
    });

    it("should extract JSON with nested braces", () => {
      const content = 'Result: {"outer": {"inner": {"deep": 1}}}';

      const result = extractJson(content);
      expect(result).toBe('{"outer": {"inner": {"deep": 1}}}');
    });

    it("should handle braces inside string values", () => {
      const content = 'Output: {"message": "Hello {name}!"}';

      const result = extractJson(content);
      expect(result).toBe('{"message": "Hello {name}!"}');
      expect(JSON.parse(result!)).toEqual({ message: "Hello {name}!" });
    });

    it("should handle brackets inside strings in arrays", () => {
      const content = 'Items: ["[tag]", "normal", "[other]"]';

      const result = extractJson(content);
      expect(result).toBe('["[tag]", "normal", "[other]"]');
    });

    it("should extract first valid JSON when multiple are present", () => {
      const content = '{"first": 1} and then {"second": 2}';

      const result = extractJson(content);
      expect(result).toBe('{"first": 1}');
    });
  });

  describe("edge cases", () => {
    it("should return null for content without JSON", () => {
      const content = "This is just plain text without any JSON.";

      const result = extractJson(content);
      expect(result).toBeNull();
    });

    it("should return null for invalid JSON-like content", () => {
      const content = "This {is not valid} JSON";

      const result = extractJson(content);
      // The progressive parser will try but fail to parse
      expect(result).toBeNull();
    });

    it("should prefer code block over raw JSON", () => {
      const content = `{"ignored": true}
\`\`\`json
{"preferred": true}
\`\`\``;

      const result = extractJson(content);
      expect(result).toBe('{"preferred": true}');
    });

    it("should handle empty code block", () => {
      const content = "```json\n\n```";

      const result = extractJson(content);
      expect(result).toBe("");
    });
  });
});

describe("ResponseParser", () => {
  describe("without schema", () => {
    it("should return raw string when no schema provided", () => {
      const parser = new ResponseParser();
      const result = parser.parse("Hello world");

      expect(result).toBe("Hello world");
    });

    it("should have hasSchema() return false", () => {
      const parser = new ResponseParser();
      expect(parser.hasSchema()).toBe(false);
    });

    it("should have getSchema() return null", () => {
      const parser = new ResponseParser();
      expect(parser.getSchema()).toBeNull();
    });
  });

  describe("with schema", () => {
    const testSchema = z.object({
      name: z.string(),
      age: z.number(),
    });

    it("should parse and validate JSON matching schema", () => {
      const parser = new ResponseParser(testSchema);
      const result = parser.parse('{"name": "John", "age": 30}');

      expect(result).toEqual({ name: "John", age: 30 });
    });

    it("should extract JSON from code block and validate", () => {
      const parser = new ResponseParser(testSchema);
      const result = parser.parse(`Here's the data:
\`\`\`json
{"name": "Jane", "age": 25}
\`\`\`
That's it.`);

      expect(result).toEqual({ name: "Jane", age: 25 });
    });

    it("should throw ResponseParseError for invalid JSON", () => {
      const parser = new ResponseParser(testSchema);

      expect(() => parser.parse("{invalid json}")).toThrow(ResponseParseError);
    });

    it("should throw ResponseParseError for schema validation failure", () => {
      const parser = new ResponseParser(testSchema);

      // Missing required field
      expect(() => parser.parse('{"name": "John"}')).toThrow(ResponseParseError);
    });

    it("should throw ResponseParseError with validation details", () => {
      const parser = new ResponseParser(testSchema);

      try {
        parser.parse('{"name": 123, "age": "not a number"}');
        expect.fail("Should have thrown");
      } catch (err) {
        expect(err).toBeInstanceOf(ResponseParseError);
        const parseError = err as ResponseParseError;
        expect(parseError.message).toContain("Schema validation failed");
        expect(parseError.rawContent).toBe('{"name": 123, "age": "not a number"}');
      }
    });

    it("should throw ResponseParseError when no JSON found", () => {
      const parser = new ResponseParser(testSchema);

      expect(() => parser.parse("No JSON here")).toThrow(ResponseParseError);
    });

    it("should have hasSchema() return true", () => {
      const parser = new ResponseParser(testSchema);
      expect(parser.hasSchema()).toBe(true);
    });

    it("should return schema from getSchema()", () => {
      const parser = new ResponseParser(testSchema);
      expect(parser.getSchema()).toBe(testSchema);
    });
  });

  describe("tryParse", () => {
    const schema = z.object({ value: z.number() });

    it("should return parsed result on success", () => {
      const parser = new ResponseParser(schema);
      const result = parser.tryParse('{"value": 42}');

      expect(result).toEqual({ value: 42 });
    });

    it("should return null on parse failure", () => {
      const parser = new ResponseParser(schema);
      const result = parser.tryParse("invalid");

      expect(result).toBeNull();
    });

    it("should return null on schema validation failure", () => {
      const parser = new ResponseParser(schema);
      const result = parser.tryParse('{"value": "not a number"}');

      expect(result).toBeNull();
    });
  });

  describe("complex schemas", () => {
    it("should handle nested objects", () => {
      const schema = z.object({
        user: z.object({
          name: z.string(),
          email: z.string().email(),
        }),
        metadata: z.object({
          created: z.string(),
        }),
      });

      const parser = new ResponseParser(schema);
      const result = parser.parse(`{
        "user": {"name": "Test", "email": "test@example.com"},
        "metadata": {"created": "2024-01-01"}
      }`);

      expect(result.user.name).toBe("Test");
      expect(result.user.email).toBe("test@example.com");
    });

    it("should handle arrays", () => {
      const schema = z.object({
        items: z.array(z.object({ id: z.number(), name: z.string() })),
      });

      const parser = new ResponseParser(schema);
      const result = parser.parse(`{
        "items": [
          {"id": 1, "name": "first"},
          {"id": 2, "name": "second"}
        ]
      }`);

      expect(result.items).toHaveLength(2);
      expect(result.items[0].id).toBe(1);
    });

    it("should handle optional fields", () => {
      const schema = z.object({
        required: z.string(),
        optional: z.string().optional(),
      });

      const parser = new ResponseParser(schema);
      const result = parser.parse('{"required": "value"}');

      expect(result.required).toBe("value");
      expect(result.optional).toBeUndefined();
    });

    it("should handle default values", () => {
      const schema = z.object({
        value: z.number().default(42),
      });

      const parser = new ResponseParser(schema);
      const result = parser.parse("{}");

      expect(result.value).toBe(42);
    });

    it("should handle unions", () => {
      const schema = z.object({
        data: z.union([z.string(), z.number()]),
      });

      const parser = new ResponseParser(schema);

      expect(parser.parse('{"data": "text"}').data).toBe("text");
      expect(parser.parse('{"data": 123}').data).toBe(123);
    });
  });
});

describe("createResponseParser", () => {
  it("should create parser without schema", () => {
    const parser = createResponseParser();
    expect(parser.hasSchema()).toBe(false);
    expect(parser.parse("test")).toBe("test");
  });

  it("should create parser with schema", () => {
    const schema = z.object({ value: z.string() });
    const parser = createResponseParser(schema);

    expect(parser.hasSchema()).toBe(true);
    expect(parser.parse('{"value": "test"}')).toEqual({ value: "test" });
  });
});

describe("zodSchemaToPromptDescription", () => {
  it("should describe object with fields", () => {
    const schema = z.object({
      name: z.string(),
      age: z.number(),
    });

    const desc = zodSchemaToPromptDescription(schema);

    expect(desc).toContain("JSON object");
    expect(desc).toContain("name:");
    expect(desc).toContain("age:");
    expect(desc).toContain("string");
    expect(desc).toContain("number");
  });

  it("should include field descriptions if available", () => {
    const schema = z.object({
      name: z.string().describe("The user's full name"),
      email: z.string().describe("Contact email address"),
    });

    const desc = zodSchemaToPromptDescription(schema);

    expect(desc).toContain("The user's full name");
    expect(desc).toContain("Contact email address");
  });

  it("should handle schema with top-level description", () => {
    const schema = z.object({ value: z.string() }).describe("A simple value object");

    const desc = zodSchemaToPromptDescription(schema);

    expect(desc).toBe("A simple value object");
  });

  it("should handle array types", () => {
    const schema = z.array(z.string());

    const desc = zodSchemaToPromptDescription(schema);

    expect(desc).toContain("array");
  });

  it("should handle primitive types", () => {
    const stringSchema = z.string();
    const numberSchema = z.number();

    expect(zodSchemaToPromptDescription(stringSchema)).toContain("string");
    expect(zodSchemaToPromptDescription(numberSchema)).toContain("number");
  });
});

describe("formatZodError", () => {
  it("should format single issue", () => {
    const schema = z.object({ value: z.number() });
    const result = schema.safeParse({ value: "not a number" });

    if (!result.success) {
      const formatted = formatZodError(result.error);
      expect(formatted).toContain("value");
      expect(formatted).toContain("Expected number");
    }
  });

  it("should format multiple issues", () => {
    const schema = z.object({
      name: z.string().min(1),
      age: z.number().positive(),
    });
    const result = schema.safeParse({ name: "", age: -5 });

    if (!result.success) {
      const formatted = formatZodError(result.error);
      expect(formatted).toContain("name");
      expect(formatted).toContain("age");
    }
  });

  it("should handle nested path issues", () => {
    const schema = z.object({
      user: z.object({
        email: z.string().email(),
      }),
    });
    const result = schema.safeParse({ user: { email: "invalid" } });

    if (!result.success) {
      const formatted = formatZodError(result.error);
      expect(formatted).toContain("user.email");
    }
  });
});

describe("ResponseParseError", () => {
  it("should store raw content", () => {
    const error = new ResponseParseError("Test error", "raw content");
    expect(error.rawContent).toBe("raw content");
    expect(error.message).toBe("Test error");
  });

  it("should store Zod error if provided", () => {
    const schema = z.object({ value: z.number() });
    const result = schema.safeParse({ value: "bad" });

    if (!result.success) {
      const error = new ResponseParseError("Validation failed", "content", result.error);
      expect(error.zodError).toBe(result.error);
    }
  });

  it("should be instance of Error", () => {
    const error = new ResponseParseError("Test", "content");
    expect(error).toBeInstanceOf(Error);
    expect(error.name).toBe("ResponseParseError");
  });
});
