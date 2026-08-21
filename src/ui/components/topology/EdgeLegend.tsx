import { EDGE_COLORS, EDGE_HEAT_COLORS, EDGE_HEAT_LEGEND, EDGE_LEGEND } from "@/lib/edge-palette";

/**
 * The topology's edge key, rendered from lib/edge-palette.ts — the same module
 * lib/topology.ts strokes the edges from, so the key and the graph cannot
 * disagree about a colour again (issue #1521).
 *
 * Its own component rather than markup inside TopologyGraph so that
 * `__tests__/topology-edges.test.tsx` can render it: the swatches are the half
 * of the palette contract that data-level assertions cannot see, and reverting
 * one to a literal colour is exactly the regression this module exists to
 * prevent.
 *
 * Each colour arrives as an element style. That is forced, not stylistic: an
 * arbitrary-value class is a literal string the stylesheet generator has to
 * find by scanning source text, so a value read from a module could never
 * produce one.
 *
 * The second group is the traffic-heat scale, which reaches the screen only on
 * an edge that is erroring (issue #1530) and therefore needs saying: it is the
 * one case where a stroke means something other than what the rows above claim.
 * Before this, an edge could be drawn in a colour the key did not contain.
 */
export function EdgeLegend() {
  return (
    <div className="absolute top-4 left-4 z-10 rounded-lg border border-border bg-card/90 backdrop-blur-sm px-3 py-2.5 shadow-lg">
      <p className="text-[10px] font-medium text-muted-foreground mb-1.5 uppercase tracking-wider">Edges</p>
      <div className="space-y-1">
        {EDGE_LEGEND.map((entry) => (
          <div key={entry.key} className="flex items-center gap-2">
            <div
              data-testid={`edge-legend-swatch-${entry.key}`}
              className={
                entry.dashed
                  ? "w-5 h-0.5 border-t border-dashed"
                  : "w-5 h-0.5 rounded"
              }
              style={
                entry.dashed
                  ? { borderColor: EDGE_COLORS[entry.key] }
                  : { backgroundColor: EDGE_COLORS[entry.key] }
              }
            />
            <span className="text-[10px] text-muted-foreground">{entry.label}</span>
          </div>
        ))}
      </div>
      <div className="mt-2 pt-2 border-t border-border">
        <p className="text-[10px] font-medium text-muted-foreground mb-1.5 uppercase tracking-wider">Errors</p>
        <div className="space-y-1">
          {EDGE_HEAT_LEGEND.map((entry) => (
            <div key={entry.key} className="flex items-center gap-2">
              <div
                // Its own test-id space. The two loops run over unrelated sets
                // of keys, and nothing stops the same word appearing in both —
                // an `unavailable` heat band is an entirely plausible addition
                // — at which point a shared prefix would give two elements the
                // same id and break whichever tests happened to look one up.
                data-testid={`edge-legend-heat-swatch-${entry.key}`}
                className="w-5 h-0.5 rounded"
                style={{ backgroundColor: EDGE_HEAT_COLORS[entry.key] }}
              />
              <span className="text-[10px] text-muted-foreground">{entry.label}</span>
            </div>
          ))}
        </div>
        <p className="mt-2 text-[10px] text-muted-foreground">Overrides the edge colour above.</p>
      </div>
    </div>
  );
}
