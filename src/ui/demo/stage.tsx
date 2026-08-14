// THROWAWAY PROTOTYPE — scroll-scrubbed, scripted mesh topology arc.
// The COMPONENT only. Two entries mount it and each owns its own CSS:
//   scroll.tsx — dev page, unscoped, `npm run dev` → /demo/scroll.html
//   embed.tsx  — IIFE bundle for the docs site, CSS scoped to #mesh-scroll
// Not routed in the SPA and not an input to `vite build`.
//
// RENDER ARCHITECTURE
// The nodes and edges arrays are built ONCE with stable object identity.
// Pushing fresh arrays through React on every scroll frame made React Flow
// unmount and re-create every edge <g> (measured: 364 adds / 364 removes over
// 30 frames), which is what made the edges blink. Per-frame visual state is
// therefore written as CSS custom properties on the panel element, which the
// stable inline styles reference — no React render, no reconciliation.
// The only React state in the scroll path is `lead` (the beat whose node
// badges/title are authoritative), which changes 13 times in the whole page.
import { useEffect, useMemo, useRef, useState } from "react";
import {
  ReactFlow,
  Background,
  BackgroundVariant,
  Position,
  type Node,
  type Edge,
  type ReactFlowInstance,
} from "@xyflow/react";

import { buildGraphFromAgents } from "@/lib/topology";
import { AgentNode } from "@/components/topology/AgentNode";
import {
  BEATS,
  MAXIMAL,
  MAXIMAL_REPLICAS,
  buildWorld,
  ACCENT,
  CHAPTERS,
  BUILT_CHAPTERS,
  TOTAL_VH,
  HEADER_VH,
  SPACER_VH,
  REVEAL,
  REVEAL_VH,
  HOTEL,
  WEATHER,
  WEATHER_GROUP,
} from "./script";
import {
  clamp, smoothstep, lerp, lerpColor, POS, camFor, GUTTER, LEAD_FLIP,
  restWidth, totalTravel, rawFromVh, R_CLEAR, R_BEAT_OUT, R_HEAD, R_PHASE_0,
  R_PHASE_STEP, R_PHASE_SPAN, R_OUT, R_CTA, SNAP_VH, CHAPTER_VH, CHAPTER_SPAN,
  TEXT_ENTRY, ACTIVATABLE,
} from "./timeline";

const nodeTypes = { agentNode: AgentNode };

const N = BEATS.length;

// Two builds: the single-instance world (which supplies the real node data and
// edge colours) and the replica-collapsed world, whose weather node/edges carry
// different ids (`group:weather-agent`). Both variants live in the stable graph
// at once; per-beat opacity picks which one is on screen. The group node
// inherits the single node's canonical position so the swap has no motion.
const canonical = buildGraphFromAgents(MAXIMAL);
const canonicalGrouped = buildGraphFromAgents(MAXIMAL_REPLICAS);

const unionEdges = new Map<string, Edge>();
for (const e of [...canonical.edges, ...canonicalGrouped.edges]) {
  if (!unionEdges.has(e.id)) unionEdges.set(e.id, e);
}

const NODE_IDS = [...canonical.nodes.map((n) => n.id), WEATHER_GROUP];
const EDGE_IDS = [...unionEdges.keys()];

/** Per-beat build: real builder → real edge colours, real node data. */
const BUILT = BEATS.map((b) => {
  const g = buildGraphFromAgents(buildWorld(b.world));
  return {
    nodeData: new Map(g.nodes.map((n) => [n.id, n.data])),
    edgeStroke: new Map(
      g.edges.map((e) => [e.id, (e.style?.stroke as string) ?? "#6b7280"])
    ),
  };
});

// A node id only exists in the beats that render its variant, so keep a
// fallback so the off-variant still has renderable data at opacity 0.
const FALLBACK_DATA = new Map<string, Record<string, unknown>>();
for (const built of BUILT) {
  for (const [id, data] of built.nodeData) {
    if (!FALLBACK_DATA.has(id)) FALLBACK_DATA.set(id, data);
  }
}
const dataFor = (id: string, lead: number) =>
  BUILT[lead].nodeData.get(id) ?? FALLBACK_DATA.get(id)!;
const strokeFor = (id: string, beat: number) =>
  BUILT[beat].edgeStroke.get(id) ?? "#6b7280";
const nodeVar = (i: number) => `--n${i}`;
const edgeVar = (i: number) => `--e${i}`;

/** Built once. Only `data` is ever replaced (on beat change). */
// Fallback of 0, and it is not cosmetic: these styles are attached before the
// driver's first apply, and `var(--n0-o)` with no fallback is invalid at
// computed-value time, so opacity falls back to 1. That paints one frame of
// the ENTIRE topology at once — every node, every beat's worth of graph —
// which is the exact opposite of B1's single card. Same reasoning as the
// stroke-width fallback below.
const NODE_STYLE = new Map(
  NODE_IDS.map((id, i) => [id, { opacity: `var(${nodeVar(i)}-o, 0)` } as const])
);

/** Resting stroke width per edge — tier-2 tool edges are drawn lighter. */
const EDGE_W = EDGE_IDS.map(restWidth);

const STABLE_EDGES: Edge[] = [...unionEdges.values()].map((e, i) => {
  const isTier2 = e.id.startsWith("llm|");
  return {
    ...e,
    animated: false,
    style: {
      // Fallbacks throughout: before the first apply an unresolved var() would
      // leave stroke at its inherited value (black) and opacity at 1.
      stroke: `var(${edgeVar(i)}-c, transparent)`,
      // Driver-written so a beat can single an edge out by weight as well as
      // by opacity; the fallback is the resting width.
      strokeWidth: `var(${edgeVar(i)}-w, ${EDGE_W[i]})`,
      strokeDasharray: isTier2 ? "6 5" : undefined,
      opacity: `var(${edgeVar(i)}-o, 0)`,
    },
    labelStyle: { fill: "#94a3b8", fontSize: 10, opacity: `var(${edgeVar(i)}-l, 0)` },
    labelBgStyle: { fill: "#0a1628", fillOpacity: `var(${edgeVar(i)}-l, 0)` },
    labelBgPadding: [4, 2] as [number, number],
  };
});

// Node objects are cached by (id, visible-data signature). React Flow remounts
// EVERY edge whenever the nodes array changes, so at a beat boundary we hand
// back the exact same object for any node whose card didn't actually change —
// and the same array when none of them did.
// Signature of everything AgentNode actually renders that can vary — group
// cards expose a different shape from single cards.
const nodeSig = (data: Record<string, unknown>): string => {
  if (data.kind === "group") {
    const inst = data.instances as Array<{ id: string; runtime?: string }>;
    return `g|${data.status}|${data.dependencies_resolved}/${data.total_dependencies}|${inst.length}|${inst[0]?.runtime}`;
  }
  const a = data.agent as {
    status: string;
    runtime?: string;
    dependencies_resolved: number;
    total_dependencies: number;
    a2a_producer?: boolean;
    a2a_consumer?: boolean;
    capabilities?: Array<{ task?: boolean }>;
  };
  const badges = `${a.a2a_producer ? "P" : ""}${a.a2a_consumer ? "C" : ""}${
    a.capabilities?.some((c) => c.task) ? "J" : ""
  }`;
  return `${a.status}|${a.runtime}|${a.dependencies_resolved}/${a.total_dependencies}|${badges}`;
};

// Cards that B11's spotlight ring applies to (--pulse is only non-zero there).
const PULSED = new Set([HOTEL, WEATHER, WEATHER_GROUP]);

/**
 * Horizontal centre of a card's handles, in card-local coordinates.
 *
 * NOT `w / 2`. Chrome lays out in LayoutUnits of 1/64px and React Flow reads
 * the HANDLE ELEMENT's own bounding rect rather than deriving x from the node
 * width, so the handle's `left: 50%` is resolved by layout and TRUNCATED to
 * 1/64px before React Flow ever sees it. getComputedStyle also hands back a
 * rounded decimal (244.781 for a true 244.78125), and halving the rounded
 * number loses the bit that decides the truncation — hence snap first, then
 * halve, then floor.
 *
 * This is why every integer-width card matched byte-exact while fractional
 * ones drifted, always downward, always by 0.01 at 2dp. Verified against all
 * six distinct widths in the fixture: 36/36 edge paths in both states.
 */
const LAYOUT_UNIT = 64;
const snapLU = (n: number) => Math.round(n * LAYOUT_UNIT) / LAYOUT_UNIT;
const handleCentreX = (w: number) =>
  Math.floor((snapLU(w) / 2) * LAYOUT_UNIT) / LAYOUT_UNIT;

/**
 * Build-time only: measured card boxes, so the SAME component can be rendered
 * to static markup in Node with real edges.
 *
 * React Flow will not lay out an edge until both endpoints are "initialized",
 * which in a browser means a ResizeObserver has measured the card and a
 * MutationObserver has measured its handles. Neither exists under
 * renderToStaticMarkup, so a server render emits nodes and NO edges. v12
 * provides the escape hatch used here: a node carrying `measured` plus an
 * explicit `handles` array skips measurement entirely (see `parseHandles` and
 * `toHandleBounds` in @xyflow/system).
 *
 * Left unset on the browser path, where measurement is real and authoritative.
 * That is the point: this adds a build-time input and changes nothing at
 * runtime, so the React bundle and the prerendered bundle render the same
 * component from the same beat data.
 */
export interface SsrBox {
  w: number;
  h: number;
}
let SSR_GEOMETRY: Map<string, SsrBox> | null = null;
export function setSsrGeometry(g: Map<string, SsrBox> | null) {
  SSR_GEOMETRY = g;
  NODE_CACHE.clear();
  lastNodes = [];
}

/**
 * Handle box, solved backwards from React Flow's own connection-point maths
 * (`getHandlePosition`): a Bottom handle connects at `x + width/2, y + height`
 * and a Top handle at `x + width/2, y`. The captured offsets are relative to
 * the CARD box, so the handle rect is placed such that those two expressions
 * reproduce them exactly. Only edge geometry consumes these — the visible
 * handle dots are rendered by AgentNode's own <Handle> elements.
 */
const HANDLE_SIZE = 8;
/** Connection point relative to the card box, captured from the running build. */
const HANDLE_OFFSET = { source: 4, target: -4 };

const NODE_CACHE = new Map<string, Node>();
function nodeObj(id: string, lead: number): Node {
  const data = dataFor(id, lead);
  const key = `${id}|${nodeSig(data)}`;
  const hit = NODE_CACHE.get(key);
  if (hit) return hit;
  const n: Node = {
    id,
    type: "agentNode",
    position: POS.get(id)!,
    data,
    draggable: false,
    selectable: false,
    className: PULSED.has(id) ? "demo-pulse" : undefined,
    style: NODE_STYLE.get(id),
  };
  const box = SSR_GEOMETRY?.get(id);
  if (box) {
    const cx = handleCentreX(box.w);
    n.measured = { width: box.w, height: box.h };
    n.handles = [
      {
        type: "target",
        position: Position.Top,
        x: cx - HANDLE_SIZE / 2,
        y: HANDLE_OFFSET.target,
        width: HANDLE_SIZE,
        height: HANDLE_SIZE,
      },
      {
        type: "source",
        position: Position.Bottom,
        x: cx - HANDLE_SIZE / 2,
        y: box.h + HANDLE_OFFSET.source - HANDLE_SIZE,
        width: HANDLE_SIZE,
        height: HANDLE_SIZE,
      },
    ];
  }
  NODE_CACHE.set(key, n);
  return n;
}

let lastNodes: Node[] = [];
function nodesForBeat(lead: number): Node[] {
  const next = NODE_IDS.map((id) => nodeObj(id, lead));
  if (
    lastNodes.length === next.length &&
    next.every((n, i) => n === lastNodes[i])
  ) {
    return lastNodes;
  }
  lastNodes = next;
  return next;
}

/**
 * Inline markup shared by every string in script.ts: `backticks` are code,
 * *asterisks* are an annotation. Two contexts use it with different scales —
 * the mono sub-line (where code is the base voice and the annotation steps
 * out of it into sans) and the sans description (where it is the reverse).
 */
interface Inline {
  code: string;
  em: string;
}
export const SUB_INLINE: Inline = {
  code: "text-slate-300",
  em: "font-sans not-italic text-slate-500",
};
// Mono runs optically larger than sans at the same px, so code spans sit a
// notch under the 15px body they are set in.
export const DESC_INLINE: Inline = {
  code: "font-mono text-[13.5px] text-slate-300",
  em: "italic text-slate-300",
};

export function inline(text: string, s: Inline) {
  return text.split(/(`[^`]+`|\*[^*]+\*)/g).map((part, i) => {
    if (part.length > 2 && part.startsWith("`") && part.endsWith("`")) {
      return (
        <code key={i} className={s.code}>
          {part.slice(1, -1)}
        </code>
      );
    }
    if (part.length > 2 && part.startsWith("*") && part.endsWith("*")) {
      return (
        <em key={i} className={s.em}>
          {part.slice(1, -1)}
        </em>
      );
    }
    return part;
  });
}

/** The CTA is set in the accent, so code spans inherit rather than recolour. */
const CTA_INLINE: Inline = { code: "", em: "font-sans not-italic" };

/**
 * Two registers for the reveal grid, switchable at runtime so they can be
 * compared on the same frame rather than from memory:
 *
 *   open   — bare label over body copy. The shipped arrangement.
 *   framed — the same six cells as bordered rectangles with the label knocked
 *            into the top border, the schematic convention. Deliberately has
 *            no glow, no scanlines and no second accent: if the register needs
 *            effects to work, it has not worked.
 */
const GRID_VARIANTS = ["framed", "open"] as const;
type GridVariant = (typeof GRID_VARIANTS)[number];
const VARIANT_KEY = "demo-grid-variant";

// Built once — the driver writes the variables these reference every frame, so
// nothing here re-renders. Same trick as the node and edge styles.
const GRAPH_STYLE = { opacity: "var(--graph, 1)" } as const;
const BEAT_COPY_STYLE = { opacity: "var(--beat, 1)" } as const;
const REVEAL_COPY_STYLE = { opacity: "var(--reveal, 0)" } as const;
const CTA_STYLE = { opacity: "var(--cta, 0)" } as const;
const RAIL_STYLE = { opacity: "var(--rail, 1)" } as const;

// ---------------------------------------------------------------------------
// Stage
// ---------------------------------------------------------------------------
export interface StageProps {
  /** Render the grid-variant switch. Dev page always; embed only on ?mesh-grid. */
  devTools?: boolean;
  /**
   * Render the internal 70vh hero above B1. OFF by default — the docs page has
   * its own hero and a second one read as a duplicate. The dev page turns it
   * on so the standalone reading still opens on something.
   */
  showHeader?: boolean;
}

export function Stage({ devTools = false, showHeader = false }: StageProps) {
  const sectionRef = useRef<HTMLDivElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const instRef = useRef<ReactFlowInstance | null>(null);

  const [reduced] = useState(
    () => window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false
  );
  const [lead, setLead] = useState(0);
  const leadRef = useRef(0);

  // A/B for the reveal grid's register — see GRID_VARIANTS. Switching is
  // instant and touches nothing in the scroll path, so the same frame can be
  // flipped back and forth; the choice survives a reload within the session.
  // Guarded: this runs on the SHIPPED path, not just the dev one — `devTools`
  // gates the toggle UI, not this state. sessionStorage throws SecurityError
  // when storage is blocked or the page is in a sandboxed iframe, and an
  // exception in a useState initializer unmounts the whole section. A
  // dev-only affordance must not be able to take the piece down.
  const [variant, setVariant] = useState<GridVariant>(() => {
    try {
      return (sessionStorage.getItem(VARIANT_KEY) as GridVariant | null) ?? "framed";
    } catch {
      return "framed";
    }
  });
  const framed = variant === "framed";
  const pickVariant = (v: GridVariant) => {
    try {
      sessionStorage.setItem(VARIANT_KEY, v);
    } catch {
      /* storage blocked — the choice simply does not persist */
    }
    setVariant(v);
  };

  const nodes = useMemo(() => nodesForBeat(lead), [lead]);

  // Single imperative apply — CSS vars + camera. No React render.
  const applyRef = useRef<((force?: boolean) => void) | null>(null);
  applyRef.current = (force = false) => {
    const section = sectionRef.current;
    const panel = panelRef.current;
    const wrap = wrapRef.current;
    if (!section || !panel || !wrap) return;

    const r = section.getBoundingClientRect();
    // Below MIN_WIDTH the section is display:none, so it has no height. Once
    // the bundle has mounted it stays mounted through a resize, and without
    // this the driver would keep doing ~80 setProperty calls per scroll frame
    // for an element that is not on the page.
    if (r.height === 0) return;
    const travel = r.height - window.innerHeight;
    const progress = travel <= 0 ? 0 : clamp(-r.top / travel, 0, 1);

    // The pinned section carries the topology AND the epilogue. Beat maths
    // clamps at TOTAL_VH, so the graph simply holds the final beat while the
    // reveal plays over it.
    const vhPos = progress * totalTravel;
    const raw = rawFromVh(Math.min(vhPos, TOTAL_VH));
    const rev = clamp((vhPos - TOTAL_VH) / REVEAL_VH, 0, 1);
    const pos = raw - 0.5;
    const i0 = clamp(Math.floor(pos), 0, N - 1);
    const i1 = Math.min(i0 + 1, N - 1);
    const t = clamp(pos - i0, 0, 1);
    const f = reduced ? (t >= 0.5 ? 1 : 0) : smoothstep(t);
    // Everything the next beat ADDS is held back until its title is actually
    // on screen. Reveals used to start at f = 0 while the title only flipped
    // at LEAD_FLIP, so the picture ran ahead of the words — B1's "Right now
    // there is one agent" was measured with four other cards already at
    // 0.15-0.31. Withdrawal still tracks f: a card leaving early contradicts
    // nothing, and the stagger makes each reveal read as caused by its
    // heading rather than anticipating it.
    const fIn = smoothstep(clamp((f - LEAD_FLIP) / (1 - LEAD_FLIP), 0, 1));

    const a = BEATS[i0];
    const b = BEATS[i1];
    const s = panel.style;

    for (let i = 0; i < NODE_IDS.length; i++) {
      const id = NODE_IDS[i];
      const from = a.nodes[id] ?? 0;
      const to = b.nodes[id] ?? 0;
      s.setProperty(`${nodeVar(i)}-o`, lerp(from, to, to > from ? fIn : f).toFixed(3));
    }
    for (let i = 0; i < EDGE_IDS.length; i++) {
      const id = EDGE_IDS[i];
      const from = a.edges[id] ?? 0;
      const to = b.edges[id] ?? 0;
      const o = lerp(from, to, to > from ? fIn : f);
      s.setProperty(`${edgeVar(i)}-o`, o.toFixed(3));
      s.setProperty(`${edgeVar(i)}-l`, (o > 0.55 ? o : 0).toFixed(3));
      // Weight is an assertion like colour is, so it takes the same gate —
      // and on its own direction, not the opacity's: B5 thickens an edge whose
      // opacity does not change at all across the boundary.
      const emA = a.emphasis?.includes(id) ? 1 : 0;
      const emB = b.emphasis?.includes(id) ? 1 : 0;
      const em = lerp(emA, emB, emB > emA ? fIn : f);
      s.setProperty(`${edgeVar(i)}-w`, (EDGE_W[i] * (1 + 0.5 * em)).toFixed(2));
      // Colour is an assertion too — an edge going grey is how "the provider
      // died" is drawn — so it lands with the heading, not before it.
      s.setProperty(`${edgeVar(i)}-c`, lerpColor(strokeFor(id, i0), strokeFor(id, i1), fIn));
    }

    s.setProperty("--accent", lerpColor(a.accent, b.accent, f));
    s.setProperty("--pulse", lerp(a.pulse ?? 0, b.pulse ?? 0, f).toFixed(3));
    // Mask over the reserved column, released in step with the camera so B13
    // reads as one move rather than a mask cut plus a pan.
    s.setProperty("--gutter", lerp(a.fullBleed ? 0 : 1, b.fullBleed ? 0 : 1, f).toFixed(3));
    for (let c = 0; c < BUILT_CHAPTERS; c++) {
      const { first, count } = CHAPTER_SPAN[c];
      s.setProperty(`--ch${c}-f`, `${(clamp((raw - first) / count, 0, 1) * 100).toFixed(2)}%`);
    }

    // ---- the reveal -------------------------------------------------------
    // Same idea as the beats: every value is written as a CSS variable and no
    // React state is involved. Under reduced motion the ramps step rather than
    // slide, matching how `f` already behaves.
    const ease = (x: number) =>
      reduced ? (x >= 0.5 ? 1 : 0) : smoothstep(clamp(x, 0, 1));
    const window_ = (from: number, to: number) => ease((rev - from) / (to - from));

    const cleared = ease(rev / R_CLEAR);
    // The graph and the rail leave together — the rail is the graph's index,
    // and keeping it while the topology dissolves would promise a sixth
    // chapter that never comes.
    s.setProperty("--graph", (1 - cleared).toFixed(3));
    s.setProperty("--rail", (1 - cleared).toFixed(3));

    const headIn = window_(R_HEAD[0], R_HEAD[1]);
    // --beat is driven by its OWN window, not by 1 - headIn. Tying them made
    // the two blocks a crossfade in one position: at headIn = 0.5 both the
    // beat copy and the headline sat at 0.5 and overlaid each other.
    const beatOut = window_(R_BEAT_OUT[0], R_BEAT_OUT[1]);
    // Everything the epilogue puts on screen leaves again for the CTA. Kept as
    // its own factor rather than folded into --reveal: the beat copy hides on
    // the way IN and must not come back when the headline hides on the way out.
    const gone = 1 - window_(R_OUT[0], R_OUT[1]);
    s.setProperty("--beat", (1 - beatOut).toFixed(3));
    s.setProperty("--reveal", (headIn * gone).toFixed(3));
    for (let i = 0; i < REVEAL.phases.length; i++) {
      const from = R_PHASE_0 + i * R_PHASE_STEP;
      s.setProperty(`--p${i}`, (window_(from, from + R_PHASE_SPAN) * gone).toFixed(3));
    }
    s.setProperty("--cta", window_(R_CTA[0], R_CTA[1]).toFixed(3));

    // Camera
    const W = wrap.clientWidth;
    const H = wrap.clientHeight;
    if (W && H && instRef.current) {
      const ca = camFor(i0, W, H);
      const cb = camFor(i1, W, H);
      // Geometric zoom interpolation — a linear ramp reads as a lurch.
      const zoom = Math.exp(lerp(Math.log(ca.zoom), Math.log(cb.zoom), f));
      const cx = lerp(ca.cx, cb.cx, f);
      const cy = lerp(ca.cy, cb.cy, f);
      // Anchor is interpolated too, so B12 -> B13 slides the frame back to the
      // middle of the panel as it zooms out instead of jumping there.
      const ax = lerp(ca.ax, cb.ax, f);
      // 0.60 rather than 0.50: the title scrim eats the top ~220px and the
      // chapter rail the bottom ~60px, so the usable band sits low of centre.
      instRef.current.setViewport(
        { x: ax - cx * zoom, y: H * 0.6 - cy * zoom, zoom },
        { duration: 0 }
      );
    }

    const nextLead = f >= LEAD_FLIP ? i1 : i0;
    if (nextLead !== leadRef.current || force) {
      leadRef.current = nextLead;
      setLead(nextLead);
    }
  };

  useEffect(() => {
    let raf = 0;
    let lastY = -1;
    const tick = () => {
      raf = 0;
      const y = window.scrollY;
      if (y === lastY) return;
      lastY = y;
      applyRef.current?.();
    };
    const onScroll = () => {
      if (!raf) raf = requestAnimationFrame(tick);
    };
    const onResize = () => {
      lastY = -1;
      applyRef.current?.();
    };
    applyRef.current?.();
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onResize);
    return () => {
      if (raf) cancelAnimationFrame(raf);
      window.removeEventListener("scroll", onScroll);
      window.removeEventListener("resize", onResize);
    };
  }, [reduced]);

  // ---- keyboard stepping --------------------------------------------------
  // The driver is a pure function of scroll position, so the only safe way to
  // move a keyboard user is to move the SCROLL POSITION onto a composed frame.
  // Nothing here advances the animation independently of the page.
  const pumpRef = useRef({ raf: 0, idle: 0, last: -1 });
  const targetRef = useRef<number | null>(null);

  useEffect(() => {
    // Captured once: the object identity never changes, only its fields, so
    // the cleanup below cancels the frame this effect actually started.
    const p = pumpRef.current;
    // Drive the frame from rAF for the duration of a programmatic scroll, so
    // the animation advances deterministically instead of waiting on scroll
    // events to be delivered and coalesced. Applying twice for one position is
    // idempotent, so the ordinary `scroll` listener above simply becomes
    // redundant while this runs.
    //
    // HISTORICAL NOTE, because this comment used to say something false: a
    // programmatic scroll was once reported to move the page while the
    // animation stayed frozen, and an earlier version of this comment blamed
    // it on a harness writing document.body.scrollTop against a documentElement
    // scroller. That was wrong. The cause was a BACKGROUNDED TAB — a hidden
    // tab suspends requestAnimationFrame (and IntersectionObserver, and
    // painting, and key delivery), so the driver's tick never ran even though
    // scrollY was updating correctly. document.scrollingElement really is
    // documentElement here and window.scrollTo really does feed the listener.
    // There is no page defect to route around, and no reason to avoid
    // scrollTo. The pump stays because it is the right way to make the
    // keyboard path independent of event timing — not because scroll events
    // are unreliable.
    const pump = () => {
      p.raf = 0;
      const y = window.scrollY;
      applyRef.current?.();
      if (y === p.last) p.idle += 1;
      else {
        p.idle = 0;
        p.last = y;
      }
      // Keep going ~10 frames past the last movement so the settled frame is
      // definitely applied, then release the pending target.
      if (p.idle < 10) p.raf = requestAnimationFrame(pump);
      else targetRef.current = null;
    };
    const startPump = () => {
      p.idle = 0;
      p.last = -1;
      if (!p.raf) p.raf = requestAnimationFrame(pump);
    };

    const onKey = (e: KeyboardEvent) => {
      if (e.defaultPrevented || e.metaKey || e.ctrlKey || e.altKey) return;
      const t = e.target as HTMLElement | null;
      if (t && (t.isContentEditable || TEXT_ENTRY.has(t.tagName))) return;
      const space = e.key === " " || e.key === "Spacebar";
      // A focused control keeps its own activation keys — this is what stops
      // Space on the variant toggle from being hijacked into a scroll.
      if (t && ACTIVATABLE.has(t.tagName) && (space || e.key === "Enter")) return;

      let dir = 0;
      let byChapter = false;
      if (e.key === "PageDown" || e.key === "ArrowDown") {
        dir = 1;
        byChapter = e.shiftKey;
      } else if (e.key === "PageUp" || e.key === "ArrowUp") {
        dir = -1;
        byChapter = e.shiftKey;
      } else if (space) {
        // Shift-Space stays "previous beat". It is the universal page-up
        // gesture and predates the Shift modifier used above; overloading it
        // into "next chapter" would break a convention to gain a duplicate of
        // Shift-PageDown.
        dir = e.shiftKey ? -1 : 1;
      }
      // Home/End and everything else keep the browser's behaviour.
      if (!dir) return;

      const section = sectionRef.current;
      if (!section) return;
      // Auto-repeat paces itself to the scrolls rather than to the key-repeat
      // rate: held down, that advances a beat per completed scroll (~3/sec)
      // instead of consuming all 22 targets in under a second. Distinct
      // presses are never throttled — they retarget immediately.
      if (e.repeat && targetRef.current !== null) {
        e.preventDefault();
        return;
      }
      const H = window.innerHeight;
      const r = section.getBoundingClientRect();
      // Only take over while the panel is actually pinned. Above and below the
      // section the page scrolls normally.
      if (r.top > 0 || r.bottom < H) return;

      const sectionTop = window.scrollY + r.top;
      const stops = (byChapter ? CHAPTER_VH : SNAP_VH).map((vh) => sectionTop + vh * H);
      // Step from the target already in flight, not from the position we
      // happen to be passing through: three quick presses should advance three
      // beats, and each scrollTo replaces the previous one rather than adding
      // to it, so nothing can stack into a runaway.
      const from = targetRef.current ?? window.scrollY;
      const EPS = 8;
      const next =
        dir > 0
          ? stops.find((y) => y > from + EPS)
          : [...stops].reverse().find((y) => y < from - EPS);
      // Past the last stop in either direction: let the page leave the section.
      if (next === undefined) return;

      e.preventDefault();
      targetRef.current = next;
      window.scrollTo({ top: next, behavior: reduced ? "auto" : "smooth" });
      startPump();
    };

    // Any real scrolling input invalidates the pending target.
    const onUserScroll = () => {
      targetRef.current = null;
    };

    window.addEventListener("keydown", onKey);
    window.addEventListener("wheel", onUserScroll, { passive: true });
    window.addEventListener("touchstart", onUserScroll, { passive: true });
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("wheel", onUserScroll);
      window.removeEventListener("touchstart", onUserScroll);
      if (p.raf) cancelAnimationFrame(p.raf);
      p.raf = 0;
    };
  }, [reduced]);

  const beat = BEATS[lead];

  return (
    <div className="min-h-screen bg-[#050c17] text-slate-200">
      {/* Dev affordance, deliberately not part of the design: no accent
          colour, no animation, and it sits outside the panel so it can never
          be mistaken for chrome. Clicking re-renders the grid only — `lead`
          is untouched, so the node array keeps its identity and the scroll
          position does not move. Never rendered on the shipped path: `framed`
          is the decided variant and the switch is a comparison tool. */}
      {devTools && (
      <div className="fixed right-4 top-4 z-50 flex items-center gap-2 rounded border border-slate-700 bg-[#050c17]/90 px-3 py-1.5 font-mono text-[11px] text-slate-600">
        <span>grid:</span>
        {GRID_VARIANTS.map((v, i) => (
          <span key={v} className="flex items-center gap-2">
            {i > 0 && <span className="text-slate-700">|</span>}
            <button
              type="button"
              // A mouse click leaves focus on the button, and Space on a
              // focused button activates it — so the next Space meant as
              // "scroll" would flip the grid instead. event.detail is 0 for
              // keyboard activation and >0 for a real pointer click, so this
              // releases focus for mouse users without stealing it from
              // keyboard users mid-tab-order.
              onClick={(e) => {
                pickVariant(v);
                if (e.detail > 0) e.currentTarget.blur();
              }}
              className={
                v === variant ? "text-slate-200" : "text-slate-600 hover:text-slate-400"
              }
            >
              {v}
            </button>
          </span>
        ))}
      </div>
      )}

      {showHeader && (
      <header
        className="mx-auto flex max-w-3xl flex-col justify-center px-6 text-center"
        style={{ height: `${HEADER_VH}vh` }}
      >
        <p className="font-mono text-[11px] uppercase tracking-[0.4em] text-orange-500">
          MCP MESH
        </p>
        <h1 className="mt-6 text-6xl font-semibold tracking-tight text-white">
          One agent becomes twelve.
        </h1>
        <p className="mt-5 text-lg text-slate-400">
          Keep scrolling. They find each other.
        </p>
        <p className="mt-12 animate-bounce font-mono text-xs text-slate-500">↓</p>
      </header>
      )}

      <div ref={sectionRef} data-mesh="section" style={{ height: `${100 + totalTravel * 100}vh` }}>
        <div className="sticky top-0 h-screen w-full py-6">
          <div
            ref={panelRef}
            className="demo-panel relative mx-auto h-full w-[94vw] overflow-hidden rounded-2xl border border-slate-800 bg-[#0a1628]"
          >
            <div ref={wrapRef} className="demo-graph absolute inset-0" style={GRAPH_STYLE}>
              <ReactFlow
                nodes={nodes}
                edges={STABLE_EDGES}
                nodeTypes={nodeTypes}
                onInit={(inst) => {
                  instRef.current = inst;
                  applyRef.current?.(true);
                }}
                fitView={false}
                minZoom={0.05}
                maxZoom={4}
                nodesDraggable={false}
                nodesConnectable={false}
                elementsSelectable={false}
                panOnDrag={false}
                panOnScroll={false}
                zoomOnScroll={false}
                zoomOnPinch={false}
                zoomOnDoubleClick={false}
                preventScrolling={false}
                // --- keyboard scrolling ------------------------------------
                // nodesFocusable/edgesFocusable default to TRUE in the store
                // and are NOT implied by nodesDraggable/elementsSelectable, so
                // every node and every edge was rendering tabIndex={0} — 33 tab
                // stops inside the sticky panel. Once focus is in there, the
                // nearest scrollable ancestor of the focused element is the
                // .react-flow wrapper (overflow:hidden, but its transformed
                // node layer creates real scrollable overflow), so Page Down
                // scrolled THAT instead of the document — and React Flow's own
                // wrapper onScroll handler snaps it straight back to 0,0
                // ("Undo scroll events, preventing viewport from shifting when
                // nodes outside of it are focused", @xyflow/react
                // dist/esm/index.js:3601). Net effect: the page barely moves.
                nodesFocusable={false}
                edgesFocusable={false}
                disableKeyboardA11y
                // Focusing a node outside the viewport calls setCenter, which
                // would fight the driver's per-frame setViewport. Belt and
                // braces now that nothing is focusable.
                autoPanOnNodeFocus={false}
                // Every *ActivationKeyCode registers a DOCUMENT-level keydown
                // listener that calls preventDefault() when the key matches —
                // and panActivationKeyCode defaults to 'Space'. That killed
                // Space/Shift-Space scrolling across the whole page, not just
                // over the panel. Passing null skips the listener entirely
                // (useKeyPress early-returns on `keyCode !== null`). None of
                // these gestures exist in a display-only graph.
                panActivationKeyCode={null}
                zoomActivationKeyCode={null}
                selectionKeyCode={null}
                multiSelectionKeyCode={null}
                deleteKeyCode={null}
                proOptions={{ hideAttribution: true }}
              >
                <Background variant={BackgroundVariant.Dots} gap={22} size={1} color="#1e3a5f" />
              </ReactFlow>
            </div>

            {/* Mask for the reserved column. Sibling above the canvas with an
                explicit z-index — React Flow's panes make their own stacking
                context — and below the copy, which is z-20 later in the DOM. */}
            <div
              className="demo-gutter pointer-events-none absolute inset-y-0 left-0 z-20"
              style={{ width: `${GUTTER * 100}%` }}
            />

            {/* Six lifecycle phases, across the WHOLE panel. The gutter exists
                to keep the graph out from under the copy; in the reveal there
                is no graph, so holding that line only cost the left third of
                the frame and left an L-shaped void under the headline.
                3 x 2 at full width gives a wider measure than 2 x 3 did at
                two-thirds width, and reading across-then-down still yields the
                canonical Learn -> Develop -> Test -> Deploy -> Secure ->
                Observe order. px-8 is the panel's left margin — the same one
                the accent rule and the chapter rail have used throughout.

                Vertical: the box is inset from the header's baseline by the
                same amount it is inset from the panel floor, so centring
                inside it puts equal air above and below the grid. */}
            <div className="pointer-events-none absolute inset-0 z-10 flex items-center pb-8 pt-[132px]">
              {/* Rows size to their content. A fixed 1fr pitch left a
                  100-150px void under every short cell, which reads as content
                  that failed to load rather than as breathing room.

                  OPEN cells are top-aligned so the accent labels line up
                  across the frame and the length variation hangs below them.
                  FRAMED cells stretch instead: a border makes a ragged bottom
                  edge obvious in a way that bare text does not. */}
              <div
                className={`grid w-full grid-cols-3 gap-x-10 gap-y-12 px-8 ${
                  framed ? "items-stretch" : "items-start"
                }`}
              >
                {REVEAL.phases.map((p, i) => (
                  <div
                    key={p.label}
                    className="demo-phase min-w-0"
                    style={{ ["--p" as string]: `var(--p${i}, 0)` }}
                  >
                    {framed ? (
                      // Label set into the top border with the panel colour
                      // knocked out behind it — the technical-drawing
                      // convention. Nothing else changes: same copy, same
                      // type, same accent, no glow and no second colour.
                      <div className="relative h-full rounded-[2px] border border-slate-700/60 px-6 pb-6 pt-7">
                        <p className="demo-accent absolute -top-[7px] left-5 bg-[#0a1628] px-2 font-mono text-[10px] uppercase leading-[14px] tracking-[0.32em]">
                          <span className="text-slate-600">/</span> {p.label}{" "}
                          <span className="text-slate-600">/</span>
                        </p>
                        <p className="text-[15px] leading-[1.7] text-slate-400">
                          {inline(p.body, DESC_INLINE)}
                        </p>
                      </div>
                    ) : (
                      <>
                        <p className="demo-accent font-mono text-[10px] uppercase tracking-[0.32em]">
                          {p.label}
                        </p>
                        {/* Same 15px as the beat descriptions — it is the same
                            kind of body copy. The cell is 403px at 1440 (57-59
                            characters, untouched by the cap) and 553px at 1920,
                            where the 480px cap holds the measure at ~69 rather
                            than letting it run to 78. */}
                        <p className="mt-2 max-w-[30rem] text-[15px] leading-[1.7] text-slate-400">
                          {inline(p.body, DESC_INLINE)}
                        </p>
                      </>
                    )}
                  </div>
                ))}
              </div>
            </div>

            {/* Copy column — same x, same y, every beat. Width is the gutter
                the camera reserves (see GUTTER), so this never sits on a node.
                The one exception is B14, which goes full-bleed under a title
                that the top scrim already separates from the graph.

                The reveal's header is a sibling below, not a child: it shares
                the x, the rule and the type, but not the 32% ceiling. */}
            <div className="pointer-events-none absolute inset-x-0 top-0 z-20">
              <div className="absolute inset-x-0 top-0 h-56 bg-gradient-to-b from-[#050c17] via-[#050c17]/75 to-transparent" />
              <div className="relative" style={{ width: `${GUTTER * 100}%` }}>
                <div className="flex gap-4 px-8 pt-8" style={BEAT_COPY_STYLE}>
                  <div className="demo-rule mt-1 h-[62px] w-[3px] shrink-0 rounded-full" />
                  <div className="min-w-0">
                    <p
                      data-mesh="chapter"
                      className="demo-accent font-mono text-[10px] uppercase tracking-[0.32em]"
                    >
                      {CHAPTERS[beat.chapter]}
                    </p>
                    <h2
                      key={`t-${lead}`}
                      data-mesh="title"
                      // whitespace-pre-line honours the authored `\n` breaks;
                      // text-balance keeps the rest off ragged single-word
                      // last lines in a 350px column.
                      className="demo-fade mt-2 whitespace-pre-line text-balance text-[30px] font-semibold leading-[1.12] tracking-tight text-white"
                    >
                      {beat.title}
                    </h2>
                    <p
                      key={`s-${lead}`}
                      data-mesh="sub"
                      // break-words is containment, not style: B6's sub is a
                      // JSON literal with no spaces, so without it the line
                      // cannot wrap and overflows the reserved column by 25px
                      // into the graph — which is exactly what the gutter
                      // exists to prevent.
                      className="demo-fade mt-3 whitespace-pre-line text-balance break-words font-mono text-[13px] leading-relaxed text-slate-400"
                    >
                      {inline(beat.sub, SUB_INLINE)}
                    </p>
                    {beat.desc && (
                      <p
                        key={`d-${lead}`}
                        data-mesh="desc"
                        className="demo-fade mt-4 text-[15px] leading-[1.7] text-slate-400"
                      >
                        {inline(beat.desc, DESC_INLINE)}
                      </p>
                    )}
                  </div>
                </div>
              </div>
            </div>

            {/* The epilogue's voice. Same left x, same accent rule, same 30px
                title over a 13px mono sub — every carrier of the identity is
                unchanged. Only the ceiling is: at full width the headline sets
                on one line instead of two, and the grid gets the panel. */}
            <div
              className="pointer-events-none absolute inset-x-0 top-0 z-20 flex gap-4 px-8 pt-8"
              style={REVEAL_COPY_STYLE}
            >
              <div className="demo-rule mt-1 h-[62px] w-[3px] shrink-0 rounded-full" />
              <div className="min-w-0">
                <h2 className="whitespace-pre-line text-balance text-[30px] font-semibold leading-[1.12] tracking-tight text-white">
                  {REVEAL.title}
                </h2>
                <p className="mt-3 whitespace-pre-line break-words font-mono text-[13px] leading-relaxed text-slate-400">
                  {inline(REVEAL.sub, SUB_INLINE)}
                </p>
              </div>
            </div>

            {/* The CTA gets the panel to itself. In the left rail under the
                headline it was the least prominent thing on the busiest frame,
                which is backwards for the only element asking anyone to act.
                Centred, at title scale, after everything else has gone. */}
            <div
              className="pointer-events-none absolute inset-0 z-20 flex flex-col items-center justify-center px-8 text-center"
              style={CTA_STYLE}
            >
              <div className="demo-rule h-[3px] w-14 rounded-full" />
              <h3 className="mt-8 text-[44px] font-semibold leading-[1.1] tracking-tight text-white">
                {REVEAL.cta.title}
              </h3>
              <p className="mt-6 font-mono text-[15px] leading-relaxed text-slate-300">
                {inline(REVEAL.cta.sub, CTA_INLINE)}
              </p>
            </div>

            {/* Chapter rail. Leaves with the graph — it is the topology's
                index, and an epilogue is not a sixth chapter. */}
            <div
              className="pointer-events-none absolute inset-x-0 bottom-0 z-20 bg-gradient-to-t from-[#050c17] via-[#050c17]/80 to-transparent px-8 pb-6 pt-16"
              style={RAIL_STYLE}
            >
              <div className="flex gap-2">
                {CHAPTERS.map((label, c) => {
                  const built = c < BUILT_CHAPTERS;
                  const active = built && beat.chapter === c;
                  return (
                    <div key={label} className="flex-1">
                      <div
                        className="relative h-[3px] w-full overflow-hidden rounded-full"
                        style={
                          built
                            ? { background: "rgba(148,163,184,0.18)" }
                            : { border: "1px dashed rgba(148,163,184,0.25)" }
                        }
                      >
                        {built && (
                          <div
                            className="demo-rail-fill absolute inset-y-0 left-0 rounded-full"
                            style={{
                              width: `var(--ch${c}-f, 0%)`,
                              // Only the chapter being played takes the live
                              // accent. --accent goes red for "It dies.", and
                              // letting completed chapters follow it read as
                              // "everything is broken" — the opposite of the
                              // point, which is that one component failed and
                              // the rest of the mesh carried on.
                              background: active ? undefined : ACCENT,
                            }}
                          />
                        )}
                      </div>
                      <p
                        data-mesh-rail={c}
                        className={`mt-2 font-mono text-[10px] tracking-[0.18em] ${
                          active ? "demo-accent" : built ? "text-slate-500" : "text-slate-700"
                        }`}
                      >
                        {label}
                        {!built && <span className="ml-1 opacity-60">·</span>}
                      </p>
                    </div>
                  );
                })}
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* No footer copy: the reveal ends on the CTA, and repeating it here
          immediately below would undercut it. This is just somewhere for the
          scroll to come to rest after the panel unpins. */}
      <div style={{ height: `${SPACER_VH}vh` }} />
    </div>
  );
}
