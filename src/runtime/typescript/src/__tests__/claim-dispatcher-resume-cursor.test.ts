/**
 * Issue #1277 (Wave 2b): TypeScript `resumeCursor` opt-in gate.
 *
 * The claim dispatcher seeds a reclaimed `JobController` from the claim
 * response's persisted `recv_cursor` map ONLY when the tool opted in
 * (`resumeCursor: true`) AND the registry returned a usable, non-empty
 * cursor. Otherwise it passes `undefined` ⇒ replay-from-0 (the Wave 1/2a
 * default posture).
 *
 * These tests exercise the GATE by spying on `makeJobController` — no live
 * native controller is needed. We assert the dispatcher forwards the claimed
 * `recv_cursor` as the 5th (`initialCursors`) constructor arg when opted in,
 * and `undefined` when the flag is off or the cursor is absent/malformed.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";

// Capture makeJobController call args per-test. The controller shape only
// needs the methods `_dispatch` touches on the happy path (none, since
// runWithJobContext is a pass-through and the handler resolves).
//
// `vi.hoisted` so the spy exists when the (hoisted) vi.mock factory runs.
const { makeJobControllerMock } = vi.hoisted(() => ({
  makeJobControllerMock: vi.fn((..._args: unknown[]) => ({
    releaseLease: vi.fn(async () => {}),
    fail: vi.fn(async () => {}),
    isTerminal: vi.fn(async () => false),
    complete: vi.fn(async () => {}),
  })),
}));

vi.mock("../inbound-job-dispatch.js", () => ({
  makeJobController: makeJobControllerMock,
  // Pass-through: run the thunk so the handler executes.
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

import { ClaimDispatcher, normalizeRecvCursor } from "../claim-dispatcher.js";

function makeDispatcher(resumeCursor?: boolean): ClaimDispatcher {
  return new ClaimDispatcher(
    "test_cap",
    "test-instance",
    "http://registry:8000",
    async () => "ok",
    undefined,
    undefined,
    resumeCursor,
  );
}

// The 5th positional arg to makeJobController is `initialCursors`.
function initialCursorsArg(): unknown {
  expect(makeJobControllerMock).toHaveBeenCalledTimes(1);
  return makeJobControllerMock.mock.calls[0][4];
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("resumeCursor gate (issue #1277)", () => {
  it("resumeCursor:true + recv_cursor present → seeds initialCursors", async () => {
    const d = makeDispatcher(true);
    const cursor = { "default": 7, "answers": 3 };

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    await (d as any)._dispatch({
      id: "job-1",
      submitted_payload: {},
      recv_cursor: cursor,
    });

    expect(initialCursorsArg()).toEqual(cursor);
  });

  it("resumeCursor:false (default) + recv_cursor present → no initialCursors", async () => {
    const d = makeDispatcher(false);

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    await (d as any)._dispatch({
      id: "job-2",
      submitted_payload: {},
      recv_cursor: { "default": 5 },
    });

    expect(initialCursorsArg()).toBeUndefined();
  });

  it("resumeCursor default undefined + recv_cursor present → no initialCursors", async () => {
    const d = makeDispatcher(); // flag omitted entirely

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    await (d as any)._dispatch({
      id: "job-2b",
      submitted_payload: {},
      recv_cursor: { "default": 5 },
    });

    expect(initialCursorsArg()).toBeUndefined();
  });

  it("resumeCursor:true + no recv_cursor → no initialCursors (replay-from-0)", async () => {
    const d = makeDispatcher(true);

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    await (d as any)._dispatch({ id: "job-3", submitted_payload: {} });

    expect(initialCursorsArg()).toBeUndefined();
  });

  it("resumeCursor:true + empty recv_cursor {} → no initialCursors", async () => {
    const d = makeDispatcher(true);

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    await (d as any)._dispatch({
      id: "job-4",
      submitted_payload: {},
      recv_cursor: {},
    });

    expect(initialCursorsArg()).toBeUndefined();
  });

  it("resumeCursor:true + malformed recv_cursor → treated as absent, never throws", async () => {
    const d = makeDispatcher(true);

    // Non-object cursor value; the gate must degrade to replay, not throw.
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    await (d as any)._dispatch({
      id: "job-5",
      submitted_payload: {},
      recv_cursor: "not-an-object",
    });

    expect(initialCursorsArg()).toBeUndefined();
  });

  it("resumeCursor:true + partially-junk recv_cursor → keeps only valid seqs", async () => {
    const d = makeDispatcher(true);

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    await (d as any)._dispatch({
      id: "job-6",
      submitted_payload: {},
      recv_cursor: { good: 4, negative: -1, frac: 2.5, str: "x", nul: null },
    });

    expect(initialCursorsArg()).toEqual({ good: 4 });
  });
});

describe("normalizeRecvCursor (fail-safe helper)", () => {
  it("returns undefined for absent / null / non-object / array inputs", () => {
    expect(normalizeRecvCursor(undefined)).toBeUndefined();
    expect(normalizeRecvCursor(null)).toBeUndefined();
    expect(normalizeRecvCursor("nope")).toBeUndefined();
    expect(normalizeRecvCursor(42)).toBeUndefined();
    expect(normalizeRecvCursor([1, 2, 3])).toBeUndefined();
  });

  it("returns undefined for empty or all-invalid maps", () => {
    expect(normalizeRecvCursor({})).toBeUndefined();
    expect(normalizeRecvCursor({ a: -1, b: 1.5, c: "x" })).toBeUndefined();
  });

  it("keeps only non-negative integer seqs", () => {
    expect(normalizeRecvCursor({ a: 0, b: 9, c: -2, d: 3.3 })).toEqual({
      a: 0,
      b: 9,
    });
  });

  it("shared cross-runtime mixed-map → only {a:4} survives", () => {
    // Identical mix asserted in the Python and Java suites: a non-negative
    // int survives; negative, fractional, and non-number values are dropped.
    expect(normalizeRecvCursor({ a: 4, b: -1, c: 2.5, d: "x" })).toEqual({
      a: 4,
    });
  });
});
