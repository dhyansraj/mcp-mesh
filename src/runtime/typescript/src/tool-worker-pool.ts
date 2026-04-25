/**
 * Tool worker pool for isolating user tool execution from the main event loop.
 *
 * Mirrors the Python `_mcp_mesh.shared.tool_executor` design: spawn N worker
 * threads (V8 isolates here, since Node has no GIL/asyncio split), each with
 * its own event loop and undici connection pool, and dispatch tool calls
 * round-robin across them. A user's blocking call (`execFileSync`, CPU spin,
 * etc.) blocks one worker thread, NOT the main thread that serves
 * /health, /ready, FastMCP HTTP, and registry heartbeats.
 *
 * Pool size:
 *   Default `min(8, max(2, os.availableParallelism() ?? 2))`.
 *   Override via `MCP_MESH_TOOL_WORKERS=<N>`.
 *
 * The pool is created lazily on first dispatch (matches Python parity) and
 * cached for the process lifetime. Workers that crash are respawned on the
 * next dispatch.
 */

import { Worker } from "node:worker_threads";
import { fileURLToPath } from "node:url";
import os from "node:os";
import path from "node:path";

export interface DepConfig {
  endpoint: string;
  capability: string;
  functionName: string;
  kwargs: Record<string, unknown>;
}

export interface DispatchPayload {
  toolName: string;
  cleanArgs: unknown;
  depsConfig: (DepConfig | null)[];
  traceContext: unknown;
  propagatedHeaders: Record<string, string>;
}

interface WorkerSlot {
  worker: Worker | null;
  ready: Promise<void> | null;
  pending: Map<number, { resolve: (v: unknown) => void; reject: (e: Error) => void }>;
  alive: boolean;
}

const _slots: WorkerSlot[] = [];
let _poolSize = 0;
let _initialized = false;
let _nextIdx = 0;
let _msgId = 0;
let _shutdownRegistered = false;

function deserializeError(serialized: any): Error {
  const err: any = new Error(serialized?.message ?? "worker error");
  if (serialized?.name) err.name = serialized.name;
  if (serialized?.stack) err.stack = serialized.stack;
  if (serialized?.code !== undefined) err.code = serialized.code;
  if (serialized?.cause !== undefined) err.cause = deserializeError(serialized.cause);
  return err;
}

function _resolvePoolSize(): number {
  const envVal = process.env.MCP_MESH_TOOL_WORKERS;
  if (envVal) {
    const n = parseInt(envVal, 10);
    if (!isNaN(n) && n >= 1) return n;
    console.warn(
      `MCP_MESH_TOOL_WORKERS=${envVal} is invalid; falling back to default`
    );
  }
  // os.availableParallelism is Node 19.4+; fall back to cpus().length.
  const cpu =
    typeof os.availableParallelism === "function"
      ? os.availableParallelism()
      : os.cpus().length || 2;
  return Math.min(8, Math.max(2, cpu || 2));
}

function _resolveWorkerEntryPath(): string {
  // tool-worker-pool.js sits next to tool-worker-entry.js in dist/.
  const here = fileURLToPath(import.meta.url);
  return path.join(path.dirname(here), "tool-worker-entry.js");
}

function _resolveSdkEntryPath(): string {
  // dist/tool-worker-pool.js → dist/index.js
  const here = fileURLToPath(import.meta.url);
  return path.join(path.dirname(here), "index.js");
}

function _resolveUserModulePath(): string {
  // process.argv[1] is the user's entry script when launched via `npx tsx <file>`
  // or `node <file>`. Resolve to absolute for consistent worker resolution.
  const argv1 = process.argv[1];
  if (!argv1) {
    throw new Error(
      "Cannot determine user module path: process.argv[1] is empty"
    );
  }
  return path.resolve(argv1);
}

function _initPool(): void {
  if (_initialized) return;
  _initialized = true;
  _poolSize = _resolvePoolSize();
  for (let i = 0; i < _poolSize; i++) {
    _slots.push({ worker: null, ready: null, pending: new Map(), alive: false });
  }
  if (!_shutdownRegistered) {
    _shutdownRegistered = true;
    process.once("exit", () => {
      // Synchronous best-effort termination on exit.
      for (const slot of _slots) {
        if (slot.worker) {
          try {
            slot.worker.terminate();
          } catch {
            // ignore
          }
        }
      }
    });
  }
}

function _spawnWorker(slot: WorkerSlot, slotIdx: number): void {
  const workerEntry = _resolveWorkerEntryPath();
  const userModulePath = _resolveUserModulePath();
  const sdkEntryPath = _resolveSdkEntryPath();

  const worker = new Worker(workerEntry, {
    workerData: {
      userModulePath,
      sdkEntryPath,
      slotIdx,
    },
  });

  slot.worker = worker;
  slot.alive = true;
  slot.pending = new Map();

  slot.ready = new Promise<void>((resolveReady, rejectReady) => {
    let readyResolved = false;

    worker.on("message", (msg: any) => {
      if (msg && msg.kind === "ready") {
        if (!readyResolved) {
          readyResolved = true;
          resolveReady();
        }
        return;
      }
      if (msg && msg.kind === "fatal") {
        const err = new Error(
          msg.error?.message ?? "Worker fatal error during init"
        );
        if (msg.error?.name) err.name = msg.error.name;
        if (!readyResolved) {
          readyResolved = true;
          rejectReady(err);
        }
        // Fail any in-flight calls too.
        for (const [, pending] of slot.pending) pending.reject(err);
        slot.pending.clear();
        slot.alive = false;
        return;
      }
      if (msg && typeof msg.id === "number") {
        const pending = slot.pending.get(msg.id);
        if (!pending) return;
        slot.pending.delete(msg.id);
        if (msg.kind === "result") {
          pending.resolve(msg.value);
        } else if (msg.kind === "error") {
          pending.reject(deserializeError(msg.error));
        }
      }
    });

    worker.on("error", (err) => {
      slot.alive = false;
      if (!readyResolved) {
        readyResolved = true;
        rejectReady(err);
      }
      for (const [, pending] of slot.pending) pending.reject(err);
      slot.pending.clear();
      slot.worker = null;
      slot.ready = null;
    });

    worker.on("exit", (code) => {
      slot.alive = false;
      if (slot.pending.size > 0) {
        const err = new Error(`Worker exited (code=${code}) with pending calls`);
        for (const [, pending] of slot.pending) pending.reject(err);
        slot.pending.clear();
      }
      if (!readyResolved) {
        readyResolved = true;
        rejectReady(new Error(`Worker exited (code=${code}) before ready`));
      }
      slot.worker = null;
      slot.ready = null;
    });
  });
}

function _pickSlot(): WorkerSlot {
  const idx = _nextIdx % _poolSize;
  _nextIdx = (_nextIdx + 1) % _poolSize;
  const slot = _slots[idx];
  if (!slot.worker || !slot.alive) {
    _spawnWorker(slot, idx);
  }
  return slot;
}

/**
 * Dispatch a tool call to a worker.
 *
 * Round-robin selects a worker, awaits its readiness (first call only),
 * sends the payload, and resolves with the worker's `{result}` or rejects
 * with its `{error}`. Worker crashes propagate as a rejection.
 */
export async function dispatch(payload: DispatchPayload): Promise<unknown> {
  _initPool();
  const slot = _pickSlot();

  // Wait for readiness before enqueuing the first call. After ready, pending
  // calls are buffered by Node's MessagePort regardless.
  if (slot.ready) {
    await slot.ready;
  }

  const id = ++_msgId;
  return new Promise<unknown>((resolve, reject) => {
    slot.pending.set(id, { resolve, reject });
    if (!slot.worker) {
      slot.pending.delete(id);
      reject(new Error("Worker died during dispatch"));
      return;
    }
    try {
      slot.worker.postMessage({
        id,
        kind: "call",
        toolName: payload.toolName,
        cleanArgs: payload.cleanArgs,
        depsConfig: payload.depsConfig,
        traceContext: payload.traceContext,
        propagatedHeaders: payload.propagatedHeaders,
      });
    } catch (err) {
      slot.pending.delete(id);
      reject(err instanceof Error ? err : new Error(String(err)));
    }
  });
}

/**
 * Drain in-flight calls (up to deadlineMs), then forcefully terminate all
 * workers. Calls still pending after the deadline are rejected with a
 * descriptive error.
 *
 * Called automatically on `process.exit`; can be invoked explicitly during
 * shutdown if you want to await completion.
 */
export async function closePool(deadlineMs = 5000): Promise<void> {
  if (!_initialized) return;
  const workers = _slots.slice();
  _slots.length = 0;
  _initialized = false;
  _poolSize = 0;
  _nextIdx = 0;

  // Phase 1: drain — wait up to `deadlineMs` for in-flight calls to finish.
  const deadline = Date.now() + deadlineMs;
  for (const slot of workers) {
    while (slot.pending.size > 0 && Date.now() < deadline) {
      await new Promise((r) => setTimeout(r, 50));
    }
  }

  // Phase 2: reject anything still pending after the deadline.
  for (const slot of workers) {
    if (slot.pending.size > 0) {
      const err = new Error(
        `Worker pool closed with ${slot.pending.size} in-flight call(s) still pending after ${deadlineMs}ms drain`
      );
      for (const [, pending] of slot.pending) pending.reject(err);
      slot.pending.clear();
    }
  }

  // Phase 3: terminate workers.
  await Promise.all(
    workers.map((s) => (s.worker ? s.worker.terminate().catch(() => undefined) : Promise.resolve()))
  );
}
