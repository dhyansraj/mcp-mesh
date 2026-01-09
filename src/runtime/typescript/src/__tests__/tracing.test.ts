/**
 * Unit tests for tracing.ts
 *
 * Tests distributed tracing utilities for MCP Mesh TypeScript SDK.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  generateTraceId,
  generateSpanId,
  parseTraceContext,
  createTraceHeaders,
  initTracing,
  isTracingAvailable,
  publishTraceSpan,
  type TraceContext,
  type AgentMetadata,
  type SpanData,
} from "../tracing.js";

// Mock the @mcpmesh/core module
vi.mock("@mcpmesh/core", () => ({
  isTracingEnabled: vi.fn(() => false),
  initTracePublisher: vi.fn(async () => true),
  publishSpan: vi.fn(async () => true),
  isTracePublisherAvailable: vi.fn(async () => true),
}));

describe("generateTraceId", () => {
  it("should generate a 32-character hex string (UUID without dashes)", () => {
    const traceId = generateTraceId();

    expect(traceId).toHaveLength(32);
    expect(traceId).toMatch(/^[0-9a-f]{32}$/);
  });

  it("should not contain dashes", () => {
    const traceId = generateTraceId();

    expect(traceId).not.toContain("-");
  });

  it("should generate unique trace IDs", () => {
    const traceId1 = generateTraceId();
    const traceId2 = generateTraceId();
    const traceId3 = generateTraceId();

    expect(traceId1).not.toBe(traceId2);
    expect(traceId2).not.toBe(traceId3);
    expect(traceId1).not.toBe(traceId3);
  });

  it("should generate 1000 unique trace IDs without collision", () => {
    const traceIds = new Set<string>();

    for (let i = 0; i < 1000; i++) {
      traceIds.add(generateTraceId());
    }

    expect(traceIds.size).toBe(1000);
  });
});

describe("generateSpanId", () => {
  it("should generate a valid UUID format", () => {
    const spanId = generateSpanId();

    // UUID format: 8-4-4-4-12
    expect(spanId).toMatch(
      /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/
    );
  });

  it("should generate unique span IDs", () => {
    const spanId1 = generateSpanId();
    const spanId2 = generateSpanId();

    expect(spanId1).not.toBe(spanId2);
  });
});

describe("parseTraceContext", () => {
  it("should parse trace context from lowercase headers", () => {
    const headers = {
      "x-trace-id": "abc123def456",
      "x-parent-span-id": "span-789",
    };

    const context = parseTraceContext(headers);

    expect(context).not.toBeNull();
    expect(context?.traceId).toBe("abc123def456");
    expect(context?.parentSpanId).toBe("span-789");
  });

  it("should parse trace context from mixed-case headers", () => {
    const headers = {
      "X-Trace-Id": "trace-mixed-case",
      "X-Parent-Span-Id": "parent-mixed-case",
    };

    const context = parseTraceContext(headers);

    expect(context).not.toBeNull();
    expect(context?.traceId).toBe("trace-mixed-case");
    expect(context?.parentSpanId).toBe("parent-mixed-case");
  });

  it("should return null when trace ID is missing", () => {
    const headers = {
      "x-parent-span-id": "orphan-span",
    };

    const context = parseTraceContext(headers);

    expect(context).toBeNull();
  });

  it("should handle missing parent span ID", () => {
    const headers = {
      "x-trace-id": "root-trace",
    };

    const context = parseTraceContext(headers);

    expect(context).not.toBeNull();
    expect(context?.traceId).toBe("root-trace");
    expect(context?.parentSpanId).toBeNull();
  });

  it("should handle empty headers", () => {
    const context = parseTraceContext({});

    expect(context).toBeNull();
  });

  it("should handle undefined header values", () => {
    const headers: Record<string, string | undefined> = {
      "x-trace-id": undefined,
    };

    const context = parseTraceContext(headers);

    expect(context).toBeNull();
  });
});

describe("createTraceHeaders", () => {
  it("should create headers with trace ID and span ID", () => {
    const headers = createTraceHeaders("my-trace-id", "my-span-id");

    expect(headers["X-Trace-Id"]).toBe("my-trace-id");
    expect(headers["X-Parent-Span-Id"]).toBe("my-span-id");
  });

  it("should create headers that can be parsed back", () => {
    const originalTraceId = generateTraceId();
    const originalSpanId = generateSpanId();

    const headers = createTraceHeaders(originalTraceId, originalSpanId);
    const parsed = parseTraceContext(headers);

    expect(parsed).not.toBeNull();
    expect(parsed?.traceId).toBe(originalTraceId);
    expect(parsed?.parentSpanId).toBe(originalSpanId);
  });
});

describe("TraceContext interface", () => {
  it("should have correct structure", () => {
    const context: TraceContext = {
      traceId: "test-trace-id",
      parentSpanId: "test-parent-span",
    };

    expect(context.traceId).toBe("test-trace-id");
    expect(context.parentSpanId).toBe("test-parent-span");
  });

  it("should allow null parentSpanId for root spans", () => {
    const context: TraceContext = {
      traceId: "root-trace",
      parentSpanId: null,
    };

    expect(context.traceId).toBe("root-trace");
    expect(context.parentSpanId).toBeNull();
  });
});

describe("AgentMetadata interface", () => {
  it("should have all required fields", () => {
    const metadata: AgentMetadata = {
      agentId: "test-agent-123",
      agentName: "test-agent",
      agentNamespace: "default",
      agentHostname: "localhost",
      agentIp: "127.0.0.1",
      agentPort: 8080,
      agentEndpoint: "http://127.0.0.1:8080",
    };

    expect(metadata.agentId).toBe("test-agent-123");
    expect(metadata.agentName).toBe("test-agent");
    expect(metadata.agentNamespace).toBe("default");
    expect(metadata.agentHostname).toBe("localhost");
    expect(metadata.agentIp).toBe("127.0.0.1");
    expect(metadata.agentPort).toBe(8080);
    expect(metadata.agentEndpoint).toBe("http://127.0.0.1:8080");
  });
});

describe("SpanData interface", () => {
  it("should have all required fields for a successful span", () => {
    const span: SpanData = {
      traceId: "trace-123",
      spanId: "span-456",
      parentSpan: "parent-789",
      functionName: "test_function",
      startTime: 1704067200.0,
      endTime: 1704067200.5,
      durationMs: 500,
      success: true,
      error: null,
      resultType: "string",
      argsCount: 2,
      kwargsCount: 3,
      dependencies: ["dep1", "dep2"],
      injectedDependencies: 2,
      meshPositions: [0, 1],
    };

    expect(span.success).toBe(true);
    expect(span.error).toBeNull();
    expect(span.durationMs).toBe(500);
  });

  it("should have correct structure for a failed span", () => {
    const span: SpanData = {
      traceId: "trace-error",
      spanId: "span-error",
      parentSpan: null,
      functionName: "failing_function",
      startTime: 1704067200.0,
      endTime: 1704067200.1,
      durationMs: 100,
      success: false,
      error: "Connection timeout",
      resultType: "error",
      argsCount: 0,
      kwargsCount: 0,
      dependencies: [],
      injectedDependencies: 0,
      meshPositions: [],
    };

    expect(span.success).toBe(false);
    expect(span.error).toBe("Connection timeout");
    expect(span.parentSpan).toBeNull();
  });
});

describe("initTracing", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // Reset module state by reimporting
    vi.resetModules();
  });

  it("should check if tracing is enabled via Rust core", async () => {
    const { isTracingEnabled } = await import("@mcpmesh/core");

    const metadata: AgentMetadata = {
      agentId: "test-agent",
      agentName: "test",
      agentNamespace: "default",
      agentHostname: "localhost",
      agentIp: "127.0.0.1",
      agentPort: 8080,
      agentEndpoint: "http://127.0.0.1:8080",
    };

    // Re-import to get fresh module state
    const { initTracing: freshInit } = await import("../tracing.js");
    await freshInit(metadata);

    expect(isTracingEnabled).toHaveBeenCalled();
  });
});

describe("publishTraceSpan", () => {
  it("should return false when tracing is disabled", async () => {
    const span: SpanData = {
      traceId: "trace-123",
      spanId: "span-456",
      parentSpan: null,
      functionName: "test",
      startTime: Date.now() / 1000,
      endTime: Date.now() / 1000,
      durationMs: 0,
      success: true,
      error: null,
      resultType: "string",
      argsCount: 0,
      kwargsCount: 0,
      dependencies: [],
      injectedDependencies: 0,
      meshPositions: [],
    };

    // Tracing is disabled by default in our mock
    const result = await publishTraceSpan(span);

    expect(result).toBe(false);
  });
});
