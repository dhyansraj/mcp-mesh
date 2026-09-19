/**
 * Backpressure tests for sse-stream.ts (mesh.sseStream) — issue #1567.
 *
 * These run against a REAL HTTP server and a REAL TCP client socket. A mock
 * that returns ``false`` on command would pass against a fix that is wrong
 * about Node stream semantics (when ``drain`` actually fires, what a
 * destroyed response emits, whether ``end()`` flushes a queued frame), so the
 * consumer here is a paused socket that genuinely fills the kernel buffer and
 * makes ``res.write()`` return ``false`` on its own.
 *
 * Covered:
 * - a slow consumer receives every chunk AND the ``[DONE]`` terminator
 * - a consumer that disconnects while the producer is parked on ``drain``
 *   terminates promptly with upstream ``return()`` cleanup
 * - drain listeners do not accumulate across many backpressure cycles
 * - a consumer that stalls without disconnecting is bounded by
 *   ``MCP_MESH_SSE_DRAIN_TIMEOUT``
 */

import { describe, it, expect, vi, afterEach } from "vitest";
import http from "node:http";
import net from "node:net";
import type { AddressInfo } from "node:net";
import type { Response } from "express";
import { sseStream } from "../sse-stream.js";

/** 128 KiB per frame — comfortably past any socket highWaterMark. */
const CHUNK_BODY = "x".repeat(128 * 1024);

/** Frames are prefixed with ``#<index>#`` so the client can count them. */
function chunkAt(i: number): string {
  return `#${i}#${CHUNK_BODY}`;
}

interface ServerCtx {
  port: number;
  /** Resolves when the sseStream() call in the handler returns. */
  handlerDone: Promise<void>;
  /** True once handlerDone has settled — used to assert "still streaming". */
  isDone: () => boolean;
  /** Resolves the first time res.write() genuinely returned false. */
  backpressured: Promise<void>;
  /** Count of write() calls that returned false (real backpressure events). */
  falseCount: () => number;
  /** Peak listener counts observed one microtask after each false write. */
  peakListeners: () => { drain: number; close: number; error: number };
  /** Listener counts after the handler finished. */
  finalListeners: () => { drain: number; close: number; error: number };
  close: () => Promise<void>;
}

function startSseServer(source: AsyncIterable<string>): Promise<ServerCtx> {
  let falses = 0;
  let done = false;
  const peak = { drain: 0, close: 0, error: 0 };
  const final = { drain: 0, close: 0, error: 0 };
  let resolveDone!: () => void;
  let resolveBackpressured!: () => void;
  const handlerDone = new Promise<void>((r) => {
    resolveDone = r;
  });
  const backpressured = new Promise<void>((r) => {
    resolveBackpressured = r;
  });

  const server = http.createServer((_req, res) => {
    const counts = (): { drain: number; close: number; error: number } => ({
      drain: res.listenerCount("drain"),
      close: res.listenerCount("close"),
      error: res.listenerCount("error"),
    });
    const baseline = counts();
    const origWrite = res.write.bind(res);
    // Real write, real return value — only the bookkeeping is ours.
    res.write = ((data: string) => {
      const ok = origWrite(data);
      if (!ok) {
        falses += 1;
        resolveBackpressured();
        // One microtask later the producer has attached its drain/close/error
        // listeners (waitForDrain runs synchronously after write returns).
        queueMicrotask(() => {
          const c = counts();
          peak.drain = Math.max(peak.drain, c.drain - baseline.drain);
          peak.close = Math.max(peak.close, c.close - baseline.close);
          peak.error = Math.max(peak.error, c.error - baseline.error);
        });
      }
      return ok;
    }) as typeof res.write;

    void sseStream(res as unknown as Response, source).then(() => {
      const c = counts();
      final.drain = c.drain - baseline.drain;
      final.close = c.close - baseline.close;
      final.error = c.error - baseline.error;
      done = true;
      resolveDone();
    });
  });

  return new Promise<ServerCtx>((resolve) => {
    server.listen(0, "127.0.0.1", () => {
      resolve({
        port: (server.address() as AddressInfo).port,
        handlerDone,
        isDone: () => done,
        backpressured,
        falseCount: () => falses,
        peakListeners: () => ({ ...peak }),
        finalListeners: () => ({ ...final }),
        close: () =>
          new Promise<void>((r) => {
            server.closeAllConnections?.();
            server.close(() => r());
          }),
      });
    });
  });
}

interface ClientCtx {
  socket: net.Socket;
  /** Everything received so far (raw, including chunked-transfer framing). */
  received: () => string;
  /**
   * Resolves once ``marker`` appears in the received bytes.
   *
   * Completion is detected from the body rather than from socket close:
   * sseStream sets ``Connection: keep-alive``, so the server holds the
   * connection for ``keepAliveTimeout`` (5s) after the response ends.
   */
  waitFor: (marker: string) => Promise<void>;
  /** Resolves when the connection is closed (used for the destroy paths). */
  closed: Promise<void>;
}

/**
 * Connect and send the request, then STOP READING. The socket stays paused
 * until the caller resumes it, which is what fills the buffer and forces
 * real backpressure on the server side.
 */
function connectPaused(port: number): Promise<ClientCtx> {
  return new Promise<ClientCtx>((resolve) => {
    let buf = "";
    const waiters: { marker: string; resolve: () => void }[] = [];
    const socket = net.connect(port, "127.0.0.1", () => {
      socket.write("GET / HTTP/1.1\r\nHost: localhost\r\n\r\n");
      socket.pause();
      resolve({
        socket,
        received: () => buf,
        waitFor: (marker: string) =>
          new Promise<void>((r) => {
            if (buf.includes(marker)) {
              r();
              return;
            }
            waiters.push({ marker, resolve: r });
          }),
        closed,
      });
    });
    socket.on("data", (b: Buffer) => {
      buf += b.toString("utf8");
      for (let i = waiters.length - 1; i >= 0; i--) {
        if (buf.includes(waiters[i].marker)) {
          waiters.splice(i, 1)[0].resolve();
        }
      }
    });
    socket.on("error", () => {
      /* a mid-stream destroy surfaces as ECONNRESET; not a test failure */
    });
    const closed = new Promise<void>((r) => socket.on("close", () => r()));
  });
}

/** Indices of the ``#<i>#``-prefixed frames present in a raw SSE response. */
function receivedIndices(raw: string): number[] {
  return [...raw.matchAll(/^data: #(\d+)#/gm)].map((m) => Number(m[1]));
}

async function* framesUpTo(n: number): AsyncGenerator<string, void, void> {
  for (let i = 0; i < n; i++) {
    yield chunkAt(i);
  }
}

const delay = (ms: number): Promise<void> =>
  new Promise((r) => setTimeout(r, ms));

/** Bound a wait so a regression reports what never happened, not "timed out". */
async function within<T>(p: Promise<T>, ms: number, what: string): Promise<T> {
  let timer: ReturnType<typeof setTimeout>;
  const guard = new Promise<never>((_, reject) => {
    timer = setTimeout(() => reject(new Error(`timed out after ${ms}ms: ${what}`)), ms);
  });
  try {
    return await Promise.race([p, guard]);
  } finally {
    clearTimeout(timer!);
  }
}

afterEach(() => {
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
});

describe("sseStream backpressure (real socket)", () => {
  it("delivers every chunk and [DONE] to a consumer slower than the producer", async () => {
    const N = 24;
    const server = await startSseServer(framesUpTo(N));
    const client = await connectPaused(server.port);

    // Consumer reads nothing for 200ms — the producer fills the socket buffer
    // and res.write() starts returning false for real.
    await server.backpressured;
    expect(
      server.isDone(),
      "sseStream ended on backpressure instead of parking on drain"
    ).toBe(false);
    await delay(200);
    client.socket.resume();

    await within(server.handlerDone, 3000, "sseStream never finished");
    await within(
      client.waitFor("data: [DONE]"),
      3000,
      "slow consumer never received the [DONE] terminator"
    );

    // Guard against a vacuous pass: the run must actually have backpressured.
    expect(server.falseCount()).toBeGreaterThan(0);

    const raw = client.received();
    expect(receivedIndices(raw)).toEqual([...Array(N).keys()]);
    expect(raw).toContain("data: [DONE]");

    await server.close();
  });

  it("keeps drain/close/error listeners flat across many backpressure cycles", async () => {
    const N = 24;
    const server = await startSseServer(framesUpTo(N));
    const client = await connectPaused(server.port);

    await server.backpressured;
    await delay(150);
    client.socket.resume();
    await within(server.handlerDone, 3000, "sseStream never finished");
    await within(
      client.waitFor("data: [DONE]"),
      3000,
      "slow consumer never received the [DONE] terminator"
    );

    // Many cycles, so an un-removed listener would show up as a growing count.
    expect(server.falseCount()).toBeGreaterThan(3);
    expect(server.peakListeners()).toEqual({ drain: 1, close: 1, error: 1 });
    expect(server.finalListeners()).toEqual({ drain: 0, close: 0, error: 0 });

    await server.close();
  });

  it("terminates promptly with upstream cleanup when the consumer disconnects mid-drain", async () => {
    let returnCalled = false;
    let produced = 0;

    async function* tracked(): AsyncGenerator<string, void, void> {
      try {
        for (let i = 0; i < 200; i++) {
          produced += 1;
          yield chunkAt(i);
        }
      } finally {
        returnCalled = true;
      }
    }

    const server = await startSseServer(tracked());
    const client = await connectPaused(server.port);

    // Never read: the producer parks on 'drain', which will never fire.
    await server.backpressured;
    await delay(150);
    expect(
      server.isDone(),
      "sseStream ended on backpressure instead of parking on drain"
    ).toBe(false);
    const producedWhileParked = produced;

    client.socket.destroy();

    await within(
      server.handlerDone,
      3000,
      "sseStream did not terminate after the consumer disconnected mid-drain"
    );

    expect(returnCalled).toBe(true);
    // No further chunks were pulled from upstream after the disconnect.
    expect(produced).toBe(producedWhileParked);

    await server.close();
  });

  it("abandons a consumer that stalls without disconnecting after MCP_MESH_SSE_DRAIN_TIMEOUT", async () => {
    vi.stubEnv("MCP_MESH_SSE_DRAIN_TIMEOUT", "0.3");
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);

    let returnCalled = false;
    async function* tracked(): AsyncGenerator<string, void, void> {
      try {
        for (let i = 0; i < 200; i++) {
          yield chunkAt(i);
        }
      } finally {
        returnCalled = true;
      }
    }

    const server = await startSseServer(tracked());
    const client = await connectPaused(server.port);

    // The client stays connected and simply never reads: no 'close', no
    // 'error', no 'drain'. Only the timeout can release the upstream.
    await server.backpressured;
    const started = Date.now();
    await within(
      server.handlerDone,
      4000,
      "sseStream never gave up on a consumer stalled without disconnecting"
    );

    expect(Date.now() - started).toBeLessThan(3000);
    expect(returnCalled).toBe(true);
    expect(warn.mock.calls.flat().join(" ")).toMatch(
      /stalled without disconnecting/
    );
    // The timeout path destroys the socket so it does not linger. Resume the
    // client first: a paused socket does not process the teardown.
    client.socket.resume();
    await client.closed;

    await server.close();
  });
});
