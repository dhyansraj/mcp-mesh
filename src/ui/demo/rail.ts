// WHO IS ON SCREEN, AS AN ASSISTIVE TOOL SEES IT — shared by both renderers.
//
// THE RAIL IS THE PROSE COLUMN AND THE EPILOGUE, and that is all: fourteen beat
// blocks stacked in one position, the epilogue's headline, its six lifecycle
// cells and the closing call to action. All of them are in the document the
// whole time, at any scroll position nearly all of them are at zero opacity,
// and a zero-opacity block must not be announced by a screen reader, reachable
// by Tab, or matched by find-in-page.
//
// WHAT IS DELIBERATELY NOT IN IT, since "everything with words in it" would be
// the wrong reading of the list above: the agent cards, which carry a name, a
// capability line and a runtime badge each and are driven to zero by their own
// --n{i}-o and by --graph for the whole epilogue; and the chapter rail's five
// labels, which go with --rail. Both are graph furniture rather than reading
// matter, both are marked by nothing today, and extending this to them is a
// separate question about what the section's reading order should be — not
// something to slip in behind a helper that says "every block".
//
// THE RULE IS THE COMPOSITED OPACITY, and nothing else. It used to be `lead` —
// the index of the beat whose title is current — which was right for the
// topology arc and wrong on both sides of it:
//
//   `lead` freezes at the last beat for the whole epilogue while the copy
//   column fades to nothing, so B14's words stayed announced and findable at
//   zero opacity for the ~620vh of the reveal; and
//
//   `lead` says nothing at all about the epilogue's own blocks, so the
//   headline, the six cells and the call to action were never marked at any
//   position — a reader met the entire epilogue throughout the topology arc.
//
// Both are the same defect: a second, weaker answer to a question the frame
// already answers. The numbers that DRAW each block decide whether it is there,
// so there is one answer and it cannot lag the picture.
//
// Deliberately free of React, like timeline.ts, and deliberately not IN
// timeline.ts: everything there is a pure function of scroll position, and this
// touches the document.
import { VISIBLE, beatShown, type CopyFrame } from "./timeline";

/** One block, with the opacity the browser composites for it. */
export interface RailBlock {
  el: HTMLElement;
  /**
   * EFFECTIVE opacity: the block's own custom property times its column's,
   * exactly as the stylesheet multiplies them. The beats read theirs through
   * beatShown, which is where that product is defined.
   */
  opacity: (fr: CopyFrame) => number;
  /** Last state written, so a settled frame does no DOM work. */
  live?: boolean;
}

/**
 * The rail's blocks in `root` — the fourteen beats, the headline, the call to
 * action and the six lifecycle cells, and nothing else (see the note at the top
 * of this file for what is left out and why).
 *
 * Found in whatever arrangement the caller has: the React component renders
 * them and the driver adopts them into a prerendered shell, but both address
 * them through the same attributes.
 *
 * Indices come from the ATTRIBUTES rather than from document order — the
 * opacities are addressed by index, and an ordering assumption is the kind of
 * thing that survives a markup change while quietly meaning something else.
 */
export function collectRail(root: ParentNode): RailBlock[] {
  const out: RailBlock[] = [];
  for (const el of root.querySelectorAll<HTMLElement>('[data-mesh="copy"] > [data-mesh-beat]')) {
    const k = Number(el.dataset.meshBeat);
    if (Number.isInteger(k)) out.push({ el, opacity: (fr) => beatShown(fr, k) });
  }
  const reveal = root.querySelector<HTMLElement>('[data-mesh="reveal"]');
  if (reveal) out.push({ el: reveal, opacity: (fr) => fr.reveal.reveal });
  const cta = root.querySelector<HTMLElement>('[data-mesh="cta"]');
  if (cta) out.push({ el: cta, opacity: (fr) => fr.reveal.cta });
  for (const el of root.querySelectorAll<HTMLElement>("[data-mesh-phase]")) {
    const i = Number(el.dataset.meshPhase);
    if (Number.isInteger(i)) out.push({ el, opacity: (fr) => fr.reveal.p[i] ?? 0 });
  }
  return out;
}

/**
 * Bring the hidden state into step with the frame.
 *
 * Called every animation frame, from the same apply that writes the opacities,
 * so the two can never describe different positions. The per-block `live` cache
 * means a settled frame touches no attributes at all — the cost is one
 * evaluation and one comparison per block.
 */
export function applyRailHidden(rail: RailBlock[], fr: CopyFrame): void {
  for (const b of rail) {
    const live = b.opacity(fr) > VISIBLE;
    if (b.live === live) continue;
    b.live = live;
    if (live) {
      b.el.removeAttribute("aria-hidden");
      b.el.removeAttribute("inert");
    } else {
      b.el.setAttribute("aria-hidden", "true");
      b.el.setAttribute("inert", "");
    }
  }
}
