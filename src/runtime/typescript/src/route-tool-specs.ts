/**
 * Registry tool specs for `mesh.route()` consumer routes.
 *
 * Shared by BOTH route registration paths — the auto-start API runtime
 * (`api-runtime.ts`) and `MeshExpress` (`express.ts`) — so the same route
 * declaration reaches the registry identically either way (issue #1593: the
 * API-runtime copy had drifted and dropped the expected-schema fields).
 */
import type { JsDependencySpec, JsToolSpec } from "@mcpmesh/core";

import type { RouteMetadata } from "./route.js";
import {
  clusterStrictEnabled,
  normalizeSchemaWithPolicy,
} from "./schema-normalize.js";

export function buildRouteToolSpecs(routes: RouteMetadata[]): JsToolSpec[] {
  // Issue #547 Phase 4: cluster strict knob promotes WARN→BLOCK. Routes are
  // consumer-side so there's no per-tool override.
  const clusterStrict = clusterStrictEnabled();

  return routes
    .filter((route) => route.dependencies.length > 0)
    .map((route) => ({
      functionName: route.routeId,
      capability: "", // Routes don't provide capabilities, they consume them
      version: "1.0.0",
      tags: [],
      description: "",
      // Note: tags may contain nested arrays for OR alternatives (TagSpec[])
      // Serialize to JSON for Rust binding - preserves nested structure
      dependencies: route.dependencies.map(
        (dep): JsDependencySpec => {
          // Issue #547: per-dep expectedSchema → canonical + hash + matchMode.
          let expectedCanonical: string | undefined;
          let expectedHash: string | undefined;
          if (dep.expectedSchemaRaw) {
            const r = normalizeSchemaWithPolicy(
              dep.expectedSchemaRaw,
              `route ${route.routeId} dependency on '${dep.capability}'`,
              clusterStrict,
              true
            );
            expectedCanonical = r.canonicalJson ?? undefined;
            expectedHash = r.hash ?? undefined;
          }
          return {
            capability: dep.capability,
            tags: JSON.stringify(dep.tags ?? []),
            version: dep.version,
            expectedSchemaCanonical: expectedCanonical,
            expectedSchemaHash: expectedHash,
            matchMode: dep.matchMode,
            // Issue #1249: carry the required flag so the registry factors
            // this route edge into transitive availability. Only when true.
            required: dep.required ? true : undefined,
          };
        }
      ),
      inputSchema: undefined,
    }));
}
