/**
 * Shared timeout utilities for fetch requests.
 *
 * Consolidates the duplicated AbortController + setTimeout pattern
 * used across proxy.ts, llm-agent.ts, and other HTTP callers.
 */

/**
 * Execute a fetch request with a timeout.
 * Automatically handles AbortController setup and cleanup.
 *
 * @param url - The URL to fetch
 * @param options - Standard RequestInit options plus an optional `timeout` in ms
 * @returns The fetch Response
 */
export async function fetchWithTimeout(
  url: string,
  options: RequestInit & { timeout?: number },
): Promise<Response> {
  const { timeout: timeoutMs, ...fetchOptions } = options;

  if (!timeoutMs) {
    return fetch(url, fetchOptions);
  }

  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

  try {
    return await fetch(url, { ...fetchOptions, signal: controller.signal });
  } finally {
    clearTimeout(timeoutId);
  }
}

/**
 * Check if an error is a timeout (AbortError).
 */
export function isTimeoutError(error: unknown): boolean {
  return error instanceof Error && error.name === "AbortError";
}
