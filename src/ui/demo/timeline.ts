// THE ANIMATION MATHS — shared by both renderers, owned by neither.
//
// Two things now draw this section: the React component (stage.tsx, the dev
// page) and the vanilla driver (driver.ts, what ships). If each carried its own
// copy of the camera and the timeline, "the prerendered build matches the React
// build" would be a statement about one afternoon rather than a property of the
// code — the two would drift on the first weight change and nothing would say
// so. Everything here is a pure function of scroll position and beat data, so
// both can import it and there is exactly one definition of every number.
//
// Deliberately free of React AND of the graph builder: importing
// lib/topology.ts here would pull dagre back into the shipped bundle, which is
// most of what the prerender exists to remove. Node and edge ids arrive as
// arguments; the emitter bakes the orders into generated.json.
import {
  BEATS, CUM, TOTAL_VH, REVEAL_VH, BUILT_CHAPTERS, REVEAL,
  WEATHER, WEATHER_GROUP,
  FLIGHT, HOTEL, POI, PREFS, PLANNER, CLAUDE, OPENAI, GATEWAY,
  BUDGET, ADVENTURE, LOGISTICS,
} from "./script";

const N = BEATS.length;

// ---------------------------------------------------------------------------
// Math
// ---------------------------------------------------------------------------
export const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));
export const smoothstep = (t: number) => t * t * (3 - 2 * t);
export const lerp = (a: number, b: number, t: number) => a + (b - a) * t;

const hexToRgb = (hex: string): [number, number, number] => {
  const h = hex.replace("#", "");
  return [
    parseInt(h.slice(0, 2), 16),
    parseInt(h.slice(2, 4), 16),
    parseInt(h.slice(4, 6), 16),
  ];
};
export function lerpColor(a: string, b: string, t: number): string {
  if (a === b) return a;
  const [r1, g1, b1] = hexToRgb(a);
  const [r2, g2, b2] = hexToRgb(b);
  return `rgb(${Math.round(lerp(r1, r2, t))},${Math.round(lerp(g1, g2, t))},${Math.round(
    lerp(b1, b2, t)
  )})`;
}

// ---------------------------------------------------------------------------
// Layout — authored, not inferred
// ---------------------------------------------------------------------------
// dagre is still used for the graph CONTENT in the React build
// (buildGraphFromAgents gives the real nodes, edges and status colours) but its
// layout output is discarded. Two rounds of trying to steer it failed:
// insertion order does not survive crossing minimisation (poi-agent got flung
// to x=2240 to sit under weather, leaving an 1800px hole mid-graph in the early
// beats), and the specialists' provider edges push claude a rank below openai,
// which breaks the chapter-03 swap. A scroll-scrubbed narrative needs reveal
// order to read left-to-right, which is a different objective from crossing
// minimisation.
//
// ROWS is in reveal order, left to right, top to bottom.
//
// The split is 5+5 rather than 8+2 for aspect ratio: at 8 wide the graph was
// 2800x860 (3.3:1) against a ~2.4:1 panel, so it was width-bound and B13
// bottomed out at 0.43 zoom. 5+5 is 1720x860 (2:1) in the same four rows —
// adding a FIFTH row would have traded the width problem for a height one.
//
// Row 2 = what the planner wires to directly for the trip plus its two brains;
// row 3 = second-hop leaves and the delegated specialists. Keeping claude and
// openai on row 2 next to the planner is deliberate: chapters 02-03 are the
// story, and demoting the providers a rank would push their edges behind the
// tool row exactly where the provider swap has to read cleanly.
export const NODE_W = 280;
export const NODE_H = 140;
const ROWS: string[][] = [
  [GATEWAY],
  [PLANNER],
  [FLIGHT, HOTEL, POI, CLAUDE, OPENAI],
  [PREFS, WEATHER, BUDGET, ADVENTURE, LOGISTICS],
];
const PITCH_X = NODE_W + 80;
const PITCH_Y = NODE_H + 100;

export const POS = (() => {
  const spanOf = (n: number) => n * NODE_W + (n - 1) * 80;
  const widest = Math.max(...ROWS.map((r) => r.length));
  const out = new Map<string, { x: number; y: number }>();
  ROWS.forEach((row, r) => {
    // Rows share a centre axis so short rows don't strand the wide finale with
    // a lopsided empty half.
    const x0 = (spanOf(widest) - spanOf(row.length)) / 2;
    row.forEach((id, i) => out.set(id, { x: x0 + i * PITCH_X, y: r * PITCH_Y }));
  });
  return out;
})();
POS.set(WEATHER_GROUP, POS.get(WEATHER)!);

function bboxOf(ids: string[]) {
  const pts = ids.map((id) => POS.get(id)!).filter(Boolean);
  const x = Math.min(...pts.map((p) => p.x));
  const y = Math.min(...pts.map((p) => p.y));
  return {
    x,
    y,
    w: Math.max(...pts.map((p) => p.x)) + NODE_W - x,
    h: Math.max(...pts.map((p) => p.y)) + NODE_H - y,
  };
}
const BEAT_BOX = BEATS.map((b) => bboxOf(b.focus));

// ---------------------------------------------------------------------------
// Camera
// ---------------------------------------------------------------------------
/**
 * Fraction of the panel width reserved, on the left, for the pinned copy.
 * The camera frames every beat inside the REMAINING band, so no node can ever
 * land under the text. Placing the text in whatever gap a beat happens to leave
 * was the alternative and it is worse: the open space migrates as the camera
 * moves, so the copy would chase it around the panel and the title would stop
 * being pinned. A fixed column costs zoom (see BAND_FILL) but the reader's eye
 * never has to re-acquire it.
 */
export const GUTTER = 0.32;
/**
 * Share of the reserved band the graph is allowed to occupy. Slightly wider
 * than the old full-panel 0.9 to claw back some of the zoom the gutter costs;
 * the left margin is already a hard edge, so this only trims the right one.
 */
const BAND_FILL = 0.94;

export function camFor(i: number, W: number, H: number) {
  const box = BEAT_BOX[i];
  const gutter = BEATS[i].fullBleed ? 0 : GUTTER;
  const band = W * (1 - gutter);
  // Leave headroom for the title block and the chapter rail. With the planner
  // as hub the graph is wide and flat (rank 1 holds five cards), so the
  // horizontal allowance has to be generous or every wide beat under-zooms.
  const fit = Math.min((band * BAND_FILL) / box.w, (H * 0.62) / box.h);
  return {
    cx: box.x + box.w / 2,
    cy: box.y + box.h / 2,
    /** Screen x the beat's centre is pinned to — mid-band, not mid-panel. */
    ax: W * gutter + band / 2,
    zoom: clamp(fit, 0.12, BEATS[i].maxZoom ?? 1.1),
  };
}

/**
 * Crossfade position at which the title/sub/description flip to the incoming
 * beat. Also the gate for every reveal — see `fIn` in the driver.
 */
export const LEAD_FLIP = 0.4;

/** Resting stroke width — tier-2 tool edges are drawn lighter. */
export const restWidth = (edgeId: string) => (edgeId.startsWith("llm|") ? 1.8 : 2.4);

/** Total pinned travel: the topology arc plus the epilogue, in vh. */
export const totalTravel = TOTAL_VH + REVEAL_VH;

/** vh travelled → continuous beat position, honouring per-beat weights. */
export function rawFromVh(vh: number): number {
  for (let i = 0; i < N; i++) {
    if (vh < CUM[i + 1] || i === N - 1) {
      return i + clamp((vh - CUM[i]) / BEATS[i].weight, 0, 1);
    }
  }
  return N - 1;
}

// ---------------------------------------------------------------------------
// The reveal
// ---------------------------------------------------------------------------
// Reveal timeline, in fractions of REVEAL_VH (6.9vh):
//
//   0.000-0.096  graph and rail clear                  0.00-0.66vh
//   0.019-0.096  B14's copy leaves with them           0.13-0.66vh
//   0.096-0.109  EMPTY PANEL                           0.66-0.75vh
//   0.109-0.185  headline arrives into the empty rail  0.75-1.28vh
//   0.222-0.635  six phases stagger in and stay        1.53-4.38vh
//   0.635-0.787  hold — the whole grid readable        4.38-5.43vh
//   0.787-0.859  grid and headline leave, completely   5.43-5.93vh
//   0.859-0.876  EMPTY PANEL                           5.93-6.05vh
//   0.876-0.929  CTA arrives into an empty frame       6.05-6.41vh
//   0.929-1.000  hold                                  6.41-6.90vh
//
// THE GAPS ARE NOT THE BLANK. smoothstep is flat at both ends — it crosses the
// 0.005 perceptual floor at t = 0.0414 — so each window is imperceptible for its
// first and last ~4%. The blank a reader sees is the nominal gap PLUS those
// tails from the outgoing and incoming windows, which is why these fractions
// look far too small to produce the ~120px and ~140px they actually give.
// Size them by computing the measured span, never by scaling the fraction.
//
// BOTH handoffs are sequential, and for the same reason. The beat copy and the
// reveal headline occupy the IDENTICAL left-rail position, so fading one out
// while fading the other in does not dissolve — it superimposes. B14's two-line
// title over the two-line headline put four strings on screen at once, all
// legible, for two or three scroll notches. The exit is deliberately the longer
// of the two: its pause precedes the finale and is doing work, where the
// entrance's only job is to prevent a collision.
//
// This is NOT how beat-to-beat works: there the title is one <h2> whose React
// key changes, so the old element unmounts and the new one fades in alone. One
// title exists at a time BY CONSTRUCTION, at any length — which is why beat
// copy may lengthen freely without risking this class of bug. The driver
// reproduces that by replacing the element rather than its text.
export const R_CLEAR = 0.096;
export const R_BEAT_OUT = [0.019, 0.096] as const;
export const R_HEAD = [0.109, 0.185] as const;
export const R_PHASE_0 = 0.222;
export const R_PHASE_STEP = 0.0652;
export const R_PHASE_SPAN = 0.087;
export const R_OUT = [0.787, 0.859] as const;
export const R_CTA = [0.876, 0.929] as const;

/**
 * Keyboard snap targets, as vh travelled inside the pinned section.
 *
 * One press = one composed frame. A beat is fully settled where `pos` lands
 * exactly on its index, which is the MIDPOINT of its own weight — the beat
 * boundaries are where the transitions happen, so snapping to them would land
 * the reader mid-dissolve, which is the thing a multiplier would also do.
 * Index 0 is the section entry, which renders the same frame as B1's midpoint.
 *
 * The reveal's stages are targets too: without them the epilogue is a single
 * press. The empty beat before the CTA deliberately is NOT a target — landing
 * on a blank panel reads as a broken page rather than as a pause, so the last
 * press plays hold -> exit -> empty -> CTA as one movement.
 */
export const SNAP_VH: number[] = (() => {
  const out = [0];
  for (let i = 1; i < N; i++) out.push(CUM[i] + BEATS[i].weight / 2);
  out.push(TOTAL_VH + R_HEAD[1] * REVEAL_VH);
  for (let i = 0; i < REVEAL.phases.length; i++) {
    out.push(TOTAL_VH + (R_PHASE_0 + i * R_PHASE_STEP + R_PHASE_SPAN) * REVEAL_VH);
  }
  out.push(TOTAL_VH + R_CTA[1] * REVEAL_VH);
  return out;
})();

/**
 * Chapter-level stops for the Shift modifier: the first beat of each chapter at
 * ITS settled midpoint — never the chapter boundary, for the same reason the
 * beat targets avoid beat boundaries — then the reveal headline and the CTA.
 * Seven stops for the whole piece instead of twenty-two.
 *
 * Two readings of the same section: beat-by-beat for a reader consuming the
 * story, chapter-by-chapter for one who has seen it and wants the end. Every
 * entry here is also a SNAP_VH entry except the first, which is B1's midpoint
 * where SNAP_VH uses the section entry — the two render an identical frame.
 */
export const CHAPTER_VH: number[] = (() => {
  const out: number[] = [];
  for (let c = 0; c < BUILT_CHAPTERS; c++) {
    const i = BEATS.findIndex((b) => b.chapter === c);
    if (i >= 0) out.push(CUM[i] + BEATS[i].weight / 2);
  }
  out.push(TOTAL_VH + R_HEAD[1] * REVEAL_VH);
  out.push(TOTAL_VH + R_CTA[1] * REVEAL_VH);
  return out;
})();

/**
 * First beat index and beat count per chapter, for the progress rail's fill.
 * Precomputed: this was a findIndex + filter over all 14 beats, per chapter,
 * inside the per-frame apply — ~140 array element visits every frame at 60fps
 * to recompute constants.
 */
export const CHAPTER_SPAN = Array.from({ length: BUILT_CHAPTERS }, (_, c) => ({
  first: BEATS.findIndex((b) => b.chapter === c),
  count: BEATS.filter((b) => b.chapter === c).length,
}));

/** Focus in these swallows the keys entirely — they are text entry. */
export const TEXT_ENTRY = new Set(["INPUT", "TEXTAREA", "SELECT"]);
/** Space/Enter belong to these; the paging keys still do not. */
export const ACTIVATABLE = new Set(["BUTTON", "A"]);
