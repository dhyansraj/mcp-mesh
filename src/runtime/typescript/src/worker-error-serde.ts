/**
 * Shared error (de)serialization for the tool worker boundary.
 *
 * `worker_threads` postMessage uses the structured-clone algorithm, which does
 * NOT preserve an Error subclass's prototype: a `UserError` (or any subclass)
 * thrown inside a worker arrives on the main thread as a plain object. If we
 * naively rebuild it as `new Error(message)`, the main-thread `instanceof
 * UserError` check in fastmcp fails, and fastmcp emits its GENERIC error branch
 * — prefixing the message with `Tool '<name>' execution failed: ...`. That
 * prefix corrupts reserved JSON envelopes (issue #1278's `claim_superseded`,
 * issue #1273's `dependency_unavailable`) so the consumer's `JSON.parse` fails.
 *
 * These two functions are the matched halves of ONE wire contract and MUST stay
 * in sync, so they live together here (worker side calls {@link serializeError},
 * main-thread pool calls {@link deserializeError}). Keeping them co-located also
 * makes the round-trip unit-testable from the main thread — `tool-worker-entry`
 * throws at import time when loaded outside a worker, so its copy could not be
 * exercised directly.
 */
import { UserError } from "fastmcp";

export interface SerializedError {
  name?: string;
  message?: string;
  stack?: string;
  code?: string | number;
  cause?: SerializedError;
  /**
   * Issue #1278: set when the source error was a fastmcp `UserError` (or a
   * subclass such as `MeshSupersededError`). The main-thread deserializer uses
   * this to reconstruct a real `UserError` so `instanceof UserError` survives
   * the worker hop and fastmcp emits the clean `content:[{text: message}]`
   * envelope instead of the generic `Tool '...' execution failed:` branch.
   */
  isUserError?: boolean;
  /**
   * Issue #1278: `UserError.extras`, carried only when structured-cloneable so
   * a non-cloneable extras can never break the postMessage that carries the
   * (always cloneable) reserved-envelope message.
   */
  extras?: unknown;
}

/**
 * Flatten an Error (or arbitrary throw) into a structured-clone-safe shape for
 * postMessage. Preserves `name`, walks `cause`, and — issue #1278 — flags
 * `UserError` identity so the main thread can rebuild a real `UserError`.
 */
export function serializeError(err: unknown): SerializedError {
  if (!(err instanceof Error)) {
    return { name: "Error", message: String(err) };
  }
  const out: SerializedError = {
    name: err.name,
    message: err.message,
    stack: err.stack,
  };
  const errAny = err as Error & { code?: string | number; cause?: unknown };
  if (errAny.code !== undefined) out.code = errAny.code;
  if (errAny.cause !== undefined) out.cause = serializeError(errAny.cause);
  // Issue #1278: preserve UserError identity across the worker boundary.
  if (err instanceof UserError) {
    out.isUserError = true;
    const extras = (err as UserError).extras;
    if (extras !== undefined) {
      // Only carry extras if it survives structured clone — a non-cloneable
      // extras must NOT break the postMessage that carries the (always
      // cloneable) reserved-envelope message.
      try {
        structuredClone(extras);
        out.extras = extras;
      } catch {
        /* drop non-cloneable extras; message still crosses intact */
      }
    }
  }
  return out;
}

/**
 * Rebuild an Error on the main thread from its {@link SerializedError} shape.
 *
 * Issue #1278: when `isUserError` is set, reconstruct a real fastmcp
 * `UserError` (the SAME class the fastmcp tool handler and agent.ts use) so
 * `instanceof UserError` holds and fastmcp emits the clean envelope. The
 * `message` is preserved EXACTLY — the reserved JSON envelope must survive
 * verbatim. `name` is restored afterwards for diagnostics (fastmcp's clean
 * branch keys off `message`/`extras`, not `name`). A non-UserError rebuilds as
 * a plain `Error` and takes fastmcp's generic branch, unchanged.
 */
export function deserializeError(
  serialized: SerializedError | undefined | null,
): Error {
  const message = serialized?.message ?? "worker error";
  const err = (
    serialized?.isUserError
      ? new UserError(
          message,
          serialized.extras as ConstructorParameters<typeof UserError>[1],
        )
      : new Error(message)
  ) as Error & { code?: string | number; cause?: Error };
  if (serialized?.name) err.name = serialized.name;
  if (serialized?.stack) err.stack = serialized.stack;
  if (serialized?.code !== undefined) err.code = serialized.code;
  if (serialized?.cause !== undefined) {
    err.cause = deserializeError(serialized.cause);
  }
  return err;
}
