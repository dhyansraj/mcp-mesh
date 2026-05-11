/**
 * Unit tests for `task-store.ts` (spec §4.8 + Appendix B item 5).
 *
 * Coverage:
 * - Insert / retrieve / contains / size.
 * - Terminal record eviction after `TERMINAL_EVICTION_MS` (300s).
 * - Non-terminal records never evicted.
 * - `markTerminal` flips a non-terminal record to terminal preserving
 *   `jobProxy` reference (idempotent — first-write-wins).
 * - JobProxy reference preserved across `markTerminal` (referential).
 * - `TERMINAL_EVICTION_MS === 300_000` cross-runtime parity assertion.
 * - Concurrent `markTerminal` first-write-wins via `Promise.all`.
 *
 * Mirrors Java's `MeshA2ATaskStoreTest`.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import type { JobProxy } from "@mcpmesh/core";

import {
  A2ATaskStore,
  TERMINAL_EVICTION_MS,
  type TaskRecord,
} from "../../../a2a/producer/task-store.js";

/**
 * Fake JobProxy — we only need referential equality + shape compatibility
 * for the store tests. Real `JobProxy` is a napi-rs class so we can't
 * construct one without binding the registry; the store is purely a
 * `Map<string, TaskRecord>` wrapper that never calls JobProxy methods.
 */
function fakeJobProxy(id: string): JobProxy {
  return {
    jobId: id,
    status: async () => ({ status: "running" }),
    wait: async () => null,
    cancel: async () => undefined,
  } as unknown as JobProxy;
}

describe("A2ATaskStore (spec §4.8)", () => {
  let store: A2ATaskStore;

  beforeEach(() => {
    store = new A2ATaskStore();
  });

  /** Spec Appendix B item 5: 300s grace window matches Python/Java exactly. */
  it("TERMINAL_EVICTION_MS === 300_000 (cross-runtime parity)", () => {
    expect(TERMINAL_EVICTION_MS).toBe(300_000);
  });

  /** Insert + retrieve a terminal record. */
  it("inserts and retrieves a terminal record", () => {
    const record: TaskRecord = {
      sessionId: "t1",
      terminalEnvelope: { id: "t1", status: { state: "completed" } },
      terminalAt: Date.now(),
      jobProxy: null,
    };
    store.put("t1", record);
    expect(store.contains("t1")).toBe(true);
    expect(store.get("t1")).toBe(record);
    expect(store.size()).toBe(1);
  });

  /** Insert + retrieve a non-terminal record; jobProxy ref preserved. */
  it("preserves JobProxy referential equality across put/get", () => {
    const proxy = fakeJobProxy("job-1");
    const record: TaskRecord = {
      sessionId: "t2",
      jobProxy: proxy,
    };
    store.put("t2", record);
    const retrieved = store.get("t2");
    expect(retrieved).toBeDefined();
    expect(retrieved!.jobProxy).toBe(proxy);
    expect(retrieved!.terminalEnvelope).toBeUndefined();
    expect(retrieved!.terminalAt).toBeUndefined();
  });

  /** Spec §4.5: markTerminal flips non-terminal → terminal. */
  it("markTerminal flips non-terminal record to terminal", () => {
    const proxy = fakeJobProxy("job-2");
    store.put("t3", { sessionId: "t3", jobProxy: proxy });
    const env = { id: "t3", status: { state: "completed" } };

    const updated = store.markTerminal("t3", env);
    expect(updated).toBeDefined();
    expect(updated!.terminalEnvelope).toBe(env);
    expect(updated!.terminalAt).toBeTypeOf("number");
    // jobProxy preserved on terminal record so callers can still read
    // status() in the eviction grace window.
    expect(updated!.jobProxy).toBe(proxy);
  });

  /** Spec §4.5: idempotent ack — first-write-wins. */
  it("markTerminal is idempotent (first-write-wins)", () => {
    store.put("t4", { sessionId: "t4", jobProxy: fakeJobProxy("job-3") });
    const env1 = { id: "t4", status: { state: "completed" } };
    const env2 = { id: "t4", status: { state: "failed" } };

    const r1 = store.markTerminal("t4", env1);
    const r2 = store.markTerminal("t4", env2);

    // Second call returns the SAME record with env1 still cached.
    expect(r2).toBeDefined();
    expect(r2!.terminalEnvelope).toBe(env1);
    expect(r2!.terminalAt).toBe(r1!.terminalAt);
  });

  /** markTerminal on unknown task id returns undefined (no insert). */
  it("markTerminal returns undefined for unknown task id", () => {
    const result = store.markTerminal(
      "ghost",
      { status: { state: "completed" } },
    );
    expect(result).toBeUndefined();
    expect(store.contains("ghost")).toBe(false);
  });

  /** Spec §4.8 eviction: terminal records >300s old evicted on access. */
  it("evicts terminal records older than TERMINAL_EVICTION_MS on access", () => {
    vi.useFakeTimers();
    try {
      const t0 = Date.parse("2026-01-01T00:00:00Z");
      vi.setSystemTime(t0);

      store.put("t5", {
        sessionId: "t5",
        terminalEnvelope: { id: "t5", status: { state: "completed" } },
        terminalAt: Date.now(),
        jobProxy: null,
      });
      expect(store.contains("t5")).toBe(true);

      // Advance well past the 300s eviction window.
      vi.setSystemTime(t0 + TERMINAL_EVICTION_MS + 1_000);
      expect(store.contains("t5")).toBe(false);
      expect(store.get("t5")).toBeUndefined();
      expect(store.size()).toBe(0);
    } finally {
      vi.useRealTimers();
    }
  });

  /** Non-terminal records never auto-evicted regardless of clock advance. */
  it("does NOT evict non-terminal records even after long durations", () => {
    vi.useFakeTimers();
    try {
      const t0 = Date.parse("2026-01-01T00:00:00Z");
      vi.setSystemTime(t0);

      const proxy = fakeJobProxy("job-long");
      store.put("t6", { sessionId: "t6", jobProxy: proxy });

      // Advance an hour — non-terminal records never expire.
      vi.setSystemTime(t0 + 60 * 60_000);
      expect(store.contains("t6")).toBe(true);
      expect(store.get("t6")!.jobProxy).toBe(proxy);
    } finally {
      vi.useRealTimers();
    }
  });

  /**
   * Concurrent markTerminal — first-write-wins.
   *
   * JavaScript is single-threaded so these "concurrent" calls are
   * actually sequential within the event loop; this test asserts the
   * invariant that markTerminal preserves the first-write regardless of
   * how many async callers race for it (mirrors Java's
   * `computeIfPresent` semantics).
   */
  it("concurrent markTerminal calls converge to first-write-wins", async () => {
    store.put("t7", { sessionId: "t7", jobProxy: fakeJobProxy("job-c") });
    const env1 = { id: "t7", status: { state: "completed" } };
    const env2 = { id: "t7", status: { state: "canceled" } };
    const env3 = { id: "t7", status: { state: "failed" } };

    await Promise.all([
      Promise.resolve(store.markTerminal("t7", env1)),
      Promise.resolve(store.markTerminal("t7", env2)),
      Promise.resolve(store.markTerminal("t7", env3)),
    ]);

    const final = store.get("t7");
    expect(final).toBeDefined();
    expect(final!.terminalEnvelope).toBe(env1);
  });

  /** clear() drops every record. */
  it("clear() removes all records", () => {
    store.put("a", { sessionId: "a", jobProxy: fakeJobProxy("a") });
    store.put("b", {
      sessionId: "b",
      terminalEnvelope: {},
      terminalAt: Date.now(),
    });
    expect(store.size()).toBe(2);
    store.clear();
    expect(store.size()).toBe(0);
    expect(store.contains("a")).toBe(false);
    expect(store.contains("b")).toBe(false);
  });

  afterEach(() => {
    vi.useRealTimers();
  });
});
