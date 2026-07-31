/**
 * Strict-mode COMPILE test for the positional dependency contract (#1401).
 *
 * The runtime Proxy in `positional-deps.ts` is a *migration* aid — it fires at
 * request time. The stronger guarantee is that an un-migrated handler does not
 * reach runtime at all: the shape change from `Record<string, McpMeshTool>` to
 * `Array<McpMeshTool | null>` is a compile error at every site that named a
 * capability, INCLUDING the `mount<{...}>` type argument.
 *
 * The project's `tsc --noEmit` (strict) type-checks this file, so each
 * `@ts-expect-error` below is an assertion: if a listed pattern ever starts
 * compiling again, the *unused* `@ts-expect-error` breaks the build.
 *
 * Nothing here is invoked — the bodies exist purely for the compiler. Vitest
 * runs a trivial assertion so the file counts as a spec.
 */
import { describe, it, expect } from "vitest";
import type { Request, Response } from "express";
import type { Application } from "express";
import { route } from "../route.js";
import { mount } from "../a2a/producer/mount.js";
import type {
  A2ADependencies,
  A2AHandler,
} from "../a2a/producer/dispatcher.js";
import type {
  MeshRouteHandler,
  RouteDependencies,
} from "../route.js";
import type { McpMeshTool, PositionalDependencies } from "../index.js";

const app = {} as unknown as Application;
const config = { path: "/agents/date", skillId: "get-date", dependencies: ["date_service"] };

// ── The OLD capability-keyed type argument must NOT satisfy the constraint ───
// This is the load-bearing compile break: a consumer's
// `mount<{ date_service: McpMeshTool }>(...)` stops compiling outright rather
// than surviving to runtime and reading `undefined`.
// @ts-expect-error #1401: capability-keyed deps are gone; the type argument must be an array (or tuple) of McpMeshTool | null.
type _OldKeyedHandlerArg = A2AHandler<{ date_service: McpMeshTool }>;
// @ts-expect-error #1401: same constraint on the route handler type.
type _OldKeyedRouteArg = MeshRouteHandler<{ calculator: McpMeshTool }>;

// ── ...and the NEW forms must compile ────────────────────────────────────────
function _newMountTypeArgsCompile(): void {
  // Tuple — per-slot typing, the recommended form.
  mount<[McpMeshTool | null]>(app, config, async ([dateService], _payload) => {
    return dateService === null ? null : await dateService({});
  });
  // The default/alias name still works and still names the array type.
  mount<A2ADependencies>(app, config, async (deps) => deps[0]);
  // No type argument at all.
  mount(app, config, async ([dateService]) => dateService);
}

// ── The alias types are all the same array type ──────────────────────────────
const _routeDepsIsPositional: RouteDependencies = [] as PositionalDependencies;
const _a2aDepsIsPositional: A2ADependencies = [] as PositionalDependencies;
const _positionalIsRouteDeps: PositionalDependencies = [] as RouteDependencies;

// ── mesh.route: naming a capability on deps must NOT compile ─────────────────
const _oldRouteAccessIsRejected: MeshRouteHandler = async (_req, _res, deps) => {
  // @ts-expect-error #1401: `deps` is an array; capabilities are not keys.
  void deps.calculator;
};

const _oldRouteDestructureIsRejected: MeshRouteHandler = async (
  _req,
  _res,
  // @ts-expect-error #1401: object destructuring no longer matches the deps type.
  { calculator }
) => {
  void calculator;
};

// ── ...and the positional forms compile ──────────────────────────────────────
const _newRouteDestructureCompiles: MeshRouteHandler = async (
  _req,
  _res,
  [calculator]
) => {
  if (calculator) await calculator({});
};

const _tupleTypedRouteHandler: MeshRouteHandler<[McpMeshTool, McpMeshTool | null]> =
  async (_req, _res, [always, maybe]) => {
    await always({});
    if (maybe) await maybe({});
  };

function _routeFactoryAcceptsPositionalHandler(): void {
  // Unannotated: `add` / `subtract` are contextually typed McpMeshTool | null.
  route(
    [{ capability: "add" }, { capability: "subtract" }],
    async (_req: Request, _res: Response, [add, subtract]) => {
      if (add) await add({});
      if (subtract) await subtract({});
    }
  );
  // The 4-parameter (next) form is accepted by the same signature.
  route([{ capability: "add" }], async (_req, _res, [add], next) => {
    if (!add) return next();
    await add({});
  });
  // Tuple type argument for per-slot narrowing at the factory.
  route<[McpMeshTool, McpMeshTool | null]>(
    [{ capability: "add" }, { capability: "subtract" }],
    async (_req, _res, [add, subtract]) => {
      await add({});
      if (subtract) await subtract({});
    }
  );
}

// ── A2AHandler generic still constrains to the array shape ───────────────────
const _a2aHandlerTuple: A2AHandler<[McpMeshTool | null]> = async ([dep]) => dep;

describe("positional dependency contract compiles as documented (#1401)", () => {
  it("type-checks the positional idioms and rejects the keyed ones", () => {
    expect(typeof _newMountTypeArgsCompile).toBe("function");
    expect(typeof _routeFactoryAcceptsPositionalHandler).toBe("function");
    expect(typeof _oldRouteAccessIsRejected).toBe("function");
    expect(typeof _oldRouteDestructureIsRejected).toBe("function");
    expect(typeof _newRouteDestructureCompiles).toBe("function");
    expect(typeof _tupleTypedRouteHandler).toBe("function");
    expect(typeof _a2aHandlerTuple).toBe("function");
    expect(_routeDepsIsPositional).toEqual([]);
    expect(_a2aDepsIsPositional).toEqual([]);
    expect(_positionalIsRouteDeps).toEqual([]);
    // Reference the compile-only aliases so `noUnusedLocals` stays quiet;
    // their assertions live in the @ts-expect-error directives above.
    const _refs: [_OldKeyedHandlerArg?, _OldKeyedRouteArg?] = [];
    expect(_refs).toEqual([]);
  });
});
