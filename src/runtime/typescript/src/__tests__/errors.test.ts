/**
 * Unit tests for errors.ts
 *
 * Tests typed error classes for mesh operations.
 */

import { describe, it, expect } from "vitest";
import {
  MaxIterationsError,
  ToolExecutionError,
  LLMAPIError,
  ResponseParseError,
  ProviderUnavailableError,
} from "../errors.js";

describe("MaxIterationsError", () => {
  it("should create error with iteration count", () => {
    const error = new MaxIterationsError(10, { lastText: "thinking..." });

    expect(error).toBeInstanceOf(Error);
    expect(error).toBeInstanceOf(MaxIterationsError);
    expect(error.name).toBe("MaxIterationsError");
    expect(error.iterations).toBe(10);
    expect(error.lastResponse).toEqual({ lastText: "thinking..." });
    expect(error.message).toContain("10");
  });

  it("should include message history when provided", () => {
    const messages = [
      { role: "user", content: "Hello" },
      { role: "assistant", content: "Hi!" },
    ];
    const error = new MaxIterationsError(5, null, messages);

    expect(error.messages).toEqual(messages);
  });

  it("should handle undefined messages", () => {
    const error = new MaxIterationsError(3, "response");

    expect(error.messages).toBeUndefined();
  });
});

describe("ToolExecutionError", () => {
  it("should create error with tool name and cause", () => {
    const cause = new Error("Connection timeout");
    const error = new ToolExecutionError("get_weather", cause);

    expect(error).toBeInstanceOf(Error);
    expect(error).toBeInstanceOf(ToolExecutionError);
    expect(error.name).toBe("ToolExecutionError");
    expect(error.toolName).toBe("get_weather");
    expect(error.cause).toBe(cause);
    expect(error.message).toContain("get_weather");
    expect(error.message).toContain("Connection timeout");
  });

  it("should include arguments when provided", () => {
    const cause = new Error("Invalid input");
    const args = { city: "NYC", units: "celsius" };
    const error = new ToolExecutionError("get_weather", cause, args);

    expect(error.args).toEqual(args);
  });

  it("should handle error without args", () => {
    const cause = new Error("Failed");
    const error = new ToolExecutionError("process_data", cause);

    expect(error.args).toBeUndefined();
  });
});

describe("LLMAPIError", () => {
  it("should create error with status code and body", () => {
    const error = new LLMAPIError(500, "Internal server error");

    expect(error).toBeInstanceOf(Error);
    expect(error).toBeInstanceOf(LLMAPIError);
    expect(error.name).toBe("LLMAPIError");
    expect(error.statusCode).toBe(500);
    expect(error.body).toBe("Internal server error");
    expect(error.message).toContain("500");
  });

  it("should include provider when specified", () => {
    const error = new LLMAPIError(429, "Rate limit exceeded", "openai");

    expect(error.provider).toBe("openai");
  });

  it("should handle various HTTP status codes", () => {
    const badRequest = new LLMAPIError(400, "Bad request");
    expect(badRequest.statusCode).toBe(400);

    const unauthorized = new LLMAPIError(401, "Unauthorized");
    expect(unauthorized.statusCode).toBe(401);

    const rateLimit = new LLMAPIError(429, "Too many requests");
    expect(rateLimit.statusCode).toBe(429);
  });
});

describe("ResponseParseError", () => {
  it("should create error with message and raw content", () => {
    const error = new ResponseParseError(
      "Invalid JSON",
      '{"incomplete": '
    );

    expect(error).toBeInstanceOf(Error);
    expect(error).toBeInstanceOf(ResponseParseError);
    expect(error.name).toBe("ResponseParseError");
    expect(error.message).toBe("Invalid JSON");
    expect(error.rawContent).toBe('{"incomplete": ');
  });

  it("should include Zod error when provided", () => {
    const zodError = { issues: [{ path: ["name"], message: "Required" }] };
    const error = new ResponseParseError(
      "Schema validation failed",
      '{"age": 30}',
      zodError
    );

    expect(error.zodError).toBe(zodError);
  });

  it("should include expected schema when provided", () => {
    const schema = { type: "object", properties: { name: { type: "string" } } };
    const error = new ResponseParseError(
      "Missing required field",
      "{}",
      undefined,
      schema
    );

    expect(error.expectedSchema).toEqual(schema);
  });

  it("should handle all optional parameters", () => {
    const zodError = { issues: [] };
    const schema = { type: "string" };
    const error = new ResponseParseError(
      "Parse error",
      "raw content",
      zodError,
      schema
    );

    expect(error.rawContent).toBe("raw content");
    expect(error.zodError).toBe(zodError);
    expect(error.expectedSchema).toBe(schema);
  });
});

describe("ProviderUnavailableError", () => {
  it("should create error with provider spec", () => {
    const spec = { capability: "llm", tags: ["claude"] };
    const error = new ProviderUnavailableError(spec);

    expect(error).toBeInstanceOf(Error);
    expect(error).toBeInstanceOf(ProviderUnavailableError);
    expect(error.name).toBe("ProviderUnavailableError");
    expect(error.providerSpec).toEqual(spec);
    expect(error.message).toContain("LLM provider unavailable");
    expect(error.message).toContain(JSON.stringify(spec));
  });

  it("should include reason when provided", () => {
    const spec = { capability: "llm" };
    const error = new ProviderUnavailableError(spec, "No providers registered");

    expect(error.reason).toBe("No providers registered");
    expect(error.message).toContain("No providers registered");
  });

  it("should handle string provider spec", () => {
    const error = new ProviderUnavailableError("llm");

    expect(error.providerSpec).toBe("llm");
    expect(error.message).toContain('"llm"');
  });

  it("should handle complex provider spec", () => {
    const spec = {
      capability: "llm",
      tags: ["claude", "fast"],
      version: ">=1.0.0",
    };
    const error = new ProviderUnavailableError(spec, "Version mismatch");

    expect(error.providerSpec).toEqual(spec);
    expect(error.reason).toBe("Version mismatch");
  });
});

describe("Error inheritance", () => {
  it("all custom errors should be instanceof Error", () => {
    expect(new MaxIterationsError(1, null)).toBeInstanceOf(Error);
    expect(new ToolExecutionError("test", new Error())).toBeInstanceOf(Error);
    expect(new LLMAPIError(500, "error")).toBeInstanceOf(Error);
    expect(new ResponseParseError("msg", "content")).toBeInstanceOf(Error);
    expect(new ProviderUnavailableError({})).toBeInstanceOf(Error);
  });

  it("errors should be catchable in try/catch", () => {
    try {
      throw new MaxIterationsError(5, "response");
    } catch (err) {
      expect(err).toBeInstanceOf(MaxIterationsError);
      expect(err).toBeInstanceOf(Error);
    }
  });

  it("errors should work with error type guards", () => {
    const errors: Error[] = [
      new MaxIterationsError(1, null),
      new ToolExecutionError("test", new Error("cause")),
      new LLMAPIError(400, "bad request"),
      new ResponseParseError("parse failed", "raw"),
      new ProviderUnavailableError("llm"),
    ];

    for (const error of errors) {
      expect(error.name).toBeDefined();
      expect(error.message).toBeDefined();
    }
  });
});
