/**
 * Issue #1593: tool worker threads have their own module state, so tracing
 * initialized on the main thread does not exist inside a worker and every
 * outbound span an isolated tool's proxy call publishes was dropped. The pool
 * now hands the main thread's tracing metadata to each worker, which runs
 * `initTracing` with it (tool-worker-entry.ts).
 */
import { describe, it, expect, vi, afterEach } from "vitest";

const spawned = vi.hoisted(
  () => [] as Array<{ entry: string; options: { workerData: Record<string, unknown> } }>,
);

vi.mock("node:worker_threads", async (importOriginal) => {
  const actual = await importOriginal<typeof import("node:worker_threads")>();
  const { EventEmitter } = await import("node:events");
  class FakeWorker extends EventEmitter {
    constructor(entry: string, options: { workerData: Record<string, unknown> }) {
      super();
      spawned.push({ entry, options });
      queueMicrotask(() => this.emit("message", { kind: "ready" }));
    }
    postMessage(msg: { id: number }) {
      queueMicrotask(() => this.emit("message", { id: msg.id, kind: "result", value: "ok" }));
    }
    terminate() {
      return Promise.resolve(0);
    }
  }
  return { ...actual, Worker: FakeWorker };
});

const metadata = {
  agentId: "agent-1",
  agentName: "agent",
  agentNamespace: "default",
  agentHostname: "h",
  agentIp: "127.0.0.1",
  agentPort: 9000,
  agentEndpoint: "http://127.0.0.1:9000",
};
let tracingMeta: typeof metadata | null = metadata;

vi.mock("../tracing.js", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../tracing.js")>();
  return { ...actual, getTracingAgentMetadata: () => tracingMeta };
});

import { dispatch, closePool } from "../tool-worker-pool.js";

afterEach(async () => {
  await closePool(10);
  spawned.length = 0;
});

const payload = {
  toolName: "t",
  cleanArgs: {},
  depsConfig: [],
  traceContext: null,
  propagatedHeaders: {},
};

describe("tool worker tracing hand-off", () => {
  it("passes the main thread's tracing metadata to each spawned worker", async () => {
    tracingMeta = metadata;
    expect(await dispatch(payload)).toBe("ok");
    expect(spawned).toHaveLength(1);
    expect(spawned[0].options.workerData.tracingAgentMetadata).toEqual(metadata);
  });

  it("passes null when tracing is disabled on the main thread", async () => {
    tracingMeta = null;
    await dispatch(payload);
    expect(spawned[0].options.workerData.tracingAgentMetadata).toBeNull();
  });
});
