// PIXEL EQUIVALENCE — the layer the numeric capture cannot reach.
//
//   make docs-scroll-compare              # terminal 1
//   node demo/screenshots.mjs             # terminal 2
//
// equivalence.mjs proves both builds compute the same numbers. It says nothing
// about whether those numbers land on the same pixels: the prerendered markup
// came out of a server render, so a missing class, a dropped attribute or a
// wrapper element that React adds on mount would leave every custom property
// identical and still change the picture.
//
// So this screenshots both builds across the whole travel and diffs them with
// ImageMagick. Output lands in demo/dist/shots/ so any failure can be looked at
// rather than just counted.
//
// THREE METRICS, BECAUSE ONE OF THEM LIES. AE counts every pixel that differs
// by even 1/255, so a uniform rounding difference in how a semi-transparent
// card is composited lights up the card's entire area and reports tens of
// thousands of "differences" that no one can see. AE alone reported 38,638
// differing pixels on a pair of frames that are indistinguishable by eye, and
// whose worst single pixel is 9/255 apart. PAE (worst pixel) and RMSE
// (frame-wide) are what make that judgeable, so all three are printed.
//
// AND RUN THE CONTROL. The React build is NOT pixel-deterministic across runs
// of ITSELF — measured at 5/41 frames differing, one by 9,248 px — because
// live ResizeObserver measurements carry sub-milli-pixel jitter that moves
// antialiasing. Any cross-build number below that floor means nothing. Pass
// --self=react to reproduce the control before trusting a comparison.
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
//   MESH_PLAYWRIGHT=~/.npm/_npx/<hash>/node_modules/ node screenshots.mjs

import { createRequire } from "node:module";
import { execFileSync, spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

const require_ = createRequire(process.env.MESH_PLAYWRIGHT ?? import.meta.url);
const { chromium } = require_("playwright");

const BASE = process.env.MESH_COMPARE_BASE ?? "http://localhost:8899/compare.html";
const OUT = path.join(import.meta.dirname, "dist", "shots");
const VIEWPORT = { width: 1500, height: 900 };

/**
 * Where to look. The settled beat frames are the frames a reader stops on, and
 * the mid-transition samples are where a renderer difference would show up as
 * a element that moved rather than one that is missing. 0.5-steps through the
 * whole travel gives both.
 */
const STOPS = [];
for (let i = 0; i <= 40; i++) STOPS.push(i / 40);

async function shoot(variant, tag = variant) {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: VIEWPORT, deviceScaleFactor: 1 });
  await page.goto(`${BASE}?v=${variant}`, { waitUntil: "load" });
  await page.waitForSelector('#mesh-scroll[data-mesh-scroll-mounted="1"]');
  await page.evaluate(() => document.fonts.ready);
  await page.waitForTimeout(400);

  const geom = await page.evaluate(() => {
    const s = document.querySelector('[data-mesh="section"]').getBoundingClientRect();
    return { top: window.scrollY + s.top, travel: s.height - window.innerHeight };
  });

  const files = [];
  for (let i = 0; i < STOPS.length; i++) {
    await page.evaluate(
      ([y]) => window.scrollTo(0, y),
      [Math.round(geom.top + STOPS[i] * geom.travel)]
    );
    // Let the driver paint, and let the card colour transition (300ms) finish
    // so the two builds are compared at rest rather than mid-ease.
    await page.waitForTimeout(450);
    const f = path.join(OUT, `${tag}-${String(i).padStart(2, "0")}.png`);
    await page.screenshot({ path: f });
    files.push(f);
  }
  await browser.close();
  return files;
}

// PREFLIGHT. Without this the first real failure mode is a silent one: no
// ImageMagick means no comparison, and a harness that cannot compare must say
// so before it spends two minutes taking screenshots.
try {
  execFileSync("compare", ["-version"], { stdio: ["ignore", "pipe", "pipe"] });
} catch (e) {
  console.error(
    e.code === "ENOENT"
      ? "ImageMagick's `compare` is not on PATH. Install it (brew install imagemagick).\n" +
          "This script verifies nothing without it, so it will not pretend to run."
      : `ImageMagick's \`compare\` is present but not runnable: ${e.message}`
  );
  process.exit(2);
}

fs.rmSync(OUT, { recursive: true, force: true });
fs.mkdirSync(OUT, { recursive: true });

// --self=<variant> shoots the SAME bundle twice. That is the control: it
// measures how much this page differs from itself between two runs, which is
// the floor any cross-build number has to clear to mean anything.
const selfArg = process.argv.find((x) => x.startsWith("--self="));
const self = selfArg ? selfArg.slice("--self=".length) : null;
// Named by role so a diff file says which bundle it came from. In control
// mode both runs are the same bundle, so they need distinguishing suffixes.
const a = await shoot(self ?? "react", self ? `${self}-run1` : "react");
const b = await shoot(self ?? "static", self ? `${self}-run2` : "static");
if (self) console.log(`CONTROL: ${self} vs itself\n`);

let worst = 0;
let worstAt = "";
let clean = 0;
const bad = [];
for (let i = 0; i < a.length; i++) {
  const diff = path.join(OUT, `diff-${String(i).padStart(2, "0")}.png`);
  const metric = (m, out) => {
    // spawnSync, not execFileSync: `compare` writes the metric to STDERR in
    // both cases and signals "images differ" with a non-zero exit, so the
    // value has to be read on the success path too. execFileSync only hands
    // back stdout on success, which made an identical pair parse as null —
    // correct by accident under the old `|| 0`, and undetectable when it was
    // not.
    const r = spawnSync("compare", ["-metric", m, a[i], b[i], out ?? "null:"], {
      encoding: "utf8",
    });
    // FAIL LOUD, NOT OPEN. Every branch below used to collapse to 0 — a
    // PERFECT PASS having compared nothing. This is the only layer that checks
    // whether anything painted; it must never report success it did not earn.
    if (r.error) {
      if (r.error.code === "ENOENT") {
        throw new Error(
          "ImageMagick's `compare` is not on PATH. Install it (brew install imagemagick) — " +
            "this script cannot verify anything without it."
        );
      }
      throw new Error(`\`compare\` could not be run: ${r.error.message}`);
    }
    // 0 = identical, 1 = differ. Anything else is a real error: a dimension
    // mismatch, an unreadable file, a permission problem.
    if (r.status !== 0 && r.status !== 1) {
      throw new Error(
        `\`compare -metric ${m}\` failed (status ${r.status}) on ` +
          `${path.basename(a[i])} vs ${path.basename(b[i])}: ${String(r.stderr).trim().slice(0, 200)}`
      );
    }
    // ImageMagick prints `<raw> (<normalized>)` for PAE and RMSE, and a bare
    // integer for AE. The NORMALIZED value is used wherever it exists, which
    // removes the quantum-depth question entirely: an earlier version divided
    // by a hardcoded 65535, which is right for a Q16 build and understates the
    // figure ~256x on Q8 — and that figure is exactly what was used to call
    // the difference imperceptible.
    const text = `${r.stderr ?? ""} ${r.stdout ?? ""}`.trim();
    const first = Number(text.split(/\s+/)[0]);
    // A genuine 0 and a parse failure are NOT the same thing.
    if (!Number.isFinite(first)) {
      throw new Error(
        `could not parse \`compare -metric ${m}\` output for ` +
          `${path.basename(a[i])}: ${JSON.stringify(text.slice(0, 200))}`
      );
    }
    if (m === "AE") return first;
    const norm = /\(([-\d.eE+]+)\)/.exec(text);
    if (!norm || !Number.isFinite(Number(norm[1]))) {
      throw new Error(
        `\`compare -metric ${m}\` gave no normalized value for ${path.basename(a[i])}: ` +
          `${JSON.stringify(text.slice(0, 200))}. Refusing to guess the quantum depth.`
      );
    }
    return Number(norm[1]);
  };
  const px = metric("AE", diff);
  const pae = px ? metric("PAE") : 0;
  const rmse = px ? metric("RMSE") : 0;
  if (px === 0) {
    clean++;
    fs.rmSync(diff, { force: true });
  } else {
    bad.push(
      `  stop ${i} (p=${STOPS[i].toFixed(3)}): ${px} px differ, ` +
        `worst pixel ${(pae * 100).toFixed(2)}%, frame RMSE ${(rmse * 100).toFixed(4)}%  ` +
        `-> ${path.basename(diff)}`
    );
    if (px > worst) {
      worst = px;
      worstAt = `stop ${i}`;
    }
  }
}

const total = VIEWPORT.width * VIEWPORT.height;
console.log(`${a.length} frames compared at ${VIEWPORT.width}x${VIEWPORT.height}`);
console.log(`${clean}/${a.length} pixel-identical`);
if (self && bad.length) {
  console.log("this is the NOISE FLOOR — cross-build differences at or below it are not attributable");
}
if (bad.length) {
  console.log(bad.join("\n"));
  console.log(`worst: ${worst} px at ${worstAt} = ${((worst / total) * 100).toFixed(4)}% of the frame`);
  // In CONTROL mode a difference is the measurement, not a failure — the whole
  // point is to find out how much this page differs from itself. Only a
  // cross-build run has a verdict to fail.
  if (!self) process.exitCode = 1;
}
