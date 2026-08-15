// THE topology edge colours. One definition, two consumers: lib/topology.ts
// strokes the edges from it, and the legend in components/topology/EdgeLegend.tsx
// renders its swatches from it. They used to carry separate copies of the same
// six hexes, which is how the legend came to describe a colour the builder no
// longer emitted (issue #1521).
//
// The traffic-heat scale at the foot of this file is a second, deliberately
// separate axis. Read its note before merging anything into `EDGE_COLORS`.
//
// The legend swatches read these values as INLINE STYLES. That is not a
// stylistic choice: the swatches were arbitrary-value classes, which are literal
// strings the stylesheet generator has to find by scanning source text, so a
// value read from this file could never produce one.

/**
 * An edge's colour describes WHAT IS BEING CALLED, never who is calling
 * (issue #1521). `dependency` vs `job` is decided by the provider's matching
 * capability; the caller's agent_type is not consulted anywhere.
 */
export const EDGE_COLORS = {
  /** Resolved dependency on an ordinary capability. */
  dependency: "#22c55e",
  /** Resolved dependency whose provider declared the capability `task=true`. */
  job: "#ec4899",
  /** Resolved `@mesh.llm(filter=...)` tool. */
  llmTool: "#22d3ee",
  /** Resolved `@mesh.llm(provider=...)` model provider. */
  llmProvider: "#a855f7",
  /**
   * A dependency whose provider is unavailable — and, on LLM tool/provider
   * edges, the unresolved case too: those two kinds have never drawn the grey
   * below. Hence the legend wording.
   */
  unavailable: "#ef4444",
  /** A declared dependency nothing satisfies yet. `dep` edges only. */
  unresolved: "#6b7280",
} as const;

export type EdgeColorKey = keyof typeof EDGE_COLORS;

export interface EdgeLegendEntry {
  key: EdgeColorKey;
  label: string;
  /** Drawn as a dashed rule rather than a solid one, as the edge itself is. */
  dashed?: boolean;
}

/**
 * The legend, in render order — every colour the builder can emit, and nothing
 * else. `__tests__/topology-edges.test.tsx` asserts that both ways round, so a
 * new stroke without a row here (or a row for a stroke that is no longer
 * reachable, which is what #1521 was) fails the suite.
 */
export const EDGE_LEGEND: EdgeLegendEntry[] = [
  { key: "dependency", label: "Dependency" },
  { key: "job", label: "MeshJob" },
  { key: "llmTool", label: "LLM tool" },
  { key: "llmProvider", label: "LLM provider" },
  { key: "unavailable", label: "Unavailable — or LLM unresolved" },
  { key: "unresolved", label: "Unresolved dependency", dashed: true },
];

/**
 * The traffic-heat scale. A SEPARATE AXIS from `EDGE_COLORS`, kept apart on
 * purpose — do not fold the two together on the grounds that they share two
 * values.
 *
 * `EDGE_COLORS` answers WHAT AN EDGE IS, which is a fact about the topology and
 * changes when the mesh is rewired. These answer HOW IT IS GOING, which is a
 * fact about the last window of calls and changes while nothing is rewired at
 * all. That `clean` and `failing` happen to hold the same two hexes as
 * `dependency` and `unavailable` is a coincidence of taste, not a shared
 * meaning: if the dependency stroke were ever restyled, a healthy edge under
 * traffic should not move with it, and a single constant would drag it along.
 *
 * These have no legend row — `elevated` in particular is a colour the legend
 * cannot explain — because they are painted OVER the palette above by
 * `mergeEdgeStatsIntoEdges` in components/topology/TopologyGraph.tsx. That the
 * heat scale overrides edge kind at all is a known and separate question; the
 * legend contract asserted in `__tests__/topology-edges.test.tsx` is therefore
 * scoped to the builder, and says so.
 */
export const EDGE_HEAT_COLORS = {
  /** No errors observed on this edge. */
  clean: "#22c55e",
  /** Errors, but under the threshold that counts as failing. */
  elevated: "#eab308",
  /** Failing often enough to be the first thing you should look at. */
  failing: "#ef4444",
} as const;
