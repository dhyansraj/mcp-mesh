/**
 * Response parser for LLM outputs with Zod schema validation.
 *
 * Handles extraction of structured data from LLM responses, including:
 * - JSON extraction from code blocks or raw text
 * - Schema validation using Zod
 * - Error handling with informative messages
 *
 * @example
 * ```typescript
 * const schema = z.object({
 *   answer: z.string(),
 *   confidence: z.number(),
 * });
 *
 * const parser = new ResponseParser(schema);
 * const result = parser.parse('{"answer": "hello", "confidence": 0.95}');
 * // => { answer: "hello", confidence: 0.95 }
 * ```
 */

import type { ZodType, ZodError as ZodErrorType } from "zod";
import { ResponseParseError } from "./errors.js";

// Re-export for backwards compatibility
export { ResponseParseError };

/**
 * Extract JSON from a string that may contain markdown code blocks.
 *
 * Handles:
 * - ```json ... ``` code blocks
 * - ``` ... ``` code blocks (no language)
 * - Raw JSON (object or array)
 */
export function extractJson(content: string): string | null {
  // Try to extract from markdown code blocks first
  const codeBlockMatch = content.match(/```(?:json)?\s*([\s\S]*?)```/);
  if (codeBlockMatch) {
    return codeBlockMatch[1].trim();
  }

  // Try to find raw JSON object or array
  const jsonMatch = content.match(/(\{[\s\S]*\}|\[[\s\S]*\])/);
  if (jsonMatch) {
    return jsonMatch[1].trim();
  }

  return null;
}

/**
 * Parser for LLM responses with optional Zod schema validation.
 *
 * @template T - The output type (inferred from Zod schema)
 */
export class ResponseParser<T = string> {
  private schema: ZodType<T> | null;

  /**
   * Create a new ResponseParser.
   *
   * @param schema - Optional Zod schema for validation. If not provided, returns raw string.
   */
  constructor(schema?: ZodType<T>) {
    this.schema = schema ?? null;
  }

  /**
   * Parse an LLM response string.
   *
   * If a schema is provided, attempts to extract and validate JSON.
   * If no schema, returns the raw string content.
   *
   * @param content - Raw LLM response content
   * @returns Parsed and validated result
   * @throws ResponseParseError if parsing or validation fails
   */
  parse(content: string): T {
    // No schema - return raw string
    if (!this.schema) {
      return content as unknown as T;
    }

    // Extract JSON from content
    const jsonStr = extractJson(content);
    if (!jsonStr) {
      throw new ResponseParseError(
        "Could not extract JSON from response. Expected JSON object or array.",
        content
      );
    }

    // Parse JSON
    let parsed: unknown;
    try {
      parsed = JSON.parse(jsonStr);
    } catch (err) {
      throw new ResponseParseError(
        `Invalid JSON: ${err instanceof Error ? err.message : String(err)}`,
        content
      );
    }

    // Validate with Zod schema
    const result = this.schema.safeParse(parsed);
    if (!result.success) {
      const issues = result.error.issues
        .map((i) => `${i.path.join(".")}: ${i.message}`)
        .join("; ");
      throw new ResponseParseError(
        `Schema validation failed: ${issues}`,
        content,
        result.error
      );
    }

    return result.data;
  }

  /**
   * Try to parse, returning null on failure instead of throwing.
   *
   * @param content - Raw LLM response content
   * @returns Parsed result or null if parsing fails
   */
  tryParse(content: string): T | null {
    try {
      return this.parse(content);
    } catch {
      return null;
    }
  }

  /**
   * Get the Zod schema (if any).
   */
  getSchema(): ZodType<T> | null {
    return this.schema;
  }

  /**
   * Check if this parser has a schema.
   */
  hasSchema(): boolean {
    return this.schema !== null;
  }
}

/**
 * Create a response parser with an optional Zod schema.
 *
 * @param schema - Optional Zod schema for validation
 * @returns ResponseParser instance
 *
 * @example
 * ```typescript
 * // No schema - returns raw string
 * const stringParser = createResponseParser();
 * const str = stringParser.parse("Hello world");
 *
 * // With schema - validates and returns typed object
 * const objectParser = createResponseParser(z.object({
 *   name: z.string(),
 *   age: z.number(),
 * }));
 * const obj = objectParser.parse('{"name": "John", "age": 30}');
 * ```
 */
export function createResponseParser<T = string>(
  schema?: ZodType<T>
): ResponseParser<T> {
  return new ResponseParser(schema);
}

/**
 * Convert a Zod schema to a JSON Schema object for LLM prompting.
 * This is useful for including the expected format in system prompts.
 */
export function zodSchemaToPromptDescription(schema: ZodType): string {
  // Get the Zod description or use a generic message
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const zodSchema = schema as any;
  const description = zodSchema._def?.description;

  if (description) {
    return description;
  }

  // Try to infer from shape if it's an object
  if (zodSchema._def?.typeName === "ZodObject") {
    const shape = zodSchema._def.shape();
    const fields = Object.keys(shape).map((key) => {
      const fieldType = shape[key]._def?.typeName || "unknown";
      const fieldDesc = shape[key]._def?.description || "";
      return `  - ${key}: ${fieldType.replace("Zod", "").toLowerCase()}${fieldDesc ? ` (${fieldDesc})` : ""}`;
    });
    return `JSON object with fields:\n${fields.join("\n")}`;
  }

  return "JSON";
}

/**
 * Format a Zod error into a human-readable string.
 */
export function formatZodError(error: ZodErrorType): string {
  return error.issues
    .map((issue) => {
      const path = issue.path.length > 0 ? issue.path.join(".") + ": " : "";
      return `${path}${issue.message}`;
    })
    .join("\n");
}
