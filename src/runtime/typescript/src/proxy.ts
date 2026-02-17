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
} from "./tracing.js";

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
  const timeout = (kwargs?.timeout ?? 30) * 1000; // Convert to ms
  const maxAttempts = kwargs?.maxAttempts ?? 1;

  // The proxy function that calls the bound tool
  // Returns parsed object (like Python) or raw string if not JSON
  const proxyFn = async (
    args?: Record<string, unknown>
  ): Promise<unknown> => {
    const result = await callMcpTool(endpoint, functionName, args, timeout, maxAttempts, capability);
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
        args?: Record<string, unknown>
      ): Promise<unknown> => {
        const result = await callMcpTool(endpoint, toolName, args, timeout, maxAttempts, capability);
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
async function callMcpTool(
  endpoint: string,
  toolName: string,
  args: Record<string, unknown> | undefined,
  timeout: number,
  maxAttempts: number,
  capability: string
): Promise<string> {
  // Ensure endpoint ends with /mcp
  const mcpEndpoint = endpoint.endsWith("/mcp")
    ? endpoint
    : `${endpoint.replace(/\/$/, "")}/mcp`;

  // Tracing: create span for this outgoing proxy call
  // Use AsyncLocalStorage to get trace context for the current async execution
  const traceCtx = getCurrentTraceContext();
  const spanId = traceCtx ? generateSpanId() : null;
  const startTime = Date.now() / 1000;

  // Build arguments with trace context injection (for downstream agents)
  // This is the fallback mechanism since fastmcp doesn't expose HTTP headers
  const argsWithTrace: Record<string, unknown> = { ...(args ?? {}) };
  if (traceCtx && spanId) {
    // Inject trace context into arguments - downstream agent will extract these
    // spanId is the proxy span we're about to publish, which becomes child's parent
    argsWithTrace._trace_id = traceCtx.traceId;
    argsWithTrace._parent_span = spanId;
  }
  // Inject propagated headers into args for downstream agents
  const propagatedHeaders = getCurrentPropagatedHeaders();
  if (Object.keys(propagatedHeaders).length > 0) {
    argsWithTrace._mesh_headers = { ...propagatedHeaders };
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

  let lastError: Error | null = null;

  for (let attempt = 0; attempt < maxAttempts; attempt++) {
    try {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), timeout);

      // Build headers with trace context propagation
      const headers: Record<string, string> = {
        "Content-Type": "application/json",
        Accept: "application/json, text/event-stream",
      };

      // Propagate trace context to downstream agent
      if (traceCtx && spanId) {
        Object.assign(headers, createTraceHeaders(traceCtx.traceId, spanId));
      }
      // Inject propagated headers as HTTP headers
      const propHeaders = getCurrentPropagatedHeaders();
      for (const [key, value] of Object.entries(propHeaders)) {
        headers[key] = value;
      }

      const response = await fetch(mcpEndpoint, {
        method: "POST",
        headers,
        body: JSON.stringify(payload),
        signal: controller.signal,
      });

      clearTimeout(timeoutId);

      if (!response.ok) {
        throw new Error(
          `MCP call failed: ${response.status} ${response.statusText}`
        );
      }

      const contentType = response.headers.get("content-type") ?? "";

      // Handle SSE streaming response
      if (contentType.includes("text/event-stream")) {
        const sseResult = await parseSSEResponse(response);
        // Publish success span
        publishProxySpan(traceCtx, spanId, startTime, toolName, capability, endpoint, true, null, typeof sseResult);
        return sseResult;
      }

      // Handle JSON response
      const result = (await response.json()) as {
        error?: { message?: string };
        result?: unknown;
      };

      if (result.error) {
        const errorMsg = result.error.message ?? JSON.stringify(result.error);
        // Publish error span
        publishProxySpan(traceCtx, spanId, startTime, toolName, capability, endpoint, false, errorMsg, "error");
        throw new Error(`MCP error: ${errorMsg}`);
      }

      // Extract content from result
      const content = extractContent(result.result);
      // Publish success span
      publishProxySpan(traceCtx, spanId, startTime, toolName, capability, endpoint, true, null, typeof content);
      return content;
    } catch (err) {
      lastError = err instanceof Error ? err : new Error(String(err));

      // Don't retry on abort (timeout)
      if (lastError.name === "AbortError") {
        publishProxySpan(traceCtx, spanId, startTime, toolName, capability, endpoint, false, "timeout", "error");
        throw new Error(`MCP call timed out after ${timeout}ms`);
      }

      // Retry on network errors
      if (attempt < maxAttempts - 1) {
        await sleep(100 * (attempt + 1)); // Exponential backoff
        continue;
      }
    }
  }

  // All retries failed
  publishProxySpan(traceCtx, spanId, startTime, toolName, capability, endpoint, false, lastError?.message ?? "unknown", "error");
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
  resultType: string
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
  }).catch(() => {
    // Silently ignore publish errors
  });
}

/**
 * Parse SSE response from MCP HTTP Streamable transport.
 */
async function parseSSEResponse(response: Response): Promise<string> {
  const reader = response.body?.getReader();
  if (!reader) {
    throw new Error("No response body");
  }

  const decoder = new TextDecoder();
  let buffer = "";
  let result = "";

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
 * Extract content from MCP CallToolResult.
 *
 * Handles various content formats:
 * - { content: [{ type: "text", text: "..." }] }
 * - { content: "..." }
 * - Direct string
 */
function extractContent(result: unknown): string {
  if (typeof result === "string") {
    return result;
  }

  if (result && typeof result === "object") {
    const obj = result as Record<string, unknown>;

    // Handle { content: [...] } format
    if (Array.isArray(obj.content)) {
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
