/**
 * Regression tests for #1163 LOW-6 — a second MeshAgent constructed in
 * the same synchronous chunk as another used to silently overwrite the
 * module-level pending-auto-start slot: `scheduleAutoStart` only ever
 * ran once per tick, so the first agent never started and nobody
 * noticed.
 *
 * Fixed behavior:
 *   - constructing a second agent in the same synchronous chunk (i.e.
 *     while the first is still pending its auto-start tick — in real
 *     Node the nextTick drains before any microtask continuation, so
 *     the guard window covers the whole danger zone) throws a clear
 *     "one MeshAgent per process" error;
 *   - sequential constructions across async boundaries (e.g. one agent
 *     per test in a harness) remain allowed: the guard auto-releases on
 *     the first microtask.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { MeshAgent } from "../agent.js";

function makeFastMCPStub() {
  return {
    addTool: vi.fn(),
    start: vi.fn(),
    getApp: vi.fn(),
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
  } as any;
}

let autoStartSpy: ReturnType<typeof vi.spyOn> | null = null;

beforeEach(() => {
  autoStartSpy = vi
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    .spyOn(MeshAgent.prototype as any, "_autoStart")
    .mockImplementation(async () => {
      /* no-op */
    });
});

afterEach(() => {
  if (autoStartSpy) {
    autoStartSpy.mockRestore();
    autoStartSpy = null;
  }
});

describe("one MeshAgent per process (#1163 LOW-6)", () => {
  it("throws when a second agent is constructed in the same synchronous chunk", () => {
    const first = new MeshAgent(makeFastMCPStub(), {
      name: "first-agent",
      httpPort: 0,
    });
    expect(first).toBeDefined();

    expect(
      () =>
        new MeshAgent(makeFastMCPStub(), {
          name: "second-agent",
          httpPort: 0,
        }),
    ).toThrow(/Only one MeshAgent may be constructed per process/);
    expect(
      () =>
        new MeshAgent(makeFastMCPStub(), {
          name: "second-agent",
          httpPort: 0,
        }),
    ).toThrow(/'first-agent' is already pending auto-start/);
  });

  it("allows constructing a new agent after the guard releases", async () => {
    const first = new MeshAgent(makeFastMCPStub(), {
      name: "first-agent",
      httpPort: 0,
    });
    expect(first).toBeDefined();

    // Cross the async boundary: the construction guard releases on the
    // first microtask (and in real Node the auto-start tick has already
    // consumed the pending slot by then).
    await Promise.resolve();

    expect(
      () =>
        new MeshAgent(makeFastMCPStub(), {
          name: "later-agent",
          httpPort: 0,
        }),
    ).not.toThrow();
  });
});
