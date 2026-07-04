/**
 * Issue #1268: claim dispatch must gate on locally-resolved required deps.
 *
 * - Pre-claim skip: the dispatcher must NOT POST /jobs/claim while a required
 *   dependency slot is unresolved locally.
 * - Pre-invoke guard: a still-unresolved required slot at invoke time must
 *   release the lease (retryable), never terminal-fail, and must NOT run the
 *   handler.
 * - Optional deps (no probe) run as before.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";

// Fake JobController captured per-test so assertions can inspect it.
let lastController: {
  releaseLease: ReturnType<typeof vi.fn>;
  fail: ReturnType<typeof vi.fn>;
} | null = null;

vi.mock("../inbound-job-dispatch.js", () => ({
  makeJobController: vi.fn(() => {
    lastController = {
      releaseLease: vi.fn(async () => {}),
      fail: vi.fn(async () => {}),
    };
    return lastController;
  }),
  // Pass-through: invoke the thunk so the handler runs when the guard allows.
  runWithJobContext: vi.fn(
    async (
      _jobId: string | null,
      _dl: number | null,
      _controller: unknown,
      invoke: () => Promise<unknown>,
    ) => invoke(),
  ),
}));

vi.mock("../proxy.js", () => ({
  runWithPropagatedHeaders: (_headers: unknown, fn: () => unknown) => fn(),
}));

import { ClaimDispatcher } from "../claim-dispatcher.js";

function makeDispatcher(
  handler: (payload: Record<string, unknown>, controller: unknown) => Promise<unknown>,
  requiredProbe?: () => string | null,
): ClaimDispatcher {
  return new ClaimDispatcher(
    "test_cap",
    "test-instance",
    "http://registry:8000",
    handler as never,
    undefined,
    requiredProbe,
  );
}

beforeEach(() => {
  lastController = null;
  vi.clearAllMocks();
});

describe("pre-invoke guard (issue #1268)", () => {
  it("unresolved required dep → releaseLease, no handler, no fail", async () => {
    const handlerCalls: unknown[] = [];
    const handler = async (payload: Record<string, unknown>) => {
      handlerCalls.push(payload);
    };
    const d = makeDispatcher(handler, () => "cap_a");

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    await (d as any)._dispatch({ id: "job-1", submitted_payload: {} });

    expect(handlerCalls).toEqual([]);
    expect(lastController).not.toBeNull();
    expect(lastController!.releaseLease).toHaveBeenCalledTimes(1);
    expect(lastController!.fail).not.toHaveBeenCalled();
  });

  it("resolved required dep → handler runs, no release", async () => {
    const handlerCalls: unknown[] = [];
    const handler = async (payload: Record<string, unknown>) => {
      handlerCalls.push(payload);
    };
    const d = makeDispatcher(handler, () => null);

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    await (d as any)._dispatch({ id: "job-2", submitted_payload: { x: 1 } });

    expect(handlerCalls).toEqual([{ x: 1 }]);
    expect(lastController!.releaseLease).not.toHaveBeenCalled();
    expect(lastController!.fail).not.toHaveBeenCalled();
  });

  it("optional deps (no probe) → handler runs (regression)", async () => {
    const handlerCalls: unknown[] = [];
    const handler = async (payload: Record<string, unknown>) => {
      handlerCalls.push(payload);
    };
    const d = makeDispatcher(handler); // no requiredProbe

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    await (d as any)._dispatch({ id: "job-3", submitted_payload: {} });

    expect(handlerCalls).toEqual([{}]);
    expect(lastController!.releaseLease).not.toHaveBeenCalled();
  });
});

describe("pre-claim skip (issue #1268)", () => {
  it("does not claim while a required dep is unresolved", async () => {
    const d = makeDispatcher(async () => {}, () => "cap_a");
    const claimSpy = vi.fn(async () => []);
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (d as any)._claimOnce = claimSpy;

    d.start();
    await new Promise((r) => setTimeout(r, 60));
    await d.stop(0);

    expect(claimSpy).not.toHaveBeenCalled();
  });

  it("claims once the required dep is resolved", async () => {
    let resolved = false;
    const d = makeDispatcher(async () => {}, () => (resolved ? null : "cap_a"));
    const claimSpy = vi.fn(async () => []);
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (d as any)._claimOnce = claimSpy;

    d.start();
    await new Promise((r) => setTimeout(r, 50));
    resolved = true;
    // Wait past one base poll interval (500ms) so the loop wakes, re-probes
    // (now resolved), and issues a claim.
    await new Promise((r) => setTimeout(r, 650));
    await d.stop(0);

    expect(claimSpy).toHaveBeenCalled();
  });
});
