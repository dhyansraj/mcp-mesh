/**
 * MCP Mesh proxy implementation for dependency injection.
 *
 * Provides HTTP client proxies for calling remote MCP agents.
 */

import type { McpMeshAgent, DependencyKwargs } from "./types.js";

/**
 * Create an McpMeshAgent proxy for a resolved dependency.
 *
 * The returned object is callable (invokes the bound function)
 * and also has methods for calling other tools on the agent.
 */
export function createProxy(
  endpoint: string,
  capability: string,
  functionName: string,
  kwargs?: DependencyKwargs
): McpMeshAgent {
  const timeout = (kwargs?.timeout ?? 30) * 1000; // Convert to ms
  const retryCount = kwargs?.retryCount ?? 1;

  // The proxy function that calls the bound tool
  const proxyFn = async (
    args?: Record<string, unknown>
  ): Promise<string> => {
    return callMcpTool(endpoint, functionName, args, timeout, retryCount);
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
      ): Promise<string> => {
        return callMcpTool(endpoint, toolName, args, timeout, retryCount);
      },
      writable: false,
    },
  });

  return proxyFn as McpMeshAgent;
}

/**
 * Call an MCP tool via HTTP POST.
 *
 * Uses the MCP HTTP Streamable protocol:
 * POST /mcp with JSON-RPC 2.0 payload.
 */
async function callMcpTool(
  endpoint: string,
  toolName: string,
  args: Record<string, unknown> | undefined,
  timeout: number,
  retryCount: number
): Promise<string> {
  // Ensure endpoint ends with /mcp
  const mcpEndpoint = endpoint.endsWith("/mcp")
    ? endpoint
    : `${endpoint.replace(/\/$/, "")}/mcp`;

  const payload = {
    jsonrpc: "2.0",
    id: generateRequestId(),
    method: "tools/call",
    params: {
      name: toolName,
      arguments: args ?? {},
    },
  };

  let lastError: Error | null = null;

  for (let attempt = 0; attempt < retryCount; attempt++) {
    try {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), timeout);

      const response = await fetch(mcpEndpoint, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Accept: "application/json, text/event-stream",
        },
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
        return await parseSSEResponse(response);
      }

      // Handle JSON response
      const result = (await response.json()) as {
        error?: { message?: string };
        result?: unknown;
      };

      if (result.error) {
        throw new Error(
          `MCP error: ${result.error.message ?? JSON.stringify(result.error)}`
        );
      }

      // Extract content from result
      return extractContent(result.result);
    } catch (err) {
      lastError = err instanceof Error ? err : new Error(String(err));

      // Don't retry on abort (timeout)
      if (lastError.name === "AbortError") {
        throw new Error(`MCP call timed out after ${timeout}ms`);
      }

      // Retry on network errors
      if (attempt < retryCount - 1) {
        await sleep(100 * (attempt + 1)); // Exponential backoff
        continue;
      }
    }
  }

  throw lastError ?? new Error("MCP call failed");
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
 */
export function normalizeDependency(
  dep: string | { capability: string; tags?: string[]; version?: string }
): { capability: string; tags: string[]; version?: string } {
  if (typeof dep === "string") {
    return { capability: dep, tags: [] };
  }
  return {
    capability: dep.capability,
    tags: dep.tags ?? [],
    version: dep.version,
  };
}
