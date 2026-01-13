/**
 * Unit tests for sse.ts
 *
 * Tests Server-Sent Events (SSE) parsing utilities.
 */

import { describe, it, expect } from "vitest";
import { parseSSEResponse, isSSEResponse, parseSSEStream } from "../sse.js";

describe("isSSEResponse", () => {
  it("should return true for SSE format", () => {
    const sse = "event: message\ndata: {}\n";
    expect(isSSEResponse(sse)).toBe(true);
  });

  it("should return false for plain JSON", () => {
    const json = '{"result": 42}';
    expect(isSSEResponse(json)).toBe(false);
  });

  it("should return false for JSON starting with bracket", () => {
    const json = "[1, 2, 3]";
    expect(isSSEResponse(json)).toBe(false);
  });

  it("should return false for text not starting with event:", () => {
    const text = "Some text\nevent: message\ndata: {}";
    expect(isSSEResponse(text)).toBe(false);
  });
});

describe("parseSSEResponse", () => {
  describe("SSE format", () => {
    it("should parse basic SSE message", () => {
      const sse = 'event: message\ndata: {"result": 42}\n';
      const result = parseSSEResponse<{ result: number }>(sse);

      expect(result).toEqual({ result: 42 });
    });

    it("should parse JSON-RPC style SSE response", () => {
      const sse = `event: message
data: {"jsonrpc":"2.0","id":123,"result":{"value":"hello"}}
`;
      const result = parseSSEResponse<{
        jsonrpc: string;
        id: number;
        result: { value: string };
      }>(sse);

      expect(result.jsonrpc).toBe("2.0");
      expect(result.id).toBe(123);
      expect(result.result.value).toBe("hello");
    });

    it("should extract the last data line when multiple events exist", () => {
      const sse = `event: progress
data: {"status": "processing"}

event: message
data: {"status": "complete", "result": 100}
`;
      const result = parseSSEResponse<{ status: string; result?: number }>(sse);

      expect(result.status).toBe("complete");
      expect(result.result).toBe(100);
    });

    it("should handle SSE with extra whitespace", () => {
      const sse = "event: message\ndata: { \"value\" : 1 }\n\n";
      const result = parseSSEResponse<{ value: number }>(sse);

      expect(result.value).toBe(1);
    });

    it("should throw error when no data line found", () => {
      const sse = "event: message\n\n";

      expect(() => parseSSEResponse(sse)).toThrow("No data found in SSE response");
    });

    it("should throw error for invalid JSON in data line", () => {
      const sse = "event: message\ndata: {invalid json}\n";

      expect(() => parseSSEResponse(sse)).toThrow();
    });
  });

  describe("plain JSON format", () => {
    it("should parse plain JSON object", () => {
      const json = '{"name": "test", "value": 123}';
      const result = parseSSEResponse<{ name: string; value: number }>(json);

      expect(result).toEqual({ name: "test", value: 123 });
    });

    it("should parse plain JSON array", () => {
      const json = "[1, 2, 3, 4, 5]";
      const result = parseSSEResponse<number[]>(json);

      expect(result).toEqual([1, 2, 3, 4, 5]);
    });

    it("should throw error for invalid plain JSON", () => {
      const invalid = "not json at all";

      expect(() => parseSSEResponse(invalid)).toThrow();
    });
  });

  describe("real-world responses", () => {
    it("should parse FastMCP tool call response", () => {
      const sse = `event: message
data: {"jsonrpc":"2.0","id":"abc123","result":{"content":[{"type":"text","text":"Hello, world!"}]}}
`;
      interface MCPResponse {
        jsonrpc: string;
        id: string;
        result: {
          content: Array<{ type: string; text: string }>;
        };
      }

      const result = parseSSEResponse<MCPResponse>(sse);

      expect(result.id).toBe("abc123");
      expect(result.result.content[0].text).toBe("Hello, world!");
    });

    it("should parse MCP Mesh registry heartbeat response", () => {
      const response = JSON.stringify({
        agent_id: "test-agent-123",
        status: "success",
        dependencies_resolved: { calculator: "http://localhost:9001" },
        llm_tools: {},
        message: "Agent registered via heartbeat",
      });

      const result = parseSSEResponse<{
        agent_id: string;
        status: string;
        dependencies_resolved: Record<string, string>;
      }>(response);

      expect(result.agent_id).toBe("test-agent-123");
      expect(result.status).toBe("success");
      expect(result.dependencies_resolved.calculator).toBe("http://localhost:9001");
    });
  });
});

describe("parseSSEStream", () => {
  it("should parse multiple data events", () => {
    const sse = `event: progress
data: {"step": 1}

event: progress
data: {"step": 2}

event: done
data: {"step": 3, "complete": true}
`;
    const results = parseSSEStream<{ step: number; complete?: boolean }>(sse);

    expect(results).toHaveLength(3);
    expect(results[0].step).toBe(1);
    expect(results[1].step).toBe(2);
    expect(results[2].step).toBe(3);
    expect(results[2].complete).toBe(true);
  });

  it("should return empty array for non-SSE content", () => {
    const json = '{"result": 42}';
    const results = parseSSEStream(json);

    expect(results).toEqual([]);
  });

  it("should skip empty data lines", () => {
    const sse = `event: message
data: {"value": 1}

data:

event: message
data: {"value": 2}
`;
    const results = parseSSEStream<{ value: number }>(sse);

    expect(results).toHaveLength(2);
    expect(results[0].value).toBe(1);
    expect(results[1].value).toBe(2);
  });

  it("should handle streaming chat completion style", () => {
    const sse = `event: message
data: {"delta": "Hello"}

event: message
data: {"delta": " world"}

event: message
data: {"delta": "!"}

event: done
data: {"finished": true}
`;
    interface Delta {
      delta?: string;
      finished?: boolean;
    }

    const results = parseSSEStream<Delta>(sse);

    expect(results).toHaveLength(4);
    expect(results.filter((r) => r.delta).map((r) => r.delta).join("")).toBe("Hello world!");
    expect(results[3].finished).toBe(true);
  });

  it("should throw for invalid JSON in stream", () => {
    const sse = `event: message
data: {"valid": true}

event: message
data: invalid json here
`;

    expect(() => parseSSEStream(sse)).toThrow();
  });
});
