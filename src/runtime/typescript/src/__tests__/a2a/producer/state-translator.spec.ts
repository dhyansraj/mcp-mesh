/**
 * Unit tests for `state-translator.ts` (spec §7.2).
 *
 * Coverage:
 * - Every mesh → A2A state mapping.
 * - UK→US spelling boundary (`cancelled` → `canceled`) — Appendix B
 *   documented requirement.
 * - Fallback semantics on `null` / `undefined` / unknown strings.
 * - `isTerminal` / `isMeshTerminal` truthiness across the enumerated
 *   states and spellings.
 * - `meshStatusOf` payload extraction.
 *
 * Mirrors Java's `MeshA2AStateTranslatorTest` and Python's
 * `tests/test_a2a_state_translator.py` for cross-runtime parity.
 */
import { describe, it, expect } from "vitest";

import {
  A2A_SUBMITTED,
  A2A_WORKING,
  A2A_COMPLETED,
  A2A_FAILED,
  A2A_CANCELED,
  fromMesh,
  isTerminal,
  isMeshTerminal,
  meshStatusOf,
} from "../../../a2a/producer/state-translator.js";

describe("state-translator: fromMesh (spec §7.2)", () => {
  /** Spec §7.2 mapping table — table-driven coverage. */
  it.each<[string | null | undefined, string]>([
    ["pending", A2A_SUBMITTED],
    ["working", A2A_WORKING],
    ["running", A2A_WORKING],
    ["completed", A2A_COMPLETED],
    ["failed", A2A_FAILED],
    ["cancelled", A2A_CANCELED], // UK spelling input
    ["canceled", A2A_CANCELED], // US spelling input
    ["cancelling", A2A_WORKING], // in-flight; client polls
    ["canceling", A2A_WORKING],
  ])("maps mesh state %s -> A2A state %s", (input, expected) => {
    expect(fromMesh(input)).toBe(expected);
  });

  /**
   * Spec §7.2 + Appendix B: the UK→US spelling boundary is the most
   * error-prone part of the translator. Assert EXACTLY `"canceled"`
   * (NOT `"cancelled"`) so a regression that leaks the UK spelling
   * upstream is caught here.
   */
  it("translates UK 'cancelled' to US 'canceled' (Appendix B)", () => {
    const result = fromMesh("cancelled");
    expect(result).toBe("canceled");
    expect(result).not.toBe("cancelled");
  });

  /** Spec §7.2: null / undefined / empty fall back to `working`. */
  it.each<string | null | undefined>([null, undefined, ""])(
    "falls back to working when input is %p",
    (input) => {
      expect(fromMesh(input)).toBe(A2A_WORKING);
    },
  );

  /** Spec §7.2 fallback: unknown strings → working (never escape the enum). */
  it("falls back to working on unknown strings", () => {
    expect(fromMesh("not-a-real-state")).toBe(A2A_WORKING);
    expect(fromMesh("WORKING")).toBe(A2A_WORKING); // case-sensitive
  });
});

describe("state-translator: isTerminal (spec §7.1)", () => {
  /** Spec §7.1: completed / failed / canceled are the three terminal A2A states. */
  it.each<[string, boolean]>([
    [A2A_COMPLETED, true],
    [A2A_FAILED, true],
    [A2A_CANCELED, true],
    [A2A_WORKING, false],
    [A2A_SUBMITTED, false],
  ])("isTerminal(%s) === %s", (state, expected) => {
    expect(isTerminal(state)).toBe(expected);
  });

  it("isTerminal handles null / undefined / unknown as non-terminal", () => {
    expect(isTerminal(null)).toBe(false);
    expect(isTerminal(undefined)).toBe(false);
    expect(isTerminal("nonsense")).toBe(false);
    expect(isTerminal("cancelled")).toBe(false); // UK spelling is NOT an A2A terminal
  });
});

describe("state-translator: isMeshTerminal (spec §7.2)", () => {
  /**
   * Spec §7.2: accept both UK and US spellings on the mesh side since the
   * mesh substrate emits `cancelled` but a normalizer upstream may have
   * already translated to `canceled`.
   */
  it.each<[string, boolean]>([
    ["completed", true],
    ["failed", true],
    ["cancelled", true], // UK spelling — mesh substrate
    ["canceled", true], // US spelling — already-normalized
    ["working", false],
    ["running", false],
    ["pending", false],
    ["cancelling", false], // in-flight, still polling
  ])("isMeshTerminal(%s) === %s", (state, expected) => {
    expect(isMeshTerminal(state)).toBe(expected);
  });

  it("isMeshTerminal handles null / undefined / empty as non-terminal", () => {
    expect(isMeshTerminal(null)).toBe(false);
    expect(isMeshTerminal(undefined)).toBe(false);
    expect(isMeshTerminal("")).toBe(false);
  });
});

describe("state-translator: meshStatusOf", () => {
  /** Extracts the mesh-side status field from a payload (spec §4.4). */
  it("returns the status string when present", () => {
    expect(meshStatusOf({ status: "running" })).toBe("running");
    expect(meshStatusOf({ status: "completed", progress: 1.0 })).toBe(
      "completed",
    );
  });

  /** Spec §4.4: missing status field → null (callers default to `working`). */
  it("returns null when status is missing", () => {
    expect(meshStatusOf({})).toBeNull();
  });

  it("returns null for null / undefined / non-object payloads", () => {
    expect(meshStatusOf(null)).toBeNull();
    expect(meshStatusOf(undefined)).toBeNull();
    expect(meshStatusOf(123 as unknown as Record<string, unknown>)).toBeNull();
    expect(meshStatusOf("a" as unknown as Record<string, unknown>)).toBeNull();
    expect(meshStatusOf(true as unknown as Record<string, unknown>)).toBeNull();
    expect(
      meshStatusOf(Symbol("x") as unknown as Record<string, unknown>),
    ).toBeNull();
    expect(meshStatusOf([] as unknown as Record<string, unknown>)).toBeNull();
  });

  /** Coerces non-string statuses to strings (defensive). */
  it("coerces non-string status values to strings", () => {
    expect(meshStatusOf({ status: 42 } as unknown as Record<string, unknown>)).toBe(
      "42",
    );
  });

  /** Spec §4.4: null status field → null. */
  it("returns null when status field is explicitly null", () => {
    expect(meshStatusOf({ status: null })).toBeNull();
  });
});
