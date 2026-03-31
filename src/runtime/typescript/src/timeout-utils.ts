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
  options: RequestInit & { timeout?: number; dispatcher?: unknown },
): Promise<Response> {
  const { timeout: timeoutMs, dispatcher, ...fetchOptions } = options;

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const opts: any = { ...fetchOptions };
  if (dispatcher) opts.dispatcher = dispatcher;

  if (!timeoutMs) {
    return fetch(url, opts);
  }

  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

  try {
    return await fetch(url, { ...opts, signal: controller.signal });
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
