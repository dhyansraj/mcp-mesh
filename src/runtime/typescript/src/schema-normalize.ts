/**
 * Issue #547: thin wrapper around the Rust normalizer exposed via @mcpmesh/core.
 *
 * The runtime uses this to canonicalize JSON Schemas (input/output for tools,
 * expected schemas for dependencies) so capability matching reduces to
 * byte-equal hash comparison. Mirrors the Python pipeline.
 */

import * as core from "@mcpmesh/core";

export interface NormalizedSchemaResult {
  /** Canonical normalized schema as a JSON string (suitable for shipping). */
  canonicalJson: string | null;
  /** SHA256 hash (sha256:<hex>) of the canonical schema. */
  hash: string | null;
  /** Normalizer verdict: "OK", "WARN", or "BLOCK". */
  verdict: string;
  /** Normalizer warnings (may be empty). */
  warnings: string[];
}

/**
 * Issue #547 Phase 4: cluster-wide schema strict mode.
 *
 * Reads `MCP_MESH_SCHEMA_STRICT` once per call. When true, WARN verdicts are
 * promoted to BLOCK so ops can harden a whole cluster without changing every
 * consumer.
 */
export function clusterStrictEnabled(): boolean {
  const v = process.env.MCP_MESH_SCHEMA_STRICT;
  if (v === undefined) return false;
  return ["1", "true", "yes"].includes(v.trim().toLowerCase());
}

/**
 * Issue #547 Phase 4: schema verdict policy.
 *
 * Composes the cluster-wide strict knob and the per-tool `outputSchemaStrict`
 * override. Returns true when the SDK should refuse agent startup.
 *
 * Truth table:
 *   verdict=BLOCK + toolStrict=true  -> refuse
 *   verdict=BLOCK + toolStrict=false -> log only (override wins)
 *   verdict=WARN  + clusterStrict=true + toolStrict=true  -> refuse
 *   verdict=WARN  + clusterStrict=true + toolStrict=false -> log only
 *   verdict=WARN  + clusterStrict=false                   -> log only
 *   verdict=OK -> never refuse
 */
export function shouldRefuseStartup(
  verdict: string,
  clusterStrict: boolean,
  toolStrict: boolean
): boolean {
  if (verdict === "BLOCK") return toolStrict;
  if (verdict === "WARN") return clusterStrict && toolStrict;
  return false;
}

/**
 * Normalize a raw JSON Schema via the Rust core and apply the verdict
 * policy (Issue #547 Phase 4).
 *
 * Resolves to a `null`-fielded result if `@mcpmesh/core` does not expose
 * `normalizeSchema` (legacy bundled binary). Returns the (possibly warning-tagged) result, or throws when startup must
 * be refused. Logs WARN/demoted-BLOCK loudly so they show up in normal
 * deployments.
 */
export function normalizeSchemaWithPolicy(
  raw: object,
  contextLabel: string,
  clusterStrict: boolean,
  toolStrict: boolean
): NormalizedSchemaResult {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const normalizeFn = (core as any).normalizeSchema as
    | ((rawJson: string, origin?: string) => string)
    | undefined;

  if (typeof normalizeFn !== "function") {
    console.warn(
      `[mesh] normalizeSchema not found in @mcpmesh/core for ${contextLabel} ` +
        `(rebuild napi binding to enable schema canonicalization)`
    );
    return { canonicalJson: null, hash: null, verdict: "OK", warnings: [] };
  }

  let parsed: { canonical?: unknown; hash?: string; verdict?: string; warnings?: string[] };
  try {
    parsed = JSON.parse(normalizeFn(JSON.stringify(raw), "typescript"));
  } catch (err) {
    console.warn(
      `[mesh] schema normalization failed for ${contextLabel}: ${
        err instanceof Error ? err.message : String(err)
      }`
    );
    return { canonicalJson: null, hash: null, verdict: "OK", warnings: [] };
  }

  const verdict = parsed.verdict ?? "OK";
  let warnings = parsed.warnings ?? [];

  if (shouldRefuseStartup(verdict, clusterStrict, toolStrict)) {
    const promoted =
      verdict === "WARN"
        ? " (MCP_MESH_SCHEMA_STRICT=true upgraded WARN→BLOCK)"
        : "";
    throw new Error(
      `Schema normalization ${verdict} for ${contextLabel}${promoted}: ${warnings.join("; ")}. Cannot start agent.`
    );
  }

  if (verdict === "BLOCK") {
    // Demoted by per-tool override — log loudly + tag warnings.
    console.warn(
      `[mesh] Schema BLOCK demoted to WARN for ${contextLabel} ` +
        `(outputSchemaStrict=false): ${warnings.join("; ")}`
    );
    warnings = warnings.map((w) => `[demoted from BLOCK] ${w}`);
  } else if (verdict === "WARN") {
    console.warn(`[mesh] Schema WARN for ${contextLabel}: ${warnings.join("; ")}`);
  }

  const canonicalJson =
    parsed.canonical !== undefined && parsed.canonical !== null
      ? JSON.stringify(parsed.canonical)
      : null;
  const hash = parsed.hash || null;
  return { canonicalJson, hash, verdict, warnings };
}
