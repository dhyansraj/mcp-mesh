/**
 * SSE (Server-Sent Events) parsing utilities for MCP responses.
 *
 * FastMCP stateless HTTP stream returns responses in SSE format:
 * ```
 * event: message
 * data: {"jsonrpc":"2.0","id":123,"result":{...}}
 * ```
 *
 * This module provides utilities to parse these responses.
 */

/**
 * Parse a response that may be in SSE format or plain JSON.
 *
 * @param responseText - Raw response text from HTTP request
 * @returns Parsed JSON object
 * @throws Error if no data found in SSE response or JSON parse fails
 *
 * @example
 * ```typescript
 * // SSE format
 * const sse = "event: message\ndata: {\"result\":42}\n";
 * const result = parseSSEResponse(sse);
 * // => { result: 42 }
 *
 * // Plain JSON (passed through)
 * const json = '{"result":42}';
 * const result = parseSSEResponse(json);
 * // => { result: 42 }
 * ```
 */
export function parseSSEResponse<T = unknown>(responseText: string): T {
  // Check if it's SSE format (starts with "event:")
  if (responseText.startsWith("event:")) {
    const lines = responseText.split("\n");
    let jsonData = "";

    // Extract the last "data:" line (in case of multiple events)
    for (const line of lines) {
      if (line.startsWith("data: ")) {
        jsonData = line.slice(6); // Remove "data: " prefix
      }
    }

    if (!jsonData) {
      throw new Error("No data found in SSE response");
    }

    return JSON.parse(jsonData) as T;
  }

  // Plain JSON - parse directly
  return JSON.parse(responseText) as T;
}

/**
 * Check if a response text is in SSE format.
 */
export function isSSEResponse(responseText: string): boolean {
  return responseText.startsWith("event:");
}

/**
 * Extract all data payloads from an SSE stream.
 * Useful when multiple events are expected.
 *
 * @param responseText - Raw SSE response text
 * @returns Array of parsed JSON objects from each data line
 */
export function parseSSEStream<T = unknown>(responseText: string): T[] {
  const results: T[] = [];
  const lines = responseText.split("\n");

  for (const line of lines) {
    if (line.startsWith("data: ")) {
      const jsonData = line.slice(6);
      if (jsonData.trim()) {
        results.push(JSON.parse(jsonData) as T);
      }
    }
  }

  return results;
}
