// EQUIVALENCE CAPTURE — React bundle vs prerendered bundle, numerically.
//
//   make docs-scroll-compare          # terminal 1: builds both, serves :8899
//   node demo/equivalence.mjs         # terminal 2: captures both and diffs
//
// WHAT THIS IS FOR. The settled frames are the easy case and the least
// informative: the driver's job is the TRANSITIONS between them, which is where
// three separate bugs hid during this build (the gated reveal, the sequential
// handoff, the per-frame chapter scan). So the sample set is dominated by
// intermediate positions, not snap targets.
//
// ROUNDING DISCIPLINE. Nothing here rounds. Every value compared is a string
// the driver itself wrote — `.toFixed(3)`, `.toFixed(2)`, `rgb(r,g,b)` with
// integer components, or a transform built from the same expression in both
// builds. So the comparison is byte-exact by construction and a difference is
// a real difference, not a float artifact. An epsilon comparator would have
// hidden exactly the kind of drift this is meant to catch.
// RUNNING IT — Playwright is deliberately not a dependency of src/ui, so it is
// resolved from an existing install via MESH_PLAYWRIGHT. Two things bite here,
// and BOTH fail in a way that reads like this script is broken:
//
//   1. The path has to be discovered. There is no canonical location:
//        ls ~/.npm/_npx/*/node_modules/playwright/package.json
//
//   2. The candidate's browser revision must already be cached. A newer
//      install wants a chromium build that may not be on disk — 1.63-alpha
//      wants chromium 1237, 1.62.1 wants 1234 — and the launch failure names
//      a missing executable rather than a version mismatch. Check the
//      candidate against the cache before suspecting the harness — the wanted
//      revision is in the candidate's own playwright-core:
//        node -p "JSON.parse(require('fs').readFileSync('<dir>/playwright-core/browsers.json')).browsers.find(b=>b.name==='chromium').revision"
//        ls ~/Library/Caches/ms-playwright
//
//   MESH_PLAYWRIGHT=~/.npm/_npx/<hash>/node_modules/ node equivalence.mjs

import { createRequire } from "node:module";
import fs from "node:fs";
import path from "node:path";

// Playwright is not a dependency of src/ui and should not become one for a
// capture that runs by hand. MESH_PLAYWRIGHT points at any resolvable install
// (an npx cache directory is fine); the browser build it wants must already be
// in ~/Library/Caches/ms-playwright.
const require_ = createRequire(process.env.MESH_PLAYWRIGHT ?? import.meta.url);
const { chromium } = require_("playwright");

// COUNTS ARE DERIVED, NEVER WRITTEN AS LITERALS. An earlier version hardcoded
// 13 nodes / 18 edges / 5 chapters while the driver iterated
// `G.nodeOrder.length`, so a fourteenth node would have gone unnoticed by this
// comparison forever — and it would still have printed IDENTICAL. Reading the
// same manifest the driver is handed makes that impossible.
const G = JSON.parse(
  fs.readFileSync(path.join(import.meta.dirname, "generated", "graph.json"), "utf8")
);
const NODE_IDS = G.nodeOrder;
const EDGE_IDS = G.edgeOrder;
const CHAPTER_COUNT = G.chapterCount;
const PHASE_COUNT = G.phaseCount;
const BEAT_COUNT = G.beatCount;

const BASE = process.env.MESH_COMPARE_BASE ?? "http://localhost:8899/compare.html";
const OUT = path.join(import.meta.dirname, "dist");
// The viewport the geometry fixture was captured at. Changing it changes the
// camera, so both sides must use the same one — that is the point.
const VIEWPORT = { width: 1500, height: 900 };
/** Intermediate samples across the pinned travel. */
const SAMPLES = 200;

async function capture(variant) {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: VIEWPORT });
  const errors = [];
  page.on("console", (m) => {
    if (m.type() === "error") errors.push(m.text());
  });
  page.on("pageerror", (e) => errors.push(String(e)));

  await page.goto(`${BASE}?v=${variant}`, { waitUntil: "load" });
  // THE HARNESS'S OWN PRECONDITION, checked before anything is measured.
  // compare.html refuses to load either bundle if the served copy is not
  // there, because the prerendered build ADOPTS it — without it the comparison
  // runs against the in-bundle fallback and reports IDENTICAL having compared
  // something other than what ships. Read here so that failure is one line of
  // output rather than a selector timeout.
  //
  // WAITED FOR RATHER THAN SAMPLED. The flag is set from a `fetch` chain, and a
  // pending fetch does not hold back the load event — so reading it the instant
  // `load` fires is a race the slow case loses, and losing it costs exactly the
  // clear message this exists to give. Three outcomes resolve this: the mount
  // flag means the copy arrived and the bundle took over, the fatal flag means
  // the precondition failed, and the RESTORED flag means the bundle loaded and
  // then put the served copy back (demo/static.ts). The third is the one this
  // used to sit through: a refusal never sets the mount flag, so waiting on
  // only the first two spent a full selector timeout and then reported the
  // wait, not the refusal that caused it.
  await page.waitForFunction(
    () =>
      document.documentElement.dataset.meshHarnessFatal !== undefined ||
      document.querySelector("#mesh-scroll[data-mesh-scroll-restored]") !== null ||
      document.querySelector('#mesh-scroll[data-mesh-scroll-mounted="1"]') !== null
  );
  const fatal = await page.evaluate(() => document.documentElement.dataset.meshHarnessFatal);
  if (fatal) {
    await browser.close();
    console.error(`harness precondition failed (${variant}): ${fatal}`);
    console.error("Refusing to report a verdict — nothing comparable was loaded.");
    process.exit(1);
  }
  const restored = await page.evaluate(
    () => document.querySelector("#mesh-scroll")?.dataset.meshScrollRestored
  );
  if (restored) {
    await browser.close();
    console.error(
      `the ${variant} bundle restored the served copy instead of animating (${restored})` +
        (errors.length ? `: ${errors[0]}` : "")
    );
    console.error("Refusing to report a verdict — nothing comparable was loaded.");
    process.exit(1);
  }
  await page.waitForSelector('#mesh-scroll[data-mesh-scroll-mounted="1"]');
  await page.waitForSelector('[data-mesh="section"]');
  await page.evaluate(() => document.fonts.ready);
  // React needs a commit after mount before the first frame is authoritative.
  await page.waitForTimeout(300);

  const frames = await page.evaluate(async ({ SAMPLES, NODE_IDS, EDGE_IDS, CHAPTER_COUNT, PHASE_COUNT, BEAT_COUNT }) => {
    const section = document.querySelector('[data-mesh="section"]');
    const panel = document.querySelector(".demo-panel");
    const viewport = document.querySelector(".react-flow__viewport");
    const top = window.scrollY + section.getBoundingClientRect().top;
    const travel = section.getBoundingClientRect().height - window.innerHeight;

    const raf = () => new Promise((r) => requestAnimationFrame(r));
    const settle = async () => {
      // Three frames: one for the scroll event, one for the driver's rAF tick,
      // one for React to commit a lead change. The static build needs fewer;
      // giving both the same budget keeps the comparison fair.
      await raf();
      await raf();
      await raf();
      // ...then longer than the longest transition in scroll.css (90ms).
      //
      // THIS IS NOT SLACK. The graph is transitioned — edges, nodes, the gutter
      // and the graph layer — so their PAINTED values trail what the driver
      // wrote for up to 90ms, and this capture reads computed style on purpose,
      // to measure what the browser does rather than what the driver said. At
      // 20ms it was reading the middle of a fade and calling it a settled frame.
      //
      // IT CANNOT HIDE A MARKING SKEW, which is the thing to keep true here.
      // Nothing on the rail is transitioned any more — not the beats, not the
      // headline, not the call to action and, since the 90ms came off them, not
      // the six lifecycle cells — so for every block whose accessibility state
      // is asserted below, the painted opacity is the value written for the
      // frame that marked it. A settle long enough to let an ease finish is
      // exactly what would make that assertion unable to fail.
      await new Promise((r) => setTimeout(r, 120));
    };

    // Every custom property either build writes, by name. Read back off the
    // inline style, so what is compared is literally what was written.
    const names = [];
    for (let i = 0; i < NODE_IDS.length; i++) names.push(`--n${i}-o`);
    for (let i = 0; i < EDGE_IDS.length; i++) {
      names.push(`--e${i}-o`, `--e${i}-l`, `--e${i}-w`, `--e${i}-c`);
    }
    names.push("--accent", "--pulse", "--gutter");
    for (let c = 0; c < CHAPTER_COUNT; c++) names.push(`--ch${c}-f`);
    names.push("--graph", "--rail", "--beat", "--reveal", "--cta");
    for (let i = 0; i < PHASE_COUNT; i++) names.push(`--p${i}`);
    for (let i = 0; i < BEAT_COUNT; i++) names.push(`--b${i}`);

    const positions = [];
    for (let i = 0; i <= SAMPLES; i++) positions.push(i / SAMPLES);

    const out = [];
    for (const p of positions) {
      window.scrollTo(0, Math.round(top + p * travel));
      await settle();
      const vars = {};
      for (const n of names) vars[n] = panel.style.getPropertyValue(n);

      // THE COPY BLOCKS. All fourteen are in the document now, stacked in one
      // position, so "the copy on screen" is no longer whatever the one <h2>
      // happens to say — it is the block with the highest RENDERED opacity.
      // Read from the computed style rather than from the custom property, so
      // this measures what a CSS mistake would actually do (a stray transition,
      // a rule that stops applying) and not just what the driver wrote.
      const blocks = Array.from(
        document.querySelectorAll('[data-mesh="copy"] > [data-mesh-beat]')
      );
      const stackOpacity = Number(
        getComputedStyle(document.querySelector('[data-mesh="copy"]').parentElement).opacity
      );
      const shown = blocks.map((b) => Number(getComputedStyle(b).opacity) * stackOpacity);
      let active = 0;
      for (let i = 1; i < shown.length; i++) if (shown[i] > shown[active]) active = i;
      const lead = blocks[active] ?? document;
      const title = lead.querySelector('[data-mesh="title"]');
      const sub = lead.querySelector('[data-mesh="sub"]');
      const desc = lead.querySelector('[data-mesh="desc"]');
      const chapter = lead.querySelector('[data-mesh="chapter"]');
      const state = (el) =>
        !el
          ? "??"
          : (el.getAttribute("aria-hidden") === "true" ? "h" : "-") +
            (el.hasAttribute("inert") ? "i" : "-");
      const copyState = blocks.map(state).join("");
      // THE EPILOGUE'S BLOCKS, on the same terms. Nothing used to mark these at
      // all — the hidden state keyed off the current beat index, which says
      // nothing about them — so a reader met the whole epilogue throughout the
      // topology arc while it sat at zero opacity. Captured beside the rendered
      // opacity of each one, so the rule can be checked rather than only
      // compared between the builds (which agreed while both were wrong).
      const epilogueEls = [
        document.querySelector('[data-mesh="reveal"]'),
        document.querySelector('[data-mesh="cta"]'),
        ...Array.from(document.querySelectorAll("[data-mesh-phase]")),
      ];
      const epilogueState = epilogueEls.map(state).join("|");
      const epilogueShown = epilogueEls.map((el) =>
        el ? Number(getComputedStyle(el).opacity) : -1
      );
      // Above this, two blocks would be legible at once. 0.005 is the floor the
      // reveal's windows were sized against — smoothstep crosses it at 4.14% of
      // a window, which is where a fade stops being nothing.
      const VISIBLE = 0.005;
      const superimposed = shown.filter((o) => o > VISIBLE).length;
      const pat = document.querySelector(".react-flow__background pattern");
      const dot = document.querySelector(".react-flow__background circle");
      // THE CARDS. This is what applyLead actually rewrites at the 14 flips,
      // and the capture was blind to it: --n{i}-o is the WRAPPER's opacity, so
      // an off-by-one in byBeat, a wrong FALLBACK, or a status colour landing a
      // beat late would leave all of the custom properties byte-identical.
      const cards = {};
      for (const id of NODE_IDS) {
        const node = document.querySelector(
          `.react-flow__node[data-id="${CSS.escape(id)}"]`
        );
        const card = node && node.children[1];
        cards[id] = card ? { cls: card.className, html: card.innerHTML } : null;
      }
      // THE EDGE LABELS. If measureLabels never succeeds these stay
      // visibility:hidden in the static build while React shows them, and
      // nothing else in this capture would notice.
      const labels = {};
      const labelBox = {};
      for (const id of EDGE_IDS) {
        const g = document.querySelector(
          `.react-flow__edge[data-id="${CSS.escape(id)}"]`
        );
        const w = g && g.querySelector(".react-flow__edge-textwrapper");
        const t = g && g.querySelector(".react-flow__edge-text");
        const r = g && g.querySelector(".react-flow__edge-textbg");
        labels[id] = w
          ? [
              w.getAttribute("transform"),
              w.getAttribute("visibility"),
              t && t.getAttribute("y"),
              r && r.getAttribute("width"),
              r && r.getAttribute("height"),
            ].join("|")
          : null;
        // The live box, so the harness can check the wrapper is actually
        // CENTRED on it rather than only that both builds agree.
        const bb = t && t.getBBox();
        labelBox[id] = bb ? [bb.width, bb.height] : null;
      }
      out.push({
        p,
        y: window.scrollY,
        vars,
        cards,
        labels,
        labelBox,
        blockCount: blocks.length,
        copyState,
        shown,
        epilogueState,
        epilogueShown,
        superimposed,
        activeBeat: active,
        transform: viewport ? viewport.style.transform : null,
        title: title ? title.textContent : null,
        sub: sub ? sub.textContent : null,
        desc: desc ? desc.textContent : null,
        chapter: chapter ? chapter.textContent : null,
        // The background is a pure function of the transform in both builds;
        // if it drifts, the dots detach from the graph as it pans.
        bg: pat
          ? [
              pat.getAttribute("x"), pat.getAttribute("y"),
              pat.getAttribute("width"), pat.getAttribute("height"),
              pat.getAttribute("patternTransform"),
              dot && dot.getAttribute("r"),
            ].join("|")
          : null,
        // Edge geometry: proves the B14 state switch lands on the same paths.
        d: Array.from(document.querySelectorAll(".react-flow__edge-path"))
          .map((el) => el.getAttribute("d"))
          .join(";"),
      });
    }
    return out;
  }, { SAMPLES, NODE_IDS, EDGE_IDS, CHAPTER_COUNT, PHASE_COUNT, BEAT_COUNT });

  await browser.close();
  return { frames, errors };
}

const react = await capture("react");
const stat = await capture("static");

fs.mkdirSync(OUT, { recursive: true });
// Card bodies are compared in full but written out as lengths: at 13 cards x
// 2.6 kB x 201 positions the dumps would be ~7 MB each and nobody would open
// them. The comparison above has already run against the full strings.
const forDump = (frames) =>
  frames.map((f) => ({
    ...f,
    cards: Object.fromEntries(
      Object.entries(f.cards).map(([k, v]) => [k, v ? { cls: v.cls, htmlLen: v.html.length } : null])
    ),
  }));
fs.writeFileSync(path.join(OUT, "equiv-react.json"), JSON.stringify(forDump(react.frames), null, 1));
fs.writeFileSync(path.join(OUT, "equiv-static.json"), JSON.stringify(forDump(stat.frames), null, 1));

// FRAME COUNTS MUST MATCH. `Math.min` below would otherwise compare the
// shorter run and report IDENTICAL — the same fail-open class as swallowing
// ImageMagick's errors. If one build produced fewer frames, something went
// wrong in it and that is the finding.
if (react.frames.length !== stat.frames.length) {
  console.error(
    `frame count differs: react ${react.frames.length}, static ${stat.frames.length}. ` +
      `The two runs are not comparable; refusing to report a verdict.`
  );
  process.exit(1);
}

/**
 * Compared byte-exact, one value per frame each. Named in one place so the
 * count printed at the end is derived from the list rather than written next
 * to it, which is how it came to be reported as six while nine were compared.
 * The last three are the copy stack: same number of blocks, the same one on
 * screen, and the same thirteen out of the accessibility tree and out of
 * find-in-page.
 */
const SCALAR_FIELDS = [
  "transform", "title", "sub", "desc", "chapter", "bg",
  "blockCount", "copyState", "epilogueState", "activeBeat",
];

const diffs = [];
/** Half of the fixture's own 2dp rounding step — an order below a device pixel. */
const PATH_TOLERANCE = 0.005;
let maxPathDelta = 0;
let pathCmp = 0;
let cardCmp = 0;
let labelCmp = 0;
/** Covers React's own measured ~1.0px spread, with headroom. See the note below. */
const LABEL_TOLERANCE = 1.25;
let maxLabelDelta = 0;

/** Offset of the first differing character, for a readable mismatch report. */
const firstDiff = (x, y) => {
  const n = Math.min(x.length, y.length);
  for (let i = 0; i < n; i++) if (x[i] !== y[i]) return i;
  return n;
};
const n = Math.min(react.frames.length, stat.frames.length);
let varCmp = 0;
for (let i = 0; i < n; i++) {
  const a = react.frames[i];
  const b = stat.frames[i];
  const where = `p=${a.p.toFixed(4)} y=${a.y}`;
  for (const k of Object.keys(a.vars)) {
    varCmp++;
    if (a.vars[k] !== b.vars[k]) {
      diffs.push(`${where} ${k}: react="${a.vars[k]}" static="${b.vars[k]}"`);
    }
  }
  // Cards: compared in FULL, not by a hash. A hash would tell us something
  // changed; the class string is where the border colour lives and the body is
  // where the badges and dependency counts do, so a mismatch should say what.
  for (const id of Object.keys(a.cards)) {
    const ca = a.cards[id];
    const cb = b.cards[id];
    cardCmp += 2;
    if (!ca || !cb) {
      if (ca !== cb) diffs.push(`${where} card ${id}: react=${ca ? "present" : "MISSING"} static=${cb ? "present" : "MISSING"}`);
      continue;
    }
    if (ca.cls !== cb.cls) {
      diffs.push(`${where} card ${id} class:\n    react  ${ca.cls}\n    static ${cb.cls}`);
    }
    if (ca.html !== cb.html) {
      const at = firstDiff(ca.html, cb.html);
      diffs.push(
        `${where} card ${id} body differs at offset ${at}:\n` +
          `    react  …${ca.html.slice(Math.max(0, at - 40), at + 60)}\n` +
          `    static …${cb.html.slice(Math.max(0, at - 40), at + 60)}`
      );
    }
  }
  // EDGE LABELS: presence and VISIBILITY byte-exact, geometry within tolerance.
  //
  // Visibility is the whole point of capturing these — if the driver's getBBox
  // measurement never succeeds, the labels stay visibility:hidden in the
  // prerendered build while React shows them, and nothing else here would
  // notice. That is never tolerated; it is compared as a string.
  //
  // THE GEOMETRY TOLERANCE IS SET BY REACT'S OWN INSTABILITY, not by what the
  // prerendered build happens to need. React Flow re-measures every label with
  // getBBox on re-render, and Chrome returns zoom-dependent metrics for this
  // variable font, so the SAME label in the SAME build reports a background
  // box of 17, 17.290690422058105 and 16.298681259155273 at different scroll
  // positions — a spread of ~1.0px. The prerendered build measures once and
  // holds 17.10344696044922 everywhere, which sits INSIDE that range.
  //
  // So this is not the static build approximating React; it is React
  // disagreeing with itself by more than the two builds disagree, and the
  // static build being the stable one. Demanding byte-equality here would be
  // demanding that it reproduce a zoom-dependent measurement artifact.
  // Measured with demo/ scratch probes: every text-affecting computed style
  // (fontFamily, letterSpacing, fontVariationSettings, textRendering, and
  // eleven others) is identical between the builds, so this is Chrome's text
  // metrics under transform, not a styling divergence.
  for (const id of Object.keys(a.labels)) {
    labelCmp++;
    const la = a.labels[id];
    const lb = b.labels[id];
    if (la === null || lb === null) {
      if (la !== lb) diffs.push(`${where} edge label ${id}: react=${la} static=${lb}`);
      continue;
    }
    const va = /\|(visible|hidden)\|/.exec(la);
    const vb = /\|(visible|hidden)\|/.exec(lb);
    if ((va && va[1]) !== (vb && vb[1])) {
      diffs.push(`${where} edge label ${id} VISIBILITY: react=${va && va[1]} static=${vb && vb[1]}`);
    }
    const na = la.match(/-?\d+\.?\d*/g) ?? [];
    const nb = lb.match(/-?\d+\.?\d*/g) ?? [];
    if (na.length !== nb.length) {
      diffs.push(`${where} edge label ${id}: field count differs\n    react  ${la}\n    static ${lb}`);
      continue;
    }
    for (let j = 0; j < na.length; j++) {
      const delta = Math.abs(Number(na[j]) - Number(nb[j]));
      if (delta > maxLabelDelta) maxLabelDelta = delta;
      if (delta > LABEL_TOLERANCE) {
        diffs.push(`${where} edge label ${id}[${j}]: react ${na[j]} static ${nb[j]} (delta ${delta})`);
      }
    }
  }

  for (const k of SCALAR_FIELDS) {
    if (a[k] !== b[k]) {
      const trim = (v) => (v === null ? "null" : String(v).slice(0, 120));
      diffs.push(`${where} ${k}:\n    react  ${trim(a[k])}\n    static ${trim(b[k])}`);
    }
  }

  // EDGE PATHS ARE THE ONE FIELD COMPARED NUMERICALLY, and the reason is a
  // property of the React build, not a concession by the prerendered one.
  // React Flow derives handle positions from live ResizeObserver measurements,
  // which carry ~4e-4 px of jitter that varies BETWEEN RUNS of the same build —
  // `120.00036184105772` where the geometry is exactly 120. The prerendered
  // build has no observer and emits the exact value. Demanding byte-equality
  // here would be demanding that the static build reproduce noise.
  //
  // The fixture already takes this position: it rounds at capture precisely so
  // this jitter "must never reach" the compared values. So: same path count,
  // same structure, and every coordinate within a tolerance far below one
  // device pixel.
  const na = (a.d ?? "").match(/-?\d+\.?\d*/g) ?? [];
  const nb = (b.d ?? "").match(/-?\d+\.?\d*/g) ?? [];
  if (na.length !== nb.length) {
    diffs.push(`${where} d: coordinate COUNT differs — react ${na.length}, static ${nb.length}`);
  } else {
    for (let j = 0; j < na.length; j++) {
      const delta = Math.abs(Number(na[j]) - Number(nb[j]));
      if (delta > maxPathDelta) maxPathDelta = delta;
      if (delta > PATH_TOLERANCE) {
        diffs.push(`${where} d[${j}]: react ${na[j]} static ${nb[j]} (delta ${delta})`);
      }
    }
    pathCmp += na.length;
  }
}

// LABEL CENTRING, CHECKED AGAINST THE FIXTURE — not against the other build.
//
// This exists because a real bug got past the cross-build comparison: the
// driver wrote every label's wrapper transform BEFORE it had measured the
// label, centring each one on a 0x0 box, and its `state === geomState` guard
// then blocked any re-application. Every label sat half its own box off centre.
// The harness reported IDENTICAL throughout, because it only ever asked
// "do the two builds agree?" — and React's first frame has the same ordering,
// so both were wrong together.
//
// The fix in the harness is to compare against something that is NOT the other
// renderer: React Flow's own rule is transform = (labelX - w/2, labelY - h/2),
// labelX/labelY come from the fixture, and w/h are measured live. A stale
// transform fails this no matter what the other build does.
{
  const byState = G.states.map((st) => st.label);
  let checked = 0;
  let worstOff = 0;
  const off = [];
  for (const [name, cap] of [["react", react], ["static", stat]]) {
    for (const f of cap.frames) {
      for (const id of EDGE_IDS) {
        const raw = f.labels[id];
        const box = f.labelBox[id];
        if (!raw || !box || !box[0]) continue;
        const m = /translate\(([-\d.]+) ([-\d.]+)\)/.exec(raw);
        if (!m) continue;
        checked++;
        // Accept a match against either geometry state: which one is live at a
        // given frame is the driver's business, and a half-box offset matches
        // neither.
        const best = Math.min(
          ...byState.map((L) =>
            L[id] ? Math.max(Math.abs(+m[1] - (L[id][0] - box[0] / 2)), Math.abs(+m[2] - (L[id][1] - box[1] / 2))) : Infinity
          )
        );
        if (best > worstOff) worstOff = best;
        if (best > LABEL_TOLERANCE) {
          off.push(`  ${name} p=${f.p.toFixed(4)} ${id}: ${best.toFixed(3)} px off centre`);
        }
      }
    }
  }
  console.log(`checked ${checked} label centrings against the fixture, worst ${worstOff.toFixed(4)} px off centre`);
  if (off.length) {
    console.log(`${off.length} LABELS NOT CENTRED ON THEIR OWN BOX:`);
    for (const l of off.slice(0, 20)) console.log(l);
    process.exitCode = 1;
  }
}

// NO TWO BEATS ON SCREEN AT ONCE, measured rather than reasoned about.
//
// The guarantee used to be structural: one copy block existed at a time, so
// superimposition was impossible at any copy length. All fourteen are mounted
// now, so it is a timing property of two windows that meet at LEAD_FLIP —
// swept exhaustively in demo/copy-overlap.test.ts, and confirmed HERE against
// what the browser actually renders, which is the part maths cannot see.
{
  let worst = 0;
  const bad = [];
  for (const [name, cap] of [["react", react], ["static", stat]]) {
    for (const f of cap.frames) {
      if (f.blockCount !== BEAT_COUNT) {
        bad.push(`  ${name} p=${f.p.toFixed(4)}: ${f.blockCount} copy blocks, expected ${BEAT_COUNT}`);
      }
      if (f.superimposed > worst) worst = f.superimposed;
      if (f.superimposed > 1) {
        bad.push(`  ${name} p=${f.p.toFixed(4)}: ${f.superimposed} copy blocks legible at once`);
      }
    }
  }
  console.log(
    `copy stack: ${BEAT_COUNT} blocks in both builds, at most ${worst} legible at any sampled position`
  );
  if (bad.length) {
    console.log("COPY STACK FAILURES:");
    for (const l of bad.slice(0, 20)) console.log(l);
    process.exitCode = 1;
  }
}

// THE HIDDEN STATE IS THE OPACITY — checked as a RULE, not as an agreement.
//
// The two builds agreeing proves nothing here, and demonstrably so: they agreed
// for the whole of the previous implementation, in which the state keyed off the
// current beat index. That froze at the last beat through the epilogue, so
// B14's words stayed announced and findable at zero opacity for ~620vh, and the
// epilogue's own blocks were never marked at any position. Both builds were
// wrong together, byte for byte.
//
// So this asserts the property against the RENDERED opacity of each block:
// live above the threshold, out of the accessibility tree at or below it.
// Sampled across the whole travel, which means the epilogue positions — where
// every one of those failures lived — are covered by construction.
{
  // The floor the reveal's windows were sized against, and the one the
  // renderers apply. Same value as VISIBLE in demo/timeline.ts.
  const VISIBLE = 0.005;
  // The renderers apply the rule to the full-precision value and then write the
  // opacity out at 3dp, so a block within half a step of the threshold can be
  // marked one way and painted the other for one frame. That is rounding, not
  // drift; anything further out is the rule being wrong.
  const ROUNDING = 0.001;
  const wrong = [];
  let checked = 0;
  let epiloguePositions = 0;
  for (const [name, cap] of [["react", react], ["static", stat]]) {
    for (const f of cap.frames) {
      // Anything the epilogue is doing means the beat column is on its way out
      // or already gone — the positions the old rule could not describe.
      const inEpilogue = f.epilogueShown.some((o) => o > VISIBLE);
      if (inEpilogue) epiloguePositions++;
      const marks = [
        // `?? []` is not defensiveness for its own sake: copyState is one pair
        // of characters per copy block, so it is "" exactly when the stack is
        // empty — which the block above has already reported as the failure it
        // is. Without the guard the harness dies of a TypeError in the one case
        // it had just diagnosed correctly, and the diagnosis never prints.
        ...(f.copyState.match(/../g) ?? []).map((s, i) => [`B${i + 1}`, s, f.shown[i]]),
        ...f.epilogueState.split("|").map((s, i) => [
          // `i - 2` because the two epilogue blocks come first: the third
          // element is the cell whose `data-mesh-phase` is 0, so this names the
          // cell a reader can find in the DOM rather than its neighbour.
          i === 0 ? "headline" : i === 1 ? "cta" : `phase ${i - 2}`,
          s,
          f.epilogueShown[i],
        ]),
      ];
      for (const [what, mark, opacity] of marks) {
        checked++;
        const live = mark === "--";
        const painted = opacity > VISIBLE;
        if (live !== painted && Math.abs(opacity - VISIBLE) > ROUNDING) {
          wrong.push(
            `  ${name} p=${f.p.toFixed(4)} ${what}: opacity ${opacity.toFixed(4)} but ` +
              `${live ? "in" : "OUT of"} the accessibility tree (${mark})`
          );
        }
        // Half-marked is its own failure: `inert` without `aria-hidden` leaves
        // the block announced but unreachable, which is worse than either.
        if (mark !== "--" && mark !== "hi") {
          wrong.push(`  ${name} p=${f.p.toFixed(4)} ${what}: half-marked (${mark})`);
        }
      }
    }
  }
  console.log(
    `hidden state: ${checked} block states checked against their own rendered ` +
      `opacity, ${epiloguePositions} of the sampled positions inside the epilogue`
  );
  if (!epiloguePositions) {
    console.log("NO EPILOGUE POSITIONS SAMPLED — the rule is unproven where it used to fail.");
    process.exitCode = 1;
  }
  if (wrong.length) {
    console.log(`${wrong.length} BLOCKS MARKED AGAINST WHAT IS PAINTED:`);
    for (const l of wrong.slice(0, 20)) console.log(l);
    process.exitCode = 1;
  }
}

console.log(`sampled ${n} positions x ${Object.keys(react.frames[0].vars).length} custom properties`);
console.log(`compared ${varCmp} custom-property values + ${n * SCALAR_FIELDS.length} other fields`);
console.log(`compared ${cardCmp} card class/body values across ${NODE_IDS.length} cards`);
console.log(`compared ${labelCmp} edge-label states across ${EDGE_IDS.length} edges (visibility exact, geometry max deviation ${maxLabelDelta.toFixed(4)} px, tolerance ${LABEL_TOLERANCE})`);
console.log(`compared ${pathCmp} edge-path coordinates, max deviation ${maxPathDelta} px (tolerance ${PATH_TOLERANCE})`);
// A throwing driver must not be able to pass a script whose exit code is its
// verdict. These were previously printed and then ignored.
if (react.errors.length) {
  console.log(`react console/page errors:  ${react.errors.length}\n  ${react.errors.join("\n  ")}`);
  process.exitCode = 1;
}
if (stat.errors.length) {
  console.log(`static console/page errors: ${stat.errors.length}\n  ${stat.errors.join("\n  ")}`);
  process.exitCode = 1;
}
if (!diffs.length) {
  console.log("\nIDENTICAL — no differing value at any sampled position.");
} else {
  console.log(`\n${diffs.length} DIFFERENCES:`);
  for (const d of diffs.slice(0, 80)) console.log("  " + d);
  if (diffs.length > 80) console.log(`  ... and ${diffs.length - 80} more`);
  process.exitCode = 1;
}
