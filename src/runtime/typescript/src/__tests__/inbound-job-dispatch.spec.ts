/**
 * Tests for the inbound MeshJob dispatch wrapper (Phase 1).
 *
 * Mirrors the behavioural envelope of Python's
 * `tests/test_job_dispatch.py`. We don't bind to the napi-rs
 * `JobController` here — those are exercised by the cross-FFI test
 * suite. Instead we verify:
 *
 *   - `readJobHeaders` returns the right shape on the standard
 *     headers + on absent / malformed inputs;
 *   - `runWithJobContext` runs the thunk inside `CURRENT_JOB.run`
 *     when a controller is present, and bypasses the wrap when
 *     either jobId or controller is null;
 *   - the auto-complete path fires only when the controller hadn't
 *     already gone terminal, and propagates user exceptions verbatim.
 */
import { describe, it, expect, vi } from "vitest";
import {
  readJobHeaders,
  runWithJobContext,
} from "../inbound-job-dispatch.js";
import { currentJob } from "../job-context.js";

describe("readJobHeaders", () => {
  it("returns [null, null] when headers is null/undefined", () => {
    expect(readJobHeaders(null)).toEqual([null, null]);
    expect(readJobHeaders(undefined)).toEqual([null, null]);
    expect(readJobHeaders({})).toEqual([null, null]);
  });

  it("extracts job id only when X-Mesh-Timeout is absent", () => {
    expect(readJobHeaders({ "x-mesh-job-id": "job-123" })).toEqual([
      "job-123",
      null,
    ]);
  });

  it("extracts both headers and parses timeout as float", () => {
    expect(
      readJobHeaders({
        "x-mesh-job-id": "job-456",
        "x-mesh-timeout": "12.5",
      }),
    ).toEqual(["job-456", 12.5]);
  });

  it("ignores malformed timeout (non-numeric / non-positive)", () => {
    expect(
      readJobHeaders({
        "x-mesh-job-id": "j1",
        "x-mesh-timeout": "abc",
      }),
    ).toEqual(["j1", null]);
    expect(
      readJobHeaders({
        "x-mesh-job-id": "j2",
        "x-mesh-timeout": "0",
      }),
    ).toEqual(["j2", null]);
    expect(
      readJobHeaders({
        "x-mesh-job-id": "j3",
        "x-mesh-timeout": "-1.5",
      }),
    ).toEqual(["j3", null]);
  });
});

describe("runWithJobContext", () => {
  it("runs the thunk directly when jobId or controller is null", async () => {
    const result = await runWithJobContext(null, null, null, async () => {
      // No active job inside the thunk.
      expect(currentJob()).toBeNull();
      return "ran";
    });
    expect(result).toBe("ran");
  });

  it("sets CURRENT_JOB inside the scope when controller is provided", async () => {
    // Build a stub that mimics the JobController surface readWithJobContext
    // touches: isTerminal() and complete(). The napi binding's actual
    // behaviour is exercised in the Rust test suite.
    const stub = {
      isTerminal: vi.fn().mockResolvedValue(true), // already terminal → no auto-complete
      complete: vi.fn().mockResolvedValue(undefined),
      fail: vi.fn().mockResolvedValue(undefined),
    };
    const result = await runWithJobContext(
      "job-abc",
      30,
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      stub as any,
      async () => {
        const cur = currentJob();
        expect(cur?.jobId).toBe("job-abc");
        expect(cur?.deadlineSecsRemaining).toBe(30);
        return 42;
      },
    );
    expect(result).toBe(42);
    // Already-terminal probe → no auto-complete.
    expect(stub.complete).not.toHaveBeenCalled();
    // Outside the scope CURRENT_JOB is gone again.
    expect(currentJob()).toBeNull();
  });

  it("auto-completes when the controller is not yet terminal", async () => {
    const stub = {
      isTerminal: vi.fn().mockResolvedValue(false),
      complete: vi.fn().mockResolvedValue(undefined),
      fail: vi.fn().mockResolvedValue(undefined),
    };
    const userValue = { ok: true, n: 42 };
    const result = await runWithJobContext(
      "job-auto",
      null,
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      stub as any,
      async () => userValue,
    );
    // withJobAsync round-trips through napi-rs serde so the resolved
    // value is a structurally-equal copy, not the same reference.
    expect(result).toStrictEqual(userValue);
    expect(stub.complete).toHaveBeenCalledOnce();
    expect(stub.complete).toHaveBeenCalledWith(userValue);
  });

  it("auto-completes nested JSON-safe arrays/objects verbatim", async () => {
    const stub = {
      isTerminal: vi.fn().mockResolvedValue(false),
      complete: vi.fn().mockResolvedValue(undefined),
      fail: vi.fn().mockResolvedValue(undefined),
    };
    const userValue = { items: [1, 2, { nested: "ok" }], count: 3 };
    await runWithJobContext(
      "job-deep",
      null,
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      stub as any,
      async () => userValue,
    );
    // Nested-but-JSON-safe → forwarded verbatim, no { value: ... } wrap.
    expect(stub.complete).toHaveBeenCalledWith(userValue);
  });

  it("calls fail() on user exception when not yet terminal", async () => {
    const stub = {
      isTerminal: vi.fn().mockResolvedValue(false),
      complete: vi.fn().mockResolvedValue(undefined),
      fail: vi.fn().mockResolvedValue(undefined),
    };
    await expect(
      runWithJobContext(
        "job-fail",
        null,
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        stub as any,
        async () => {
          throw new Error("boom");
        },
      ),
    ).rejects.toThrow("boom");
    expect(stub.fail).toHaveBeenCalledOnce();
    expect(stub.fail).toHaveBeenCalledWith("boom");
    expect(stub.complete).not.toHaveBeenCalled();
  });

  it("does not call fail() when the controller is already terminal", async () => {
    const stub = {
      isTerminal: vi.fn().mockResolvedValue(true),
      complete: vi.fn().mockResolvedValue(undefined),
      fail: vi.fn().mockResolvedValue(undefined),
    };
    await expect(
      runWithJobContext(
        "job-already",
        null,
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        stub as any,
        async () => {
          throw new Error("ignored-fail");
        },
      ),
    ).rejects.toThrow("ignored-fail");
    expect(stub.fail).not.toHaveBeenCalled();
  });
});
