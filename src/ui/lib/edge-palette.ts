// THE topology edge colours. One definition, two consumers: lib/topology.ts
// strokes the edges from it, and the legend in components/topology/EdgeLegend.tsx
// renders its swatches from it. They used to carry separate copies of the same
// six hexes, which is how the legend came to describe a colour the builder no
// longer emitted (issue #1521).
//
// The traffic-heat scale at the foot of this file is a second, deliberately
// separate axis. Read its note before merging anything into `EDGE_COLORS`. It
// now paints only over an edge with errors, so both palettes reach the screen
// at once and both are in the legend (issue #1530).
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
 * purpose — do not fold the two together, and do not reach for a value from one
 * while writing the other.
 *
 * `EDGE_COLORS` answers WHAT AN EDGE IS, which is a fact about the topology and
 * changes when the mesh is rewired. These answer HOW IT IS GOING, which is a
 * fact about the last window of calls and changes while nothing is rewired at
 * all.
 *
 * NO VALUE HERE SHARES A HEX WITH `EDGE_COLORS`, and that is a requirement now
 * rather than an accident. `failing` held the same red as `unavailable` until
 * both axes started appearing in the key together, at which point a reader
 * looking at a red edge had two rows and no way to choose between them — and a
 * caption saying which one wins settles precedence, not identity. So heat has a
 * ramp of its own, amber then a warmer step, in a hue no edge kind occupies,
 * and red is left meaning exactly one thing.
 *
 * That ramp also orders the two axes the way you want them read. An edge whose
 * provider is unavailable is in worse shape than one still succeeding nine
 * times in ten, so the unavailable stroke outranking the failing one is the
 * correct reading rather than a compromise the palette forced.
 *
 * ONLY ERRORS PAINT (issue #1530). `mergeEdgeStatsIntoEdges` in
 * components/topology/TopologyGraph.tsx used to repaint every edge that carried
 * any traffic at all, a zero error rate included — so wherever tracing is on,
 * the palette above was thrown away almost everywhere in order to report a
 * state almost every edge is in. One measured mesh ran 2,495 calls with 1 error
 * across 326 edges, every one of them sampled at 0.000. An edge with no errors
 * now keeps its kind stroke, and only an edge with errors takes a colour from
 * here, because at that point the error is the more urgent fact.
 *
 * So both values below are reachable on screen, and both have a legend row.
 * `__tests__/topology-edges.test.tsx` asserts that against the MERGED strokes
 * rather than against the builder alone, and in the direction that matters here
 * — is this row a colour anything paints? — against only the strokes the merge
 * CHANGED, so no row can be satisfied by an edge kind that happens to match.
 *
 * There is deliberately no third value for the healthy case. It had one, and it
 * lost its last consumer the moment a clean edge stopped being repainted;
 * keeping it would have left a green nothing draws and a legend row saying so.
 */
export const EDGE_HEAT_COLORS = {
  /** Errors, but under the threshold that counts as failing. */
  elevated: "#eab308",
  /**
   * Failing often enough to be the first thing you should look at — but still
   * a step below `unavailable`, which is why it is not that red.
   */
  failing: "#f97316",
} as const;

export type EdgeHeatKey = keyof typeof EDGE_HEAT_COLORS;

/**
 * The heat rows of the legend, in render order. The same two-way contract
 * `EDGE_LEGEND` carries, over this axis: every colour HEAT can put on screen is
 * named here, and every row here is a colour heat actually paints. The second
 * direction is checked against the strokes the merge CHANGED rather than every
 * stroke it emits — a row that named a colour only some edge kind draws would
 * otherwise pass while heat never painted it at all.
 *
 * The boundary in the labels is the one `getEdgeHeatColor` applies, and it is a
 * PERCENTAGE of an edge's calls — see the note on that function for why the
 * unit is the load-bearing part.
 */
export const EDGE_HEAT_LEGEND: { key: EdgeHeatKey; label: string }[] = [
  { key: "elevated", label: "Errors under 10%" },
  { key: "failing", label: "Errors 10% or more" },
];
