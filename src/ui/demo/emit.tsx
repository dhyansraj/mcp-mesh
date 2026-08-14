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
  Stage, setSsrGeometry, HANDLE_OFFSET, type SsrBox,
  RevealTitle, RevealSub, PhaseCopy, CtaCopy,
} from "./stage";
import { beatBlocks, renderPartial } from "./partial";
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
function renderStage(
  state: number,
  copy: "inline" | "slot",
  register?: "framed" | "open"
): string {
  setSsrGeometry(boxes(state));
  try {
    return renderToStaticMarkup(
      <Stage showHeader={EMBED_SHOWS_HEADER} copy={copy} register={register} />
    );
  } finally {
    setSsrGeometry(null);
  }
}

// One shell per geometry state, derived from the fixture rather than written
// out — a third state must not silently go unrendered.
//
// `copy="slot"`: the shipped shell leaves the copy stack EMPTY, because the
// docs page already serves the fourteen blocks and the driver moves those in.
// Rendering them here as well would put two copies of every beat in the
// document, one of them permanently at opacity 0 and still readable by every
// tool this was done for.
const shells = GEO.states.map((_, i) => renderStage(i, "slot"));

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
    const key = `${part.cls}\x00${part.html}`;
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
    // The copy stack. EMPTY here by construction; that half is asserted in the
    // copy section below, since `0` means "at least one" in this table.
    ['data-mesh="copy"', 1],
    // The epilogue's blocks, which the driver takes out of the accessibility
    // tree as each one's opacity window closes. Missing, they would stay
    // announced and findable for the whole section — silently, since nothing
    // about the picture would change.
    ['data-mesh="reveal"', 1],
    ['data-mesh="cta"', 1],
    // One wrapper, path, interaction path and label per edge; one card per node.
    ["react-flow__node", NODE_IDS.length],
    ["react-flow__edge-path", EDGE_IDS.length],
    ["react-flow__edge-interaction", EDGE_IDS.length],
    ["react-flow__edge-textwrapper", EDGE_IDS.length],
    ["react-flow__edge-textbg", EDGE_IDS.length],
    ["react-flow__edge-text", EDGE_IDS.length],
  ];
  for (let c = 0; c < BUILT_CHAPTERS; c++) required.push([`data-mesh-rail="${c}"`, 1]);
  for (let i = 0; i < REVEAL.phases.length; i++) required.push([`data-mesh-phase="${i}"`, 1]);
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
// Beat copy — the served document's, and the fallback
// ---------------------------------------------------------------------------
// These fourteen blocks are written to demo/copy.generated.html, which
// docs/index.md includes, so they are elements in the first HTML response. The
// same strings also go into the bundle as `beatCopy`, for a host page that does
// not carry them — see the note on Generated.beatCopy in driver.ts.
const blocks = beatBlocks();
const beatCopy = blocks.map((html) => ({ html }));

/**
 * React's escaping, undone — the five references it emits, plus the newline one
 * keepBreaks adds. Enough to compare authored prose against rendered output,
 * and deliberately not a general HTML parser: anything else appearing here
 * would mean the renderer changed, which is worth failing on rather than
 * absorbing.
 */
const decodeEntities = (s: string) =>
  s
    .replace(/&#x27;|&#39;/g, "'")
    .replace(/&quot;/g, '"')
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&#10;/g, "\n")
    // Last, so a literal "&amp;lt;" in the copy does not decode twice.
    .replace(/&amp;/g, "&");

/**
 * A searchable plain-text opening for each piece of epilogue prose.
 *
 * The strings in script.ts carry inline markup — `backticks` become <code> and
 * *asterisks* become <em> — so only the run before the first marker survives as
 * one uninterrupted piece of text. THAT RUN MUST EXIST: `split("`")[0]` returns
 * "" for a body that opens with a marker, and indexOf("") is 0, so the guard
 * would have reported such a string as present without looking for it. An
 * empty prefix is an authoring case this cannot check, and it says so instead
 * of passing.
 */
function prosePrefixes(): string[] {
  const sources = [...REVEAL.phases.map((p) => p.body), REVEAL.cta.title];
  return sources.map((s) => {
    const prefix = s.split(/[`*]/)[0].slice(0, 40).trim();
    if (!prefix) {
      throw new Error(
        `epilogue copy opens with inline markup, so it has no plain-text run ` +
          `to search the partial for: ${JSON.stringify(s.slice(0, 60))}. ` +
          `Give the guard something to match on, or check this string another way.`
      );
    }
    return prefix;
  });
}

// EQUIVALENCE, LAYER 4: the blocks the docs page serves must BE the blocks the
// component renders.
//
// This is what makes adoption safe. The driver takes nodes it did not create
// and animates them by index, so if the served markup and <Stage>'s markup ever
// diverged — a class, an attribute, an element order — the prerendered build
// and the React reference would render differently from the same beat data, and
// nothing downstream looks inside the copy.
//
// Compared against a Stage rendered with `copy="inline"`, which is what the dev
// page and the React bundle mount. Neither render carries any hidden state —
// that is written per frame from the opacities by whichever renderer is
// animating (see rail.ts), so the two markups are directly comparable.
//
// THE REGISTER IS FORCED, AND THAT IS ONLY HALF THE COMPARISON. `open` is the
// register the served copy sets the phase cells in, so it is what this render
// has to be for the partial to be checkable against it — and forcing it also
// keeps the choice out of a `sessionStorage` lookup that in Node decides it by
// throwing. But `framed` is the register that SHIPS, so a guard that only ever
// saw `open` would leave the six cells the page actually animates compared to
// nothing at all. They are checked separately, against the emitted shell rather
// than against a second synthetic render — see the phase cells below.
//
// The partial itself, and the one place it is written. Committed rather than
// ignored, unlike everything else this file emits, for two reasons that both
// matter: pymdownx.snippets runs with check_paths, so a missing snippet is a
// hard docs-build failure and `mkdocs serve` would need a bundle build first;
// and it is product prose, which belongs in a diff where it can be read. CI
// regenerates it and fails on any difference.
//
// RENDERED ONCE. Every guard below reads this exact string and it is this exact
// string that goes on disk, so nothing can be checked in a render that is not
// the one shipped.
const partialPath = path.join(HERE, "copy.generated.html");
const partial = renderPartial();
{
  const inlineShell = renderStage(0, "inline", "open");
  const missing: string[] = [];
  for (let i = 0; i < blocks.length; i++) {
    if (inlineShell.indexOf(blocks[i]) === -1) {
      missing.push(`  beat ${i + 1}: ${blocks[i].slice(0, 200)}`);
    }
  }
  if (missing.length) {
    throw new Error(
      "the copy blocks the docs page serves do not appear in <Stage>'s own " +
        "render — the served markup and the component have diverged, and the " +
        "driver adopts the served one:\n" + missing.join("\n")
    );
  }
  // THE WRITTEN FILE, not just the rendered blocks. What goes on disk has its
  // authored line breaks written as character references so the docs minifier
  // cannot collapse them (see keepBreaks) — which is only correct if the
  // parser puts back exactly what was taken out. Decoded here and compared to
  // the block that produced it, so an escape that changed anything else would
  // fail the build rather than reach the page.
  const decoded = partial.split("&#10;").join("\n");
  const notRoundTripped = blocks.filter((b) => decoded.indexOf(b) === -1);
  if (notRoundTripped.length) {
    throw new Error(
      "the written copy partial does not decode back to the blocks it was " +
        "rendered from — the line-break escaping is lossy:\n  " +
        notRoundTripped[0].slice(0, 200)
    );
  }
  // THE EPILOGUE, ON THE SAME TERMS AS THE BEATS.
  //
  // It reached this build hand-copied from stage.tsx into partial.tsx and had
  // already drifted — the served call to action rendered its code spans with
  // the mono sub-line's inline style instead of its own. Nothing caught it
  // because nothing compared them: the beat blocks had this guard and the
  // epilogue had none, which is precisely the gap a shared component plus this
  // assertion closes. Both outputs, so re-inlining either one fails the build.
  const epilogue: Array<[string, string]> = [
    ["the reveal headline", renderToStaticMarkup(<RevealTitle />)],
    ["the reveal sub-line", renderToStaticMarkup(<RevealSub />)],
    ...REVEAL.phases.map(
      (p) => [`phase ${p.label}`, renderToStaticMarkup(<PhaseCopy phase={p} />)] as [string, string]
    ),
    ["the call to action", renderToStaticMarkup(<CtaCopy />)],
  ];
  const drifted: string[] = [];
  for (const [what, html] of epilogue) {
    const inShell = inlineShell.indexOf(html) !== -1;
    const inPartial = decoded.indexOf(html) !== -1;
    if (!inShell || !inPartial) {
      drifted.push(
        `  ${what}: ${inShell ? "" : "NOT in <Stage>'s render"}` +
          `${!inShell && !inPartial ? ", " : ""}` +
          `${inPartial ? "" : "NOT in the served partial"}\n    ${html.slice(0, 200)}`
      );
    }
  }
  if (drifted.length) {
    throw new Error(
      "the epilogue's markup differs between the panel and the served copy. " +
        "Both must render the SAME components — only the arrangement around " +
        "them may differ:\n" + drifted.join("\n")
    );
  }
  // THE PHASE CELLS AS THEY SHIP, which is a different register from the one
  // above and for a while was the gap in this guard: the panel renders `framed`
  // unless a reader has picked otherwise in the session, and while that markup
  // was written out inside <Stage> the check above was comparing the register
  // the page does not use. Both registers now come from PhaseCopy, so the
  // shipped one can be checked the same way — against the EMITTED SHELL, the
  // string that goes into graph.json and gets mounted, rather than against
  // another render of the same component. Every state, since every one of them
  // is a shell the driver may be handed.
  const framedCells = REVEAL.phases.map(
    (p) => [p.label, renderToStaticMarkup(<PhaseCopy phase={p} register="framed" />)] as const
  );
  const notShipped: string[] = [];
  for (const [label, html] of framedCells) {
    // Named for what it holds rather than `states`, which is the emitted edge
    // geometry two hundred lines up and still in scope.
    const absentFrom = shells.map((s, i) => [i, s.indexOf(html)] as const).filter(([, at]) => at === -1);
    if (absentFrom.length) {
      notShipped.push(
        `  phase ${label}: not in shell state${absentFrom.length > 1 ? "s" : ""} ` +
          `${absentFrom.map(([i]) => i).join(", ")}\n    ${html.slice(0, 200)}`
      );
    }
  }
  if (notShipped.length) {
    throw new Error(
      "the prerendered shell's lifecycle cells are not what PhaseCopy renders in " +
        "the shipped register. The panel's markup and the shared component have " +
        "diverged, and the shell is what the docs page animates:\n" + notShipped.join("\n")
    );
  }
  // ...and the shipped shell carries no copy at all, so nothing the driver
  // adopts can end up in the document twice.
  if (shells.some((s) => s.indexOf("data-mesh-beat") !== -1)) {
    throw new Error(
      "the prerendered shell contains beat copy. It must ship an EMPTY stack: " +
        "the copy comes from the served document, and a second set would be " +
        "readable by every tool this exists to serve while being invisible."
    );
  }
}

// What the served document must actually contain. Counted rather than trusted:
// this is the only artifact here whose purpose is to be READ, so "it rendered"
// is not the same as "the words are in it".
{
  const count = (needle: string) => partial.split(needle).length - 1;
  const want: Array<[string, number]> = [
    ['data-mesh="title"', BEATS.length],
    ['data-mesh="sub"', BEATS.length],
    ['data-mesh="chapter"', BEATS.length],
    ['data-mesh="desc"', BEATS.filter((b) => b.desc).length],
  ];
  const bad = want.filter(([sel, n]) => count(sel) !== n);
  // Every phase body and the CTA, by their own text — the blocks above are
  // structural, but the epilogue's copy has no marker of its own.
  //
  // COMPARED AS TEXT, NOT AS MARKUP, on both sides. The needle is authored
  // prose and the haystack is React's output, where `'` is a character
  // reference and `&`, `<` and `>` are entities — so this compared an
  // unescaped string against an escaped one and passed only for as long as no
  // phase body happened to open with an apostrophe. The next one to do so
  // would have failed a build for a file that was completely correct.
  const text = decodeEntities(partial);
  const proseMissing = prosePrefixes().filter((s) => text.indexOf(s) === -1);
  if (bad.length || proseMissing.length) {
    throw new Error(
      "the generated copy partial is incomplete:\n" +
        bad.map(([sel, n]) => `  ${sel}: found ${count(sel)}, expected ${n}`).join("\n") +
        proseMissing.map((s) => `  missing reveal copy: ${s.slice(0, 60)}…`).join("\n")
    );
  }
}
fs.writeFileSync(partialPath, partial);

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
  beatCount: BEATS.length,
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
console.log(
  `  prerender: ${blocks.length} copy blocks + the epilogue written to ` +
    `demo/copy.generated.html (${(partial.length / 1024).toFixed(1)} kB), verified against <Stage>`
);
if (process.argv.includes("--report")) {
  console.log(`    shell markup   ${kb(shells[0].length)}`);
  console.log(`    card variants  ${kb(JSON.stringify(cards).length)}`);
  console.log(`    beat copy      ${kb(JSON.stringify(beatCopy).length)}`);
  console.log(`    geometry       ${kb(JSON.stringify(states).length)}`);
}
