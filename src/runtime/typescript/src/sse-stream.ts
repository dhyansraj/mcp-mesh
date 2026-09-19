/**
 * SSE streaming helper for Express route handlers.
 *
 * Pipes any ``AsyncIterable<string>`` to an Express ``Response`` as
 * ``text/event-stream``. Designed to be called from inside a ``mesh.route``
 * handler — for example, to forward chunks from a remote streaming tool to
 * a browser client via SSE.
 *
 * Wire format mirrors the Python ``mesh.route`` SSE adapter:
 * - ``data: <chunk>\n\n`` per item
 * - ``data: [DONE]\n\n`` terminator on normal completion
 * - ``event: error\ndata: <json>\n\n`` on per-chunk error
 *
 * @example
 * ```typescript
 * import { mesh } from "@mcpmesh/sdk";
 *
 * // Dependencies bind by position: deps[0] is the first declared dependency.
 * app.post("/plan", mesh.route(["trip_planner"], async (req, res, [tripPlanner]) => {
 *   if (!tripPlanner) return res.status(503).end();
 *   await mesh.sseStream(res, tripPlanner.stream(req.body));
 * }));
 * ```
 */

import type { Response } from "express";

/**
 * Seconds to wait for a backpressured response to drain before giving up on
 * the consumer. ``0`` disables the bound entirely (wait forever).
 *
 * Default matches ``MCP_MESH_CALL_TIMEOUT``'s fallback (300s): a stream that
 * has not moved a byte for longer than the default mesh call budget is
 * holding an upstream iterator — and therefore an upstream agent's generator
 * and connection — for longer than any single mesh call is allowed to take.
 * Unlike a disconnect, a stalled-but-connected consumer (a zero-window peer
 * that never sends FIN) emits neither ``close`` nor ``error``, so without a
 * bound nothing would ever release that upstream.
 *
 * Read at call time, not module load, so a process that configures its
 * environment late (or a test) sees the current value.
 */
const DEFAULT_DRAIN_TIMEOUT_SECS = 300;

const warnedDrainTimeoutValues = new Set<string>();

function resolveDrainTimeoutMs(): number {
  const raw = process.env.MCP_MESH_SSE_DRAIN_TIMEOUT;
  if (raw === undefined || raw.trim() === "") {
    return DEFAULT_DRAIN_TIMEOUT_SECS * 1000;
  }
  const parsed = Number(raw.trim());
  if (!Number.isFinite(parsed) || parsed < 0) {
    if (!warnedDrainTimeoutValues.has(raw)) {
      warnedDrainTimeoutValues.add(raw);
      console.warn(
        `[mcp-mesh] Invalid MCP_MESH_SSE_DRAIN_TIMEOUT value '${raw}' — using default ${DEFAULT_DRAIN_TIMEOUT_SECS}s`
      );
    }
    return DEFAULT_DRAIN_TIMEOUT_SECS * 1000;
  }
  return parsed * 1000;
}

/**
 * Outcome of one attempted frame write.
 *
 * The three states are deliberately distinct: ``res.write()`` returning
 * ``false`` means the internal buffer passed ``highWaterMark`` — the frame
 * WAS accepted and queued — not that the consumer went away. Collapsing it
 * into a single boolean is what made a slow consumer look like a disconnect
 * (issue #1567).
 */
type WriteOutcome = "ok" | "backpressure" | "closed";

/** Outcome of waiting for a backpressured response to drain. */
type DrainOutcome = "drained" | "closed" | "timeout";

/**
 * Minimal EventEmitter surface used for the drain race.
 *
 * Every real Express/Node ``ServerResponse`` is an EventEmitter; this type
 * exists so the wait can be skipped (rather than throwing) for a hand-rolled
 * test double that only implements ``write``/``end``.
 */
interface DrainEvents {
  once(event: string, listener: (...args: unknown[]) => void): unknown;
  removeListener(event: string, listener: (...args: unknown[]) => void): unknown;
}

/**
 * Wait for a backpressured response to drain, racing the connection dying.
 *
 * A consumer that disconnects while we are parked here never emits
 * ``drain``, so ``close`` and ``error`` are raced alongside it — otherwise
 * the producer (and the upstream iterator it holds open) would hang forever.
 * Exactly one of the three listeners wins; the losers are removed on every
 * path, so a stream that backpressures thousands of times does not
 * accumulate handlers.
 */
function waitForDrain(res: Response, timeoutMs: number): Promise<DrainOutcome> {
  if (res.writableEnded || res.destroyed) {
    return Promise.resolve("closed");
  }
  const emitter = res as unknown as Partial<DrainEvents>;
  if (typeof emitter.once !== "function" || typeof emitter.removeListener !== "function") {
    // Not an EventEmitter (test double): drain can never be observed, so
    // treat the backpressure as terminal rather than parking forever.
    return Promise.resolve("closed");
  }
  const once = emitter.once.bind(emitter) as DrainEvents["once"];
  const removeListener = emitter.removeListener.bind(emitter) as DrainEvents["removeListener"];

  return new Promise<DrainOutcome>((resolve) => {
    let settled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const finish = (outcome: DrainOutcome): void => {
      if (settled) return;
      settled = true;
      removeListener("drain", onDrain);
      removeListener("close", onClose);
      removeListener("error", onError);
      if (timer !== undefined) clearTimeout(timer);
      resolve(outcome);
    };
    const onDrain = (): void => finish("drained");
    const onClose = (): void => finish("closed");
    const onError = (): void => finish("closed");
    once("drain", onDrain);
    once("close", onClose);
    // Also claims the 'error' event for the duration of the wait: an
    // unhandled 'error' on a ServerResponse would otherwise be thrown.
    once("error", onError);
    if (timeoutMs > 0) {
      timer = setTimeout(() => finish("timeout"), timeoutMs);
      // Never hold the process open just to time out a drain wait.
      if (typeof timer.unref === "function") timer.unref();
    }
  });
}

const SSE_HEADERS: Record<string, string> = {
  "Content-Type": "text/event-stream",
  "Cache-Control": "no-cache",
  Connection: "keep-alive",
  // Disable nginx response buffering so chunks reach the browser immediately
  "X-Accel-Buffering": "no",
};

/**
 * Format a single chunk as SSE ``data:`` lines per spec.
 *
 * Each newline in the chunk becomes its own ``data:`` line; the record is
 * terminated by a blank line. Empty chunks still emit a single ``data:``
 * line so consumers see a heartbeat-style event (matches Python behavior).
 */
function frameChunkAsSSE(chunk: string): string {
  // splitlines() in Python splits on any line boundary; in JS we normalize
  // CRLF to LF first then split on \n. An empty chunk still emits one frame.
  const normalized = chunk.replace(/\r\n/g, "\n");
  const lines = normalized === "" ? [""] : normalized.split("\n");
  return lines.map((l) => `data: ${l}\n`).join("") + "\n";
}

/**
 * Pipe an ``AsyncIterable<string>`` to an Express ``Response`` as SSE.
 *
 * Sets the standard SSE headers, writes one ``data: <chunk>\n\n`` frame per
 * item from the iterable, and terminates with ``data: [DONE]\n\n``. On
 * per-chunk error (e.g. the upstream stream throws), writes
 * ``event: error\ndata: <json>\n\n`` and ends the response.
 *
 * Resolves when the response has been fully written. Callers do not need to
 * call ``res.end()`` themselves.
 *
 * If the consumer disconnects mid-stream (``res.writableEnded``), iteration
 * stops cleanly via the iterable's ``return()`` method (so the upstream
 * proxy stream's ``finally`` block can release its underlying reader).
 *
 * A consumer that is merely SLOW is not a disconnect: when ``res.write()``
 * reports backpressure the frame is already queued, so iteration pauses
 * until the response drains (racing ``close``/``error`` so a consumer that
 * leaves mid-wait still releases the upstream). A consumer that stalls
 * without disconnecting is abandoned after ``MCP_MESH_SSE_DRAIN_TIMEOUT``
 * seconds (default 300, ``0`` waits forever).
 *
 * @param res - Express response object
 * @param source - Async iterable yielding strings
 */
export async function sseStream(
  res: Response,
  source: AsyncIterable<string>
): Promise<void> {
  // Set headers if not already sent. Use writeHead for a single atomic flush
  // so the browser sees the full set immediately (some proxies buffer until
  // headers arrive). If the caller already wrote headers we just continue.
  if (!res.headersSent) {
    for (const [k, v] of Object.entries(SSE_HEADERS)) {
      res.setHeader(k, v);
    }
    // Some Express versions need an explicit flushHeaders() to commit before
    // the first data frame; call it if available.
    if (typeof (res as Response & { flushHeaders?: () => void }).flushHeaders === "function") {
      (res as Response & { flushHeaders: () => void }).flushHeaders();
    }
  }

  // Track whether end() has been called so we never double-end (which would
  // throw "ERR_STREAM_WRITE_AFTER_END" on Node). ``writable`` flips to false
  // when further writes will fail (e.g. socket closed) but we still want to
  // call res.end() exactly once for cleanup.
  let endCalled = false;
  let writable = true;
  const safeEnd = (): void => {
    if (endCalled) return;
    endCalled = true;
    try {
      res.end();
    } catch {
      // ignore — response may already be torn down
    }
  };
  const safeWrite = (data: string): WriteOutcome => {
    if (!writable) return "closed";
    if (res.writableEnded || res.destroyed) {
      writable = false;
      return "closed";
    }
    try {
      // false here means the frame was queued but the buffer is over its
      // highWaterMark — backpressure, NOT a disconnect (issue #1567).
      return res.write(data) ? "ok" : "backpressure";
    } catch {
      writable = false;
      return "closed";
    }
  };

  const iterator = source[Symbol.asyncIterator]();
  const releaseUpstream = async (): Promise<void> => {
    if (typeof iterator.return === "function") {
      try {
        await iterator.return();
      } catch {
        // upstream cleanup is best-effort
      }
    }
  };
  try {
    while (true) {
      const { value, done } = await iterator.next();
      if (done) break;
      if (typeof value !== "string") {
        // v1 supports str only — surface a structured error and stop
        const errPayload = JSON.stringify({
          error: `sseStream: expected string chunk, got ${typeof value}`,
          type: "TypeError",
        });
        // Return value ignored: the frame is queued even when write()
        // reports backpressure, and res.end() flushes whatever is buffered
        // before sending FIN, so a false here still reaches a live consumer.
        safeWrite(`event: error\ndata: ${errPayload}\n\n`);
        safeEnd();
        // best-effort cleanup of upstream
        await releaseUpstream();
        return;
      }
      const outcome = safeWrite(frameChunkAsSSE(value));
      if (outcome === "closed") {
        // Consumer disconnected (or write threw) — clean up upstream and end.
        await releaseUpstream();
        safeEnd();
        return;
      }
      if (outcome === "backpressure") {
        // The frame is already queued; wait for the socket to catch up before
        // pushing more at it. Racing close/error means a consumer that walks
        // away mid-wait still releases the upstream iterator promptly.
        const drain = await waitForDrain(res, resolveDrainTimeoutMs());
        if (drain !== "drained") {
          if (drain === "timeout") {
            console.warn(
              "[mcp-mesh] sseStream: consumer stalled without disconnecting; " +
                "abandoning the stream after MCP_MESH_SSE_DRAIN_TIMEOUT"
            );
          }
          writable = false;
          await releaseUpstream();
          safeEnd();
          if (drain === "timeout") {
            // end() alone cannot help here: the FIN queues behind a buffer
            // the peer is not reading, so the socket would linger. Destroy it
            // so the timeout actually reclaims the connection.
            try {
              res.destroy();
            } catch {
              // ignore — response may already be torn down
            }
          }
          return;
        }
      }
    }
    // Return value ignored for the same reason as the error frame above: a
    // backpressured [DONE] is still queued, and end() flushes it.
    safeWrite("data: [DONE]\n\n");
    safeEnd();
  } catch (err) {
    const errPayload = JSON.stringify({
      error: err instanceof Error ? err.message : String(err),
      type: err instanceof Error ? err.constructor.name : "Error",
    });
    safeWrite(`event: error\ndata: ${errPayload}\n\n`);
    safeEnd();
    // Release the upstream iterator if the failure originated outside the
    // iterator itself (e.g. safeWrite threw). Without this, an upstream
    // proxy.stream() generator's finally block — which cancels the
    // OkHttp/fetch reader — never runs until GC, leaking the connection.
    await releaseUpstream();
  }
}
