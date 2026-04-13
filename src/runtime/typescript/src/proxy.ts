/**
 * MCP Mesh proxy implementation for dependency injection.
 *
 * Provides HTTP client proxies for calling remote MCP agents.
 */

import { AsyncLocalStorage } from "node:async_hooks";
import type { McpMeshTool, DependencyKwargs, DependencySpec, NormalizedDependency } from "./types.js";
import type { TraceContext } from "./tracing.js";
import {
  generateSpanId,
  publishTraceSpan,
  createTraceHeaders,
  matchesPropagateHeader,
  injectTraceContext,
} from "./tracing.js";
import { isTimeoutError } from "./timeout-utils.js";
import { getDispatcher } from "./http-pool.js";

/** Options for callMcpTool, derived from DependencyKwargs. */
export interface CallOptions {
  timeout: number;
  maxAttempts: number;
  streamTimeout: number;
  customHeaders?: Record<string, string>;
  retryDelay: number;
  retryBackoff: number;
  maxResponseSize: number;
}

/** Default CallOptions for internal callers that don't go through createProxy. */
export const DEFAULT_CALL_OPTIONS: CallOptions = {
  timeout: 30_000,
  maxAttempts: 1,
  streamTimeout: 300_000,
  retryDelay: 100,
  retryBackoff: 2.0,
  maxResponseSize: 10 * 1024 * 1024,
};

/**
 * AsyncLocalStorage for trace context - provides async-safe context propagation.
 * Unlike module-level variables, this correctly handles concurrent requests
 * without trace context bleeding between them.
 */
const traceContextStorage = new AsyncLocalStorage<TraceContext>();

/**
 * AsyncLocalStorage for propagated headers - provides async-safe header propagation.
 */
const propagatedHeadersStorage = new AsyncLocalStorage<Record<string, string>>();

/**
 * Run a function with propagated headers context.
 */
export function runWithPropagatedHeaders<T>(
  headers: Record<string, string>,
  fn: () => T | Promise<T>
): T | Promise<T> {
  return propagatedHeadersStorage.run(headers, fn);
}

/**
 * Get the current propagated headers.
 */
export function getCurrentPropagatedHeaders(): Record<string, string> {
  return propagatedHeadersStorage.getStore() ?? {};
}

/**
 * Run a function with trace context.
 * The context is automatically propagated to all async operations within the callback.
 * This is the preferred way to set trace context for tool execution.
 */
export function runWithTraceContext<T>(
  ctx: TraceContext,
  fn: () => T | Promise<T>
): T | Promise<T> {
  return traceContextStorage.run(ctx, fn);
}

/**
 * Get the current trace context.
 * Returns the trace context for the current async execution context,
 * or null if not within a traced context.
 */
export function getCurrentTraceContext(): TraceContext | null {
  return traceContextStorage.getStore() ?? null;
}

/**
 * @deprecated Use runWithTraceContext() instead for async-safe context propagation.
 * This function is kept for backward compatibility but does nothing.
 */
export function setCurrentTraceContext(_ctx: TraceContext | null): void {
  // No-op - use runWithTraceContext() instead
  // This is kept for backward compatibility with any external code
}

/**
 * Create an McpMeshTool proxy for a resolved dependency.
 *
 * The returned object is callable (invokes the bound function)
 * and also has methods for calling other tools on the agent.
 */
export function createProxy(
  endpoint: string,
  capability: string,
  functionName: string,
  kwargs?: DependencyKwargs
): McpMeshTool {
  const options: CallOptions = {
    timeout: (kwargs?.timeout ?? 30) * 1000,
    maxAttempts: kwargs?.maxAttempts ?? 1,
    streamTimeout: (kwargs?.streamTimeout ?? 300) * 1000,
    customHeaders: kwargs?.customHeaders,
    retryDelay: (kwargs?.retryDelay ?? 0.1) * 1000,
    retryBackoff: kwargs?.retryBackoff ?? 2.0,
    maxResponseSize: kwargs?.maxResponseSize ?? 10 * 1024 * 1024,
  };
  // Use streamTimeout when streaming is enabled
  if (kwargs?.streaming) {
    options.timeout = options.streamTimeout;
  }

  // The proxy function that calls the bound tool
  // Returns parsed object (like Python) or raw string if not JSON
  // Multi-content results (resource_link, image, etc.) are returned as-is
  const proxyFn = async (
    args?: Record<string, unknown>,
    callParams?: { headers?: Record<string, string> }
  ): Promise<unknown> => {
    const result = await callMcpTool(endpoint, functionName, args, options, capability, callParams?.headers);
    // Multi-content results are returned as structured objects
    if (typeof result === "object") {
      return result;
    }
    // Parse JSON if possible, otherwise return raw string (matches Python behavior)
    try {
      return JSON.parse(result);
    } catch {
      return result;
    }
  };

  // Attach properties and methods
  Object.defineProperties(proxyFn, {
    endpoint: { value: endpoint, writable: false },
    capability: { value: capability, writable: false },
    functionName: { value: functionName, writable: false },
    isAvailable: { value: true, writable: false },
    callTool: {
      value: async (
        toolName: string,
        args?: Record<string, unknown>,
        callParams?: { headers?: Record<string, string> }
      ): Promise<unknown> => {
        const result = await callMcpTool(endpoint, toolName, args, options, capability, callParams?.headers);
        if (typeof result === "object") {
          return result;
        }
        try {
          return JSON.parse(result);
        } catch {
          return result;
        }
      },
      writable: false,
    },
  });

  return proxyFn as McpMeshTool;
}

/**
 * Call an MCP tool via HTTP POST.
 *
 * Uses the MCP HTTP Streamable protocol:
 * POST /mcp with JSON-RPC 2.0 payload.
 * Includes distributed tracing: propagates trace context and publishes spans.
 */
export async function callMcpTool(
  endpoint: string,
  toolName: string,
  args: Record<string, unknown> | undefined,
  options: CallOptions,
  capability: string,
  extraHeaders?: Record<string, string>
): Promise<string | MultiContentResult> {
  // Ensure endpoint ends with /mcp
  const mcpEndpoint = endpoint.endsWith("/mcp")
    ? endpoint
    : `${endpoint.replace(/\/$/, "")}/mcp`;

  // Tracing: create span for this outgoing proxy call
  // Use AsyncLocalStorage to get trace context for the current async execution
  const traceCtx = getCurrentTraceContext();
  const spanId = traceCtx ? generateSpanId() : null;
  const startTime = Date.now() / 1000;

  // Build merged headers: session propagated + per-call (per-call wins, filtered by allowlist)
  const propagatedHeaders = getCurrentPropagatedHeaders();
  const mergedHeaders: Record<string, string> = { ...propagatedHeaders };
  if (extraHeaders) {
    for (const [key, value] of Object.entries(extraHeaders)) {
      if (matchesPropagateHeader(key)) {
        mergedHeaders[key.toLowerCase()] = value;
      }
    }
  }

  // Build arguments with trace context injection via Rust core
  let argsWithTrace: Record<string, unknown>;
  if (traceCtx && spanId) {
    try {
      const argsJson = JSON.stringify(args ?? {});
      const headersJson = Object.keys(mergedHeaders).length > 0 ? JSON.stringify(mergedHeaders) : undefined;
      const injectedJson = injectTraceContext(argsJson, traceCtx.traceId, spanId, headersJson);
      argsWithTrace = JSON.parse(injectedJson);
    } catch {
      // Fallback to manual injection
      argsWithTrace = { ...(args ?? {}) };
      argsWithTrace._trace_id = traceCtx.traceId;
      argsWithTrace._parent_span = spanId;
      if (Object.keys(mergedHeaders).length > 0) {
        argsWithTrace._mesh_headers = mergedHeaders;
      }
    }
  } else {
    argsWithTrace = { ...(args ?? {}) };
    // Still inject propagated headers even without trace context
    if (Object.keys(mergedHeaders).length > 0) {
      argsWithTrace._mesh_headers = mergedHeaders;
    }
  }

  const payload = {
    jsonrpc: "2.0",
    id: generateRequestId(),
    method: "tools/call",
    params: {
      name: toolName,
      arguments: argsWithTrace,
    },
  };

  // Use X-Mesh-Timeout from propagated headers to override client timeout (#769).
  // This ensures the client-side AbortController doesn't kill the call before
  // the registry proxy's timeout expires.
  let effectiveTimeout = options.timeout;
  const meshTimeoutStr = mergedHeaders["x-mesh-timeout"] || headers["X-Mesh-Timeout"];
  if (meshTimeoutStr) {
    const meshTimeoutMs = parseInt(meshTimeoutStr, 10) * 1000;
    if (!isNaN(meshTimeoutMs) && meshTimeoutMs > 0) {
      effectiveTimeout = meshTimeoutMs;
    }
  }

  let lastError: Error | null = null;
  const bodyStr = JSON.stringify(payload);
  const requestBytes = Buffer.byteLength(bodyStr, "utf8");

  for (let attempt = 0; attempt < options.maxAttempts; attempt++) {
    try {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), effectiveTimeout);

      // Build headers: custom headers first, then protocol-required headers override
      const headers: Record<string, string> = {
        ...(options.customHeaders ?? {}),
        "Content-Type": "application/json",
        Accept: "application/json, text/event-stream",
      };

      // Propagate trace context (higher priority)
      if (traceCtx && spanId) {
        Object.assign(headers, createTraceHeaders(traceCtx.traceId, spanId));
      }
      // Inject merged headers (highest priority)
      for (const [key, value] of Object.entries(mergedHeaders)) {
        headers[key] = value;
      }

      // Set X-Mesh-Timeout for registry proxy (#769). If already propagated, keep it.
      if (!headers["X-Mesh-Timeout"] && !headers["x-mesh-timeout"]) {
        const callTimeout = process.env.MCP_MESH_CALL_TIMEOUT || String(Math.floor(options.timeout / 1000));
        headers["X-Mesh-Timeout"] = callTimeout;
      }

      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const fetchOptions: Record<string, any> = {
        method: "POST",
        headers,
        body: bodyStr,
        signal: controller.signal,
      };

      // Use pooled dispatcher for connection reuse
      const dispatcher = getDispatcher(mcpEndpoint);
      if (dispatcher) {
        fetchOptions.dispatcher = dispatcher;
      }

      const response = await fetch(mcpEndpoint, fetchOptions as RequestInit);

      clearTimeout(timeoutId);

      if (!response.ok) {
        throw new Error(
          `MCP call failed: ${response.status} ${response.statusText}`
        );
      }

      // Check response size against limit
      const contentLength = parseInt(response.headers.get("content-length") ?? "0", 10);
      if (contentLength > 0 && contentLength > options.maxResponseSize) {
        throw new Error(
          `Response size ${contentLength} bytes exceeds limit of ${options.maxResponseSize} bytes`
        );
      }

      const contentType = response.headers.get("content-type") ?? "";

      // Handle SSE streaming response
      if (contentType.includes("text/event-stream")) {
        const sseResult = await parseSSEResponse(response);
        // Estimate response size from content-length header (exact size not available for SSE)
        const sseResponseBytes = contentLength > 0 ? contentLength : undefined;
        // Publish success span
        publishProxySpan(traceCtx, spanId, startTime, toolName, capability, endpoint, true, null, typeof sseResult, requestBytes, sseResponseBytes);
        return sseResult;
      }

      // Handle JSON response — read as text to measure byte size
      const responseText = await response.text();
      const responseBytes = Buffer.byteLength(responseText, "utf8");
      const result = JSON.parse(responseText) as {
        error?: { message?: string };
        result?: unknown;
      };

      if (result.error) {
        const errorMsg = result.error.message ?? JSON.stringify(result.error);
        // Publish error span
        publishProxySpan(traceCtx, spanId, startTime, toolName, capability, endpoint, false, errorMsg, "error", requestBytes, responseBytes);
        throw new Error(`MCP error: ${errorMsg}`);
      }

      // Extract content from result
      const content = extractContent(result.result);
      // Publish success span
      publishProxySpan(traceCtx, spanId, startTime, toolName, capability, endpoint, true, null, typeof content, requestBytes, responseBytes);
      return content;
    } catch (err) {
      lastError = err instanceof Error ? err : new Error(String(err));

      // Don't retry on abort (timeout)
      if (isTimeoutError(lastError)) {
        publishProxySpan(traceCtx, spanId, startTime, toolName, capability, endpoint, false, "timeout", "error", requestBytes);
        throw new Error(`MCP call timed out after ${options.timeout}ms`);
      }

      // Retry on network errors
      if (attempt < options.maxAttempts - 1) {
        await sleep(options.retryDelay * Math.pow(options.retryBackoff, attempt));
        continue;
      }
    }
  }

  // All retries failed
  publishProxySpan(traceCtx, spanId, startTime, toolName, capability, endpoint, false, lastError?.message ?? "unknown", "error", requestBytes);
  throw lastError ?? new Error("MCP call failed");
}

/**
 * Helper to publish a proxy call span (fire and forget).
 */
function publishProxySpan(
  traceCtx: TraceContext | null,
  spanId: string | null,
  startTime: number,
  _toolName: string,
  _capability: string,
  endpoint: string,
  success: boolean,
  error: string | null,
  resultType: string,
  requestBytes?: number,
  responseBytes?: number,
): void {
  if (!traceCtx || !spanId) return;

  const endTime = Date.now() / 1000;
  const durationMs = (endTime - startTime) * 1000;

  // Fire and forget - don't await
  publishTraceSpan({
    traceId: traceCtx.traceId,
    spanId,
    parentSpan: traceCtx.parentSpanId,
    functionName: "proxy_call_wrapper",
    startTime,
    endTime,
    durationMs,
    success,
    error,
    resultType,
    argsCount: 0,
    kwargsCount: 0,
    dependencies: [endpoint],
    injectedDependencies: 0,
    meshPositions: [],
    requestBytes,
    responseBytes,
  }).catch(() => {
    // Silently ignore publish errors
  });
}

/**
 * Parse SSE response from MCP HTTP Streamable transport.
 */
async function parseSSEResponse(response: Response): Promise<string | MultiContentResult> {
  const reader = response.body?.getReader();
  if (!reader) {
    throw new Error("No response body");
  }

  const decoder = new TextDecoder();
  let buffer = "";
  let result: string | MultiContentResult = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });

    // Parse SSE events
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? ""; // Keep incomplete line

    for (const line of lines) {
      if (line.startsWith("data: ")) {
        const data = line.slice(6);
        if (data === "[DONE]") continue;

        try {
          const event = JSON.parse(data);

          // Handle JSON-RPC response
          const jsonRpcEvent = event as { result?: unknown; error?: { message?: string } };
          if (jsonRpcEvent.result) {
            result = extractContent(jsonRpcEvent.result);
          } else if (jsonRpcEvent.error) {
            throw new Error(
              `MCP error: ${jsonRpcEvent.error.message ?? JSON.stringify(jsonRpcEvent.error)}`
            );
          }
        } catch (e) {
          // Ignore parse errors for non-JSON data events
          if (!(e instanceof SyntaxError)) throw e;
        }
      }
    }
  }

  return result;
}

/**
 * Multi-content result returned when MCP response contains non-text content
 * items (resource_link, image, embedded_resource, etc.).
 */
export interface MultiContentResult {
  type: "multi_content";
  content: Record<string, unknown>[];
}

/**
 * Extract content from MCP CallToolResult.
 *
 * Handles various content formats:
 * - { content: [{ type: "text", text: "..." }] }
 * - { content: "..." }
 * - Direct string
 *
 * If ALL content items are text, returns a joined string (backward compat).
 * If mixed content (resource_link, image, embedded_resource, etc.), returns
 * a structured MultiContentResult preserving all content items.
 */
export function extractContent(result: unknown): string | MultiContentResult {
  if (typeof result === "string") {
    return result;
  }

  if (result && typeof result === "object") {
    const obj = result as Record<string, unknown>;

    // Handle { content: [...] } format
    if (Array.isArray(obj.content)) {
      // Check if all items are text-only (type "text" or plain strings)
      const allText = obj.content.every(
        (item: unknown) =>
          typeof item === "string" ||
          (item && typeof item === "object" && (item as Record<string, unknown>).type === "text")
      );

      if (allText) {
        // Backward compatible: join text items into a single string
        const textParts: string[] = [];
        for (const item of obj.content) {
          if (item && typeof item === "object" && "text" in item) {
            textParts.push(String((item as { text: unknown }).text));
          } else if (typeof item === "string") {
            textParts.push(item);
          }
        }
        const text = textParts.join("");

        // Try to parse as JSON if it looks like JSON
        if (text.startsWith("{") || text.startsWith("[")) {
          try {
            return JSON.stringify(JSON.parse(text));
          } catch {
            return text;
          }
        }
        return text;
      }

      // Mixed content: preserve all items as structured data
      return {
        type: "multi_content",
        content: obj.content.map((item: unknown) => {
          if (typeof item === "string") {
            return { type: "text", text: item };
          }
          return item as Record<string, unknown>;
        }),
      };
    }

    // Handle { content: "..." } format
    if (typeof obj.content === "string") {
      return obj.content;
    }

    // Return JSON stringified
    return JSON.stringify(result);
  }

  return String(result);
}

/**
 * Generate a unique request ID.
 */
function generateRequestId(): string {
  return `req_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
}

/**
 * Sleep for a given duration.
 */
function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * Normalize a DependencySpec to canonical form.
 * Handles both simple string dependencies and full specs with tag-level OR alternatives.
 */
export function normalizeDependency(dep: DependencySpec): NormalizedDependency {
  if (typeof dep === "string") {
    return { capability: dep, tags: [] };
  }
  return {
    capability: dep.capability,
    tags: dep.tags ?? [],
    version: dep.version,
  };
}
