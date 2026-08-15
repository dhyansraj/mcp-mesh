// @vitest-environment node
//
// NODE, NOT THE SUITE'S DEFAULT JSDOM. Nothing in this file touches a DOM — it
// shells out to builds, reads files and loads the build configs — and the last
// of those cannot be done under jsdom at all: importing vite pulls in esbuild,
// which refuses to start when `new TextEncoder().encode("") instanceof
// Uint8Array` is false, and jsdom's TextEncoder comes from a different realm so
// it is. The directive has to stay in the first comment of the file, which is
// why it is above the heading rather than beside the test that needs it.
//
// The dashboard has to SHIP the faces its theme names.
//
// WHY THIS EXISTS. app/globals.css has named "Geist" and "Geist Mono" since the
// dashboard was written, and no rule ever declared either one, so every reader
// got whatever the platform substituted — SF on macOS, Segoe on Windows,
// something else on Linux. Nobody noticed for the project's whole life, because
// a missing face has no failure mode: the text still renders, in the wrong
// thing. There is nothing to see in a review diff, nothing in a console, and
// nothing in a build log. Found from outside, while building something that
// inherits the same stack (#1522).
//
// DO NOT REACH FOR document.fonts.check(). It returns TRUE with nothing loaded
// at all, because it answers "can this text be rendered", and fallback counts.
// It was measured returning true against a document whose document.fonts.size
// was 0. Nothing in this file uses it, and nothing added to this file should.
//
// WHAT IS ASSERTED, AND WHY IT CANNOT PASS VACUOUSLY. The required families are
// DERIVED from the built stylesheet rather than written down here: the var
// chain that Tailwind's preflight applies to the document is resolved to a
// concrete stack, and its first non-generic entry is what must have a face.
// So renaming the theme's font moves the requirement with it, and deleting the
// face fails. A hardcoded ["Geist", "Geist Mono"] would keep passing if the
// theme were repointed at a family nothing declares — the exact bug this file
// is named after, one rename later.
//
// AND THE FILES ARE OPENED, not merely mentioned. A stylesheet can carry a
// perfectly formed @font-face whose url() resolves to nothing: Vite warns on an
// unresolvable css url and emits the build anyway. So each src is resolved
// against the emitted asset directory and read, and its woff2 signature is
// checked — "the CSS says woff2" and "there is a woff2 there" are different
// claims and only the second one is worth anything.
//
// It builds, like __tests__/spa-css-isolation.test.ts, and for the same reason:
// nothing else in the suite looks at what actually ships.
//
// WHAT IT DOES NOT REACH. This file builds src/ui/dist and reads src/ui/dist.
// The binary is made of cmd/mcp-mesh-ui/dist, which three separate scripts
// populate by copying the first over the second, so the last links in the chain
// are checked by reading those scripts rather than by opening the binary — see
// the last two tests of the first block.
//
// The blocks after the first are not about fonts, and live here because this
// file already builds and already owns the question of what reaches the binary.
// They are the same class of bug one layer down: dist/ was holding React's
// development bundle and everything was green, and the two configs this file
// does not build are wired by hand and asserted by nothing.
import { describe, it, expect, beforeAll } from "vitest";
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import zlib from "node:zlib";

const UI = path.resolve(__dirname, "..");
const ASSETS = path.join(UI, "dist", "assets");
/** Where the payloads are authored. Neutral ground: the scroll demo reads the
 *  same two files, and neither bundle may reach into the other's directory. */
const FONTS = path.join(UI, "fonts");
/** The notice the licence requires to travel with them. */
const NOTICE = "OFL.txt";
/** The Go file that compiles dist/ into the meshui binary. */
const EMBED_GO = path.resolve(UI, "..", "..", "cmd", "mcp-mesh-ui", "embed.go");
/** React's two builds, as npm installed them. Used to keep the production-build
 *  check below from going quietly vacuous — see its comment. */
const REACT_DEV = path.join(UI, "node_modules/react-dom/cjs/react-dom-client.development.js");
const REACT_PROD = path.join(UI, "node_modules/react-dom/cjs/react-dom-client.production.js");

/** Families a browser resolves without being given a file. */
const GENERIC = new Set([
  "serif",
  "sans-serif",
  "monospace",
  "cursive",
  "fantasy",
  "system-ui",
  "ui-serif",
  "ui-sans-serif",
  "ui-monospace",
  "ui-rounded",
  "math",
  "emoji",
  "fangsong",
  "inherit",
  "initial",
  "unset",
  "revert",
]);

/** Build into `outDir`, or into dist/ when it is omitted. */
function build(outDir?: string, env: NodeJS.ProcessEnv = { NODE_ENV: "production" }): void {
  const args = outDir ? ["--outDir", outDir, "--emptyOutDir"] : [];
  try {
    execFileSync("npx", ["vite", "build", ...args], {
      cwd: UI,
      stdio: "pipe",
      // NOT INHERITED. vitest sets NODE_ENV=test for its whole process tree,
      // this child would take it, and a build with NODE_ENV set to anything but
      // production emits React's development build — 1,087,205 B against
      // 722,653 B, into the directory //go:embed compiles into the binary.
      // vite.config.ts pins the same value for every build; saying it here as
      // well means the call site does not depend on reading that file to be
      // correct. The one caller that passes something else is testing the pin.
      env: { ...process.env, ...env },
    });
  } catch (err) {
    const e = err as { stdout?: Buffer; stderr?: Buffer; message?: string };
    throw new Error(
      `the dashboard build failed, so this check never ran.\n${e.message ?? ""}\n` +
        `--- stderr ---\n${e.stderr?.toString() ?? ""}\n` +
        `--- stdout ---\n${e.stdout?.toString() ?? ""}`
    );
  }
}

function builtCss(): { file: string; css: string } {
  const files = fs.readdirSync(ASSETS).filter((f) => f.endsWith(".css"));
  expect(
    files,
    "expected exactly one stylesheet from the dashboard build. None means it " +
      "emitted no CSS; more than one means CSS is being split per chunk, and " +
      "this check would be reading only whichever came first."
  ).toHaveLength(1);
  const file = path.join(ASSETS, files[0]);
  return { file, css: fs.readFileSync(file, "utf8") };
}

/** Brace-matched @font-face bodies. Minified output has no newlines to lean on. */
function fontFaces(css: string): string[] {
  const out: string[] = [];
  for (const m of css.matchAll(/@font-face\s*\{/g)) {
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

function descriptor(body: string, name: string): string | null {
  const m = new RegExp(`(?:^|;)\\s*${name}\\s*:([^;]*)`, "i").exec(body);
  return m ? m[1].trim() : null;
}

const unquote = (s: string) => s.trim().replace(/^["']|["']$/g, "").trim();

/**
 * Every custom property declared anywhere in the stylesheet, by name.
 *
 * Last declaration wins, which is what the cascade does for the identical
 * selectors Tailwind emits these under. Good enough here: the point is to
 * follow a chain of the build's own making, not to reimplement the cascade.
 */
function customProps(css: string): Map<string, string> {
  const out = new Map<string, string>();
  for (const m of css.matchAll(/(--[A-Za-z0-9_-]+)\s*:\s*([^;{}]+)/g)) {
    out.set(m[1], m[2].trim());
  }
  return out;
}

/** Follow var(--a) -> var(--b) -> a literal stack. Falls back to the var()'s
 *  own default only when the name is genuinely undeclared, which is what the
 *  browser does. */
function resolveVars(value: string, props: Map<string, string>, depth = 0): string {
  if (depth > 12) return value;
  const m = /^var\(\s*(--[A-Za-z0-9_-]+)\s*(?:,([\s\S]*))?\)$/.exec(value.trim());
  if (!m) return value;
  const declared = props.get(m[1]);
  if (declared !== undefined) return resolveVars(declared, props, depth + 1);
  return m[2] !== undefined ? resolveVars(m[2].trim(), props, depth + 1) : "";
}

// ---------------------------------------------------------------------------
// Reading a woff2's own name table.
//
// fonts/OFL.txt names "Geist, Version 1.800" and "Geist Mono, Version 1.701"
// and says it read them out of the files. Without this, that claim is prose:
// the payloads could be replaced with a different cut of either family and
// every check in this file would still pass, leaving a licence notice
// describing software that is no longer the software being redistributed.
//
// NO NEW DEPENDENCY. A woff2 is a brotli stream of the concatenated sfnt
// tables, brotli is in node:zlib, and the name table is one of the ones woff2
// never transforms — so it comes out of the stream byte-for-byte as the sfnt
// spec defines it. That is the whole reason this is ~60 lines rather than a
// font-parsing package.
// ---------------------------------------------------------------------------

/** WOFF2 known-table tags, in the order the spec's flag index refers to them.
 *  Order is load-bearing: glyf and loca are the tables that carry a transformed
 *  length, so mislabelling an index shifts every offset after it. */
const WOFF2_TAGS = [
  "cmap", "head", "hhea", "hmtx", "maxp", "name", "OS/2", "post", "cvt ", "fpgm",
  "glyf", "loca", "prep", "CFF ", "VORG", "EBDT", "EBLC", "gasp", "hdmx", "kern",
  "LTSH", "PCLT", "VDMX", "vhea", "vmtx", "BASE", "GDEF", "GPOS", "GSUB", "EBSC",
  "JSTF", "MATH", "CBDT", "CBLC", "COLR", "CPAL", "SVG ", "sbix", "acnt", "avar",
  "bdat", "bloc", "bsln", "cvar", "fdsc", "feat", "fmtx", "fvar", "gvar", "hsty",
  "just", "lcar", "mort", "morx", "opbd", "prop", "trak", "Zapf", "Silf", "Glat",
  "Gloc", "Feat", "Sill",
];

/** UIntBase128: seven bits per byte, high bit continues. */
function base128(buf: Buffer, pos: number): [number, number] {
  let v = 0;
  for (let i = 0; i < 5; i++) {
    const b = buf[pos++];
    v = (v << 7) | (b & 0x7f);
    if ((b & 0x80) === 0) return [v >>> 0, pos];
  }
  throw new Error("malformed UIntBase128 in the woff2 table directory");
}

/** The `name` table, lifted out of a woff2's brotli stream. */
function nameTable(file: string): Buffer {
  const buf = fs.readFileSync(file);
  if (buf.subarray(0, 4).toString("latin1") !== "wOF2") {
    throw new Error(`${path.basename(file)} is not a woff2 file`);
  }
  const numTables = buf.readUInt16BE(12);
  const compressedSize = buf.readUInt32BE(20);
  // The table directory starts immediately after the 48-byte header.
  let pos = 48;
  const dir: { tag: string; length: number }[] = [];
  for (let i = 0; i < numTables; i++) {
    const flags = buf[pos++];
    const idx = flags & 0x3f;
    let tag: string;
    if (idx === 0x3f) {
      tag = buf.subarray(pos, pos + 4).toString("latin1");
      pos += 4;
    } else {
      tag = WOFF2_TAGS[idx];
    }
    let length: number;
    [length, pos] = base128(buf, pos);
    // A transformed length follows only where a transform is actually defined:
    // glyf and loca at transform version 0, hmtx at version 1. Everything else
    // — name included — is stored at its original length.
    const version = (flags >> 6) & 0x03;
    const transformed =
      ((tag === "glyf" || tag === "loca") && version === 0) ||
      (tag === "hmtx" && version === 1);
    if (transformed) [length, pos] = base128(buf, pos);
    dir.push({ tag, length });
  }
  const sfnt = zlib.brotliDecompressSync(buf.subarray(pos, pos + compressedSize));
  // Tables are concatenated in directory order with no padding, so the offset
  // of one is the sum of the lengths before it.
  let off = 0;
  for (const t of dir) {
    if (t.tag === "name") return sfnt.subarray(off, off + t.length);
    off += t.length;
  }
  throw new Error(`${path.basename(file)} has no name table`);
}

/** Name records by name ID. First record for an ID wins, which is enough here:
 *  every platform's copy of these three carries the same text. */
function fontNames(file: string): Map<number, string> {
  const t = nameTable(file);
  const count = t.readUInt16BE(2);
  const strings = t.readUInt16BE(4);
  const out = new Map<number, string>();
  for (let i = 0; i < count; i++) {
    const rec = 6 + i * 12;
    const platform = t.readUInt16BE(rec);
    const id = t.readUInt16BE(rec + 6);
    const len = t.readUInt16BE(rec + 8);
    const off = t.readUInt16BE(rec + 10);
    const raw = Buffer.from(t.subarray(strings + off, strings + off + len));
    // Platform 1 (Macintosh) is single-byte; 0 and 3 are UTF-16BE.
    out.set(id, platform === 1 ? raw.toString("latin1") : raw.swap16().toString("utf16le"));
  }
  return out;
}

/** Family name (name ID 1), version (5) and copyright (0). */
const NAME_FAMILY = 1;
const NAME_VERSION = 5;
const NAME_COPYRIGHT = 0;

/** First entry of a font stack that a browser cannot conjure by itself. */
function firstRealFamily(stack: string): string | null {
  for (const part of stack.split(",")) {
    const fam = unquote(part);
    if (!fam || fam.startsWith("var(")) continue;
    if (GENERIC.has(fam.toLowerCase())) continue;
    return fam;
  }
  return null;
}

// One build for the whole file, and a fresh one: the point is to test what
// ships, not a stale artifact someone's last `make ui-build` left behind.
beforeAll(() => build(), 120_000);

describe("dashboard ships the fonts it names (#1522)", () => {
  it("declares a face for every family the document paints with, and the files are there", () => {
    const { file, css } = builtCss();
    const props = customProps(css);

    // The two properties Tailwind's preflight applies to the document and to
    // its monospaced utility. Reading them by name is deliberate: they are what
    // decide what ordinary text looks like, and a face for a family nothing
    // resolves to would be dead weight that still passed a looser check.
    const ROOTS = ["--default-font-family", "--default-mono-font-family"];

    // The chain has to be LOAD-BEARING. If preflight stops consuming these,
    // resolving them proves nothing about what gets painted.
    //
    // A FONT-FAMILY DECLARATION SPECIFICALLY, not a mention anywhere in the
    // file. `css.includes("var(--default-font-family")` was the first version of
    // this and it does not say what the message says: a dead custom property
    // that referenced the name and was never used by any declaration would
    // satisfy it, and the whole point of this check is that something PAINTS
    // with the value.
    for (const root of ROOTS) {
      expect(
        new RegExp(`font-family\\s*:[^;}]*var\\(\\s*${root}\\s*[,)]`).test(css),
        `no font-family declaration in the built stylesheet reads ${root}, so ` +
          "resolving it says nothing about what the dashboard renders in. " +
          "Tailwind's preflight is what normally consumes it — check whether " +
          "preflight is still being emitted."
      ).toBe(true);
    }

    const required = new Map<string, string>();
    for (const root of ROOTS) {
      const declared = props.get(root);
      expect(
        declared,
        `${root} is not declared in the built stylesheet. app/globals.css maps ` +
          "the theme's font variables onto it via @theme inline; if that mapping " +
          "is gone the document has silently fallen back to Tailwind's defaults."
      ).toBeDefined();
      const stack = resolveVars(declared!, props);
      const fam = firstRealFamily(stack);
      expect(
        fam,
        `${root} resolves to "${stack}", which names no real family — only ` +
          "generics. The theme has lost its font."
      ).toBeTruthy();
      required.set(fam!.toLowerCase(), fam!);
    }

    // Vacuity guard for the derivation itself. If the resolver ever silently
    // stops following the chain, every assertion below has nothing to check.
    // Counted against ROOTS rather than against a literal 2: one distinct
    // family per root is what "the chain was followed" means here, and a
    // hardcoded number stops meaning that the moment a third root is added.
    expect(
      [...required.values()].sort(),
      "no real font family was derived from the built stylesheet, so the face " +
        "and file checks below would pass against an empty set. Expected one " +
        `distinct family per entry in ROOTS (${ROOTS.join(", ")}).`
    ).toHaveLength(ROOTS.length);

    const faces = fontFaces(css);
    expect(
      faces.length,
      "the built stylesheet contains no @font-face at all. This is the exact " +
        "state #1522 was filed about: the theme names families the browser has " +
        "never been given, so every reader sees a platform substitute. The " +
        "declarations live in app/spa.css."
    ).toBeGreaterThan(0);

    const declaredFamilies = new Map<string, string[]>();
    for (const body of faces) {
      const fam = descriptor(body, "font-family");
      expect(fam, `an @font-face in ${path.basename(file)} has no font-family`).toBeTruthy();
      const key = unquote(fam!).toLowerCase();
      const src = descriptor(body, "src");
      expect(src, `@font-face for "${fam}" has no src descriptor`).toBeTruthy();
      declaredFamilies.set(key, [...(declaredFamilies.get(key) ?? []), src!]);
    }

    for (const [key, fam] of required) {
      expect(
        [...declaredFamilies.keys()].sort(),
        `the dashboard renders in "${fam}" but declares no @font-face for it, so ` +
          "the browser falls through to the next entry in the stack and the " +
          "typography is whatever the platform happens to have. Add the face to " +
          "app/spa.css, next to the others."
      ).toContain(key);
    }

    // ---- the files, opened ------------------------------------------------
    const opened: string[] = [];
    /** Every directory of dist/ a payload actually landed in. */
    const shippedTo = new Set<string>();
    for (const [key, srcs] of declaredFamilies) {
      if (!required.has(key)) continue;
      for (const src of srcs) {
        const urls = [...src.matchAll(/url\(\s*(?:"([^"]*)"|'([^']*)'|([^)\s]*))\s*\)/g)].map(
          (m) => m[1] ?? m[2] ?? m[3]
        );
        expect(
          urls.length,
          `the @font-face for "${required.get(key)}" has a src with no url(): ${src}`
        ).toBeGreaterThan(0);

        for (const url of urls) {
          expect(
            /^(https?:)?\/\//.test(url),
            `the face for "${required.get(key)}" is fetched from ${url}. The ` +
              "dashboard is compiled into the meshui binary and is expected to " +
              "run with no route to the public internet, so a remote font is a " +
              "font that does not load. Self-host it."
          ).toBe(false);

          // Resolved the way the browser resolves it: relative to the
          // stylesheet, which is what makes this a reachability check rather
          // than a spelling check.
          const onDisk = path.resolve(path.dirname(file), url.split("?")[0].split("#")[0]);
          expect(
            fs.existsSync(onDisk),
            `the stylesheet points "${required.get(key)}" at ${url}, and nothing ` +
              `is there. Resolved to ${path.relative(UI, onDisk)} relative to the ` +
              "emitted stylesheet. Vite only WARNS on a css url() it cannot " +
              "resolve, so a moved or deleted source file ships a stylesheet that " +
              "looks correct and loads nothing."
          ).toBe(true);

          const buf = fs.readFileSync(onDisk);
          expect(
            buf.subarray(0, 4).toString("latin1"),
            `${path.relative(UI, onDisk)} is not a woff2 file — its first four ` +
              "bytes are not the wOF2 signature. A truncated or wrong-format " +
              "payload is served with a 200 and silently ignored by the browser."
          ).toBe("wOF2");
          expect(
            buf.length,
            `${path.relative(UI, onDisk)} is implausibly small for a font.`
          ).toBeGreaterThan(4096);

          // Inside dist/ is what makes it reachable at runtime at all — see the
          // embed assertion below.
          expect(
            path.relative(path.join(UI, "dist"), onDisk).startsWith(".."),
            `${path.relative(UI, onDisk)} is outside dist/, so it is not part of ` +
              "the build output and will not be compiled into the binary."
          ).toBe(false);

          opened.push(path.relative(UI, onDisk));
          shippedTo.add(path.dirname(onDisk));
        }
      }
    }

    expect(
      opened.length,
      "no font file was opened, so every check above ran against nothing."
    ).toBeGreaterThanOrEqual(2);

    // ---- and the licence goes with them -----------------------------------
    //
    // SIL OFL 1.1 clause 2: the notice travels with the font software wherever
    // it is redistributed, and this build output is redistributed inside a Go
    // binary. A notice that exists only in the source tree reaches whoever
    // clones the repo and nobody who receives what it builds.
    //
    // Compared BYTE FOR BYTE against the authored file, which is the whole
    // argument for emitting it from there (vite.fonts.ts) rather than keeping a
    // second copy under public/ for Vite to carry: a second copy is free to
    // describe a version of a font that is no longer the one shipping, and
    // nothing would say so.
    const authored = fs.readFileSync(path.join(FONTS, NOTICE));
    expect(
      shippedTo.size,
      "no directory was recorded for the fonts, so the licence check below has " +
        "nowhere to look and would pass without testing anything."
    ).toBeGreaterThan(0);
    for (const dir of shippedTo) {
      const beside = path.join(dir, NOTICE);
      expect(
        fs.existsSync(beside),
        `the fonts ship from ${path.relative(UI, dir)} and there is no ${NOTICE} ` +
          "there. They are licensed under the SIL Open Font License, which " +
          "requires the notice to be included with every redistribution of the " +
          "font software — and this directory is compiled into the meshui " +
          "binary. It is emitted by the shipFontLicence plugin in vite.fonts.ts; " +
          "if that has been dropped from the plugin list, put it back."
      ).toBe(true);
      expect(
        fs.readFileSync(beside).equals(authored),
        `${path.relative(UI, beside)} is not byte-identical to the authored ` +
          `${path.relative(UI, path.join(FONTS, NOTICE))}. There should be exactly ` +
          "one copy of this file in the repository, emitted into each build that " +
          "carries the fonts; two copies drift, and the one that drifts is the " +
          "one nobody edits when the payloads are replaced."
      ).toBe(true);
    }
  }, 120_000);

  // The sources, checked separately so a missing payload is reported as a
  // missing payload rather than as a stylesheet that points nowhere.
  it("keeps the payloads on neutral ground, with their licence", () => {
    const files = fs.readdirSync(FONTS);
    const woff2 = files.filter((f) => f.endsWith(".woff2"));
    expect(
      woff2.length,
      `no woff2 files in ${path.relative(UI, FONTS)}. Both the dashboard and the ` +
        "scroll demo read them from here; neither may reach into the other's " +
        "directory for them (#1526, #1527)."
    ).toBeGreaterThanOrEqual(2);

    // SIL Open Font License 1.1, clause 2: the notice travels with the font,
    // and this repo redistributes both files inside a binary.
    expect(
      files,
      `${path.relative(UI, FONTS)} has no OFL.txt. The fonts are licensed under ` +
        "the SIL Open Font License, which requires the copyright notice and the " +
        "licence to be included wherever the font software is redistributed."
    ).toContain("OFL.txt");
    const ofl = fs.readFileSync(path.join(FONTS, "OFL.txt"), "utf8");
    expect(
      ofl,
      "OFL.txt no longer carries the licence text it exists to carry."
    ).toContain("SIL OPEN FONT LICENSE Version 1.1");
    expect(ofl, "OFL.txt carries no copyright line.").toMatch(/Copyright/);

    // ---- and it describes THESE files -------------------------------------
    //
    // OFL.txt names a family and a version per payload and says it read them
    // out of each file's own name table. Until this ran, that was prose: the
    // woff2 files could be swapped for a different cut of either family and
    // nothing anywhere would notice, leaving the notice describing font
    // software that is no longer the font software being redistributed — which
    // is the one thing a licence notice has to get right.
    for (const f of woff2) {
      const names = fontNames(path.join(FONTS, f));
      const family = names.get(NAME_FAMILY);
      const version = names.get(NAME_VERSION);
      const copyright = names.get(NAME_COPYRIGHT);
      expect(
        family && version && copyright,
        `${f} carries no family/version/copyright in its name table, so there is ` +
          "nothing to compare OFL.txt against."
      ).toBeTruthy();

      const line = ofl.split("\n").find((l) => l.startsWith(f));
      expect(
        line,
        `OFL.txt has no line for ${f}. Every payload in ${path.relative(UI, FONTS)} ` +
          "has to be described by the notice that ships with it: one line per " +
          "file, starting with the filename."
      ).toBeTruthy();
      expect(
        line,
        `OFL.txt describes ${f} as "${line?.slice(f.length).trim()}", but the ` +
          `file's own name table says "${family}" / "${version}". The payload has ` +
          "been replaced without re-reading the notice. Read the two strings back " +
          "out of the file and correct the line — the notice is what tells a " +
          "recipient which font software they received."
      ).toContain(family!);
      expect(line, `OFL.txt records the wrong version for ${f}.`).toContain(version!);

      // The URL in the parenthetical differs between the two files (one ends
      // .git), so the holder is compared and the link is not.
      const holder = copyright!.replace(/\s*\([^)]*\)\s*$/, "").trim();
      expect(
        ofl,
        `OFL.txt does not carry the copyright line ${f} declares: "${holder}". ` +
          "SIL OFL 1.1 clause 2 requires the copyright notice to travel with the " +
          "font software, and a notice naming someone else is not that notice."
      ).toContain(holder);
    }
  });

  // Everything above proves the files are in src/ui/dist/. The binary is not
  // made of that directory — it is made of cmd/mcp-mesh-ui/dist, which every
  // build copies src/ui/dist into first. So the chain has two more links, and
  // BOTH fail silently: src/core/ui/server.go serves index.html with a 200 and
  // text/html for any path not in the embedded filesystem, so a woff2 that
  // never made it in is fetched successfully, discarded by the browser as not
  // a font, and the page renders in the platform fallback. That is
  // indistinguishable from working, and it is exactly the state #1522
  // describes.
  //
  // This one is the directive. The next one is the copy.
  it("compiles the whole of dist/ into the binary", () => {
    const go = fs.readFileSync(EMBED_GO, "utf8");
    const directives = [...go.matchAll(/^\/\/go:embed\s+(.+)$/gm)].map((m) => m[1].trim());
    expect(
      directives,
      `no //go:embed directive in ${path.relative(UI, EMBED_GO)}; the dashboard ` +
        "is not being compiled into the binary at all."
    ).not.toHaveLength(0);
    expect(
      directives,
      `${path.relative(UI, EMBED_GO)} no longer embeds dist/ wholesale. Patterns ` +
        `found: ${JSON.stringify(directives)}. An enumerated list has to be kept ` +
        "in step with whatever the build emits, and the first thing it drops is " +
        "the file types nobody thinks of — the fonts among them. Keep it as " +
        "`all:dist`."
    ).toContain("all:dist");
  });

  // The copy, which is the link `all:dist` cannot defend. //go:embed can only
  // take what is in cmd/mcp-mesh-ui/dist, and nothing in this repo builds into
  // that directory — three separate places populate it by copying src/ui/dist
  // over, and every one of them is free to copy less than the whole thing.
  //
  // All three copy wholesale today, so nothing is broken. What this holds is the
  // narrowing: `cp -r src/ui/dist/assets` looks like a tidy-up, keeps the app
  // working in every visible respect, and drops the fonts out of the binary with
  // every other assertion in this file still green — because every other
  // assertion in this file reads src/ui/dist.
  it("copies the whole of dist/ into the embed directory, everywhere it is copied", () => {
    const REPO = path.resolve(UI, "..", "..");
    const COPIES = [
      ["Makefile", "`make ui-server-build`, the local path to a binary with a dashboard in it"],
      ["packaging/scripts/build-binaries.sh", "the release cross-compile"],
      [
        "tests/src-tests/suites/build/tc01b_build_meshui/test.yaml",
        "the meshui image every integration suite runs against",
      ],
    ];

    for (const [rel, what] of COPIES) {
      const file = path.join(REPO, rel);
      expect(
        fs.existsSync(file),
        `${rel} is not there. It was one of the three places that populate ` +
          "cmd/mcp-mesh-ui/dist; if it has moved, point this list at the new one " +
          "rather than dropping the entry — an unchecked copy is how the fonts " +
          "leave the binary unnoticed."
      ).toBe(true);

      // Every line that writes the embed directory with cp. `\bcp` does not
      // match the "cp" inside "mcp-mesh", and the rm -rf that precedes each copy
      // carries no cp at all.
      const invocations = fs
        .readFileSync(file, "utf8")
        .split("\n")
        .filter((l) => l.includes("cmd/mcp-mesh-ui/dist"))
        .map((l) => ({
          line: l.trim(),
          m: /\bcp\s+((?:-[A-Za-z-]+\s+)*)([^\s&|;]+)\s+([^\s&|;]+)/.exec(l),
        }))
        .filter((x) => x.m)
        .map((x) => ({
          line: x.line,
          flags: x.m![1].trim(),
          src: x.m![2].replace(/^["']|["']$/g, ""),
          dst: x.m![3].replace(/^["']|["']$/g, ""),
        }));

      expect(
        invocations.length,
        `${rel} no longer copies anything into cmd/mcp-mesh-ui/dist, so either ` +
          "it stopped building the dashboard into the binary or it now populates " +
          "that directory some other way this check cannot see."
      ).toBeGreaterThan(0);

      for (const c of invocations) {
        expect(
          c.flags,
          `${rel} copies into the embed directory without a recursive flag:\n  ` +
            `${c.line}`
        ).toMatch(/-[A-Za-z]*[rRa]/);
        // The SOURCE is the whole of src/ui/dist and not a path inside it. This
        // is the assertion: a subdirectory, a glob or an enumeration all land
        // here, and all of them ship a binary whose dashboard renders in the
        // platform fallback with nothing to see anywhere.
        expect(
          c.src.replace(/\/+$/, ""),
          `${rel} does not copy the whole of src/ui/dist into the embed ` +
            `directory — it copies "${c.src}", in ${what}:\n  ${c.line}\n` +
            "Whatever is not copied is not in the binary, and a file missing from " +
            "the embedded filesystem is served as index.html with a 200 " +
            "(src/core/ui/server.go), so a dropped font produces a successful " +
            "request, no console error and a page in the wrong typeface."
        ).toMatch(/(^|\/)src\/ui\/dist$/);
        expect(
          c.dst.replace(/\/+$/, ""),
          `${rel} copies src/ui/dist somewhere other than the embed directory:\n  ` +
            `${c.line}`
        ).toMatch(/(^|\/)cmd\/mcp-mesh-ui\/dist$/);
      }
    }
  });
});

// What dist/ HOLDS, as opposed to what it points at.
//
// The suite's two build-shelling tests both write dist/, and dist/ is what the
// binary is made of, so the suite decides what a developer's `make
// ui-server-build` embeds if they do not rebuild in between. Under vitest that
// was React's development build — 1,087,205 B against 722,653 B — because
// vitest sets NODE_ENV=test for its whole process tree and Vite reads it. Every
// existing check passed: the stylesheet is byte-identical between the two, and
// nothing else looked at the JS at all.
describe("dist/ holds a production bundle", () => {
  it("is built against React's production build, not its development one", () => {
    // The markers are DERIVED, not asserted from memory. Each candidate has to
    // be present in the React that npm actually installed here and absent from
    // its production twin — otherwise it says nothing about which one was
    // bundled, and this test would sail on green after React renamed a warning.
    for (const f of [REACT_DEV, REACT_PROD]) {
      expect(
        fs.existsSync(f),
        `${path.relative(UI, f)} is not there, so there is nothing to derive a ` +
          "development-build marker from. react-dom's layout has changed; point " +
          "these two constants at its current pair."
      ).toBe(true);
    }
    const dev = fs.readFileSync(REACT_DEV, "utf8");
    const prod = fs.readFileSync(REACT_PROD, "utf8");
    const markers = ["Invalid hook call", 'unique "key" prop', "act(...)"].filter(
      (m) => dev.includes(m) && !prod.includes(m)
    );
    expect(
      markers,
      "none of the strings this test uses to tell React's two builds apart still " +
        "appears in one and not the other, so the check below cannot fail and is " +
        "worth nothing. Pick fresh ones out of " +
        `${path.relative(UI, REACT_DEV)} — warning text only it carries.`
    ).not.toHaveLength(0);

    const js = fs.readdirSync(ASSETS).filter((f) => f.endsWith(".js"));
    expect(js, "the dashboard build emitted no JavaScript at all.").not.toHaveLength(0);
    for (const f of js) {
      const code = fs.readFileSync(path.join(ASSETS, f), "utf8");
      for (const m of markers) {
        expect(
          code.includes(m),
          `dist/assets/${f} contains ${JSON.stringify(m)}, which only React's ` +
            "development build carries. Something built this with NODE_ENV set to " +
            "something other than production, and it is the bundle //go:embed " +
            "would compile into the binary: half again the size, warning " +
            "machinery and all, with identical CSS so nothing else notices. " +
            "vite.config.ts pins NODE_ENV for builds — check it is still there."
        ).toBe(false);
      }
    }
  });

  // The pin itself, put under the condition it exists for. A marker check alone
  // does not cover this: with only a define for process.env.NODE_ENV, React
  // came out correct and the bundle was still 882,126 B, because every
  // dependency that switches by export condition had resolved its development
  // entry. Comparing the bytes is what makes that visible without having to
  // know which packages those are.
  it("emits the same bytes from an environment that asks for development", () => {
    const out = fs.mkdtempSync(path.join(os.tmpdir(), "meshui-envcheck-"));
    // Its OWN directory, deliberately: a regression here must not be able to
    // leave the development bundle sitting in dist/, which is the state this
    // whole block exists to prevent.
    try {
      build(out, { NODE_ENV: "development" });
      const name = (dir: string) => fs.readdirSync(dir).filter((f) => f.endsWith(".js"));
      const hostile = name(path.join(out, "assets"));
      const shipped = name(ASSETS);
      expect(hostile, "the hostile-environment build emitted no JavaScript.").not.toHaveLength(0);
      expect(
        hostile.sort(),
        "a build run with NODE_ENV=development emitted different files from the " +
          `one in dist/: ${JSON.stringify(hostile)} against ${JSON.stringify(shipped)}. ` +
          "The build is reading its environment; it must not."
      ).toEqual(shipped.sort());
      for (const f of hostile) {
        const a = fs.readFileSync(path.join(out, "assets", f));
        const b = fs.readFileSync(path.join(ASSETS, f));
        expect(
          a.equals(b),
          `${f} came out at ${a.length} B from an environment asking for ` +
            `development and ${b.length} B from the one in dist/. The build is ` +
            "taking NODE_ENV from whoever started it, so what lands in the binary " +
            "depends on the shell — vitest's NODE_ENV=test is how this was found. " +
            "vite.config.ts assigns process.env.NODE_ENV for builds; that is what " +
            "this asserts. (If the two differ for an unrelated reason, check " +
            "nothing has made the build nondeterministic — a timestamp in the " +
            "output would fail here too.)"
        ).toBe(true);
      }
    } finally {
      fs.rmSync(out, { recursive: true, force: true });
    }
  }, 120_000);
});

// THE OTHER TWO BUILDS, which nothing above touches.
//
// shipFontLicence is wired into three configs and only one of them is built by
// this file — building all three would be the obvious way to cover the rest and
// it is the wrong trade, because what can be broken here is not the plugin, it
// is the wiring. The plugin's own build-time error fires when fonts/OFL.txt is
// missing from the source tree; it cannot fire at all if the plugin has been
// dropped from a five-element array someone reordered. Same for the production
// pin: an inherited NODE_ENV changes what a config RESOLVES, so a config that
// has quietly gone back to being a plain object has nowhere to run the pin and
// nothing says so.
//
// Both of those are answered by loading the configs and looking, at no build
// cost. The docs workflow covers the other half for the artifact that actually
// ships: .github/workflows/docs.yml lists fonts/OFL.txt among the files the
// scroll bundle must have produced.
describe("every build that redistributes the fonts is protected the same way", () => {
  type ConfigEnv = { command: "build" | "serve"; mode: string };
  type ConfigFactory = (env: ConfigEnv) => { plugins?: unknown };

  const CONFIGS: [string, () => Promise<{ default: unknown }>, string][] = [
    ["vite.config.ts", () => import("../vite.config"), "the dashboard, compiled into the meshui binary"],
    ["vite.demo.config.ts", () => import("../vite.demo.config"), "the docs-site React bundle"],
    ["vite.static.config.ts", () => import("../vite.static.config"), "the bundle the docs site serves"],
  ];

  for (const [name, load, what] of CONFIGS) {
    it(`${name} pins production for builds and ships the licence`, async () => {
      // process.env is process-global and vitest runs this file's tests in one
      // process, so the pin is put back however it was found. Nothing else here
      // reads NODE_ENV — the build-shelling tests pass it explicitly — but a
      // test that quietly leaves the environment changed is a test that makes
      // some later failure impossible to attribute.
      const before = process.env.NODE_ENV;
      try {
        const factory = (await load()).default;
        expect(
          typeof factory,
          `${name} exports a plain config object. It has to be a factory — ` +
            "`defineConfig(({ command }) => ({ ... }))` — because the production " +
            "pin runs while the config is being produced, and an object gives it " +
            "nowhere to run. See vite.env.ts: without the pin, a build started " +
            `from a shell with NODE_ENV set resolves ${what} against every ` +
            "dependency's development entry points."
        ).toBe("function");

        process.env.NODE_ENV = "test";
        const config = (factory as ConfigFactory)({ command: "build", mode: "production" });
        expect(
          process.env.NODE_ENV,
          `${name} did not pin NODE_ENV for a build, so ${what} is resolved ` +
            "against whatever the caller's shell had. vitest sets NODE_ENV=test " +
            "across its process tree and CI shells set it for other reasons; the " +
            "measured cost is 882,126 B against 722,653 B for the dashboard and " +
            "562,474 B against 546,096 B for the docs-site React bundle, with " +
            "byte-identical CSS and no other signal. Call pinProductionBuild(command)."
        ).toBe("production");

        // AND NOT FOR THE DEV SERVER. React's development build is the whole
        // point of `npm run dev`, and vitest loads vite.config.ts the same way.
        process.env.NODE_ENV = "test";
        (factory as ConfigFactory)({ command: "serve", mode: "development" });
        expect(
          process.env.NODE_ENV,
          `${name} forces production for the dev server as well, which takes ` +
            "React's development build — and its error messages — away from " +
            "`npm run dev`. The pin is conditional on command === \"build\"."
        ).toBe("test");

        // react() and tailwindcss() each return an array of plugins, so the
        // list has to be flattened before anything can be named.
        const plugins = ((config.plugins ?? []) as unknown[])
          .flat(Infinity)
          .filter((p): p is { name: string } => !!p && typeof (p as { name?: unknown }).name === "string")
          .map((p) => p.name);
        expect(
          plugins,
          `${name} does not wire shipFontLicence, and ${what} redistributes ` +
            "fonts/*.woff2. SIL OFL 1.1 clause 2 requires the copyright notice " +
            "and the licence to be included with every redistribution of the font " +
            "software. Nothing else emits that file: no stylesheet references it " +
            "and no module imports it, so unwiring the plugin republishes both " +
            "fonts with no notice and no error — the plugin's own this.error only " +
            "fires when src/ui/fonts/OFL.txt is missing from the source tree.\n" +
            `Plugins found: ${JSON.stringify(plugins)}`
        ).toContain("ship-font-licence");
      } finally {
        if (before === undefined) delete process.env.NODE_ENV;
        else process.env.NODE_ENV = before;
      }
    });
  }
});
