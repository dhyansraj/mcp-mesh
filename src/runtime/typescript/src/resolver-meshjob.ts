/**
 * DDDI resolver for `MeshJob` parameters (Phase 1 — MeshJob substrate).
 *
 * Implements `MESHJOB_DDDI_CONTRACT.md` for the TypeScript SDK. Mirrors
 * Python's `analyze_mesh_job_signature` from
 * `_mcp_mesh.engine.signature_analyzer`.
 *
 * # TS-specific shape
 *
 * Python uses `inspect.signature` + `typing.get_type_hints` to classify
 * parameters by annotation type. TypeScript erases types at runtime,
 * and the existing SDK does not depend on `reflect-metadata` decorators
 * — `agent.addTool({ ... })` is fully declarative. So the TS resolver
 * input is the explicit declaration:
 *
 *   - `dependencies`: array of MeshTool deps in declaration order
 *     (matches Python's `dep_index` ordering today).
 *   - `meshToolPositions`: signature positions for each MeshTool dep
 *     (where in the user `execute(args, ...)` parameter list each
 *     dep proxy lands).
 *   - `meshJobParamIndex`: signature position of the single MeshJob
 *     parameter, or `undefined` if the tool has none.
 *
 * The resolver verifies the contract invariants:
 *
 *   - At most one MeshJob parameter per tool (reject otherwise).
 *   - MeshTool positions don't overlap with the MeshJob position.
 *
 * Then produces the canonical `ResolvedSignature` the dispatch wrapper
 * uses to inject deps + the MeshJob into `execute(args, ...)`.
 *
 * # Test seam
 *
 * `__tests__/resolver-meshjob.spec.ts` covers the same scenarios as
 * Python's `tests/test_resolver_meshjob.py` and Java's
 * (forthcoming) `MeshJobResolverTest.java`. Whenever any SDK's
 * resolver behaviour changes, update `MESHJOB_DDDI_CONTRACT.md` first
 * then mirror across all three test seams.
 */

/**
 * One mesh-tool dependency slot recognised by the resolver. Mirrors
 * Python's `mesh_tool_positions[i]` entry: each entry knows where in
 * the user function's parameter list it should be injected.
 */
export interface ResolvedMeshToolDep {
  /** Index into the original `dependencies` array. */
  depIndex: number;
  /**
   * Signature position (0-indexed) where the resolved proxy should be
   * injected as a positional arg to the user `execute` function. For
   * the TS SDK these positions follow `args` (the first positional
   * parameter is always the parsed args object, then deps).
   */
  signaturePosition: number;
}

/**
 * Resolver output. Mirrors Python's `MeshJobResolution` plus the
 * `meshToolDeps` projection for TS callers (Python returns just
 * positions; the TS dispatch path threads `depIndex` through).
 */
export interface ResolvedSignature {
  /**
   * Mesh-tool dependency slots in declaration order. The dispatch
   * wrapper iterates this list to inject the resolved proxies.
   *
   * Empty when the tool declares no `dependencies`.
   */
  meshToolDeps: ResolvedMeshToolDep[];

  /**
   * Signature position of the single MeshJob parameter, or
   * `undefined` if the tool does not declare one.
   *
   * Phase 1 invariant: at most one MeshJob param per tool. The
   * resolver throws (see {@link resolveMeshJobSignature}) if this
   * invariant is violated.
   */
  meshJobParamIndex?: number;
}

/**
 * Input shape for the resolver. The SDK builds this from the user's
 * `addTool({ dependencies, meshToolPositions, meshJobParamIndex })`
 * config; explicit fields keep the resolver pure and easy to test
 * without spinning up a FastMCP server.
 */
export interface ResolverInput {
  /**
   * Capability names of declared dependencies in declaration order.
   * The length defines the number of MeshTool slots.
   */
  dependencies: string[];

  /**
   * Optional explicit signature positions for each MeshTool dep. When
   * omitted, the resolver assigns positions starting at 1 (after
   * `args`) and skipping `meshJobParamIndex` if set, matching the
   * contract's "positional indexing rule".
   *
   * Length MUST match `dependencies.length` when provided.
   */
  meshToolPositions?: number[];

  /**
   * Signature position of the MeshJob parameter (if any). The contract
   * classifies it as orthogonal to MeshTool positional indexing — it
   * is recorded separately so adding/removing a MeshJob param does
   * NOT shift MeshTool positions.
   */
  meshJobParamIndex?: number;

  /**
   * Optional name(s) of MeshJob parameters detected at the call site.
   * Used by the resolver to surface a clearer error message when the
   * user accidentally declares more than one. Pass an array like
   * `["job", "secondJob"]` to enable the "at most one" check —
   * undefined skips the check (single position only).
   */
  meshJobParamNames?: string[];
}

/**
 * Sentinel error class for resolver violations. Subclasses `Error` so
 * standard `try/catch` works; the SDK calls `addTool` re-throws this
 * verbatim so the user sees the misuse at registration time.
 *
 * The contract specifies the exact wording for the multi-MeshJob case
 * — keeping it stable here lets tests assert against it.
 */
export class ResolverError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ResolverError";
  }
}

/**
 * Classify a tool's signature per `MESHJOB_DDDI_CONTRACT.md`.
 *
 * For each dependency in declaration order, assigns a signature
 * position. If `meshJobParamIndex` is set, that position is RESERVED
 * for the MeshJob and skipped when assigning MeshTool positions.
 *
 * Phase 1 invariant: at most one MeshJob parameter — multiple raises
 * `ResolverError` with the contract-specified wording so users see
 * the misuse at registration time.
 *
 * The TS SDK's existing tool-positional layout is `(args, ...deps)` —
 * args is signature position 0, deps start at 1. When
 * `meshJobParamIndex` is set inside that range, it consumes one slot
 * and the resolver shifts subsequent MeshTool positions accordingly.
 *
 * @example MeshTool only
 * ```ts
 * resolveMeshJobSignature({ dependencies: ["a", "b"] })
 * // → { meshToolDeps: [{depIndex:0, signaturePosition:1}, {depIndex:1, signaturePosition:2}] }
 * ```
 *
 * @example MeshJob in middle (sig pos 2)
 * ```ts
 * resolveMeshJobSignature({
 *   dependencies: ["weather", "flights"],
 *   meshJobParamIndex: 2,
 * })
 * // → { meshToolDeps: [{depIndex:0, signaturePosition:1}, {depIndex:1, signaturePosition:3}],
 * //     meshJobParamIndex: 2 }
 * ```
 *
 * @example Multiple MeshJob params → throws
 * ```ts
 * resolveMeshJobSignature({
 *   dependencies: [],
 *   meshJobParamIndex: 1,
 *   meshJobParamNames: ["firstJob", "secondJob"],
 * })
 * // → throws ResolverError("a tool function may declare at most one MeshJob parameter; ...")
 * ```
 */
export function resolveMeshJobSignature(
  input: ResolverInput
): ResolvedSignature {
  // Phase 1 invariant: at most one MeshJob param. This is checked when
  // the caller supplies the optional `meshJobParamNames` (set by the
  // hypothetical type-reflective shim that Phase B will introduce in
  // the dispatch wrapper). When the input plumbing only carries a
  // single index, by construction we already have at most one — so
  // skip the check rather than reject ambiguous input shapes.
  if (input.meshJobParamNames && input.meshJobParamNames.length > 1) {
    throw new ResolverError(
      `a tool function may declare at most one MeshJob parameter; ` +
        `function declares ${input.meshJobParamNames.length}: ` +
        `${input.meshJobParamNames.map((n) => `'${n}'`).join(", ")}`
    );
  }

  const meshJobParamIndex = input.meshJobParamIndex;

  // Sanity-check explicit positions if provided.
  if (input.meshToolPositions !== undefined) {
    if (input.meshToolPositions.length !== input.dependencies.length) {
      throw new ResolverError(
        `meshToolPositions length (${input.meshToolPositions.length}) ` +
          `does not match dependencies length (${input.dependencies.length})`
      );
    }
    if (
      meshJobParamIndex !== undefined &&
      input.meshToolPositions.includes(meshJobParamIndex)
    ) {
      throw new ResolverError(
        `meshJobParamIndex ${meshJobParamIndex} collides with a ` +
          `MeshTool position; MeshJob is orthogonal — it must occupy ` +
          `its own signature slot per MESHJOB_DDDI_CONTRACT.md`
      );
    }
  }

  // Compute mesh-tool positions. Two paths:
  //
  //   1. Caller supplied them explicitly — use as-is (after the
  //      collision check above).
  //   2. Default: counter starts at 1 (after `args`), skip the
  //      MeshJob position if any.
  //
  // The contract's "positional indexing rule" says: maintain a
  // mesh_tool_position_counter, increment for each MeshTool, and do
  // not touch it for MeshJob. We translate that into "skip the
  // MeshJob signature position" because the TS SDK uses the same
  // signature for `execute(args, ...deps)` whether or not a MeshJob
  // is present.
  let positions: number[];
  if (input.meshToolPositions !== undefined) {
    positions = input.meshToolPositions;
  } else {
    positions = [];
    let counter = 1; // signature pos 0 is always `args`
    for (let i = 0; i < input.dependencies.length; i++) {
      if (counter === meshJobParamIndex) {
        counter += 1; // skip MeshJob slot
      }
      positions.push(counter);
      counter += 1;
    }
  }

  const meshToolDeps: ResolvedMeshToolDep[] = positions.map(
    (signaturePosition, depIndex) => ({
      depIndex,
      signaturePosition,
    })
  );

  return {
    meshToolDeps,
    meshJobParamIndex,
  };
}
