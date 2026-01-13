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
import { zodToJsonSchema } from "zod-to-json-schema";
import { ResponseParseError } from "./errors.js";

// Re-export for backwards compatibility
export { ResponseParseError };

/**
 * Extract JSON from a string that may contain markdown code blocks.
 *
 * Handles:
 * - ```json ... ``` code blocks
 * - ``` ... ``` code blocks (no language)
 * - Raw JSON (object or array) using progressive JSON.parse
 */
export function extractJson(content: string): string | null {
  // Strategy 1: Try to extract from markdown code blocks first
  const codeBlockMatch = content.match(/```(?:json)?\s*([\s\S]*?)```/);
  if (codeBlockMatch) {
    return codeBlockMatch[1].trim();
  }

  // Strategy 2: Try to find JSON object using progressive JSON.parse
  // This handles braces inside strings correctly
  const braceStart = content.indexOf("{");
  if (braceStart !== -1) {
    const result = tryProgressiveParse(content, braceStart, "{", "}");
    if (result) return result;
  }

  // Strategy 3: Try to find JSON array using progressive JSON.parse
  const bracketStart = content.indexOf("[");
  if (bracketStart !== -1) {
    const result = tryProgressiveParse(content, bracketStart, "[", "]");
    if (result) return result;
  }

  return null;
}

/**
 * Try to extract valid JSON by progressively extending the end position.
 * This correctly handles braces/brackets inside string values.
 */
function tryProgressiveParse(
  content: string,
  start: number,
  openChar: string,
  closeChar: string
): string | null {
  // Quick check: count characters to find potential end positions
  let depth = 0;
  const potentialEnds: number[] = [];

  for (let i = start; i < content.length; i++) {
    const char = content[i];
    if (char === openChar) {
      depth++;
    } else if (char === closeChar) {
      depth--;
      if (depth === 0) {
        potentialEnds.push(i);
      }
    }
  }

  // Try each potential end position (shortest first for efficiency)
  for (const end of potentialEnds) {
    const candidate = content.slice(start, end + 1);
    try {
      JSON.parse(candidate);
      return candidate;
    } catch {
      // Not valid JSON, try next potential end
      continue;
    }
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
 * Convert a Zod schema to a human-readable description for LLM prompting.
 * Uses zod-to-json-schema for forward compatibility with Zod v4.
 */
export function zodSchemaToPromptDescription(schema: ZodType): string {
  // Convert to JSON Schema using the public API (Zod v4 compatible)
  const jsonSchema = zodToJsonSchema(schema, { $refStrategy: "none" }) as Record<string, unknown>;

  // Check for top-level description
  if (jsonSchema.description && typeof jsonSchema.description === "string") {
    return jsonSchema.description;
  }

  // If it's an object type, describe the fields
  if (jsonSchema.type === "object" && jsonSchema.properties) {
    const properties = jsonSchema.properties as Record<string, Record<string, unknown>>;
    const fields = Object.keys(properties).map((key) => {
      const prop = properties[key];
      const fieldType = (prop.type as string) || "unknown";
      const fieldDesc = prop.description ? ` (${prop.description})` : "";
      return `  - ${key}: ${fieldType}${fieldDesc}`;
    });
    return `JSON object with fields:\n${fields.join("\n")}`;
  }

  // Fallback for other types
  if (jsonSchema.type) {
    return `JSON ${jsonSchema.type}`;
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
