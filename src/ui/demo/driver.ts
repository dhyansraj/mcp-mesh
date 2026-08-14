// THE VANILLA DRIVER — what animates the prerendered markup.
//
// This replaces React, React Flow, dagre and d3 at RUNTIME only. It does not
// replace them as a source of truth: every pixel it moves was positioned by
// React Flow at build time (see emit.tsx), and every number it computes comes
// from timeline.ts, which the React component imports too.
//
// WHAT IT ACTUALLY DOES, and why that is so little:
// the React build already avoided re-rendering on scroll. Per-frame state was
// written as CSS custom properties on the panel and the stable inline styles
// referenced them, so React's only job in the scroll path was flipping `lead`
// 13 times and letting React Flow apply the camera. Those are the only two
// things that had to be reimplemented here:
//
//   setViewport(...)  ->  a transform on .react-flow__viewport (+ the
//                         background pattern, which is a pure function of it)
//   setLead(i)        ->  swap the card bodies
//
// Everything else — the ~80 setProperty calls, the camera maths, the reveal
// windows, the keyboard snapping, the hidden state — is the same code path as
// before.
import {
  BEATS, ACCENT, BUILT_CHAPTERS,
} from "./script";
import {
  clamp, lerp, lerpColor, camFor, LEAD_FLIP, restWidth,
  totalTravel, copyFrameAt,
  SNAP_VH, CHAPTER_VH, CHAPTER_SPAN, TEXT_ENTRY, ACTIVATABLE,
  type CopyFrame,
} from "./timeline";
import { collectRail, applyRailHidden } from "./rail";

export interface Generated {
  shell: string;
  nodeOrder: string[];
  edgeOrder: string[];
  beatToState: number[];
  states: Array<{
    d: Record<string, string>;
    label: Record<string, [number, number]>;
  }>;
  cards: Record<string, { variants: Array<{ cls: string; html: string }>; byBeat: number[] }>;
  /**
   * The fourteen copy blocks, as markup.
   *
   * NOT the shipping path — the docs page serves these as real elements and
   * static.ts moves those into the shell. This is the fallback for a host page
   * that does not carry them — an embedder who copied only the mount div — where
   * the alternative is an empty rail for the length of the section.
   *
   * The equivalence harness used to be the other case and deliberately is not
   * any more: it now refuses to load either bundle without the served copy,
   * because a comparison that quietly ran against this fallback would report
   * IDENTICAL having compared something other than what ships.
   */
  beatCopy: Array<{ html: string }>;
  /** BEATS.length, so static.ts can check what it adopted without importing. */
  beatCount: number;
  edgeStroke: string[][];
}

const N = BEATS.length;

/** Background dot pattern — gap and size as passed to <Background> in Stage. */
const BG_GAP = 22;
const BG_SIZE = 1;

/**
 * Take over the prerendered markup.
 *
 * Returns false, having changed NOTHING, if the shell it was handed is not the
 * one it was built for. The caller has already replaced the host page's markup
 * by then, so a silent bail-out would leave ~2205vh of reserved height with no
 * prose in it — see the restore path in static.ts.
 */
export function start(root: HTMLElement, G: Generated): boolean {
  const q = <T extends Element>(sel: string) => root.querySelector<T>(sel);

  const section = q<HTMLElement>('[data-mesh="section"]');
  const panel = q<HTMLElement>(".demo-panel");
  const wrap = q<HTMLElement>(".demo-graph");
  const viewport = q<HTMLElement>(".react-flow__viewport");
  const bgPattern = q<SVGPatternElement>(".react-flow__background pattern");
  const bgDot = q<SVGCircleElement>(".react-flow__background circle");
  if (!section || !panel || !wrap || !viewport) return false;

  const reduced = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;

  // ---- element handles, resolved once ------------------------------------
  const cardEl = new Map<string, HTMLElement>();
  for (const id of G.nodeOrder) {
    const node = root.querySelector<HTMLElement>(
      `.react-flow__node[data-id="${CSS.escape(id)}"]`
    );
    // The card is the middle child: <Handle/><div class="card"/><Handle/>.
    const card = node?.children[1] as HTMLElement | undefined;
    if (card) cardEl.set(id, card);
  }

  interface EdgeEls {
    path: SVGPathElement | null;
    interaction: SVGPathElement | null;
    wrapper: SVGGElement | null;
    text: SVGTextElement | null;
    rect: SVGRectElement | null;
    bbox: { w: number; h: number };
  }
  const edgeEl = new Map<string, EdgeEls>();
  for (const id of G.edgeOrder) {
    const g = root.querySelector<SVGGElement>(
      `.react-flow__edge[data-id="${CSS.escape(id)}"]`
    );
    edgeEl.set(id, {
      path: g?.querySelector(".react-flow__edge-path") ?? null,
      interaction: g?.querySelector(".react-flow__edge-interaction") ?? null,
      wrapper: g?.querySelector(".react-flow__edge-textwrapper") ?? null,
      text: g?.querySelector(".react-flow__edge-text") ?? null,
      rect: g?.querySelector(".react-flow__edge-textbg") ?? null,
      bbox: { w: 0, h: 0 },
    });
  }

  // ---- copy blocks --------------------------------------------------------
  // Fourteen elements that the SERVED DOCUMENT provided and static.ts moved
  // into the shell's empty stack before this ran. Nothing here creates or
  // rewrites copy; it only sets an opacity per block.
  const copyEl = Array.from(
    root.querySelectorAll<HTMLElement>('[data-mesh="copy"] > [data-mesh-beat]')
  );
  // An empty or short stack is a REFUSAL, not something to animate around. The
  // driver addresses blocks by index and reserves ~2205vh of pinned scroll for
  // them, so carrying on here is how the section comes to be twenty-two screens
  // of nothing. Checked before anything has been written, so the caller can put
  // the served copy back.
  if (copyEl.length !== N) return false;
  // ...and every block that carries words, beats and epilogue alike, paired
  // with the opacity that decides whether it is in the accessibility tree. See
  // rail.ts for why that is the opacity and not the current beat index.
  const rail = collectRail(root);
  const frame: CopyFrame = copyFrameAt(0, false);

  const railEl = Array.from({ length: BUILT_CHAPTERS }, (_, c) =>
    q<HTMLElement>(`[data-mesh-rail="${c}"]`)
  );
  const railFill = Array.from({ length: BUILT_CHAPTERS }, (_, c) =>
    railEl[c]?.previousElementSibling?.firstElementChild as HTMLElement | undefined
  );

  // ---- edge labels --------------------------------------------------------
  // React Flow measures its own label text with getBBox and centres the group
  // on the path midpoint. A server render has no layout, so the markup ships
  // with a 0x0 box and visibility:hidden. Measuring here rather than baking
  // captured numbers keeps this self-correcting: change a capability name and
  // the label re-centres on the next load, with no re-capture.
  let labelsMeasured = false;
  const measureLabels = () => {
    if (labelsMeasured) return;
    let any = false;
    for (const els of edgeEl.values()) {
      if (!els.text || !els.wrapper) continue;
      const b = els.text.getBBox();
      if (!b.width) continue;
      any = true;
      els.bbox = { w: b.width, h: b.height };
      // labelBgPadding={[4, 2]}, matching <Stage>'s edge definitions.
      els.rect?.setAttribute("width", String(b.width + 8));
      els.rect?.setAttribute("height", String(b.height + 4));
      els.text.setAttribute("y", String(b.height / 2));
      els.wrapper.setAttribute("visibility", "visible");
    }
    // Fonts can still be loading on the first frame; retry until one measures.
    if (!any) return;
    labelsMeasured = true;
    // FORCE A GEOMETRY RE-APPLY. applyGeometry centres each label wrapper on
    // `els.bbox`, and it has already run for this state — with an empty box,
    // because measurement had not succeeded yet. Its `state === geomState`
    // early return then means the wrapper keeps a transform computed from 0x0,
    // leaving every label offset by half its own box until the state genuinely
    // changes at B14. Invalidating geomState here is the whole fix: the guard
    // above stays, so this still runs exactly once.
    geomState = -1;
    applyGeometry(G.beatToState[Math.max(lead, 0)]);
  };

  // ---- geometry state (card boxes change at B14, so the paths do too) -----
  let geomState = -1;
  const applyGeometry = (state: number) => {
    if (state === geomState) return;
    geomState = state;
    const g = G.states[state];
    for (const [id, els] of edgeEl) {
      const d = g.d[id];
      if (d) {
        els.path?.setAttribute("d", d);
        els.interaction?.setAttribute("d", d);
      }
      const xy = g.label[id];
      if (xy && els.wrapper) {
        els.wrapper.setAttribute(
          "transform",
          `translate(${xy[0] - els.bbox.w / 2} ${xy[1] - els.bbox.h / 2})`
        );
      }
    }
  };

  // ---- lead flip ----------------------------------------------------------
  // The card ELEMENT is kept and only its class and body are rewritten: the
  // card carries `transition-all duration-300`, so its border colour is meant
  // to ease from green to red when a provider dies. Replacing the element
  // would make that snap.
  let lead = -1;
  const applyLead = (i: number) => {
    if (i === lead) return;
    lead = i;
    for (const [id, el] of cardEl) {
      const t = G.cards[id];
      const v = t.variants[t.byBeat[i]];
      if (el.className !== v.cls) el.className = v.cls;
      if (el.innerHTML !== v.html) el.innerHTML = v.html;
    }
    // NO HIDDEN STATE IS SET HERE, deliberately. `lead` is which beat's title
    // is current, which is not the same question as which blocks are on screen
    // — it says nothing about the epilogue and it freezes at B14 while the copy
    // column fades away. That is decided per frame from the opacities; see
    // rail.ts.
    const chapter = BEATS[i].chapter;
    for (let c = 0; c < BUILT_CHAPTERS; c++) {
      const active = chapter === c;
      const el = railEl[c];
      if (el) {
        el.className = `mt-2 font-mono text-[10px] tracking-[0.18em] ${
          active ? "demo-accent" : "text-slate-500"
        }`;
      }
      const fill = railFill[c];
      // Only the chapter being played takes the live accent. --accent goes red
      // for "It dies.", and letting completed chapters follow it read as
      // "everything is broken" — the opposite of the point.
      if (fill) fill.style.background = active ? "" : ACCENT;
    }
    applyGeometry(G.beatToState[i]);
  };

  // ---- the per-frame apply ------------------------------------------------
  const apply = () => {
    const r = section.getBoundingClientRect();
    // Below MIN_WIDTH the section is display:none, so it has no height.
    if (r.height === 0) return;
    const travel = r.height - window.innerHeight;
    const progress = travel <= 0 ? 0 : clamp(-r.top / travel, 0, 1);

    // Every number this frame is drawn from, derived once by the module the
    // React component and the overlap sweep also call. `fIn` holds back
    // everything the next beat ADDS until its title is actually on screen;
    // withdrawal still tracks `f`, since a card leaving early contradicts
    // nothing and the stagger makes each reveal read as caused by its heading
    // rather than anticipating it.
    const { raw, i0, i1, f, fIn } = copyFrameAt(progress * totalTravel, reduced, frame);

    const a = BEATS[i0];
    const b = BEATS[i1];
    const s = panel.style;

    for (let i = 0; i < G.nodeOrder.length; i++) {
      const id = G.nodeOrder[i];
      const from = a.nodes[id] ?? 0;
      const to = b.nodes[id] ?? 0;
      s.setProperty(`--n${i}-o`, lerp(from, to, to > from ? fIn : f).toFixed(3));
    }
    for (let i = 0; i < G.edgeOrder.length; i++) {
      const id = G.edgeOrder[i];
      const from = a.edges[id] ?? 0;
      const to = b.edges[id] ?? 0;
      const o = lerp(from, to, to > from ? fIn : f);
      s.setProperty(`--e${i}-o`, o.toFixed(3));
      s.setProperty(`--e${i}-l`, (o > 0.55 ? o : 0).toFixed(3));
      // Weight is an assertion like colour is, so it takes the same gate — and
      // on its own direction, not the opacity's: B5 thickens an edge whose
      // opacity does not change at all across the boundary.
      const emA = a.emphasis?.includes(id) ? 1 : 0;
      const emB = b.emphasis?.includes(id) ? 1 : 0;
      const em = lerp(emA, emB, emB > emA ? fIn : f);
      s.setProperty(`--e${i}-w`, (restWidth(id) * (1 + 0.5 * em)).toFixed(2));
      // Colour is an assertion too — an edge going grey is how "the provider
      // died" is drawn — so it lands with the heading, not before it.
      s.setProperty(`--e${i}-c`, lerpColor(G.edgeStroke[i0][i], G.edgeStroke[i1][i], fIn));
    }

    s.setProperty("--accent", lerpColor(a.accent, b.accent, f));
    s.setProperty("--pulse", lerp(a.pulse ?? 0, b.pulse ?? 0, f).toFixed(3));
    s.setProperty("--gutter", lerp(a.fullBleed ? 0 : 1, b.fullBleed ? 0 : 1, f).toFixed(3));
    for (let c = 0; c < BUILT_CHAPTERS; c++) {
      const { first, count } = CHAPTER_SPAN[c];
      s.setProperty(`--ch${c}-f`, `${(clamp((raw - first) / count, 0, 1) * 100).toFixed(2)}%`);
    }

    // ---- beat copy --------------------------------------------------------
    // The fourteen blocks share one position, so which of them is on screen is
    // decided here and nowhere else — see beatCopyOpacity for why the two
    // windows meet instead of overlapping.
    for (let k = 0; k < N; k++) s.setProperty(`--b${k}`, frame.copy[k].toFixed(3));

    // ---- the reveal -------------------------------------------------------
    const rf = frame.reveal;
    s.setProperty("--graph", rf.graph.toFixed(3));
    s.setProperty("--rail", rf.graph.toFixed(3));
    s.setProperty("--beat", rf.beat.toFixed(3));
    s.setProperty("--reveal", rf.reveal.toFixed(3));
    for (let i = 0; i < rf.p.length; i++) {
      s.setProperty(`--p${i}`, rf.p[i].toFixed(3));
    }
    s.setProperty("--cta", rf.cta.toFixed(3));

    // ---- camera -----------------------------------------------------------
    const W = wrap.clientWidth;
    const H = wrap.clientHeight;
    if (W && H) {
      const ca = camFor(i0, W, H);
      const cb = camFor(i1, W, H);
      // Geometric zoom interpolation — a linear ramp reads as a lurch.
      const zoom = Math.exp(lerp(Math.log(ca.zoom), Math.log(cb.zoom), f));
      const cx = lerp(ca.cx, cb.cx, f);
      const cy = lerp(ca.cy, cb.cy, f);
      const ax = lerp(ca.ax, cb.ax, f);
      const x = ax - cx * zoom;
      // 0.60 rather than 0.50: the title scrim eats the top ~220px and the
      // chapter rail the bottom ~60px, so the usable band sits low of centre.
      const y = H * 0.6 - cy * zoom;
      // This is precisely what React Flow's setViewport writes.
      viewport.style.transform = `translate(${x}px,${y}px) scale(${zoom})`;
      // ...and this is what <Background> recomputes from it. Both are pure
      // functions of the transform, so the dots stay locked to the graph.
      if (bgPattern && bgDot) {
        const gap = BG_GAP * zoom || 1;
        const size = BG_SIZE * zoom;
        bgPattern.setAttribute("x", String(x % gap));
        bgPattern.setAttribute("y", String(y % gap));
        bgPattern.setAttribute("width", String(gap));
        bgPattern.setAttribute("height", String(gap));
        bgPattern.setAttribute("patternTransform", `translate(-${1 + gap / 2},-${1 + gap / 2})`);
        bgDot.setAttribute("cx", String(size / 2));
        bgDot.setAttribute("cy", String(size / 2));
        bgDot.setAttribute("r", String(size / 2));
      }
    }

    applyLead(f >= LEAD_FLIP ? i1 : i0);
    // WHAT A SCREEN READER AND FIND-IN-PAGE SEE OF THE PROSE, from the same
    // frame that just drew it. Every block the rail governs and the frame is
    // not painting — thirteen beats during the arc, all fourteen plus most of
    // the epilogue after it — leaves the accessibility tree. The graph is not
    // in that set: the cards and the chapter labels also reach zero opacity and
    // are marked by nothing, which rail.ts says plainly and on purpose. The
    // served document carries neither attribute on anything and reads as the
    // whole story, which is what a crawler and a reader without JavaScript get.
    applyRailHidden(rail, frame);
    measureLabels();
  };

  // ---- scroll pump --------------------------------------------------------
  let raf = 0;
  let lastY = -1;
  const tick = () => {
    raf = 0;
    const y = window.scrollY;
    if (y === lastY) return;
    lastY = y;
    apply();
  };
  const onScroll = () => {
    if (!raf) raf = requestAnimationFrame(tick);
  };
  const onResize = () => {
    lastY = -1;
    apply();
  };
  apply();
  // The first apply runs before webfonts settle, so the label boxes measured
  // then are the fallback font's. Re-measure once the real faces are in;
  // measureLabels re-applies the geometry itself when it succeeds.
  //
  // This is a REFINEMENT, not the correctness guarantee — it used to be both,
  // which hid the bug above. Optional chaining means the whole callback is
  // skipped where document.fonts does not exist, so label centring must not
  // depend on it.
  document.fonts?.ready.then(() => {
    labelsMeasured = false;
    measureLabels();
  });
  window.addEventListener("scroll", onScroll, { passive: true });
  window.addEventListener("resize", onResize);

  // ---- keyboard stepping --------------------------------------------------
  // The driver is a pure function of scroll position, so the only safe way to
  // move a keyboard user is to move the SCROLL POSITION onto a composed frame.
  // Nothing here advances the animation independently of the page.
  const p = { raf: 0, idle: 0, last: -1 };
  let target: number | null = null;
  const pump = () => {
    p.raf = 0;
    const y = window.scrollY;
    apply();
    if (y === p.last) p.idle += 1;
    else {
      p.idle = 0;
      p.last = y;
    }
    if (p.idle < 10) p.raf = requestAnimationFrame(pump);
    else target = null;
  };
  const startPump = () => {
    p.idle = 0;
    p.last = -1;
    if (!p.raf) p.raf = requestAnimationFrame(pump);
  };

  window.addEventListener("keydown", (e: KeyboardEvent) => {
    if (e.defaultPrevented || e.metaKey || e.ctrlKey || e.altKey) return;
    const el = e.target as HTMLElement | null;
    if (el && (el.isContentEditable || TEXT_ENTRY.has(el.tagName))) return;
    const space = e.key === " " || e.key === "Spacebar";
    if (el && ACTIVATABLE.has(el.tagName) && (space || e.key === "Enter")) return;

    let dir = 0;
    let byChapter = false;
    if (e.key === "PageDown" || e.key === "ArrowDown") {
      dir = 1;
      byChapter = e.shiftKey;
    } else if (e.key === "PageUp" || e.key === "ArrowUp") {
      dir = -1;
      byChapter = e.shiftKey;
    } else if (space) {
      // Shift-Space stays "previous beat": it is the universal page-up gesture
      // and predates the Shift modifier used above.
      dir = e.shiftKey ? -1 : 1;
    }
    if (!dir) return;

    // Auto-repeat paces itself to the scrolls rather than to the key-repeat
    // rate. Distinct presses are never throttled — they retarget immediately.
    if (e.repeat && target !== null) {
      e.preventDefault();
      return;
    }
    const H = window.innerHeight;
    const r = section.getBoundingClientRect();
    // Only take over while the panel is actually pinned.
    if (r.top > 0 || r.bottom < H) return;

    const sectionTop = window.scrollY + r.top;
    const stops = (byChapter ? CHAPTER_VH : SNAP_VH).map((vh) => sectionTop + vh * H);
    // Step from the target already in flight, not from the position we happen
    // to be passing through.
    const from = target ?? window.scrollY;
    const EPS = 8;
    const next =
      dir > 0
        ? stops.find((y) => y > from + EPS)
        : [...stops].reverse().find((y) => y < from - EPS);
    if (next === undefined) return;

    e.preventDefault();
    target = next;
    window.scrollTo({ top: next, behavior: reduced ? "auto" : "smooth" });
    startPump();
  });
  const clearTarget = () => {
    target = null;
  };
  window.addEventListener("wheel", clearTarget, { passive: true });
  window.addEventListener("touchstart", clearTarget, { passive: true });
  return true;
}
