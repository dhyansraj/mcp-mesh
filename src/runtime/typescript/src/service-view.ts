/**
 * Service views (RFC #1280) for the TypeScript SDK.
 *
 * Two related roles, mirroring the Java runtime (`@McpMeshService`) so the
 * cross-runtime contract (integration suite uc37) holds identically:
 *
 *   1. CONSUMER VIEW — `mesh.serviceView({ methods, minAvailable? })` produces a
 *      branded object that occupies ONE positional dependency slot in a tool's
 *      `dependencies` array but expands into N ordinary dependency edges (one per
 *      method, SORTED BY NAME for deterministic registration). At call time the
 *      framework injects a facade whose methods delegate to each edge's own
 *      resolved proxy — so different methods may bind different provider agents
 *      and rebind independently as topology changes. There are NO wire or
 *      registry changes: every method is an ordinary dependency edge.
 *
 *   2. PRODUCER SUGAR — `agent.addService("prefix", { ... })` publishes each
 *      entry (name-sorted) as an ordinary mesh tool with capability
 *      `prefix.<method>` through the existing `addTool` machinery.
 *
 * A service view is purely consumer-local: there is no group versioning and no
 * interface-level availability summary. The optional `minAvailable` floor is a
 * consumer-local circuit breaker with no wire effect.
 */

import { z } from "zod";
import type {
  DependencySpec,
  NormalizedDependency,
  TagSpec,
  MeshToolDef,
} from "./types.js";
import { normalizeDependency } from "./proxy.js";

/**
 * Reject any {@link ServiceView} in a dependency list for a surface that does
 * NOT support the tool-parameter facade form (mesh.route, mesh.a2a.mount). A
 * view there would normalize to a `capability: undefined` edge — a settle key
 * that never resolves plus a nameless dependency shipped to the registry.
 * Shared by every such call site so the error message + policy stay identical.
 */
export function assertNoServiceViewDeps(
  deps: ReadonlyArray<unknown>,
  surface: string,
): void {
  for (const dep of deps) {
    if (isServiceView(dep)) {
      throw new Error(
        `${surface} does not support mesh.serviceView(...) dependencies ` +
          `(RFC #1280 service views are a tool-parameter surface). Declare the ` +
          `individual capability deps directly, or use a service view inside ` +
          `agent.addTool(...).`,
      );
    }
  }
}

/**
 * Segment-wise dotted capability-name grammar. Kept in lockstep with the Go
 * registry validator's `capabilityNamePattern`
 * (src/core/registry/validation.go: `^[a-zA-Z][a-zA-Z0-9_-]*(\.[a-zA-Z][a-zA-Z0-9_-]*)*$`)
 * and the Python/Java runtimes. Applied ONLY to the derived capability names
 * `agent.addService` synthesizes — the SDK deliberately does NOT add a general
 * capability-validation layer elsewhere (the registry remains the single
 * authority for hand-written capability names).
 */
export const CAPABILITY_NAME_PATTERN =
  /^[a-zA-Z][a-zA-Z0-9_-]*(\.[a-zA-Z][a-zA-Z0-9_-]*)*$/;

/**
 * Brand symbol marking a `mesh.serviceView(...)` result so the dependency
 * expander can detect a view slot structurally (config-over-reflection, the
 * same precedent as `meshJobDepIndex`). `Symbol.for` keeps the brand stable
 * across duplicate module instances.
 */
export const SERVICE_VIEW_BRAND: unique symbol = Symbol.for(
  "@mcpmesh/sdk/service-view",
);

/** A single view method — a capability string shorthand or a full selector. */
export type ServiceViewMethodSpec =
  | string
  | {
      /** Capability this method binds. */
      capability: string;
      /** Tags for filtering (supports OR alternatives via nested arrays). */
      tags?: TagSpec[];
      /** Version constraint (e.g. ">=2.0.0"). */
      version?: string;
      /** Issue #1249 opt-in strictness for this edge (default soft-fail). */
      required?: boolean;
      /**
       * Issue #547: optional Zod schema describing the expected provider
       * response for this method edge (parity with Java `@Selector` schema
       * matching). Passed through `normalizeDependency` exactly like an ordinary
       * object dependency, so the registry filters providers by canonical hash.
       */
      expectedSchema?: z.ZodType<unknown>;
      /** Issue #547: schema match mode (defaults to "subset" when expectedSchema set). */
      matchMode?: "subset" | "strict";
    };

/**
 * A consumer service-view specification. `methods` maps facade method names to
 * their capability binding; the injected facade exposes exactly these keys.
 */
export interface ServiceViewSpec {
  /** Facade method name → capability binding. At least one entry required. */
  methods: Record<string, ServiceViewMethodSpec>;
  /**
   * Optional availability floor. When fewer than `minAvailable` of the view's
   * methods currently resolve, EVERY facade call throws
   * {@link MeshServiceUnavailableError} — a consumer-local circuit breaker with
   * no wire effect. Default 0 = no floor (each method soft/hard-fails per its
   * own `required` flag).
   */
  minAvailable?: number;
  /** Optional label surfaced in floor-breach errors and logs. */
  name?: string;
}

/**
 * A single facade method. Signature mirrors {@link import("./types.js").McpMeshTool}'s
 * callable form so a view method is a drop-in for a directly-injected proxy.
 */
export type MeshServiceFacadeMethod = (
  args?: Record<string, unknown>,
  options?: { headers?: Record<string, string> },
) => Promise<unknown>;

/**
 * The injected facade type inferred from a {@link ServiceView} (or a bare
 * {@link ServiceViewSpec}). Each spec method key becomes a callable facade
 * method.
 *
 * **How to type the view slot in `execute`:** leave the positional parameters
 * un-annotated (they infer as the injected `McpMeshTool | MeshJob | null`
 * union) and narrow the view slot with a cast at point of use. A direct
 * parameter annotation (`media: MeshServiceFacade<typeof Media>`) does NOT
 * compile under `strictFunctionTypes`: `execute`'s dependency parameters are
 * checked contravariantly, so any type narrower than the full injected union —
 * including a plain `McpMeshTool | null` — is rejected. This is why the cast
 * idiom is the canonical form (it also matches how ordinary `McpMeshTool` deps
 * are consumed):
 *
 * ```ts
 * import { mesh, type MeshServiceFacade } from "@mcpmesh/sdk";
 *
 * const Media = mesh.serviceView({ methods: { caption: "media.caption" } });
 *
 * agent.addTool({
 *   name: "process",
 *   parameters: z.object({ text: z.string() }),
 *   dependencies: ["audit_log", Media],
 *   execute: async (args, auditLog, media) => {
 *     const svc = media as MeshServiceFacade<typeof Media>;
 *     return await svc.caption({ text: args.text });
 *   },
 * });
 * ```
 */
export type MeshServiceFacade<V> = V extends ServiceView<infer S>
  ? { [K in keyof S["methods"]]: MeshServiceFacadeMethod }
  : V extends ServiceViewSpec
    ? { [K in keyof V["methods"]]: MeshServiceFacadeMethod }
    : never;

/**
 * A branded service-view value produced by {@link serviceView}. Placed in a
 * tool's `dependencies` array where it occupies one positional slot.
 */
export interface ServiceView<S extends ServiceViewSpec = ServiceViewSpec> {
  readonly [SERVICE_VIEW_BRAND]: true;
  readonly spec: S;
}

/** Structural brand check — true for a `mesh.serviceView(...)` result. */
export function isServiceView(value: unknown): value is ServiceView {
  return (
    typeof value === "object" &&
    value !== null &&
    (value as Record<PropertyKey, unknown>)[SERVICE_VIEW_BRAND] === true
  );
}

/**
 * Thrown by every facade call when a view is below its declared
 * {@link ServiceViewSpec.minAvailable} floor. Carries the view label plus the
 * current/total/floor counts so the failure is actionable. Mirrors Java's
 * `MeshServiceUnavailableException`.
 */
export class MeshServiceUnavailableError extends Error {
  readonly name = "MeshServiceUnavailableError";

  constructor(
    /** View label (spec.name or a derived owner:slot label). */
    public readonly service: string,
    /** View methods currently resolving to a provider. */
    public readonly available: number,
    /** Total dependency-bound view methods. */
    public readonly total: number,
    /** The declared availability floor. */
    public readonly floor: number,
  ) {
    super(
      `Mesh service view unavailable (${service}): ${available}/${total} ` +
        `method(s) resolved, below the declared minAvailable=${floor} floor`,
    );
  }
}

/**
 * Construct a consumer service view. Validates the spec at construction time
 * (empty methods map; blank capability; out-of-range `minAvailable`) so misuse
 * fails loud before the agent talks to the registry.
 */
export function serviceView<S extends ServiceViewSpec>(spec: S): ServiceView<S> {
  if (
    spec == null ||
    typeof spec !== "object" ||
    typeof spec.methods !== "object" ||
    spec.methods === null
  ) {
    throw new Error(
      "mesh.serviceView: `methods` must be an object mapping method names to " +
        "capabilities.",
    );
  }
  const keys = Object.keys(spec.methods);
  if (keys.length === 0) {
    throw new Error(
      "mesh.serviceView: `methods` must declare at least one method (got an " +
        "empty methods map).",
    );
  }
  for (const key of keys) {
    const m = spec.methods[key];
    const capability = typeof m === "string" ? m : m?.capability;
    if (typeof capability !== "string" || capability.trim() === "") {
      throw new Error(
        `mesh.serviceView: method '${key}' has a blank capability.`,
      );
    }
  }
  const min = spec.minAvailable;
  if (min !== undefined) {
    if (!Number.isInteger(min) || min < 0) {
      throw new Error(
        `mesh.serviceView: minAvailable must be an integer >= 0 (got ${min}).`,
      );
    }
    if (min > keys.length) {
      throw new Error(
        `mesh.serviceView: minAvailable=${min} exceeds the number of methods ` +
          `(${keys.length}) — the floor can never be satisfied.`,
      );
    }
  }
  return {
    [SERVICE_VIEW_BRAND]: true,
    spec,
  } as ServiceView<S>;
}

/** One view method's flat-edge placement within the expanded dependency list. */
export interface ViewMethodEdge {
  /** Facade method name (spec key). */
  method: string;
  /** Index into the flat edge array (settle-key / resolvedDeps / wire index). */
  edgeIndex: number;
}

/**
 * One positional dependency slot after expansion. A `dep` slot maps to exactly
 * one edge; a `view` slot collapses N edges into a single facade argument. The
 * disjoint edge ranges are tracked here (mirrors Java's index-range mapping).
 */
export type DepSlot =
  | { kind: "dep"; edgeIndex: number }
  | {
      kind: "view";
      name: string;
      minAvailable: number;
      methods: ViewMethodEdge[];
    };

/** Result of expanding a mixed `(DependencySpec | ServiceView)[]` list. */
export interface ExpandedDeps {
  /**
   * Flat dependency edges in wire/settle/resolve order. This is what ships to
   * the registry, what settle keys index (`owner:dep_<edgeIndex>`), what
   * `dependency_available` events address, and what `resolvedDeps` keys — one
   * entry per edge, view methods expanded IN-PLACE at the view's array position
   * in NAME-SORTED order.
   */
  edges: NormalizedDependency[];
  /**
   * Positional execute slots (one per authored `dependencies` entry). A view
   * entry is ONE slot spanning a contiguous edge range; a non-view entry is one
   * slot mapping to one edge. For a view-free list `slots[i].edgeIndex === i`.
   */
  slots: DepSlot[];
}

function normalizeViewMethod(m: ServiceViewMethodSpec): NormalizedDependency {
  if (typeof m === "string") {
    return normalizeDependency(m);
  }
  return normalizeDependency({
    capability: m.capability,
    tags: m.tags,
    version: m.version,
    required: m.required,
    expectedSchema: m.expectedSchema,
    matchMode: m.matchMode,
  });
}

/**
 * Expand a tool's authored dependency list (a mix of {@link DependencySpec} and
 * {@link ServiceView}) into the flat edge array + the positional slot layout.
 *
 * Layout contract (identical to the Java runtime — see uc37):
 *   - non-view entries keep their exact slot↔edge pairing;
 *   - a view entry contributes ONE slot at its array position but N edges,
 *     expanded IN-PLACE (name-sorted) so the flat edge indices stay contiguous
 *     and every downstream index consumer (settle keys, wire payload,
 *     resolution events, required guard) sees ordinary edges.
 *
 * For a view-free list this returns `edges` byte-identical to
 * `deps.map(normalizeDependency)` and `slots[i] = { kind: "dep", edgeIndex: i }`
 * — zero behavior change.
 */
export function expandDependencies(
  deps: ReadonlyArray<DependencySpec | ServiceView>,
  ownerLabel: string,
): ExpandedDeps {
  const edges: NormalizedDependency[] = [];
  const slots: DepSlot[] = [];

  deps.forEach((entry, slotIndex) => {
    if (isServiceView(entry)) {
      const spec = entry.spec;
      // Object key order is insertion-based; MUST sort by name for a
      // deterministic edge layout across runtimes.
      const methodNames = Object.keys(spec.methods).sort();
      const methods: ViewMethodEdge[] = [];
      for (const method of methodNames) {
        const edgeIndex = edges.length;
        edges.push(normalizeViewMethod(spec.methods[method]));
        methods.push({ method, edgeIndex });
      }
      slots.push({
        kind: "view",
        name: spec.name ?? `${ownerLabel}:view${slotIndex}`,
        minAvailable: spec.minAvailable ?? 0,
        methods,
      });
      return;
    }

    // Guard: an object without a `capability` in a dependencies array is almost
    // certainly a producer-method object placed where a view/dep was expected
    // (or a malformed spec). Fail loud rather than shipping a `capability:
    // undefined` edge.
    if (
      typeof entry === "object" &&
      entry !== null &&
      typeof (entry as { capability?: unknown }).capability !== "string"
    ) {
      throw new Error(
        `${ownerLabel}: dependency #${slotIndex} is an object without a ` +
          `'capability' — expected a DependencySpec (string or { capability }) ` +
          `or a mesh.serviceView(...). If this is a producer method, register ` +
          `it with agent.addService(...).`,
      );
    }

    const edgeIndex = edges.length;
    edges.push(normalizeDependency(entry as DependencySpec));
    slots.push({ kind: "dep", edgeIndex });
  });

  return { edges, slots };
}

/**
 * A producer method for `agent.addService`. Either a bare execute function
 * (shorthand) or an object carrying `execute` plus any `addTool` passthrough
 * (tags/version/description/parameters/dependencies/...). `name` and
 * `capability` are DERIVED (`prefix.<method>`) and must not be supplied.
 */
export type ServiceProducerMethod =
  | ((...args: never[]) => Promise<unknown> | unknown)
  | ServiceProducerMethodObject;

/** Object form of a {@link ServiceProducerMethod}. */
export type ServiceProducerMethodObject = Omit<
  Partial<MeshToolDef>,
  "name" | "capability" | "execute" | "parameters"
> & {
  /** Method implementation (positional deps injected after args, as usual). */
  execute: MeshToolDef["execute"];
  /** Optional Zod input schema. Defaults to a permissive passthrough object. */
  parameters?: z.ZodType;
};

/** Permissive default schema for producer methods that declare no `parameters`. */
export function defaultProducerParams(): z.ZodType {
  return z.object({}).passthrough();
}
