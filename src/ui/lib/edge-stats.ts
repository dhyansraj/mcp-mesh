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
 * The field is required by the payload contract and by the type, and the server
 * always emits it — but these rows come off the network, and a registry
 * predating #1531 emits a payload without it. The type says `string`, so an
 * absent one is `undefined` at runtime while every reader believes otherwise,
 * and `undefined.localeCompare` throws inside a sort — taking the whole Traffic
 * page down rather than degrading. An older registry's rows are pair-level, and
 * an empty function is exactly what this file already means by "a row that
 * names no function".
 */
function functionOf(edge: EdgeStat): string {
  return edge.target_function ?? "";
}

/** edgeStatKey for a whole row — its React key, and its history-map key. */
export function edgeRowKey(edge: EdgeStat): string {
  return edgeStatKey(edge.source, edge.target, functionOf(edge));
}

/**
 * Sort comparator for the traffic tables: by route, then by the function called
 * on the target, so the several rows one route now contributes stay together
 * and in a stable order across polls.
 */
export function compareEdgeStats(a: EdgeStat, b: EdgeStat): number {
  const byRoute = `${a.source}->${a.target}`.localeCompare(`${b.source}->${b.target}`);
  if (byRoute !== 0) return byRoute;
  return functionOf(a).localeCompare(functionOf(b));
}
