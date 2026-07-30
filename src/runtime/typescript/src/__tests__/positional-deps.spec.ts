/**
 * Issue #1401 — the positional-dependency migration guard.
 *
 * `mesh.route()` / `mesh.a2a.mount()` handlers receive an ARRAY as of 3.4.0,
 * not a capability-keyed object. An un-migrated `deps.<capability>` read on an
 * array would evaluate to `undefined` and fail later, deep in the handler, as
 * `Cannot read properties of undefined (reading 'call')`. `wrapPositionalDeps`
 * turns that into a prescriptive throw.
 *
 * Two properties, and the second matters as much as the first:
 *
 *   1. The trap FIRES on a declared capability, naming its index and printing
 *      the corrected handler signature.
 *   2. The trap is INERT for everything else. A `get` trap sits in front of
 *      every property read a host makes, and hosts duck-type through invented
 *      sentinel keys — `$$typeof`, `@@__IMMUTABLE_ITERABLE__@@`, `nodeType`,
 *      `tagName`, `hasAttribute`, `toJSON`, `constructor` were all measured
 *      coming out of ONE vitest `toHaveBeenCalledWith` assertion. Throwing on
 *      unrecognised string keys would break `console.log`, `JSON.stringify`,
 *      and users' own route tests. The pass-through half of the contract is
 *      pinned below so a future "tighten the guard" refactor fails here.
 */
import { describe, it, expect, vi } from "vitest";
import util from "node:util";
import { wrapPositionalDeps } from "../positional-deps.js";
import type { McpMeshTool } from "../types.js";

const proxyA = (async () => "a") as unknown as McpMeshTool;

function routeDeps(): Array<McpMeshTool | null> {
  return wrapPositionalDeps([proxyA, null], ["add", "greet-lucky"], "mesh.route");
}

describe("wrapPositionalDeps — the guard fires (#1401)", () => {
  it("throws on a declared capability read by name, naming the index", () => {
    const deps = routeDeps() as unknown as Record<string, unknown>;
    expect(() => deps.add).toThrowError(
      /mesh\.route dependencies are positional as of 3\.4\.0\./
    );
    let message = "";
    try {
      void deps.add;
    } catch (err) {
      message = (err as Error).message;
    }
    expect(message).toContain("You accessed `deps.add`; \"add\" is declared dependency [0].");
    expect(message).toContain(
      "Rewrite the handler as:  async (req, res, [add, greet_lucky]) => { ... }"
    );
  });

  it("renders a bracket accessor for a non-identifier capability", () => {
    const deps = routeDeps() as unknown as Record<string, unknown>;
    let message = "";
    try {
      void deps["greet-lucky"];
    } catch (err) {
      message = (err as Error).message;
    }
    // The old shipped example used exactly this form:
    //   const greetLucky = deps["greet-lucky"];
    expect(message).toContain(
      'You accessed `deps["greet-lucky"]`; "greet-lucky" is declared dependency [1].'
    );
  });

  it("prescribes the a2a signature for the a2a surface", () => {
    const deps = wrapPositionalDeps(
      [null],
      ["date_service"],
      "mesh.a2a.mount"
    ) as unknown as Record<string, unknown>;
    let message = "";
    try {
      void deps.date_service;
    } catch (err) {
      message = (err as Error).message;
    }
    expect(message).toContain("mesh.a2a.mount dependencies are positional");
    expect(message).toContain(
      "Rewrite the handler as:  async ([date_service], payload) => { ... }"
    );
  });

  it("fires even when the capability collides with an Array.prototype member", () => {
    // A capability literally named `map` must not silently hand back
    // Array.prototype.map — the declared-capability check runs first.
    const deps = wrapPositionalDeps([proxyA], ["map"], "mesh.route") as unknown as Record<
      string,
      unknown
    >;
    expect(() => deps.map).toThrowError(/"map" is declared dependency \[0\]/);
  });

  it("still throws on a dependency whose slot is unresolved (null)", () => {
    // The un-migrated read is wrong regardless of resolution state — a silent
    // `undefined` here would look identical to the legitimate `null`.
    const deps = routeDeps() as unknown as Record<string, unknown>;
    expect(() => deps["greet-lucky"]).toThrow();
  });
});

describe("wrapPositionalDeps — the guard is inert for everything else (#1401)", () => {
  it("index reads return the slot", () => {
    const deps = routeDeps();
    expect(deps[0]).toBe(proxyA);
    expect(deps[1]).toBeNull();
    expect(deps[2]).toBeUndefined();
  });

  it("array destructuring works", () => {
    const [add, lucky] = routeDeps();
    expect(add).toBe(proxyA);
    expect(lucky).toBeNull();
  });

  it("length works", () => {
    expect(routeDeps().length).toBe(2);
  });

  it("Array.isArray sees through the Proxy to the target", () => {
    expect(Array.isArray(routeDeps())).toBe(true);
  });

  it("spread works", () => {
    expect([...routeDeps()]).toEqual([proxyA, null]);
  });

  it("for...of works", () => {
    const seen: unknown[] = [];
    for (const dep of routeDeps()) seen.push(dep);
    expect(seen).toEqual([proxyA, null]);
  });

  it("console.log does not throw", () => {
    const spy = vi.spyOn(console, "log").mockImplementation(() => {});
    expect(() => console.log(routeDeps())).not.toThrow();
    spy.mockRestore();
  });

  it("util.inspect does not throw", () => {
    expect(() => util.inspect(routeDeps())).not.toThrow();
    expect(util.inspect(routeDeps())).toContain("[");
  });

  it("JSON.stringify does not throw (reads toJSON)", () => {
    expect(() => JSON.stringify(routeDeps())).not.toThrow();
    expect(JSON.parse(JSON.stringify(routeDeps()))).toEqual([null, null]);
  });

  it("String()/template interpolation does not throw (reads join, toString)", () => {
    expect(() => `${routeDeps()}`).not.toThrow();
  });

  it("Array.prototype methods work", () => {
    expect(routeDeps().filter((d) => d !== null)).toEqual([proxyA]);
    expect(routeDeps().map((d) => d === null)).toEqual([false, true]);
    expect(routeDeps().indexOf(proxyA)).toBe(0);
    expect(routeDeps().slice(1)).toEqual([null]);
  });

  it("vitest matchers work on the wrapped array (the $$typeof regression)", () => {
    // pretty-format probes $$typeof / @@__IMMUTABLE_*__@@ / nodeType /
    // tagName / hasAttribute to duck-type the value. An unbounded throw here
    // turned this assertion into a PrettyFormatPluginError.
    const handler = vi.fn();
    handler(routeDeps());
    expect(handler).toHaveBeenCalledWith([proxyA, null]);
    expect(routeDeps()).toEqual([proxyA, null]);
  });

  it("an UNDECLARED string key is plain-array undefined, not a throw", () => {
    // This was `undefined` before positional injection too, so it is a typo,
    // not a migration signal — and there would be no rewrite to prescribe.
    const deps = routeDeps() as unknown as Record<string, unknown>;
    expect(deps.notADependency).toBeUndefined();
  });

  it("skips the Proxy entirely when nothing is declared", () => {
    const bare: Array<McpMeshTool | null> = [];
    expect(wrapPositionalDeps(bare, [], "mesh.route")).toBe(bare);
  });
});
