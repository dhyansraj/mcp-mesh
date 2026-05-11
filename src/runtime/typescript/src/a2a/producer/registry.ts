/**
 * Registry for `mesh.a2a.mount(...)` producer surfaces (issue #933).
 *
 * Mirrors the role of `RouteRegistry` on the `mesh.route()` side: built at
 * mount time, queried during request dispatch (for path-to-surface lookup),
 * card render, auth gating, and heartbeat envelope construction.
 *
 * Single process-wide singleton (matches `RouteRegistry`). Each mount call
 * registers a unique path; duplicate paths throw at mount time so wiring
 * mistakes surface synchronously instead of as silent overrides.
 *
 * Cross-cuts with `RouteRegistry`: A2A surfaces declare mesh dependencies
 * just like routes, and the producer reuses `RouteRegistry` for dependency
 * resolution so the same DDDI plumbing powers both surfaces. Each mount
 * registers its dependencies as a synthetic route in `RouteRegistry`; the
 * surface keeps a back-reference to that route's `routeId` so dispatch can
 * resolve injected `McpMeshTool` proxies.
 */
import type { DependencySpec, NormalizedDependency } from "../../types.js";

/**
 * Captured metadata for a single `mesh.a2a.mount(...)` call.
 *
 * Constructed once at mount time and immutable thereafter — the dispatcher
 * reads these fields on every request.
 */
export interface A2ASurfaceMetadata {
  /** URL path prefix for this surface; must start with `/` and not end with `/`. */
  readonly path: string;
  /** A2A skill identifier, kebab-case canonical (e.g., `"get-date"`). */
  readonly skillId: string;
  /** Human-readable skill name (defaults to `skillId` when unset). */
  readonly skillName: string;
  /** Free-form skill description (`""` when unset). */
  readonly description: string;
  /** Skill tags surfaced on the agent card. */
  readonly tags: readonly string[];
  /** Normalized dependencies (matches `RouteMetadata.dependencies`). */
  readonly dependencies: readonly NormalizedDependency[];
  /**
   * Auth scheme — `"bearer"` enables the presence-check gate (spec §6.2),
   * `""` leaves the path open. Phase 1 supports only `"bearer"`.
   */
  readonly auth: "" | "bearer";
  /**
   * The `routeId` returned by `RouteRegistry.registerRoute` for this surface's
   * dependencies — used by the dispatcher to look up resolved `McpMeshTool`
   * proxies by position via `RouteRegistry.getDependenciesForRoute(routeId)`.
   */
  readonly routeId: string;
}

/**
 * Configuration object passed to `mesh.a2a.mount(...)`.
 */
export interface A2AMountConfig {
  /** URL path prefix for this surface. MUST start with `/`. */
  path: string;
  /** A2A skill identifier (kebab-case). MUST be non-empty. */
  skillId: string;
  /** Human-readable skill name. Defaults to `skillId` when unset. */
  skillName?: string;
  /** Free-form skill description. */
  description?: string;
  /** Skill tags surfaced on the agent card. */
  tags?: string[];
  /** Mesh dependencies to inject into the handler (DDDI). */
  dependencies?: DependencySpec[];
  /**
   * Auth scheme — `"bearer"` enables the presence-check gate (spec §6.2).
   * Default: no auth gate.
   */
  auth?: "bearer";
}

/**
 * Singleton registry for `mesh.a2a.mount(...)` producer surfaces.
 *
 * Insertion order is preserved (mirrors Java's `MeshA2ARegistry`) so the
 * heartbeat envelope's `surfaces[]` array order stays stable across
 * restarts.
 */
export class A2AProducerRegistry {
  private static instance: A2AProducerRegistry | null = null;
  private readonly surfacesByPath = new Map<string, A2ASurfaceMetadata>();

  private constructor() {}

  static getInstance(): A2AProducerRegistry {
    if (!A2AProducerRegistry.instance) {
      A2AProducerRegistry.instance = new A2AProducerRegistry();
    }
    return A2AProducerRegistry.instance;
  }

  /** Reset the registry (mainly for testing). */
  static reset(): void {
    A2AProducerRegistry.instance = null;
  }

  /**
   * Register an A2A surface. Throws on duplicate path so wiring mistakes
   * fail loudly instead of silently overriding (matches Java's
   * `MeshA2ARegistry.register`).
   */
  register(metadata: A2ASurfaceMetadata): void {
    if (this.surfacesByPath.has(metadata.path)) {
      const existing = this.surfacesByPath.get(metadata.path)!;
      throw new Error(
        `mesh.a2a.mount: path collision: '${metadata.path}' is already registered ` +
          `(existing skillId=${existing.skillId}). Each producer path must be unique.`
      );
    }
    this.surfacesByPath.set(metadata.path, metadata);
  }

  /** Look up a surface by path. Returns `undefined` when no surface owns it. */
  getByPath(path: string): A2ASurfaceMetadata | undefined {
    return this.surfacesByPath.get(path);
  }

  /** @returns insertion-ordered list of every registered surface. */
  getAll(): A2ASurfaceMetadata[] {
    return Array.from(this.surfacesByPath.values());
  }

  /** @returns `true` when at least one surface is registered. */
  hasSurfaces(): boolean {
    return this.surfacesByPath.size > 0;
  }

  /** @returns number of registered surfaces. */
  size(): number {
    return this.surfacesByPath.size;
  }

  /**
   * Build the heartbeat `a2a_surfaces[]` array (spec §2.1).
   *
   * Required fields (`path`, `skill_id`) are always emitted. Optional fields
   * (`name`, `description`, `tags`) are emitted ONLY when set — never as
   * empty strings or empty arrays — so the registry's OpenAPI defaults
   * (`input_modes: ["application/json"]`, etc.) aren't overridden with empty
   * values. Spec §2.1 is explicit about this.
   *
   * @returns list of plain-object surface entries ready for JSON serialization
   */
  buildHeartbeatSurfaces(): Array<Record<string, unknown>> {
    const out: Array<Record<string, unknown>> = [];
    for (const md of this.surfacesByPath.values()) {
      const entry: Record<string, unknown> = {
        path: md.path,
        skill_id: md.skillId,
      };
      // skill_name is always present (defaulted to skillId at mount time) —
      // emit it as `name` so the registry can use it for human-readable
      // discovery. Mirrors Java's MeshA2ARegistry.buildHeartbeatSurfaces.
      entry.name = md.skillName;
      if (md.description && md.description.length > 0) {
        entry.description = md.description;
      }
      if (md.tags.length > 0) {
        entry.tags = [...md.tags];
      }
      // input_modes / output_modes default at card-render time, not at
      // heartbeat-emit time (spec §2.1). The mount config doesn't expose
      // them yet — omit so the registry's defaults apply.
      out.push(entry);
    }
    return out;
  }
}
