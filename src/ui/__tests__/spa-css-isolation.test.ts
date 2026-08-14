// The dashboard's stylesheet must contain nothing that exists only because of
// the scroll demo.
//
// WHY THIS IS A TEST AND NOT A CODE REVIEW HABIT. Tailwind v4's automatic
// source detection is rooted at the Vite root (src/ui) and extracts utility
// candidates from ANY text it scans — including prose in comments. Before
// app/spa.css the demo was contributing 79 rules and 6.2 kB to a build that
// never renders one of them, and THREE of those rules came from ordinary
// English words written in comments, twice in comments explaining this exact
// hazard. Four recurrences, three of them from prose. Discipline demonstrably
// does not hold here, so the invariant is asserted instead.
//
// WHAT IT ACTUALLY CHECKS, and why it is not a committed snapshot. A frozen
// rule list would change on every legitimate dashboard edit, which trains
// people to regenerate it without reading — and a regenerated baseline absorbs
// the leak it was meant to catch. So the demo-only surface is recomputed from
// source on every run: tokens that appear under demo/ and nowhere else in
// src/ui cannot legitimately appear in the dashboard's CSS, because the
// dashboard's build does not scan demo/. If the exclusion in app/spa.css is
// removed or defeated by a new import path, they do.
//
// MOVING the exclusion is a different failure and this check cannot see it:
// relocated into app/globals.css it still keeps the dashboard clean, while the
// demo's own entry silently loses its classes — the regression app/spa.css was
// written to document. The second assertion below covers that case, by holding
// app/globals.css free of source directives entirely.
//
// It builds the dashboard, which no other test does — that is deliberate.
// `npx tsc --noEmit` proves it type-checks and nothing proved it still
// produced a correct stylesheet.
import { describe, it, expect } from "vitest";
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

const UI = path.resolve(__dirname, "..");
const DEMO = path.join(UI, "demo");

/** Directories that are build output or vendored, never authored sources. */
const IGNORED = new Set(["node_modules", "dist", "dist-static", "generated", ".git", "public"]);
const TEXT = /\.(ts|tsx|js|jsx|mjs|cjs|css|html|json|md)$/;

function walk(dir: string, out: string[] = []): string[] {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    if (IGNORED.has(e.name)) continue;
    const p = path.join(dir, e.name);
    if (e.isDirectory()) walk(p, out);
    else if (TEXT.test(e.name)) out.push(p);
  }
  return out;
}

/**
 * Tailwind-ish candidate tokens. This does not have to match Tailwind's
 * extractor exactly — it only has to be a superset of the class names that
 * could leak, so that "appears in demo/ only" is a safe over-approximation.
 */
function tokens(file: string): Set<string> {
  const text = fs.readFileSync(file, "utf8");
  const out = new Set<string>();
  // The trailing group must be able to END on the closing bracket: an earlier
  // version required one more character after it, so a bracketed class was
  // never captured whole and that set came out almost empty.
  for (const m of text.matchAll(/[a-zA-Z][a-zA-Z0-9:_./-]*(?:\[[^\]\s"'`]+\][a-zA-Z0-9:_./-]*)?/g)) {
    out.add(m[0]);
  }
  return out;
}

/** Selector to bare class: strips the leading dot, any variant suffix, and
 *  CSS escaping. (No example spelled out — see the note in the assertion.) */
function classOf(selector: string): string | null {
  const m = /^\.((?:\\.|[^\s.:,>+~[\]()])*(?:\\\[(?:\\.|[^\]])*\\\])?(?:\\.|[^\s.:,>+~()])*)/.exec(
    selector.trim()
  );
  if (!m) return null;
  return m[1].replace(/\\(.)/g, "$1");
}

/**
 * Bodies of the named `@layer` blocks, brace-matched. Tailwind emits everything
 * it GENERATES inside these; anything outside came from a stylesheet someone
 * imported, which is not this test's business.
 */
function layerBlocks(css: string, names: string[]): string[] {
  const out: string[] = [];
  const re = new RegExp(`@layer\\s+(${names.join("|")})\\s*\\{`, "g");
  for (const m of css.matchAll(re)) {
    let depth = 1;
    let i = m.index! + m[0].length;
    const start = i;
    while (i < css.length && depth > 0) {
      if (css[i] === "{") depth++;
      else if (css[i] === "}") depth--;
      i++;
    }
    out.push(css.slice(start, i - 1));
  }
  return out;
}

describe("dashboard stylesheet isolation (#1519)", () => {
  it("contains no utility that exists only because of demo/", () => {
    // Build fresh: the point is to test what ships, not a stale artifact.
    // stdio is piped so a green run stays quiet, which means a BROKEN build
    // would otherwise surface as a bare "Command failed" with the compiler's
    // diagnosis stranded on the error object. Put it back in the message.
    try {
      execFileSync("npx", ["vite", "build"], { cwd: UI, stdio: "pipe" });
    } catch (err) {
      const e = err as { stdout?: Buffer; stderr?: Buffer; message?: string };
      throw new Error(
        `the dashboard build failed, so this check never ran.\n${e.message ?? ""}\n` +
          `--- stderr ---\n${e.stderr?.toString() ?? ""}\n` +
          `--- stdout ---\n${e.stdout?.toString() ?? ""}`
      );
    }

    const cssFiles = fs
      .readdirSync(path.join(UI, "dist", "assets"))
      .filter((f) => f.endsWith(".css"))
      .map((f) => path.join(UI, "dist", "assets", f));
    expect(
      cssFiles,
      "expected exactly one stylesheet from the dashboard build. None means the " +
        "build emitted no CSS at all; more than one means it started splitting CSS " +
        "per chunk, and this check would then be reading only whichever came first."
    ).toHaveLength(1);
    const css = fs.readFileSync(cssFiles[0], "utf8");

    const demoTokens = new Set<string>();
    for (const f of walk(DEMO)) for (const t of tokens(f)) demoTokens.add(t);

    const appTokens = new Set<string>();
    for (const f of walk(UI)) {
      if (f.startsWith(DEMO + path.sep)) continue;
      for (const t of tokens(f)) appTokens.add(t);
    }

    // ARBITRARY-VALUE CLASSES ONLY — the bracketed kind Tailwind generates
    // from a literal length or colour written inside square brackets.
    //
    // NO CLASS NAME IS SPELLED OUT ANYWHERE IN THIS FILE, and that is not
    // fastidiousness. This file lives under src/ui, so the dashboard build
    // scans it: an example written here would be emitted into the very
    // stylesheet this test guards. Worse, it would also land in the set of
    // "app tokens" below, laundering that class out of demo-only status and
    // blinding the check to a real leak of it. Writing four examples in this
    // comment added four rules and hid them from the assertion in one move.
    //
    // A short unbracketed token is ambiguous. One of them names a visual
    // effect that the dashboard emits as a bare utility, and NOT because any
    // dashboard source uses it as a class: it is the tail of a dotted name
    // inside a string literal in another test here. Tailwind's extractor
    // splits that on the dot and takes the tail as a candidate, while this
    // tokenizer keeps the dotted name whole — so a naive "demo token absent
    // from app sources" set flags it as a leak when it is in the no-demo
    // baseline. (Verified against the extractor directly, because the obvious
    // explanation is wrong: the longer hyphenated class of the same family
    // that the dashboard does use yields no such candidate.)
    // Loosening to substring matching fixes that and
    // creates the opposite problem: another of them is a prefix of a hyphenated
    // class used all over the dashboard, so a genuine leak of its bare form —
    // one of the four that actually happened — would stop being detected.
    //
    // Bracketed classes have no such ambiguity: they are long, unique, and
    // cannot appear as a fragment of another class. They are also guaranteed
    // to be present in any real regression, because the failure mode is the
    // exclusion not applying AT ALL, which brings the whole demo surface with
    // it — 79 rules, roughly a quarter of them bracketed. This is a sharp
    // detector for a blunt failure, chosen over a blunt detector that cries
    // wolf and gets deleted.
    const demoOnly = new Set(
      [...demoTokens].filter((t) => t.includes("[") && t.includes("]") && !appTokens.has(t))
    );
    // If this ever empties, the assertion below passes forever and means
    // nothing. Fail loudly instead.
    expect(
      demoOnly.size,
      "no demo-only arbitrary-value classes found — this check has gone vacuous"
    ).toBeGreaterThan(10);

    // ONLY inside Tailwind's own layers. Vendored stylesheets (React Flow's,
    // which the dashboard imports) sit outside them and legitimately define
    // classes that the demo also references but no dashboard source spells
    // out — those are not leaks, and counting them made this fail on
    // react-flow__viewport and friends.
    //
    // THE SELECTOR SCAN IS NARROWER THAN IT LOOKS, in three further ways. A
    // rule that is the FIRST one inside a nested at-rule is preceded by `{`
    // and never matches (about a hundred of them in the current output —
    // mostly feature queries, where the same rule also appears unwrapped, but
    // also the width and pointer blocks, where it does not appear anywhere
    // else). The selector body excludes commas, so an arbitrary value
    // containing one is never seen — one rule today. And classOf reads nothing
    // that does not begin with a dot, so the wrapped forms Tailwind emits for
    // some variants are skipped — around a hundred today. All three are
    // acceptable HERE because the failure being caught is the whole demo
    // surface arriving at once, not one rule; widening the pattern to close
    // them would buy precision this check does not need at the price of false
    // positives, which is how a guard gets deleted.
    const layers = layerBlocks(css, ["utilities", "components"]);
    // The other half of the vacuity guard, and the one that was missing: the
    // demoOnly set above protects the SOURCE side of the comparison, nothing
    // protected this side. If Tailwind stops emitting named layers, a minifier
    // flattens them, or the pipeline moves to another CSS transformer, these
    // bodies come back empty, every assertion below passes, and a completely
    // polluted stylesheet raises no signal at all.
    expect(
      layers.join("").length,
      "no @layer utilities/components content found in the built stylesheet — " +
        "the leak scan below had nothing to read, so its result means nothing. " +
        "Check how the build now emits generated utilities."
    ).toBeGreaterThan(0);

    const leaked: string[] = [];
    for (const layer of layers) {
      for (const m of layer.matchAll(/(^|[},])\s*(\.[^{},]+)\{/g)) {
        for (const sel of m[2].split(",")) {
          const cls = classOf(sel);
          if (cls && demoOnly.has(cls)) leaked.push(cls);
        }
      }
    }

    expect(
      [...new Set(leaked)].sort(),
      "utilities that only exist in demo/ reached the dashboard stylesheet. " +
        "The `@source not` exclusion in app/spa.css is not taking effect — check that " +
        "src/main.tsx still imports app/spa.css and that nothing else pulls " +
        "app/globals.css into the dashboard build."
    ).toEqual([]);
  }, 120_000);

  // The design's load-bearing property, which nothing else enforces. Both
  // builds compile app/globals.css, so a source directive placed there reaches
  // the demo's entry too and strips it of its own classes — the check above
  // still passes, because the dashboard itself comes out clean. Keeping this
  // free of them is what makes "the demo bundle is unchanged BY CONSTRUCTION"
  // true rather than something to re-verify by hand.
  it("keeps source directives out of app/globals.css", () => {
    const globals = fs.readFileSync(path.join(UI, "app", "globals.css"), "utf8");
    const found = [...globals.matchAll(/^[^\n]*@source[^\n]*$/gm)].map((m) => m[0].trim());
    expect(
      found,
      "app/globals.css now carries a source directive. It is the scroll demo's " +
        "own stylesheet entry as well as the dashboard's, so this also applies to " +
        "the demo's build and can silently strip its classes. Put dashboard-only " +
        "directives in app/spa.css, which the demo does not import."
    ).toEqual([]);
  });
});
