import { EdgeStat } from "./types";

/**
 * The identity of an edge-stat row: (source agent, target agent, function on
 * the target). Issue #1531 — the server keys traffic by all three, so every
 * consumer that indexes, de-duplicates or joins on a row has to use all three
 * too. Two of them is what made a pair's several tools share one number.
 *
 * Structured rather than concatenated with a separator. Every component is a
 * user-chosen name and none of them has a delimiter that cannot appear inside
 * it: the server's previous `source + " -> " + target` key had to be taken
 * apart again by scanning for the first " -> ", which an agent named with that
 * sequence in it split in the wrong place.
 */
export function edgeStatKey(
  source: string,
  target: string,
  targetFunction: string
): string {
  return JSON.stringify([source, target, targetFunction]);
}

/**
 * `target_function` as a string, whatever arrived.
 *
 * DEFENCE IN DEPTH, NOT A SUPPORTED SHAPE. The field is required by the type and
 * by the payload contract, and there is no version of the payload that omits it:
 * every producer is meshui's own binary — the live accumulator, its Tempo
 * fallback and the windowed replay — and that same binary embeds the SPA reading
 * them, so the two cannot be different versions. What this guards is a
 * MALFORMED payload, where the type says `string` but the value is `undefined`
 * at runtime, and `undefined.localeCompare` throws inside a sort — taking the
 * whole Traffic page down rather than degrading. An empty function is what this
 * file already means by "a row that names no function", so such a row lands
 * there instead.
 */
function functionOf(edge: EdgeStat): string {
  return edge.target_function ?? "";
}

/** edgeStatKey for a whole row — its React key, and its history-map key. */
export function edgeRowKey(edge: EdgeStat): string {
  return edgeStatKey(edge.source, edge.target, functionOf(edge));
}

/**
 * Sort comparator for the traffic tables: by source, then target, then by the
 * function called on the target, so the several rows one route now contributes
 * stay together and in a stable order across polls.
 *
 * Field by field, never on a joined string. `${source}->${target}` would order
 * by a separator that can appear inside an agent name, which orders such a name
 * against the wrong neighbour — the same fault that made the server's delimited
 * edge key a struct in #1531.
 */
export function compareEdgeStats(a: EdgeStat, b: EdgeStat): number {
  const bySource = a.source.localeCompare(b.source);
  if (bySource !== 0) return bySource;
  const byTarget = a.target.localeCompare(b.target);
  if (byTarget !== 0) return byTarget;
  return functionOf(a).localeCompare(functionOf(b));
}
