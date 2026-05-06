/**
 * Tests for MeshJobSubmitter (Phase 1 — MeshJob substrate).
 *
 * We don't bind to a real registry here — the napi `submitJob` is
 * mocked via vitest. The tests exercise:
 *
 *   - The retry policy (3 attempts on transient errors with 200ms /
 *     1s / 5s backoff — same as Python).
 *   - Fail-fast on non-transient errors (404 / 4xx / serialization).
 *   - Date → unix-epoch-seconds conversion for `totalDeadline`.
 *   - Number → unix-epoch-seconds normalisation (heuristic for
 *     callers that pass milliseconds).
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { MeshJobSubmitter } from "../mesh-job-submitter.js";

// Mock napi-rs core's submit_job. Vitest hoists the factory above
// imports so the SDK reads the mock regardless of import order.
vi.mock("@mcpmesh/core", async () => {
  const actual = await vi.importActual<Record<string, unknown>>("@mcpmesh/core");
  return {
    ...actual,
    submitJob: vi.fn(),
  };
});

import { submitJob } from "@mcpmesh/core";

const submitJobMock = submitJob as unknown as ReturnType<typeof vi.fn>;

describe("MeshJobSubmitter", () => {
  beforeEach(() => {
    submitJobMock.mockReset();
  });

  it("calls napi submitJob with the bound capability + payload", async () => {
    submitJobMock.mockResolvedValueOnce({ jobId: "job-123" });
    const sub = new MeshJobSubmitter(
      "generate_report",
      "consumer-abc",
      "http://localhost:8000",
    );
    const proxy = await sub.submit({ user_id: "u1", sections: ["a"] });
    expect(proxy).toEqual({ jobId: "job-123" });
    expect(submitJobMock).toHaveBeenCalledOnce();
    expect(submitJobMock).toHaveBeenCalledWith({
      registryUrl: "http://localhost:8000",
      capability: "generate_report",
      payload: { user_id: "u1", sections: ["a"] },
      submittedBy: "consumer-abc",
      ownerInstanceId: undefined,
      maxDuration: undefined,
      maxRetries: undefined,
      totalDeadline: undefined,
    });
  });

  it("forwards optional knobs to napi submit", async () => {
    submitJobMock.mockResolvedValueOnce({ jobId: "j" });
    const sub = new MeshJobSubmitter("c", "by", "http://r");
    const deadlineMs = 1735689600 * 1000; // 2025-01-01T00:00:00Z
    await sub.submit(
      { foo: 1 },
      {
        maxDuration: 60,
        maxRetries: 3,
        totalDeadline: new Date(deadlineMs),
      },
    );
    const call = submitJobMock.mock.calls[0][0];
    expect(call.maxDuration).toBe(60);
    expect(call.maxRetries).toBe(3);
    expect(call.totalDeadline).toBe(1735689600);
  });

  it("normalises a millisecond-shaped number to seconds for totalDeadline", async () => {
    submitJobMock.mockResolvedValueOnce({});
    const sub = new MeshJobSubmitter("c", "by", "http://r");
    await sub.submit({}, { totalDeadline: 1735689600_000 });
    expect(submitJobMock.mock.calls[0][0].totalDeadline).toBe(1735689600);
  });

  it("passes seconds-shaped number through unchanged", async () => {
    submitJobMock.mockResolvedValueOnce({});
    const sub = new MeshJobSubmitter("c", "by", "http://r");
    await sub.submit({}, { totalDeadline: 1735689600 });
    expect(submitJobMock.mock.calls[0][0].totalDeadline).toBe(1735689600);
  });

  it("retries up to 3 times on a network error then succeeds", async () => {
    submitJobMock
      .mockRejectedValueOnce(new Error("backend error: network error: ECONNREFUSED"))
      .mockRejectedValueOnce(new Error("backend error: network error: ECONNREFUSED"))
      .mockResolvedValueOnce({ jobId: "ok" });
    const sub = new MeshJobSubmitter("c", "by", "http://r");
    const proxy = await sub.submit({});
    expect(proxy).toEqual({ jobId: "ok" });
    expect(submitJobMock).toHaveBeenCalledTimes(3);
  });

  it("fails-fast on a 4xx error (not transient)", async () => {
    submitJobMock.mockRejectedValueOnce(
      new Error("backend error: backend error: HTTP 400: bad payload"),
    );
    const sub = new MeshJobSubmitter("c", "by", "http://r");
    await expect(sub.submit({})).rejects.toThrow(/HTTP 400/);
    expect(submitJobMock).toHaveBeenCalledOnce();
  });

  it("fails-fast on job-not-found (404)", async () => {
    submitJobMock.mockRejectedValueOnce(
      new Error("backend error: job not found: abc"),
    );
    const sub = new MeshJobSubmitter("c", "by", "http://r");
    await expect(sub.submit({})).rejects.toThrow(/not found/);
    expect(submitJobMock).toHaveBeenCalledOnce();
  });

  it("propagates the last transient error after exhausting retries", async () => {
    submitJobMock.mockRejectedValue(
      new Error("backend error: backend unavailable: 503"),
    );
    const sub = new MeshJobSubmitter("c", "by", "http://r");
    await expect(sub.submit({})).rejects.toThrow(/backend unavailable/);
    // 3 attempts total per the policy.
    expect(submitJobMock).toHaveBeenCalledTimes(3);
  }, 10_000);

  it("rejects an invalid totalDeadline shape with a TypeError", async () => {
    const sub = new MeshJobSubmitter("c", "by", "http://r");
    await expect(
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      sub.submit({}, { totalDeadline: "not-a-date" as any }),
    ).rejects.toThrow(TypeError);
  });
});
