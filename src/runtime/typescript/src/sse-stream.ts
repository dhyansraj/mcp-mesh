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
 * app.post("/plan", mesh.route(["trip_planner"], async (req, res, { trip_planner }) => {
 *   if (!trip_planner) return res.status(503).end();
 *   await mesh.sseStream(res, trip_planner.stream(req.body));
 * }));
 * ```
 */

import type { Response } from "express";

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
  const safeWrite = (data: string): boolean => {
    if (!writable) return false;
    if (res.writableEnded || res.destroyed) {
      writable = false;
      return false;
    }
    try {
      return res.write(data);
    } catch {
      writable = false;
      return false;
    }
  };

  const iterator = source[Symbol.asyncIterator]();
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
        safeWrite(`event: error\ndata: ${errPayload}\n\n`);
        safeEnd();
        // best-effort cleanup of upstream
        if (typeof iterator.return === "function") {
          try {
            await iterator.return();
          } catch {
            // ignore
          }
        }
        return;
      }
      const wroteOk = safeWrite(frameChunkAsSSE(value));
      if (!wroteOk) {
        // Consumer disconnected (or write threw) — clean up upstream and end.
        if (typeof iterator.return === "function") {
          try {
            await iterator.return();
          } catch {
            // ignore
          }
        }
        safeEnd();
        return;
      }
    }
    safeWrite("data: [DONE]\n\n");
    safeEnd();
  } catch (err) {
    const errPayload = JSON.stringify({
      error: err instanceof Error ? err.message : String(err),
      type: err instanceof Error ? err.constructor.name : "Error",
    });
    safeWrite(`event: error\ndata: ${errPayload}\n\n`);
    safeEnd();
  }
}
