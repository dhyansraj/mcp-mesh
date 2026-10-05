/**
 * Shared timeout utilities for fetch requests.
 */

/**
 * Check if an error is a timeout (AbortError).
 */
export function isTimeoutError(error: unknown): boolean {
  return error instanceof Error && error.name === "AbortError";
}
