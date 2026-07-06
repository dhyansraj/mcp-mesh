/**
 * Issue #1278: UserError identity must survive the tool worker boundary.
 *
 * Under default tool isolation (MCP_MESH_TOOL_ISOLATION=true) a tool body runs
 * in a worker thread. A `UserError` (or subclass such as `MeshSupersededError`)
 * thrown there is postMessage'd to the main thread via structured clone, which
 * drops the prototype. Before the fix the pool rebuilt a plain `Error`, so
 * fastmcp's `instanceof UserError` failed and it emitted the GENERIC branch —
 * prefixing the message `Tool '<name>' execution failed: ...` and corrupting
 * the reserved JSON envelope.
 *
 * These tests exercise the matched serialize/deserialize pair, pushing the
 * serialized shape through a real `structuredClone` (exactly what postMessage
 * does) so the round-trip proves the `UserError` prototype is reconstructed and
 * that generic errors are unaffected.
 */
import { describe, it, expect } from "vitest";
import { UserError } from "fastmcp";
import {
  serializeError,
  deserializeError,
} from "../worker-error-serde.js";
import { MeshSupersededError } from "../superseded.js";

/** Mimic the worker hop: serialize → structured-clone (postMessage) → deserialize. */
function roundTrip(err: unknown): Error {
  return deserializeError(structuredClone(serializeError(err)));
}

/**
 * Reproduce fastmcp's exact error-branch discriminator
 * (chunk-LWU5CQGW.js:1199-1216) so we can assert the user-visible wire text
 * without booting a full FastMCP HTTP server.
 */
function fastmcpErrorText(error: unknown, toolName = "some_tool"): string {
  if (error instanceof UserError) {
    return error.message; // clean branch
  }
  const errorMessage = error instanceof Error ? error.message : String(error);
  return `Tool '${toolName}' execution failed: ${errorMessage}`; // generic branch
}

describe("worker-error-serde — UserError identity (issue #1278)", () => {
  it("a UserError round-trips to an instanceof UserError with the exact message", () => {
    const original = new UserError("plain user message");
    const revived = roundTrip(original);

    expect(revived).toBeInstanceOf(UserError);
    expect(revived.message).toBe("plain user message");
  });

  it("a MeshSupersededError round-trips as UserError with an intact reserved envelope", () => {
    const original = new MeshSupersededError("stale epoch 3");
    const revived = roundTrip(original);

    // Identity survives → fastmcp emits the clean branch.
    expect(revived).toBeInstanceOf(UserError);
    // Message preserved EXACTLY — the reserved JSON must survive verbatim.
    expect(revived.message).toBe(original.message);
    const parsed = JSON.parse(revived.message);
    expect(parsed).toEqual({ error: "claim_superseded", detail: "stale epoch 3" });
    // Diagnostic name restored.
    expect(revived.name).toBe("MeshSupersededError");
  });

  it("MeshSupersededError with no detail round-trips to the marker-only envelope", () => {
    const revived = roundTrip(new MeshSupersededError());
    expect(revived).toBeInstanceOf(UserError);
    expect(JSON.parse(revived.message)).toEqual({ error: "claim_superseded" });
  });

  it("fastmcp emits the CLEAN envelope (no prefix) for a round-tripped MeshSupersededError", () => {
    const revived = roundTrip(new MeshSupersededError("stale epoch 3"));
    const text = fastmcpErrorText(revived, "reject_superseded");

    // The fix: no `Tool '...' execution failed:` prefix; text is valid JSON.
    expect(text).not.toMatch(/execution failed:/);
    expect(JSON.parse(text)).toEqual({
      error: "claim_superseded",
      detail: "stale epoch 3",
    });
  });

  it("carries structured-cloneable UserError extras", () => {
    const original = new UserError("with extras", { reason: "quota", limit: 5 });
    const revived = roundTrip(original) as UserError;

    expect(revived).toBeInstanceOf(UserError);
    expect(revived.extras).toEqual({ reason: "quota", limit: 5 });
  });

  it("drops non-cloneable extras but keeps message + UserError identity", () => {
    // A function is not structured-cloneable; it must not break the hop.
    const original = new UserError("keep me", {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      fn: (() => 1) as any,
    });
    const revived = roundTrip(original) as UserError;

    expect(revived).toBeInstanceOf(UserError);
    expect(revived.message).toBe("keep me");
    expect(revived.extras).toBeUndefined();
  });
});

describe("worker-error-serde — generic errors unaffected", () => {
  it("a plain Error round-trips to a plain Error, NOT a UserError", () => {
    const revived = roundTrip(new Error("boom"));

    expect(revived).toBeInstanceOf(Error);
    expect(revived).not.toBeInstanceOf(UserError);
    expect(revived.message).toBe("boom");
  });

  it("a plain Error takes fastmcp's GENERIC (prefixed) branch", () => {
    const revived = roundTrip(new Error("boom"));
    expect(fastmcpErrorText(revived, "calc")).toBe(
      "Tool 'calc' execution failed: boom",
    );
  });

  it("a TypeError subclass round-trips as a non-UserError, preserving name", () => {
    const revived = roundTrip(new TypeError("bad type"));

    expect(revived).not.toBeInstanceOf(UserError);
    expect(revived.name).toBe("TypeError");
    expect(revived.message).toBe("bad type");
  });

  it("preserves error code and a nested cause chain", () => {
    const cause = new Error("root");
    (cause as Error & { code?: string }).code = "ECONN";
    const top = new Error("wrapper", { cause });
    const revived = roundTrip(top) as Error & {
      cause?: Error & { code?: string };
    };

    expect(revived.message).toBe("wrapper");
    expect(revived.cause).toBeInstanceOf(Error);
    expect(revived.cause!.message).toBe("root");
    expect(revived.cause!.code).toBe("ECONN");
  });

  it("a non-Error throw (string) serializes and revives as a plain Error", () => {
    const revived = roundTrip("just a string");
    expect(revived).not.toBeInstanceOf(UserError);
    expect(revived.message).toBe("just a string");
  });
});
