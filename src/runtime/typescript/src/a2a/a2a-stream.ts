/**
 * Async iterator over parsed A2A SSE events — returned by
 * `A2AClient.subscribe` (issue #917).
 *
 * Implements `AsyncIterable<A2AEvent>` so callers can write
 * `for await (const event of stream) { ... }` idiomatically.
 * Implements TC39 `Symbol.asyncDispose` (Node 20+) for `await using`,
 * AND exposes `aclose()` as a manual fallback for older runtimes.
 *
 * Per A2A v1.0, client disconnect is a transient signal — the producer
 * continues running unless explicitly canceled. `bridge` therefore does
 * NOT POST `tasks/cancel` upstream when the mesh-side job is cancelled
 * (it just closes the SSE connection). Users who need cancel
 * propagation should use `submit` + `A2AJob.bridge` instead, which
 * polls for cancel between iterations and propagates upstream.
 *
 * Mirrors `mesh._a2a_consumer.A2AStream` (Python) and
 * `io.mcpmesh.a2a.A2AStream` (Java).
 */
import { JobController } from "@mcpmesh/core";
import type { A2AEvent } from "./a2a-event.js";
import {
  A2AJobCanceledError,
  A2AJobFailedError,
} from "./errors.js";
import { maybeJsonParse } from "./a2a-client.js";

const ASYNC_DISPOSE: typeof Symbol.asyncDispose | symbol =
  (Symbol as { asyncDispose?: symbol }).asyncDispose ??
  Symbol.for("Symbol.asyncDispose");

export class A2AStream implements AsyncIterable<A2AEvent> {
  private readonly response: Response;
  readonly taskId: string;
  private closed = false;
  private reader: ReadableStreamDefaultReader<Uint8Array> | null = null;

  constructor(response: Response, taskId: string) {
    this.response = response;
    this.taskId = taskId;
  }

  [Symbol.asyncIterator](): AsyncIterator<A2AEvent> {
    return this._iterate();
  }

  /**
   * TC39 explicit-resource-management hook — Node 20+ supports
   * `await using stream = await client.subscribe(...)`. The fallback
   * below uses Symbol.for so older runtimes still surface a usable
   * symbol on the prototype (idempotent close).
   */
  async [ASYNC_DISPOSE as typeof Symbol.asyncDispose](): Promise<void> {
    await this.aclose();
  }

  /** Mirror events into a JobController; return the final artifact value. */
  async bridge(controller: JobController): Promise<unknown> {
    if (controller == null) {
      throw new Error("A2AStream.bridge: controller must be non-null");
    }
    let lastProgress: number | undefined;
    let lastMessage: string | undefined;
    let artifactValue: unknown = "";
    let sawArtifact = false;
    let terminalState: string | undefined;
    let terminalMessage: string | undefined;

    try {
      for await (const event of this) {
        if (event.kind === "artifact") {
          const text = event.artifactText ?? "";
          artifactValue = !text ? text : maybeJsonParse(text);
          sawArtifact = true;
          continue;
        }
        if (event.progress !== undefined || event.message !== undefined) {
          const changed =
            event.progress !== lastProgress || event.message !== lastMessage;
          if (changed) {
            const rawP =
              event.progress !== undefined
                ? event.progress
                : lastProgress !== undefined
                  ? lastProgress
                  : 0.0;
            const clamped = Math.min(1.0, Math.max(0.0, rawP));
            try {
              await controller.updateProgress(clamped, event.message ?? null);
              if (event.progress !== undefined) lastProgress = event.progress;
              lastMessage = event.message;
            } catch (err) {
              // Do NOT advance lastProgress / lastMessage on delivery
              // failure — leaving them stale ensures the next event
              // still passes the equality check and retries.
              console.warn(
                `[a2a-stream] bridge: controller.updateProgress failed ` +
                  `(task=${this.taskId}, progress=${event.progress}, ` +
                  `msg=${event.message}) — will retry on next event: ` +
                  `${(err as Error)?.message ?? String(err)}`,
              );
            }
          }
        }
        if (event.final) {
          terminalState = event.state;
          terminalMessage = event.message;
          break;
        }
      }
    } finally {
      // Ensure the SSE stream is closed on any exit path (normal
      // completion, throw, etc.). aclose() is idempotent.
      await this.aclose();
    }

    if (terminalState) {
      const lower = terminalState.toLowerCase();
      if (lower === "canceled" || lower === "cancelled") {
        throw new A2AJobCanceledError(
          terminalMessage ?? `A2A task ${this.taskId} canceled`,
        );
      }
      if (lower === "failed") {
        throw new A2AJobFailedError(
          terminalMessage ?? `A2A task ${this.taskId} failed`,
        );
      }
      // Parity with A2AJob._terminalToArtifactOrThrow — completed
      // with no artifact event seen returns "" rather than throwing,
      // matching the polling-bridge semantics.
      if (lower === "completed" && !sawArtifact) {
        return "";
      }
    }
    if (!sawArtifact) {
      throw new A2AJobFailedError(
        `A2A subscribe stream ${this.taskId} ended without artifact`,
      );
    }
    return artifactValue;
  }

  /**
   * Explicit close — releases the reader lock + cancels the
   * underlying ReadableStream so the undici Agent reclaims the
   * connection promptly. Idempotent.
   */
  async aclose(): Promise<void> {
    if (this.closed) return;
    this.closed = true;
    try {
      if (this.reader) {
        try {
          await this.reader.cancel();
        } catch {
          // best-effort
        }
        try {
          this.reader.releaseLock();
        } catch {
          // best-effort
        }
        this.reader = null;
      } else if (this.response.body) {
        try {
          await this.response.body.cancel();
        } catch {
          // best-effort
        }
      }
    } catch {
      // swallow — close is best-effort
    }
  }

  private async *_iterate(): AsyncGenerator<A2AEvent> {
    if (this.closed) return;
    if (!this.response.body) {
      throw new A2AJobFailedError(
        `A2AStream(${this.taskId}): response body is null`,
      );
    }
    if (!this.reader) {
      this.reader = this.response.body.getReader();
    }
    const reader = this.reader;
    const decoder = new TextDecoder("utf-8");
    let pending = "";
    const dataBuf: string[] = [];

    const flushEvent = (): A2AEvent | null => {
      if (dataBuf.length === 0) return null;
      const payload = dataBuf.join("\n");
      dataBuf.length = 0;
      let envelope: unknown;
      try {
        envelope = JSON.parse(payload);
      } catch {
        // Skip non-JSON SSE frames silently — matches Python behavior.
        return null;
      }
      return parseSseEnvelope(envelope);
    };

    try {
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        pending += decoder.decode(value, { stream: true });
        let nlIdx: number;
        while ((nlIdx = pending.search(/\r\n|\n/)) !== -1) {
          // Accept both LF and CRLF line endings.
          const isCrLf =
            pending.charCodeAt(nlIdx) === 13 &&
            pending.charCodeAt(nlIdx + 1) === 10;
          const line = pending.slice(0, nlIdx);
          pending = pending.slice(nlIdx + (isCrLf ? 2 : 1));
          if (line === "") {
            const event = flushEvent();
            if (event !== null) {
              yield event;
              if (event.final) {
                await this.aclose();
                return;
              }
            }
            continue;
          }
          if (line.startsWith(":")) {
            // SSE comment / keepalive — ignore.
            continue;
          }
          if (line.startsWith("data:")) {
            // Strip "data:" prefix and one optional space.
            let payload = line.slice(5);
            if (payload.startsWith(" ")) payload = payload.slice(1);
            dataBuf.push(payload);
            continue;
          }
          // event:/id:/retry:/unknown — ignore for v1.0.
        }
      }
      // Stream ended without a trailing blank — flush any pending frame.
      pending += decoder.decode();
      if (pending.length > 0 && pending.startsWith("data:")) {
        let payload = pending.slice(5);
        if (payload.startsWith(" ")) payload = payload.slice(1);
        dataBuf.push(payload);
      }
      const tail = flushEvent();
      if (tail !== null) {
        yield tail;
      }
    } finally {
      await this.aclose();
    }
  }
}

function parseSseEnvelope(envelope: unknown): A2AEvent | null {
  if (!envelope || typeof envelope !== "object") return null;
  const result = (envelope as Record<string, unknown>).result;
  if (!result || typeof result !== "object") return null;
  const r = result as Record<string, unknown>;

  // ARTIFACT events have the "artifact" key.
  const artifact = r.artifact;
  if (artifact && typeof artifact === "object") {
    const text = extractFirstTextPart(artifact as Record<string, unknown>) ?? "";
    return {
      kind: "artifact",
      artifactText: text,
      final: false,
      raw: envelope,
    };
  }

  // STATUS events have the "status" key.
  const status = r.status;
  if (status && typeof status === "object") {
    const statusObj = status as Record<string, unknown>;
    const stateRaw = statusObj.state;
    const state = typeof stateRaw === "string" ? stateRaw : undefined;
    const msgObj = statusObj.message;
    let message: string | undefined;
    if (msgObj && typeof msgObj === "object") {
      message = extractFirstTextPart(msgObj as Record<string, unknown>);
    }
    let progress: number | undefined;
    const metadata = r.metadata;
    if (metadata && typeof metadata === "object") {
      const p = (metadata as Record<string, unknown>).progress;
      if (typeof p === "number" && Number.isFinite(p)) progress = p;
      else if (typeof p === "string") {
        const n = Number.parseFloat(p);
        if (Number.isFinite(n)) progress = n;
      }
    }
    const finalRaw = r.final;
    const final = finalRaw === true;
    return {
      kind: "status",
      state,
      progress,
      message,
      final,
      raw: envelope,
    };
  }

  return null;
}

function extractFirstTextPart(
  container: Record<string, unknown>,
): string | undefined {
  const parts = container.parts;
  if (!Array.isArray(parts) || parts.length === 0) return undefined;
  const first = parts[0];
  if (!first || typeof first !== "object") return undefined;
  const text = (first as Record<string, unknown>).text;
  return typeof text === "string" ? text : undefined;
}
