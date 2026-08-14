// THE NO-SUPERIMPOSITION SWEEP.
//
// Everything that carries words in the left rail — fourteen beat blocks, the
// epilogue headline, the closing call to action — is rendered in the SAME
// position. Until the copy stack existed that could not go wrong: one beat
// block was in the document at a time, so two of them could not overlap at any
// copy length, whatever the timeline did. That was a structural guarantee.
//
// It is now a timing one, which is exactly the construction that produced the
// collision between B14's copy and the epilogue headline: two blocks in one
// place, crossfaded, four legible lines on screen for two or three notches of
// scroll. That was fixed by SEQUENCING the windows rather than crossfading
// them, and this sweeps every handoff on the page for the same property.
//
// WHAT IS SWEPT: 200,000 evenly spaced positions across the whole pinned
// travel, which is a sample every ~0.0001vh — three orders of magnitude finer
// than a scroll notch, and far finer than one device pixel of scroll. At each
// one, every rail element's EFFECTIVE opacity is computed the way the browser
// composites it (a block's own value times its column's), from the same
// functions the driver and the React component call. Two above the threshold
// at the same position is a failure.
//
// The phase grid is deliberately NOT in the set: it sits in the middle of the
// panel and coexists with the headline by design.
import fs from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

import { BEATS, REVEAL, TOTAL_VH } from "./script";
import {
  LEAD_FLIP, COPY_IN, COPY_OUT, R_CTA, R_OUT, VISIBLE,
  beatCopyOpacity, beatShown, copyFrameAt, totalTravel,
} from "./timeline";
import { applyRailHidden, collectRail } from "./rail";

const N = BEATS.length;

/**
 * Every rail element's effective opacity at one scroll position — THROUGH THE
 * DRIVER'S OWN DERIVATION, not a copy of it.
 *
 * This used to re-derive `raw`, `rev`, `pos`, `i0`, `i1`, `t` and `f` by hand
 * from the same six lines the driver runs, which made the sweep a test of a
 * transcription: change how the driver derives any of them and 200,000 samples
 * would go on passing against the old arithmetic. That is the failure mode the
 * whole shared-timeline arrangement exists to remove, so the sweep calls
 * copyFrameAt exactly as the driver and the React component do.
 *
 * A block's own opacity is multiplied by its column's, which is what
 * compositing does. Omitting the column factor would report the beat copy as
 * present through the whole epilogue, where --beat has already taken it to zero.
 */
function railAt(vhPos: number, reduced: boolean): number[] {
  const fr = copyFrameAt(vhPos, reduced);
  return [
    ...fr.copy.map((_, k) => beatShown(fr, k)),
    fr.reveal.reveal,
    fr.reveal.cta,
  ];
}

const FRAMES = 200_000;

describe("beat copy never superimposes", () => {
  for (const reduced of [false, true]) {
    it(`sweeps ${FRAMES.toLocaleString()} positions (reduced motion: ${reduced})`, () => {
      let worst = 0;
      let worstAt = -1;
      const failures: string[] = [];
      for (let i = 0; i <= FRAMES; i++) {
        const vhPos = (i / FRAMES) * totalTravel;
        const o = railAt(vhPos, reduced);
        let n = 0;
        for (const v of o) if (v > VISIBLE) n++;
        if (n > worst) {
          worst = n;
          worstAt = vhPos;
        }
        if (n > 1 && failures.length < 5) {
          failures.push(
            `vh ${vhPos.toFixed(5)}: ${o
              .map((v, k) => [k, v] as const)
              .filter(([, v]) => v > VISIBLE)
              .map(([k, v]) => `${k === N ? "headline" : k === N + 1 ? "cta" : `B${k + 1}`}=${v.toFixed(4)}`)
              .join(" + ")}`
          );
        }
      }
      expect(failures, failures.join("\n")).toHaveLength(0);
      expect(worst, `worst was ${worst} at vh ${worstAt}`).toBeLessThanOrEqual(1);
    });
  }

  // The property above holds because of one relationship. Asserted separately
  // so that a future edit to the windows fails on the REASON rather than on
  // 200,000 samples that happen to miss the gap.
  it("hands off at a single point, with no shared interval", () => {
    expect(COPY_OUT[1]).toBe(LEAD_FLIP);
    expect(COPY_IN[0]).toBe(LEAD_FLIP);
    expect(COPY_OUT[0]).toBeLessThan(COPY_OUT[1]);
    expect(COPY_IN[0]).toBeLessThan(COPY_IN[1]);
  });

  // The epilogue's own handoff, for the same reason: the headline leaves before
  // the call to action arrives, and it is SEQUENCING that keeps them apart, not
  // the two windows happening to be far enough apart today. Everything the
  // headline drives is multiplied by `gone`, which reaches 0 at R_OUT[1].
  it("empties the frame before the call to action arrives", () => {
    expect(R_OUT[1]).toBeLessThanOrEqual(R_CTA[0]);
    expect(R_OUT[0]).toBeLessThan(R_OUT[1]);
    expect(R_CTA[0]).toBeLessThan(R_CTA[1]);
  });

  // The windows meet rather than overlap, and that is only worth anything if
  // the browser paints them that way. A `transition` on the copy blocks would
  // let the outgoing block's PAINTED opacity lag past the point the incoming
  // one starts rising — superimposition, produced by the stylesheet, which no
  // number above can see. The rule's own comment says so; nothing asserted it.
  //
  // ASSERTED FOR EVERY ELEMENT THE RAIL GOVERNS, not just the beats. rail.ts
  // marks a block from the value written for the current frame, so a
  // transitioned property makes the marking and the picture two different
  // things: a cell can be out of the accessibility tree while still legible for
  // as long as the ease runs. The six lifecycle cells carried a 90ms one, which
  // is why this now sweeps the whole set — and the harness settles for 120ms
  // before it reads, so nothing downstream could have caught it either.
  //
  // Both stylesheets, because either could introduce it: scroll.css styles the
  // animated arrangement and embed.css the served one, and the same elements
  // are in both.
  it("paints every block the rail governs with no transition to lag", () => {
    const sheets = ["scroll.css", "embed.css"].map((f) => ({
      name: f,
      css: fs.readFileSync(path.join(import.meta.dirname, f), "utf8"),
    }));
    const scroll = sheets[0].css;
    for (const [what, re] of [
      ["the copy stack", /\.demo-copy-stack\s*>\s*\.demo-beat\s*\{([^}]*)\}/],
      ["the phase cells", /(?:^|\})\s*\.demo-phase\s*\{([^}]*)\}/m],
    ] as const) {
      const rule = re.exec(scroll);
      expect(rule, `${what}: rule not found in scroll.css`).not.toBeNull();
      expect(rule![1], `${what} must not be transitioned`).not.toMatch(/transition|animation/);
    }
    // ...and nothing anywhere else may reintroduce one on any of them. The
    // handles are the ones collectRail queries by, plus the classes those
    // elements actually carry.
    const RAIL =
      /\.demo-beat|\.demo-phase|data-mesh-beat|data-mesh-phase|data-mesh="reveal"|data-mesh="cta"/;
    for (const { name, css } of sheets) {
      for (const m of css.matchAll(/([^{}]+)\{([^}]*)\}/g)) {
        if (!/transition|animation/.test(m[2])) continue;
        expect(
          m[1],
          `${name}: a transition here would let a block's paint lag past the frame ` +
            `that decides whether it is in the accessibility tree:\n${m[0]}`
        ).not.toMatch(RAIL);
      }
    }
  });

  // The other half of what the copy stack has to be true for: the beats are
  // addressed by index, so the arrays the driver writes and the blocks the
  // document carries have to be the same length.
  it("covers every beat and nothing else", () => {
    const o = beatCopyOpacity(new Array(N).fill(0), 0, 1, 0, false);
    expect(o).toHaveLength(N);
    expect(o[0]).toBe(1);
    expect(o.slice(1).every((v) => v === 0)).toBe(true);
    // The end of the timeline, where both indices collapse onto the last beat
    // and there is no handoff to run.
    const last = beatCopyOpacity(new Array(N).fill(0), N - 1, N - 1, 1, false);
    expect(last[N - 1]).toBe(1);
    expect(last.slice(0, N - 1).every((v) => v === 0)).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// What a screen reader and find-in-page are told, against what is drawn
// ---------------------------------------------------------------------------
// The same set of blocks, asked a different question: not "can two be read at
// once" but "is each one reachable exactly while it is on screen".
//
// THE POSITIONS THAT MATTER ARE THE EPILOGUE'S. The state used to be flipped
// from `lead`, the index of the beat whose title is current, which is right
// through the topology arc and describes nothing after it: `lead` freezes at
// B14 for the whole epilogue while the copy column fades to zero, and it says
// nothing at all about the epilogue's own blocks. So B14 stayed announced and
// findable at zero opacity for ~620vh, and the headline, the six cells and the
// call to action were never marked at any position. Both renderers did this
// identically, so no cross-build comparison could see it — which is why this
// asserts the RULE, and does it where the rule used to be absent.
describe("hidden state tracks what is painted", () => {
  const PHASES = REVEAL.phases.length;

  const build = () => {
    const root = document.createElement("div");
    const stack = document.createElement("div");
    stack.dataset.mesh = "copy";
    for (let i = 0; i < N; i++) {
      const b = document.createElement("div");
      b.dataset.meshBeat = String(i);
      stack.appendChild(b);
    }
    root.appendChild(stack);
    for (const name of ["reveal", "cta"]) {
      const el = document.createElement("div");
      el.dataset.mesh = name;
      root.appendChild(el);
    }
    for (let i = 0; i < PHASES; i++) {
      const el = document.createElement("div");
      el.dataset.meshPhase = String(i);
      root.appendChild(el);
    }
    return root;
  };

  /** Marked live, marked out, or marked half — the third is its own failure. */
  const marking = (el: Element) => {
    const h = el.getAttribute("aria-hidden") === "true";
    const i = el.hasAttribute("inert");
    return h && i ? "out" : !h && !i ? "live" : "half";
  };

  for (const reduced of [false, true]) {
    it(`matches every block's own opacity across the whole travel (reduced motion: ${reduced})`, () => {
      const root = build();
      const rail = collectRail(root);
      expect(rail).toHaveLength(N + 2 + PHASES);

      const beats = Array.from(root.querySelectorAll("[data-mesh-beat]"));
      const head = root.querySelector('[data-mesh="reveal"]')!;
      const cta = root.querySelector('[data-mesh="cta"]')!;
      const phases = Array.from(root.querySelectorAll("[data-mesh-phase]"));

      const bad: string[] = [];
      let epilogue = 0;
      const STEPS = 20_000;
      for (let s = 0; s <= STEPS; s++) {
        const vhPos = (s / STEPS) * totalTravel;
        const fr = copyFrameAt(vhPos, reduced);
        applyRailHidden(rail, fr);

        const want: Array<[Element, number, string]> = [
          ...beats.map((el, k) => [el, beatShown(fr, k), `B${k + 1}`] as [Element, number, string]),
          [head, fr.reveal.reveal, "headline"],
          [cta, fr.reveal.cta, "cta"],
          ...phases.map(
            (el, i) => [el, fr.reveal.p[i], `phase ${i}`] as [Element, number, string]
          ),
        ];
        if (want.slice(N).some(([, o]) => o > VISIBLE)) epilogue++;
        for (const [el, o, what] of want) {
          const got = marking(el);
          const expected = o > VISIBLE ? "live" : "out";
          if (got !== expected && bad.length < 5) {
            bad.push(`vh ${vhPos.toFixed(4)} ${what}: opacity ${o.toFixed(4)}, marked ${got}`);
          }
        }
      }
      expect(bad, bad.join("\n")).toHaveLength(0);
      // The sweep is worthless for this property if it never reached the part
      // of the travel where the property used to be broken.
      expect(epilogue, "no sampled position had the epilogue on screen").toBeGreaterThan(100);
    });
  }

  // The specific frames the previous rule got wrong, named rather than left to
  // a sweep — a regression here should read as what it is.
  it("retires the last beat once the copy column has gone", () => {
    const root = build();
    const rail = collectRail(root);
    const b14 = root.querySelector(`[data-mesh-beat="${N - 1}"]`)!;
    const head = root.querySelector('[data-mesh="reveal"]')!;
    const cta = root.querySelector('[data-mesh="cta"]')!;

    // Settled on the last beat, before the epilogue starts: B14 is the reading.
    applyRailHidden(rail, copyFrameAt(TOTAL_VH, false));
    expect(marking(b14)).toBe("live");

    // Deep in the epilogue, where `lead` still says 13 and the copy column is
    // at zero. B14 must be gone, and only what is drawn may be reachable.
    const end = copyFrameAt(totalTravel, false);
    applyRailHidden(rail, end);
    expect(end.reveal.beat).toBeLessThanOrEqual(VISIBLE);
    expect(marking(b14)).toBe("out");
    expect(marking(head)).toBe("out");
    expect(marking(cta)).toBe("live");
  });

  // ...and the mirror image: through the whole topology arc the epilogue is on
  // screen nowhere, and used to be announced everywhere.
  it("keeps the epilogue out of the reading for the whole topology arc", () => {
    const root = build();
    const rail = collectRail(root);
    const epilogueEls = [
      root.querySelector('[data-mesh="reveal"]')!,
      root.querySelector('[data-mesh="cta"]')!,
      ...Array.from(root.querySelectorAll("[data-mesh-phase]")),
    ];
    for (let s = 0; s <= 500; s++) {
      applyRailHidden(rail, copyFrameAt((s / 500) * TOTAL_VH, false));
      for (const el of epilogueEls) expect(marking(el)).toBe("out");
    }
  });
});
