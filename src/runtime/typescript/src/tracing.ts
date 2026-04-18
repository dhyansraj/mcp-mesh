/**
 * Distributed tracing for MCP Mesh TypeScript SDK.
 *
 * Publishes trace spans to Redis via Rust core for distributed tracing.
 * Uses the same trace format as Python SDK for interoperability.
 */

import {
  isTracingEnabled,
  initTracePublisher,
  publishSpan,
  isTracePublisherAvailable,
  generateTraceId as coreGenerateTraceId,
  generateSpanId as coreGenerateSpanId,
  matchesPropagateHeader as coreMatchesPropagateHeader,
  injectTraceContext as coreInjectTraceContext,
} from "@mcpmesh/core";

/**
 * Parse MCP_MESH_PROPAGATE_HEADERS env var into lowercase header name array.
 * Parsed once at module load. Empty array means no propagation (backward compatible).
 */
function parsePropagateHeaders(): string[] {
  const raw = process.env.MCP_MESH_PROPAGATE_HEADERS ?? "";
  const headers = raw
    .split(",")
    .map((h) => h.trim().toLowerCase())
    .filter((h) => h.length > 0);
  // Always propagate mesh infrastructure headers
  if (!headers.includes("x-mesh-timeout")) {
    headers.push("x-mesh-timeout");
  }
  return headers;
}

export const PROPAGATE_HEADERS: string[] = parsePropagateHeaders();

/**
 * Check if a header name matches the propagate headers allowlist.
 *
 * Each allowlist entry is either an exact match (plain token) or a prefix
 * match (trailing `*`). Matching is case-insensitive.
 * - `authorization` matches only `authorization`.
 * - `x-trace-*` matches `x-trace-id`, `x-trace-parent`, etc.
 *
 * Delegates to Rust core so all SDKs behave identically.
 */
export function matchesPropagateHeader(name: string): boolean {
  if (PROPAGATE_HEADERS.length === 0) return false;
  return coreMatchesPropagateHeader(name, PROPAGATE_HEADERS.join(","));
}

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
 * Delegates to Rust core.
 *
 * @returns 32-character hex string (128-bit trace ID per OTel spec)
 */
export function generateTraceId(): string {
  return coreGenerateTraceId();
}

/**
 * Generate a new span ID (OpenTelemetry compliant).
 * Delegates to Rust core.
 *
 * @returns 16-character hex string (64-bit span ID per OTel spec)
 */
export function generateSpanId(): string {
  return coreGenerateSpanId();
}

/**
 * Inject trace context into JSON-RPC arguments.
 * Delegates to Rust core. Sets _trace_id, _parent_span, and optionally _mesh_headers.
 *
 * @param argsJson - JSON string of the arguments object
 * @param traceId - Trace ID to inject
 * @param spanId - Span ID to inject as _parent_span
 * @param propagatedHeadersJson - Optional JSON string of propagated headers
 * @returns JSON string with trace context injected
 */
export function injectTraceContext(
  argsJson: string,
  traceId: string,
  spanId: string,
  propagatedHeadersJson?: string | null,
): string {
  return coreInjectTraceContext(argsJson, traceId, spanId, propagatedHeadersJson);
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

  // Payload sizes (bytes)
  requestBytes?: number;
  responseBytes?: number;

  // LLM token metadata
  llmInputTokens?: number;
  llmOutputTokens?: number;
  llmTotalTokens?: number;
  llmModel?: string;
  llmProvider?: string;
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
      runtime: "typescript",
    };

    if (span.requestBytes !== undefined) {
      spanMap.request_bytes = String(span.requestBytes);
    }
    if (span.responseBytes !== undefined) {
      spanMap.response_bytes = String(span.responseBytes);
    }
    if (span.llmInputTokens !== undefined) {
      spanMap.llm_input_tokens = String(span.llmInputTokens);
    }
    if (span.llmOutputTokens !== undefined) {
      spanMap.llm_output_tokens = String(span.llmOutputTokens);
    }
    if (span.llmTotalTokens !== undefined) {
      spanMap.llm_total_tokens = String(span.llmTotalTokens);
    }
    if (span.llmModel) {
      spanMap.llm_model = span.llmModel;
    }
    if (span.llmProvider) {
      spanMap.llm_provider = span.llmProvider;
    }

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
  executor: (args: TArgs, traceContext: TraceContext | null) => Promise<TResult>,
  enrichSpan?: (result: TResult) => Partial<Pick<SpanData, 'llmInputTokens' | 'llmOutputTokens' | 'llmTotalTokens' | 'llmModel' | 'llmProvider'>>,
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
    let executorResult: TResult | undefined;

    try {
      // Execute with trace context for propagation
      const newContext: TraceContext = { traceId, parentSpanId: spanId };
      const result = await executor(args, newContext);
      resultType = typeof result;
      executorResult = result;
      return result;
    } catch (err) {
      success = false;
      error = err instanceof Error ? err.message : String(err);
      throw err;
    } finally {
      const endTime = Date.now() / 1000;
      const durationMs = (endTime - startTime) * 1000;

      let extraFields: Partial<SpanData> = {};
      if (success && enrichSpan && executorResult !== undefined) {
        try {
          extraFields = enrichSpan(executorResult);
        } catch {
          // Silently ignore enrichment errors
        }
      }

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
        ...extraFields,
      }).catch(() => {
        // Silently ignore publish errors
      });
    }
  };
}
