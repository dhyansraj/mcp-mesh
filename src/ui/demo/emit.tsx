// BUILD-TIME EMITTER for the prerendered bundle.
//
// Renders the REAL <Stage> — the same component the React bundle mounts, with
// the same beat data and the same AgentNode — to static markup, and extracts
// everything the vanilla driver needs to animate it. Nothing here is a
// reimplementation: if a card's markup changes, this output changes with it.
//
//   node demo/dist/emit.cjs            → demo/generated/graph.json
//   node demo/dist/emit.cjs --report   → also print the equivalence summary
//
// WHY THE FIXTURE IS NOT A GENERATION SOURCE. geometry.json supplies exactly
// two things that cannot be known without a browser: the measured card boxes
// and the handle offsets. Everything else — markup, edge paths, label
// positions, card variants — is regenerated from source here, so a stale
// fixture cannot silently freeze a stale picture. The guards below fail the
// build rather than emit something that disagrees with the fixture.
import fs from "node:fs";
import path from "node:path";
import { renderToStaticMarkup } from "react-dom/server";
import { ReactFlowProvider } from "@xyflow/react";

import { AgentNode } from "@/components/topology/AgentNode";
import { buildGraphFromAgents } from "@/lib/topology";
import {
  Stage, BeatCopy, setSsrGeometry, HANDLE_OFFSET, type SsrBox,
} from "./stage";
import {
  BEATS, BUILT_CHAPTERS, REVEAL, buildWorld, MAXIMAL, MAXIMAL_REPLICAS,
  WEATHER_GROUP, EMBED_SHOWS_HEADER,
} from "./script";

// Runs both as source (tsx, __dirname = demo/) and as the esbuild bundle
// (demo/generated/). Resolve the demo root by name rather than by guessing a
// depth, so moving the compiled output again does not silently break paths.
const HERE = path.basename(__dirname) === "demo" ? __dirname : path.join(__dirname, "..");
fs.mkdirSync(path.join(HERE, "generated"), { recursive: true });

interface Geometry {
  handleOffset: { source: number; target: number };
  stateCount: number;
  beatToState: Record<string, number>;
  states: Array<{
    nodes: Record<string, { w: number; h: number }>;
    edges: Record<string, string>;
  }>;
}
const GEO: Geometry = JSON.parse(
  fs.readFileSync(path.join(HERE, "geometry.json"), "utf8")
);

// Same guard as the Phase 1 prototype, for the same reason: the two-state model
// is a fact about today's copy, not about copy in general. One more badge or a
// longer runtime label can reflow a card at some other beat, and the
// prerendered edges would then be drawn to handle positions the cards no longer
// occupy — wrong, and silently so.
const EXPECTED_STATES = 2;
if (GEO.stateCount !== EXPECTED_STATES) {
  throw new Error(
    `geometry.json has ${GEO.stateCount} distinct states, expected ${EXPECTED_STATES}. ` +
      `A card's rendered box changed. Re-capture, confirm the new state is intended, ` +
      `then update EXPECTED_STATES.`
  );
}

// The fixture carries its own copy of the handle offsets, and stage.tsx derives
// every edge endpoint from ITS copy. Nothing compared the two, so the fixture
// could be re-captured against a changed card and silently disagree with the
// code that consumes it — the same class of drift the stateCount guard exists
// to catch, on the other input.
for (const k of ["source", "target"] as const) {
  if (GEO.handleOffset[k] !== HANDLE_OFFSET[k]) {
    throw new Error(
      `geometry.json handleOffset.${k} is ${GEO.handleOffset[k]} but stage.tsx uses ` +
        `${HANDLE_OFFSET[k]}. One of them was changed without the other; every edge ` +
        `endpoint depends on this.`
    );
  }
}

const BEAT_TO_STATE = BEATS.map((_, i) => GEO.beatToState[String(i + 1)] ?? 0);
const boxes = (state: number) =>
  new Map<string, SsrBox>(Object.entries(GEO.states[state].nodes));

// ---------------------------------------------------------------------------
// Render the real component, once per geometry state
// ---------------------------------------------------------------------------
function renderStage(state: number): string {
  setSsrGeometry(boxes(state));
  try {
    return renderToStaticMarkup(<Stage showHeader={EMBED_SHOWS_HEADER} />);
  } finally {
    setSsrGeometry(null);
  }
}

// One shell per geometry state, derived from the fixture rather than written
// out — a third state must not silently go unrendered.
const shells = GEO.states.map((_, i) => renderStage(i));

/** Split the markup into one chunk per edge <g>, keyed by data-id. */
function edgeChunks(html: string): Map<string, string> {
  const out = new Map<string, string>();
  for (const chunk of html.split(/(?=<g class="react-flow__edge)/)) {
    const id = /data-id="([^"]+)"/.exec(chunk);
    if (id && chunk.startsWith("<g class=\"react-flow__edge")) out.set(id[1], chunk);
  }
  return out;
}

/** Round exactly as the fixture does — 2dp, then compare byte-exact. */
const r2 = (s: string) =>
  s.replace(/-?\d+\.?\d*/g, (m) => {
    const v = Math.round(Number(m) * 100) / 100;
    return String(v);
  });

interface StateGeom {
  d: Record<string, string>;
  label: Record<string, [number, number]>;
}
const states: StateGeom[] = shells.map((html, s) => {
  const g: StateGeom = { d: {}, label: {} };
  for (const [id, chunk] of edgeChunks(html)) {
    const d = /<path style="[^"]*"\s+d="([^"]+)"/.exec(chunk);
    if (!d) throw new Error(`state ${s}: no edge path for ${id}`);
    g.d[id] = d[1];
    // The label wrapper's translate is (labelX - bboxW/2, labelY - bboxH/2).
    // Under SSR the bbox is 0x0 — getBBox needs a layout — so what is baked
    // here is exactly (labelX, labelY). The driver re-applies the offset once
    // it has measured the text, which is what React Flow's EdgeText does too.
    const t = /class="react-flow__edge-textwrapper" visibility="hidden"/.test(chunk)
      ? /<g transform="translate\((-?[\d.]+) (-?[\d.]+)\)" class="react-flow__edge-textwrapper"/.exec(chunk)
      : null;
    if (!t) throw new Error(`state ${s}: no unmeasured label wrapper for ${id}`);
    g.label[id] = [Number(t[1]), Number(t[2])];
  }
  return g;
});

// EQUIVALENCE, LAYER 1: every edge path this build emits, in both geometry
// states, against the paths captured from the running React build.
let pathOk = 0;
const pathBad: string[] = [];
states.forEach((g, s) => {
  const want = GEO.states[s].edges;
  for (const [id, d] of Object.entries(g.d)) {
    if (r2(d) === want[id]) pathOk++;
    else pathBad.push(`  state ${s} ${id}\n    emitted  ${r2(d)}\n    captured ${want[id]}`);
  }
  for (const id of Object.keys(want)) {
    if (!(id in g.d)) pathBad.push(`  state ${s} ${id}: in fixture, not emitted`);
  }
});
if (pathBad.length) {
  throw new Error(
    `prerendered edge geometry disagrees with the captured fixture:\n${pathBad.join("\n")}`
  );
}

// ---------------------------------------------------------------------------
// Card variants — what the driver swaps at a lead flip
// ---------------------------------------------------------------------------
// AgentNode renders <Handle/><div class="card">…</div><Handle/>. The driver
// keeps the card DIV ELEMENT and rewrites its class and innerHTML, rather than
// replacing the node's markup wholesale. That is not a micro-optimisation: the
// card transitions all of its properties over 300ms, so its border colour and
// elevation are meant to EASE between beats. Replacing the element would make
// "It dies." snap from green to red instead of bleeding into it. Everything
// inside the card that changes (status dot, deps count, runtime pill, badges)
// carries no transition, so recreating those children is not observable.
const canonical = buildGraphFromAgents(MAXIMAL);
const grouped = buildGraphFromAgents(MAXIMAL_REPLICAS);
const NODE_IDS = [...canonical.nodes.map((n) => n.id), WEATHER_GROUP];
const EDGE_IDS = (() => {
  const seen = new Map<string, true>();
  for (const e of [...canonical.edges, ...grouped.edges]) seen.set(e.id, true);
  return [...seen.keys()];
})();

const renderCard = (id: string, data: Record<string, unknown>) =>
  renderToStaticMarkup(
    <ReactFlowProvider>
      <AgentNode
        id={id} type="agentNode" data={data} dragging={false} zIndex={0}
        selectable={false} deletable={false} selected={false} draggable={false}
        isConnectable={false} positionAbsoluteX={0} positionAbsoluteY={0}
      />
    </ReactFlowProvider>
  );

/** The card div is the middle child; the handles either side never change. */
const CARD_RE = /^<div [^>]*data-handlepos="top"[^>]*><\/div><div class="([^"]*)">([\s\S]*)<\/div><div [^>]*data-handlepos="bottom"[^>]*><\/div>$/;
function splitCard(markup: string): { cls: string; html: string } {
  const m = CARD_RE.exec(markup);
  if (!m) throw new Error(`AgentNode markup did not match the expected card shape:\n${markup.slice(0, 300)}`);
  return { cls: m[1], html: m[2] };
}

const perBeatData = BEATS.map(
  (b) => new Map(buildGraphFromAgents(buildWorld(b.world)).nodes.map((n) => [n.id, n.data]))
);
const FALLBACK = new Map<string, Record<string, unknown>>();
for (const m of perBeatData) {
  for (const [id, d] of m) if (!FALLBACK.has(id)) FALLBACK.set(id, d as Record<string, unknown>);
}

interface CardTable {
  variants: Array<{ cls: string; html: string }>;
  byBeat: number[];
}
const cards: Record<string, CardTable> = {};
let variantCount = 0;
for (const id of NODE_IDS) {
  const index = new Map<string, number>();
  const table: CardTable = { variants: [], byBeat: [] };
  for (let b = 0; b < BEATS.length; b++) {
    const data = (perBeatData[b].get(id) ?? FALLBACK.get(id)) as Record<string, unknown>;
    const part = splitCard(renderCard(id, data));
    const key = `${part.cls} ${part.html}`;
    let v = index.get(key);
    if (v === undefined) {
      v = table.variants.length;
      index.set(key, v);
      table.variants.push(part);
    }
    table.byBeat.push(v);
  }
  variantCount += table.variants.length;
  cards[id] = table;
}

// EQUIVALENCE, LAYER 2: the shell's own cards must BE variant byBeat[0]. This
// is what proves the variant table and the prerendered markup came from the
// same renderer — if AgentNode's output ever drifts from what <Stage> puts in
// the node wrapper, the driver's first swap would silently change the picture.
for (const id of NODE_IDS) {
  const want = cards[id].variants[cards[id].byBeat[0]];
  const literal = `<div class="${want.cls}">${want.html}</div>`;
  const at = shells[0].indexOf(literal);
  if (at === -1) {
    throw new Error(
      `the card the driver would swap in for ${id} at beat 1 does not appear in the ` +
        `prerendered shell. AgentNode's output and <Stage>'s output have diverged.\n` +
        `  expected  ${literal.slice(0, 200)}`
    );
  }
  if (shells[0].indexOf(literal, at + 1) !== -1) {
    throw new Error(`card markup for ${id} appears more than once in the shell`);
  }
}

let hookCount = 0;
// EQUIVALENCE, LAYER 3: every hook the driver reaches for must EXIST.
//
// This is the one failure this pipeline was still open to, and it is the worst
// one available. driver.ts resolves its elements once and returns silently if
// the essential ones are missing — but static.ts has already set
// data-mesh-scroll-mounted="1" by then, which is what hides the placeholder. So
// renaming a class in stage.tsx would pass the prerender, pass the bundle
// build, pass the deploy's four-file check, and ship an empty dark panel over
// 2205vh of scroll. Nothing downstream looks INSIDE the markup.
//
// Everything below is a selector driver.ts actually queries. Counts are derived
// from the same arrays the driver iterates, never written as literals — a
// fourteenth node has to change this assertion or break it.
{
  // Class names are counted on a TOKEN boundary, not as substrings. A plain
  // indexOf for `react-flow__viewport` also matches `react-flow__viewport-portal`
  // and reported 2 where the driver sees 1 — a guard that miscounts is a guard
  // that gets relaxed until it stops meaning anything.
  const count = (needle: string) =>
    needle.startsWith("<")
      ? shells[0].split(needle).length - 1
      : (shells[0].match(new RegExp(needle.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + "(?![\\w-])", "g")) ?? []).length;
  const required: Array<[string, number | "atLeastOne"]> = [
    // Structural handles — the driver bails out entirely without these.
    ['data-mesh="section"', 1],
    ["demo-panel", 1],
    ["demo-graph", 1],
    ["react-flow__viewport", 1],
    // <Background> renders the pattern the camera has to keep in step.
    ["<pattern", 1],
    ["<circle", "atLeastOne"],
    // Beat copy. `desc` is deliberately absent: it is optional per beat, and
    // the driver already treats it as such.
    ['data-mesh="title"', 1],
    ['data-mesh="sub"', 1],
    ['data-mesh="chapter"', 1],
    // One wrapper, path, interaction path and label per edge; one card per node.
    ["react-flow__node", NODE_IDS.length],
    ["react-flow__edge-path", EDGE_IDS.length],
    ["react-flow__edge-interaction", EDGE_IDS.length],
    ["react-flow__edge-textwrapper", EDGE_IDS.length],
    ["react-flow__edge-textbg", EDGE_IDS.length],
    ["react-flow__edge-text", EDGE_IDS.length],
  ];
  for (let c = 0; c < BUILT_CHAPTERS; c++) required.push([`data-mesh-rail="${c}"`, 1]);
  for (const id of NODE_IDS) required.push([`.react-flow__node[data-id="${id}"]`, 0]);
  for (const id of EDGE_IDS) required.push([`.react-flow__edge[data-id="${id}"]`, 0]);

  const bad: string[] = [];
  for (const [sel, want] of required) {
    // The per-element entries above are recorded as selectors for the error
    // message; what is actually searched for is the attribute they match on.
    const needle = sel.startsWith(".react-flow__") ? sel.slice(sel.indexOf("[") + 1, -1) : sel;
    const got = count(needle);
    if (want === "atLeastOne" ? got < 1 : want === 0 ? got < 1 : got !== want) {
      bad.push(`  ${sel}: found ${got}, expected ${want === 0 ? "at least 1" : want}`);
    }
  }
  if (bad.length) {
    throw new Error(
      "the prerendered shell is missing hooks the driver queries — it would mount, " +
        "hide the placeholder and animate nothing:\n" +
        bad.join("\n")
    );
  }
  hookCount = required.length;
}

// ---------------------------------------------------------------------------
// Beat copy — rendered from the SAME component <Stage> mounts
// ---------------------------------------------------------------------------
// The driver replaces the whole copy block at each lead flip, so what it needs
// is the markup, not the pieces. Rendering <BeatCopy> here rather than
// rebuilding the four elements from hand-copied class strings is what makes
// that safe: a type change in stage.tsx now reaches the shipped bundle by
// construction instead of by somebody remembering.
const beatCopy = BEATS.map((b, i) => ({
  html: renderToStaticMarkup(<BeatCopy beat={b} lead={i} />),
}));

// EQUIVALENCE, LAYER 4: the copy the driver swaps in at beat 1 must BE the copy
// already in the shell.
//
// HONEST SCOPE: this no longer catches class drift, and that is the point —
// both sides render <BeatCopy>, so they cannot disagree about markup. Verified
// by perturbing a class and watching this NOT fire, because both outputs moved
// together. What it still catches is the shell and the table being rendered
// from different beat data or a different lead, which is cheap to check and
// would otherwise show up only as wrong copy on the first frame.
{
  const at = shells[0].indexOf(beatCopy[0].html);
  if (at === -1) {
    throw new Error(
      "the beat-1 copy block the driver would swap in does not appear in the " +
        "prerendered shell:\n  " + beatCopy[0].html.slice(0, 240)
    );
  }
}

/** Per-beat edge stroke, so the driver never needs the graph builder. */
const edgeStroke = BEATS.map((b) => {
  const g = buildGraphFromAgents(buildWorld(b.world));
  const m = new Map(g.edges.map((e) => [e.id, (e.style?.stroke as string) ?? "#6b7280"]));
  return EDGE_IDS.map((id) => m.get(id) ?? "#6b7280");
});

const out = {
  _comment:
    "GENERATED by demo/emit.tsx. Static markup and animation tables for the " +
    "prerendered bundle, rendered from the real <Stage>. Do not edit by hand.",
  shell: shells[0],
  nodeOrder: NODE_IDS,
  edgeOrder: EDGE_IDS,
  beatToState: BEAT_TO_STATE,
  // Counts the driver's CSS variables are indexed by. Emitted so the
  // equivalence harness can derive what to read instead of hardcoding it —
  // a literal there would let a new chapter or phase go unnoticed by the
  // comparison while it still printed IDENTICAL.
  chapterCount: BUILT_CHAPTERS,
  phaseCount: REVEAL.phases.length,
  states,
  cards,
  beatCopy,
  edgeStroke,
};
// Emitted into demo/generated/, which is gitignored, and BOTH halves of that
// are load bearing.
//
// Ignored, because Tailwind v4's automatic source detection scans any text file
// under the Vite root but skips ignored paths — and this file is 150 kB of
// rendered markup. With it sitting in demo/ the DASHBOARD's stylesheet gained a
// spurious utility rule, extracted from an arbitrary-value transition property
// inside a badge's class attribute. (DO NOT NAME A UTILITY IN PROSE
// ANYWHERE UNDER src/ui. The extractor reads comments, so an ordinary English
// word that is also a Tailwind class emits a rule into the dashboard's
// stylesheet. That has now happened three times here, each with a different
// word, twice inside a comment explaining the problem. Avoid in prose:
// visible, hidden, shadow, isolate, fixed, static, block, table, grid,
// container, transform, filter, blur, border, ring. Verify with a dashboard
// build and a stylesheet diff, never by eye.)
//
// Its OWN directory rather than demo/dist/, because vite.demo.config.ts builds
// the React bundle into demo/dist/ with emptyOutDir — so writing it there meant
// building the React bundle silently deleted the prerendered bundle's only
// input, and the next type-check failed on a missing module.
//
// It is also a build artifact in the same sense the bundle is, regenerated by
// CI on every deploy, so it has no business being committed either.
fs.writeFileSync(path.join(HERE, "generated", "graph.json"), JSON.stringify(out));

const kb = (n: number) => (n / 1024).toFixed(1).padStart(7) + " kB";
const pathTotal = GEO.states.reduce((n, st) => n + Object.keys(st.edges).length, 0);
console.log(
  `  prerender: ${pathOk}/${pathTotal} edge paths match the captured fixture ` +
    `(${GEO.stateCount} states x ${EDGE_IDS.length} edges)`
);
console.log(`  prerender: ${NODE_IDS.length} cards, ${variantCount} distinct variants, shell verified against the table`);
console.log(`  prerender: ${hookCount} driver hooks present in the shell (selectors, node/edge ids, rail slots)`);
if (process.argv.includes("--report")) {
  console.log(`    shell markup   ${kb(shells[0].length)}`);
  console.log(`    card variants  ${kb(JSON.stringify(cards).length)}`);
  console.log(`    beat copy      ${kb(JSON.stringify(beatCopy).length)}`);
  console.log(`    geometry       ${kb(JSON.stringify(states).length)}`);
}
