/**
 * Distributed tracing for MCP Mesh TypeScript SDK.
 *
 * Publishes trace spans to Redis via Rust core for distributed tracing.
 * Uses the same trace format as Python SDK for interoperability.
 */

import { randomUUID } from "crypto";
import {
  isTracingEnabled,
  initTracePublisher,
  publishSpan,
  isTracePublisherAvailable,
} from "@mcpmesh/core";

/**
 * Parse MCP_MESH_PROPAGATE_HEADERS env var into lowercase header name array.
 * Parsed once at module load. Empty array means no propagation (backward compatible).
 */
function parsePropagateHeaders(): string[] {
  const raw = process.env.MCP_MESH_PROPAGATE_HEADERS ?? "";
  return raw
    .split(",")
    .map((h) => h.trim().toLowerCase())
    .filter((h) => h.length > 0);
}

export const PROPAGATE_HEADERS: string[] = parsePropagateHeaders();

// Trace context passed between agents via headers
export interface TraceContext {
  traceId: string;
  parentSpanId: string | null;
}

// Agent metadata for trace spans
export interface AgentMetadata {
  agentId: string;
  agentName: string;
  agentNamespace: string;
  agentHostname: string;
  agentIp: string;
  agentPort: number;
  agentEndpoint: string;
}

// Global state
let tracingEnabled = false;
let tracingInitialized = false;
let currentAgentMetadata: AgentMetadata | null = null;

/**
 * Initialize the tracing system.
 *
 * Must be called before publishing spans. Checks if tracing is enabled
 * and initializes the Redis connection via Rust core.
 *
 * @returns true if tracing is enabled and ready, false otherwise.
 */
export async function initTracing(agentMetadata: AgentMetadata): Promise<boolean> {
  if (tracingInitialized) {
    return tracingEnabled;
  }

  tracingInitialized = true;
  currentAgentMetadata = agentMetadata;

  // Check if tracing is enabled via env var
  tracingEnabled = isTracingEnabled();
  if (!tracingEnabled) {
    console.log("Distributed tracing: disabled");
    return false;
  }

  console.log("Distributed tracing: enabled");

  // Initialize Rust core trace publisher
  const available = await initTracePublisher();
  if (!available) {
    console.warn("Rust core trace publisher initialization failed");
    tracingEnabled = false;
    return false;
  }

  return true;
}

/**
 * Check if tracing is currently available.
 */
export async function isTracingAvailable(): Promise<boolean> {
  if (!tracingEnabled) return false;
  return await isTracePublisherAvailable();
}

/**
 * Generate a new trace ID (OpenTelemetry compliant).
 *
 * @returns 32-character hex string (128-bit trace ID per OTel spec)
 */
export function generateTraceId(): string {
  return randomUUID().replace(/-/g, "");
}

/**
 * Generate a new span ID (OpenTelemetry compliant).
 *
 * @returns 16-character hex string (64-bit span ID per OTel spec)
 */
export function generateSpanId(): string {
  return randomUUID().replace(/-/g, "").slice(0, 16);
}

/**
 * Parse trace context from HTTP headers.
 *
 * Looks for X-Trace-ID and X-Parent-Span headers (matching Python SDK).
 */
export function parseTraceContext(
  headers: Record<string, string | undefined>
): TraceContext | null {
  // Check both cases: X-Trace-ID (Python) and X-Trace-Id (legacy)
  const traceId = headers["x-trace-id"] || headers["X-Trace-ID"] || headers["X-Trace-Id"];
  if (!traceId) return null;

  return {
    traceId,
    // Check both: X-Parent-Span (Python) and X-Parent-Span-Id (legacy)
    parentSpanId: headers["x-parent-span"] || headers["X-Parent-Span"] ||
                  headers["x-parent-span-id"] || headers["X-Parent-Span-Id"] || null,
  };
}

/**
 * Create trace headers to propagate context to downstream calls.
 * Uses Python SDK convention: X-Trace-ID, X-Parent-Span
 */
export function createTraceHeaders(
  traceId: string,
  spanId: string
): Record<string, string> {
  return {
    "X-Trace-ID": traceId,
    "X-Parent-Span": spanId,
  };
}

/**
 * Span data for publishing.
 */
export interface SpanData {
  traceId: string;
  spanId: string;
  parentSpan: string | null;
  functionName: string;
  startTime: number;
  endTime: number;
  durationMs: number;
  success: boolean;
  error: string | null;
  resultType: string;
  argsCount: number;
  kwargsCount: number;
  dependencies: string[];
  injectedDependencies: number;
  meshPositions: number[];
}

/**
 * Publish a trace span to Redis via Rust core.
 *
 * Non-blocking - silently handles failures to never break agent operations.
 */
export async function publishTraceSpan(span: SpanData): Promise<boolean> {
  if (!tracingEnabled || !currentAgentMetadata) {
    return false;
  }

  try {
    // Convert span to string map for Redis storage
    const spanMap: Record<string, string> = {
      trace_id: span.traceId,
      span_id: span.spanId,
      parent_span: span.parentSpan ?? "null",
      function_name: span.functionName,
      start_time: String(span.startTime),
      end_time: String(span.endTime),
      duration_ms: span.durationMs.toFixed(2),
      success: String(span.success),
      error: span.error ?? "null",
      result_type: span.resultType,
      args_count: String(span.argsCount),
      kwargs_count: String(span.kwargsCount),
      dependencies: JSON.stringify(span.dependencies),
      injected_dependencies: String(span.injectedDependencies),
      mesh_positions: JSON.stringify(span.meshPositions),
      // Agent metadata
      agent_id: currentAgentMetadata.agentId,
      agent_name: currentAgentMetadata.agentName,
      agent_namespace: currentAgentMetadata.agentNamespace,
      agent_hostname: currentAgentMetadata.agentHostname,
      agent_ip: currentAgentMetadata.agentIp,
      agent_port: String(currentAgentMetadata.agentPort),
      agent_endpoint: currentAgentMetadata.agentEndpoint,
    };

    return await publishSpan(spanMap);
  } catch (err) {
    // Non-blocking - never fail agent operations due to trace publishing
    return false;
  }
}

/**
 * Create a traced wrapper for a tool execution function.
 *
 * Automatically captures timing, success/error status, and publishes spans.
 */
export function createTracedExecutor<TArgs, TResult>(
  functionName: string,
  dependencies: string[],
  injectedDependencies: number,
  executor: (args: TArgs, traceContext: TraceContext | null) => Promise<TResult>
): (args: TArgs, traceContext: TraceContext | null) => Promise<TResult> {
  return async (args: TArgs, traceContext: TraceContext | null): Promise<TResult> => {
    if (!tracingEnabled) {
      return executor(args, traceContext);
    }

    // Generate span context
    const traceId = traceContext?.traceId ?? generateTraceId();
    const spanId = generateSpanId();
    const parentSpan = traceContext?.parentSpanId ?? null;

    const startTime = Date.now() / 1000;
    let success = true;
    let error: string | null = null;
    let resultType = "unknown";

    try {
      // Execute with trace context for propagation
      const newContext: TraceContext = { traceId, parentSpanId: spanId };
      const result = await executor(args, newContext);
      resultType = typeof result;
      return result;
    } catch (err) {
      success = false;
      error = err instanceof Error ? err.message : String(err);
      throw err;
    } finally {
      const endTime = Date.now() / 1000;
      const durationMs = (endTime - startTime) * 1000;

      // Publish span asynchronously (fire and forget)
      publishTraceSpan({
        traceId,
        spanId,
        parentSpan,
        functionName,
        startTime,
        endTime,
        durationMs,
        success,
        error,
        resultType,
        argsCount: 0,
        kwargsCount: typeof args === "object" && args !== null ? Object.keys(args).length : 0,
        dependencies,
        injectedDependencies,
        meshPositions: [],
      }).catch(() => {
        // Silently ignore publish errors
      });
    }
  };
}
