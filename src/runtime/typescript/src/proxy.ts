/**
 * MCP Mesh proxy implementation for dependency injection.
 *
 * Provides HTTP client proxies for calling remote MCP agents.
 */

import { AsyncLocalStorage } from "node:async_hooks";
import { zodToJsonSchema } from "zod-to-json-schema";
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
 * Symbol stash for proxy dispatch metadata. Non-enumerable so it doesn't leak
 * via JSON.stringify(proxy) (which would expose endpoint, kwargs.customHeaders,
 * and any auth tokens user code put in customHeaders).
 *
 * Internal use only — read by agent.ts when serializing deps for worker
 * dispatch. User code should continue to read public properties (endpoint,
 * capability, functionName, kwargs) directly off the proxy if they need them.
 */
export const PROXY_DISPATCH_META = Symbol.for("@mcpmesh/sdk/proxy-dispatch-meta");

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

  // Stream options: always honor streamTimeout regardless of the `streaming`
  // kwarg. The unary path uses `options.timeout` (which is bumped to
  // streamTimeout only when streaming=true). For stream() the call is by
  // definition long-lived, so use streamTimeout unconditionally.
  const streamOptions: CallOptions = { ...options, timeout: options.streamTimeout };

  // Attach properties and methods. Public properties are non-enumerable so
  // JSON.stringify(proxy) doesn't leak endpoint/kwargs.customHeaders (which
  // may contain auth tokens). Matches pre-isolation baseline.
  Object.defineProperties(proxyFn, {
    endpoint: { value: endpoint, writable: false },
    capability: { value: capability, writable: false },
    functionName: { value: functionName, writable: false },
    kwargs: { value: kwargs, writable: false },
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
    stream: {
      value: (
        args?: Record<string, unknown>,
        callParams?: { headers?: Record<string, string> }
      ): AsyncIterable<string> => {
        return streamMcpTool(
          endpoint,
          functionName,
          args,
          streamOptions,
          capability,
          callParams?.headers
        );
      },
      writable: false,
      enumerable: false,
    },
  });

  // Internal: stash dispatch metadata under a non-enumerable Symbol so the
  // worker pool dispatcher can read it without depending on the public
  // properties (which we keep non-enumerable for the JSON.stringify safety
  // reason above).
  Object.defineProperty(proxyFn, PROXY_DISPATCH_META, {
    value: { endpoint, capability, functionName, kwargs },
    enumerable: false,
    writable: false,
    configurable: false,
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
  const meshTimeoutStr = mergedHeaders["x-mesh-timeout"];
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
        throw new Error(`MCP call timed out after ${effectiveTimeout}ms`);
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
 * Stream text chunks from a remote ``Stream[str]`` tool.
 *
 * Returns an async iterable that yields each chunk as the producer emits it
 * via MCP ``notifications/progress``. The final result message ends the
 * stream — its content is NOT yielded (matches Python's contract: "iterate
 * to get the whole stream").
 *
 * Wire protocol:
 * - POST /mcp with JSON-RPC ``tools/call`` and ``params._meta.progressToken``
 * - Server returns ``text/event-stream`` with one SSE event per JSON-RPC msg
 * - ``notifications/progress`` events with matching ``progressToken`` are
 *   yielded as ``params.message``
 * - The final ``result`` event ends the stream
 * - JSON-RPC ``error`` event throws
 *
 * NOTE: If the producer does not actually emit progress notifications, the
 * SSE response will only contain the final ``result`` message and this
 * iterable will yield nothing. (TS does not currently advertise
 * ``stream_type=text`` like Python; the soft-fallback isn't implemented.)
 *
 * Cancellation: when the consumer breaks out of the iteration, the underlying
 * ``fetch`` is aborted via ``AbortController`` and the reader is released.
 */
export async function* streamMcpTool(
  endpoint: string,
  toolName: string,
  args: Record<string, unknown> | undefined,
  options: CallOptions,
  capability: string,
  extraHeaders?: Record<string, string>
): AsyncGenerator<string, void, void> {
  // Ensure endpoint ends with /mcp
  const mcpEndpoint = endpoint.endsWith("/mcp")
    ? endpoint
    : `${endpoint.replace(/\/$/, "")}/mcp`;

  // Tracing: create span for this outgoing proxy stream call
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
      argsWithTrace = { ...(args ?? {}) };
      argsWithTrace._trace_id = traceCtx.traceId;
      argsWithTrace._parent_span = spanId;
      if (Object.keys(mergedHeaders).length > 0) {
        argsWithTrace._mesh_headers = mergedHeaders;
      }
    }
  } else {
    argsWithTrace = { ...(args ?? {}) };
    if (Object.keys(mergedHeaders).length > 0) {
      argsWithTrace._mesh_headers = mergedHeaders;
    }
  }

  // Generate progress token to correlate notifications with this call
  const progressToken = generateProgressToken();
  const requestId = generateRequestId();

  const payload = {
    jsonrpc: "2.0",
    id: requestId,
    method: "tools/call",
    params: {
      name: toolName,
      arguments: argsWithTrace,
      _meta: { progressToken },
    },
  };

  // Use X-Mesh-Timeout from propagated headers to override client timeout (#769)
  let effectiveTimeout = options.timeout;
  const meshTimeoutStr = mergedHeaders["x-mesh-timeout"];
  if (meshTimeoutStr) {
    const meshTimeoutMs = parseInt(meshTimeoutStr, 10) * 1000;
    if (!isNaN(meshTimeoutMs) && meshTimeoutMs > 0) {
      effectiveTimeout = meshTimeoutMs;
    }
  }
  // Stream timeout defaults are usually generous (300s) but a partial caller
  // options object could leave this undefined or non-positive — that would
  // cause setTimeout to fire on next tick and abort the stream immediately.
  // Fall back to the buffered call default in that case.
  if (typeof effectiveTimeout !== "number" || effectiveTimeout <= 0) {
    effectiveTimeout = DEFAULT_CALL_OPTIONS.streamTimeout!;
  }

  const bodyStr = JSON.stringify(payload);
  const requestBytes = Buffer.byteLength(bodyStr, "utf8");

  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), effectiveTimeout);

  // Build headers — FastMCP stateless HTTP requires BOTH content types in
  // Accept (it returns SSE for streaming responses; missing application/json
  // here yields 406 Not Acceptable). Matches the buffered callMcpTool path.
  const headers: Record<string, string> = {
    ...(options.customHeaders ?? {}),
    "Content-Type": "application/json",
    Accept: "application/json, text/event-stream",
  };
  if (traceCtx && spanId) {
    Object.assign(headers, createTraceHeaders(traceCtx.traceId, spanId));
  }
  for (const [key, value] of Object.entries(mergedHeaders)) {
    headers[key] = value;
  }
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
  const dispatcher = getDispatcher(mcpEndpoint);
  if (dispatcher) {
    fetchOptions.dispatcher = dispatcher;
  }

  let success = true;
  let errorMsg: string | null = null;
  let reader: ReadableStreamDefaultReader<Uint8Array> | undefined;

  try {
    const response = await fetch(mcpEndpoint, fetchOptions as RequestInit);
    clearTimeout(timeoutId);

    if (!response.ok) {
      throw new Error(
        `MCP stream call failed: ${response.status} ${response.statusText}`
      );
    }

    if (!response.body) {
      throw new Error("MCP stream call: no response body");
    }

    reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let streamDone = false;

    while (!streamDone) {
      const { done, value } = await reader.read();
      if (done) break;

      // Normalize CRLF to LF so the same parser handles either line ending
      buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n");

      // SSE events are separated by blank lines (\n\n)
      let sep: number;
      while ((sep = buffer.indexOf("\n\n")) !== -1) {
        const rawEvent = buffer.slice(0, sep);
        buffer = buffer.slice(sep + 2);

        // Collect data: lines from this event (per spec, multi-line data joined by \n)
        const dataLines: string[] = [];
        for (const line of rawEvent.split("\n")) {
          if (line.startsWith("data: ")) {
            dataLines.push(line.slice(6));
          } else if (line.startsWith("data:")) {
            // Allow "data:" with no space (defensive)
            dataLines.push(line.slice(5));
          }
        }
        if (dataLines.length === 0) continue;
        const data = dataLines.join("\n");
        if (!data) continue;

        // Parse the JSON-RPC message
        let msg: {
          jsonrpc?: string;
          id?: string | number;
          method?: string;
          params?: { progressToken?: string | number; message?: string; data?: string };
          result?: unknown;
          error?: { message?: string; code?: number };
        };
        try {
          msg = JSON.parse(data);
        } catch {
          // Ignore non-JSON data events (defensive)
          continue;
        }

        // Progress notification: yield message if it matches our token
        if (msg.method === "notifications/progress" && msg.params) {
          if (msg.params.progressToken === progressToken) {
            // FastMCP sends ``message``; some implementations may send ``data``
            const chunk =
              typeof msg.params.message === "string"
                ? msg.params.message
                : typeof msg.params.data === "string"
                  ? msg.params.data
                  : null;
            if (chunk !== null) {
              yield chunk;
            }
          }
          continue;
        }

        // Final response for our request: end the stream
        if (msg.id !== undefined && msg.id === requestId) {
          if (msg.error) {
            const em = msg.error.message ?? JSON.stringify(msg.error);
            throw new Error(`MCP error: ${em}`);
          }
          // result arrived — done; do NOT yield the buffered final result
          streamDone = true;
          break;
        }
      }
    }
  } catch (err) {
    success = false;
    errorMsg = err instanceof Error ? err.message : String(err);
    if (err instanceof Error && err.name === "AbortError") {
      throw new Error(`MCP stream call timed out after ${effectiveTimeout}ms`);
    }
    throw err;
  } finally {
    clearTimeout(timeoutId);
    // Release the reader; if the caller broke out of the iteration mid-stream
    // the underlying fetch must be aborted so the connection isn't leaked.
    if (reader) {
      try {
        await reader.cancel();
      } catch {
        // ignore
      }
    }
    // Abort the fetch; safe to call even if already completed
    try {
      controller.abort();
    } catch {
      // ignore
    }
    publishProxySpan(
      traceCtx,
      spanId,
      startTime,
      toolName,
      capability,
      endpoint,
      success,
      errorMsg,
      "stream",
      requestBytes,
    );
  }
}

/**
 * Generate a short random progress token for correlating notifications
 * with the originating ``tools/call`` request.
 */
function generateProgressToken(): string {
  // Prefer crypto.randomUUID if available; fall back to a Math.random-based ID
  // (Node 16+/19+ has crypto.randomUUID; the fallback keeps tests light).
  try {
    const cryptoObj = (globalThis as { crypto?: { randomUUID?: () => string } }).crypto;
    if (cryptoObj && typeof cryptoObj.randomUUID === "function") {
      return cryptoObj.randomUUID();
    }
  } catch {
    // ignore
  }
  return `pt_${Date.now()}_${Math.random().toString(36).slice(2, 10)}`;
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
 *
 * Issue #547: when expectedSchema (Zod) is supplied, eagerly extract the raw
 * JSON Schema (cheap) but defer Rust-normalizer invocation to the heartbeat
 * pipeline (Python parity). matchMode defaults to "subset" when expectedSchema
 * is set; a matchMode without expectedSchema logs a warning and is dropped.
 */
export function normalizeDependency(dep: DependencySpec): NormalizedDependency {
  if (typeof dep === "string") {
    return { capability: dep, tags: [] };
  }
  const result: NormalizedDependency = {
    capability: dep.capability,
    tags: dep.tags ?? [],
    version: dep.version,
  };

  if (dep.expectedSchema !== undefined) {
    let raw: object | undefined;
    try {
      // $refStrategy: "root" so recursive expectedSchema definitions survive
      // (mirrors agent.ts producer-side conversion).
      raw = zodToJsonSchema(dep.expectedSchema, { $refStrategy: "root" }) as object;
    } catch (err) {
      console.warn(
        `[mesh] dependency '${dep.capability}': failed to convert expectedSchema to JSON Schema: ${
          err instanceof Error ? err.message : String(err)
        }`
      );
    }
    if (raw !== undefined) {
      result.expectedSchemaRaw = raw;
      result.matchMode = dep.matchMode ?? "subset";
    }
  } else if (dep.matchMode !== undefined) {
    console.warn(
      `[mesh] dependency '${dep.capability}': matchMode set but no expectedSchema; schema check will be skipped`
    );
  }

  return result;
}
