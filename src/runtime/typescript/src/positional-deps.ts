/**
 * Positional dependency arrays for `mesh.route()` and `mesh.a2a.mount()`.
 *
 * Issue #1401 — as of 3.4.0 every mcp-mesh injection site in every runtime
 * pairs the Nth declared dependency with the Nth slot. TypeScript's `route`
 * and `a2a.mount` handlers used to receive a **capability-keyed object**
 * (`deps.calculator`); they now receive an **array** (`deps[0]`).
 *
 * ## Why a Proxy at all
 *
 * The shape change cannot misbind: string keys and numeric indices are
 * disjoint, so an un-migrated `deps.calculator` on the new array evaluates to
 * `undefined` — never to some *other* dependency's proxy. TypeScript is the
 * safe side of this migration by construction. But `undefined` is a poor
 * signal: it surfaces as `Cannot read properties of undefined (reading
 * 'call')` deep inside the handler at request time, and a cast
 * (`deps["cap"] as McpMeshTool | null`) — which both the shipped example and
 * `docs/a2a/producer.md` used — defeats the compile error too.
 *
 * So {@link wrapPositionalDeps} hands user code an array behind a `get` trap
 * that throws a prescriptive error naming the index and the rewrite.
 *
 * ## The trap is bounded to DECLARED CAPABILITIES, deliberately
 *
 * The obvious design — throw for *any* string key that is not a valid array
 * index, behind a positive allowlist of array/protocol members — does not
 * survive contact with real hosts. Every serious library duck-types unknown
 * values through its own invented sentinel key, and each one hits the `get`
 * trap. A single `expect(handler).toHaveBeenCalledWith(...)` in vitest probes,
 * measured:
 *
 *     $$typeof  @@__IMMUTABLE_ITERABLE__@@  @@__IMMUTABLE_RECORD__@@
 *     nodeType  tagName  hasAttribute  toJSON  constructor  length
 *
 * Seven library sentinels from one assertion in one framework — none of them
 * enumerable in advance, and React/immutable/DOM are only the ones that
 * happened to be in vitest's pretty-format. An allowlist cannot be closed over
 * that set, and getting it wrong turns a user's *passing* route test into a
 * `PrettyFormatPluginError` that hides the real assertion.
 *
 * The unbounded form also buys nothing. `deps.someUndeclaredThing` evaluated
 * to `undefined` before this change and evaluates to `undefined` after it —
 * that is not a migration signal, it is a typo, and there is no rewrite to
 * prescribe. The migration hazard is exactly and only reading a **declared
 * capability by name**, which is what "un-migrated handler" means. So:
 *
 *   - `prop` is a declared capability → throw, naming its index and printing
 *     the corrected handler signature. Checked BEFORE anything else, so a
 *     route declaring a capability literally named `map` or `length` still
 *     gets the loud error rather than silently receiving the array method.
 *   - anything else → plain array behaviour (`Reflect.get`).
 *
 * Consequences, all verified in `positional-deps.spec.ts`: `deps[0]`,
 * destructuring, spread, `for...of`, `deps.length`, array methods,
 * `console.log`, `util.inspect`, `JSON.stringify`, `Array.isArray` and
 * `expect(...)` matchers all behave as they would on the bare array.
 *
 * This wrapper exists for the 3.4.x migration window. Once un-migrated
 * handlers are no longer plausible it can be dropped and the raw array
 * returned.
 */

import type { McpMeshTool } from "./types.js";

/**
 * Resolved dependencies handed to a handler, **by position**. `deps[i]` is
 * the proxy for the i-th declared dependency, or `null` when it is not
 * currently resolved. Slots are never compacted: an unavailable dependency
 * holds its own index as `null` and never shifts a later dependency up.
 */
export type PositionalDependencies = Array<McpMeshTool | null>;

/** `deps.foo` when `foo` is an identifier, `deps["foo-bar"]` otherwise. */
function accessorForm(key: string): string {
  return /^[A-Za-z_$][A-Za-z0-9_$]*$/.test(key)
    ? `deps.${key}`
    : `deps[${JSON.stringify(key)}]`;
}

/** A capability rendered as a binding name usable in an array destructure. */
function bindingName(capability: string, index: number): string {
  const safe = capability.replace(/[^A-Za-z0-9_$]/g, "_");
  return /^[A-Za-z_$]/.test(safe) ? safe : `dep${index}`;
}

/** The corrected handler signature to print in the error. */
function rewriteHint(surface: string, capabilities: readonly string[]): string {
  const pattern = `[${capabilities.map(bindingName).join(", ")}]`;
  return surface === "mesh.a2a.mount"
    ? `async (${pattern}, payload) => { ... }`
    : `async (req, res, ${pattern}) => { ... }`;
}

/**
 * Wrap a positional dependency array in the migration guard described above.
 *
 * @param values       - Pre-sized, index-aligned dependency slots.
 * @param capabilities - Declared capabilities in declaration order; index i
 *                       describes `values[i]`.
 * @param surface      - `"mesh.route"` or `"mesh.a2a.mount"`, for the message.
 */
export function wrapPositionalDeps<T extends PositionalDependencies>(
  values: T,
  capabilities: readonly string[],
  surface: string
): T {
  // Nothing declared → nothing to mis-access. Skip the Proxy entirely so the
  // common dependency-free surface pays no cost.
  if (capabilities.length === 0) return values;

  return new Proxy(values, {
    get(target, prop, receiver) {
      if (typeof prop === "string") {
        const index = capabilities.indexOf(prop);
        if (index >= 0) {
          throw new TypeError(
            `${surface} dependencies are positional as of 3.4.0.\n` +
              `You accessed \`${accessorForm(prop)}\`; ` +
              `${JSON.stringify(prop)} is declared dependency [${index}].\n` +
              `Rewrite the handler as:  ${rewriteHint(surface, capabilities)}`
          );
        }
      }
      return Reflect.get(target, prop, receiver);
    },
  }) as T;
}

/**
 * The registry surface {@link resolvePositionalDeps} reads from. Declared
 * structurally rather than importing `RouteRegistry`, so this module stays a
 * leaf that `route.ts` (which owns `RouteRegistry`) can import without a cycle.
 */
export interface PositionalDepsSource {
  getDependenciesForRoute(routeId: string): PositionalDependencies;
}

/** The two views {@link resolvePositionalDeps} returns. */
export interface ResolvedPositionalDeps {
  /**
   * The padded slots WITHOUT the migration guard, for framework-side
   * pre-flight checks that read by index — `mesh.route`'s required-dependency
   * 503 among them. Reading those through the guarded view would let a
   * capability named like an array index turn a framework read into a throw.
   */
  readonly values: PositionalDependencies;
  /** The same slots behind the migration guard — this is what user code gets. */
  readonly deps: PositionalDependencies;
}

/**
 * Resolve one surface's declared dependencies into a positional array (issue
 * #1401): read the registry, pad missing slots, apply the migration guard.
 *
 * Shared by `mesh.route()` and `mesh.a2a.mount()`'s dispatcher — #1401 exists
 * because binding logic drifted across duplicated injection sites, so the
 * resolve/pad/wrap sequence lives in exactly one place.
 *
 * The array is built by an index-preserving read over the DECLARED
 * dependencies, never by collecting only the resolved ones.
 * `getDependenciesForRoute` already pre-sizes to the declared count; the loop
 * below re-pads defensively so a missing route entry (registry reset
 * mid-flight) yields `null` at its own index rather than a short array whose
 * later slots have shifted.
 *
 * Call this per request/dispatch — dependency resolution is live, so a proxy
 * that arrives between two calls must be visible to the second.
 *
 * @param source       - Registry to read resolved proxies from.
 * @param routeId      - The surface's (possibly pre-introspection) route id.
 * @param capabilities - Declared capabilities in declaration order; index i
 *                       describes slot i.
 * @param surface      - `"mesh.route"` or `"mesh.a2a.mount"`, for the guard's
 *                       error message.
 */
export function resolvePositionalDeps(
  source: PositionalDepsSource,
  routeId: string,
  capabilities: readonly string[],
  surface: string
): ResolvedPositionalDeps {
  const values = source.getDependenciesForRoute(routeId);
  for (let i = 0; i < capabilities.length; i++) {
    if (values[i] === undefined) {
      values[i] = null;
    }
  }
  return { values, deps: wrapPositionalDeps(values, capabilities, surface) };
}
