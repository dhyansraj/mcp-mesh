// Build config for the docs-site scroll bundle. SEPARATE FROM vite.config.ts
// on purpose: nothing here is shared with it and `npm run build` never reads
// this file.
//
// KNOWN, MEASURED EXCEPTION — this config does not fully separate the two
// builds, and cannot.
// Tailwind v4's automatic source detection is rooted at the Vite root
// (src/ui), and it extracts utility candidates from ANY text it scans,
// including prose inside comments and the keys of JSON data files. So every
// file under src/ui/demo/ contributes utilities to the DASHBOARD's stylesheet
// even though the dashboard never renders them.
//
// This is not fixable by writing careful prose. An earlier draft of THIS
// comment used a word that is itself a utility name and added another rule to
// the dashboard's stylesheet. The surface includes comments, copy documents
// and the keys of JSON data files.
//
// An earlier version of this comment claimed "the SPA build must not change at
// all". That was false and is exactly the kind of assertion that outlives the
// thing it describes, so it is stated accurately here instead.
//
// Two independent fixes exist, both out of scope for this config:
//   - relocate the demo outside src/ui (verified: a probe file in
//     web/scroll-demo/ is NOT scanned, one in src/ui/demo/ is);
//   - or land the prerender migration, after which the demo no longer imports
//     app/globals.css and `@source not "../demo"` works cleanly — it does not
//     today, because both entries share that Tailwind entry point.
//
//   npx vite build --config vite.demo.config.ts
//
// Output (src/ui/demo/dist/, which is gitignored — see the Phase 2 notes):
//   mesh-scroll.js    self-contained IIFE, React and React Flow included
//   mesh-scroll.css   every selector confined to #mesh-scroll
//   fonts/*.woff2     self-hosted Geist, copied verbatim
import { defineConfig, type Plugin } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import postcss from "postcss";
import path from "path";
import fs from "fs";

const SCOPE = "#mesh-scroll";

/**
 * Narrowest viewport the section is allowed to run on.
 *
 * Not a mobile design — a refusal to ship a known-broken one. Below this the
 * twelve-node graph would need ~0.23 zoom (0.61 already reads as small at
 * 1440), and the copy column is 32% of panel width by construction, which at
 * phone width is ~18 characters. The loader in docs/overrides/home.html
 * declines to fetch the bundle below this width; this file declines to reserve
 * the height. KEEP THE TWO IN SYNC.
 */
const MIN_WIDTH = 900;

/**
 * Confine the emitted stylesheet to a single root element.
 *
 * PRECISELY: every SELECTOR is prefixed, and @keyframes names are namespaced.
 * Three things remain document-global by nature and cannot be scoped —
 * @font-face (family names are ours alone), @property (Tailwind's --tw-*
 * registrations) and @layer, which is unwrapped entirely. "Every selector is
 * confined" is the accurate claim; "the stylesheet cannot affect the page" is
 * not, and was not true of keyframes until they were namespaced.
 *
 * WHY A POST-PASS AND NOT A TAILWIND FEATURE. Tailwind v4 can prefix utility
 * class NAMES (`@import "tailwindcss" prefix(tw)` → `tw:flex`), but that only
 * helps if you control every class in every file — and this bundle renders
 * meshui's real AgentNode, whose classes we are not allowed to touch. Cascade
 * layers change precedence, not reach. So the reach has to be imposed on the
 * output.
 *
 * WHY A POST-WRITE PASS AND NOT css.postcss.plugins OR generateBundle.
 * Tailwind v4 generates its utilities inside @tailwindcss/vite's own
 * transform, so a postcss plugin can run before the utilities exist. And a
 * generateBundle hook on a normal-order plugin runs BEFORE vite:css-post has
 * emitted the stylesheet asset at all — that was tried, produced a silent
 * no-op, and was only caught by grepping the output for the scope. Rewriting
 * the file after it is on disk is the one point where "everything that will
 * ship" is guaranteed to exist.
 *
 * An encapsulated DOM subtree would also have worked and was rejected: React
 * Flow measures the element it mounts into and portals into it, and
 * getBoundingClientRect across that boundary is exactly the kind of thing
 * that produces a graph rendered at the wrong zoom. A build-time rewrite has
 * no runtime behaviour at all.
 *
 * CAUTION ON WORDING IN THIS REPO: Tailwind v4 extracts utility candidates
 * from ANY text it scans, prose in comments included. Two ordinary English
 * words used here earlier were each a valid utility name, and emitted two
 * extra rules into the SPA's stylesheet — a build this file has nothing to
 * do with. Avoid bare utility words in files under src/ui; the durable fix
 * is one @source line in app/globals.css (see the Phase 2 notes).
 */
function scopeCss(): Plugin {
  const scoper = {
    postcssPlugin: "mesh-scroll-scope",
    // Once() rather than the Rule() visitor: mutating a selector inside the
    // Rule visitor re-triggers it, and walkRules over the existing tree is
    // both simpler to reason about and single-pass.
    Once(root: postcss.Root) {
      // ---- unwrap @layer ------------------------------------------------
      // UNLAYERED CSS BEATS LAYERED CSS AT ANY SPECIFICITY. That is the whole
      // reason this exists. Tailwind v4 emits everything inside
      // `@layer theme, base, components, utilities`; MkDocs Material ships
      // zero @layer rules, so it is entirely unlayered. Material's
      // `.md-typeset h2 { font-size: 1.5625em }` at (0,1,1) therefore defeated
      // our `#mesh-scroll .text-\[30px\]` at (1,1,0) — the title rendered
      // 16px x 1.5625 = 25px. Scoping had already won the specificity contest
      // and it did not matter, because the contest was never specificity.
      //
      // Hoisting each block's children in place preserves Tailwind's intended
      // precedence as source order (theme -> base -> components -> utilities),
      // which is what layer order was encoding anyway for rules of differing
      // specificity. The loop handles nesting; `@layer a, b;` statements carry
      // no rules and are simply dropped.
      //
      // `@layer properties` holds only an @supports fallback — the 78
      // @property registrations are already top-level and are not touched.
      for (let guard = 0; guard < 10; guard++) {
        const layers: postcss.AtRule[] = [];
        root.walkAtRules("layer", (at) => {
          layers.push(at);
        });
        if (!layers.length) break;
        for (const at of layers) {
          if (at.nodes) at.replaceWith(at.nodes);
          else at.remove();
        }
      }

      // ---- rem -> px ----------------------------------------------------
      // `rem` ALWAYS resolves against :root. Pinning font-size on #mesh-scroll
      // fixes `em` and does nothing for `rem`, so with Material's
      // `html { font-size: 137.5% }` every rem-derived value in this bundle
      // came out 37.5% too large: Tailwind's whole spacing scale, the radius
      // scale, the measure caps. Scoping cannot reach this — the dependency
      // has to be severed at build time.
      //
      // DELIBERATE TRADE-OFF: this removes root-font-size scaling for the
      // section, which is normally an accessibility feature. It is accepted
      // here because the section already pins its own font-size and derives
      // its entire layout from vh/vw, so it does not honour user font scaling
      // today either. Before this change it was INCONSISTENTLY scaled — type
      // fixed, spacing inflated — which is strictly worse than either being
      // coherent. If the section is ever made to honour user scaling, this is
      // the first thing that has to go, along with the vh geometry.
      //
      // Not converted, on purpose:
      //  - @font-face / @counter-style descriptors (guarded below);
      //  - at-rule PARAMS, i.e. media-query conditions. walkDecls never visits
      //    them, and it would be wrong anyway: rem in a media condition
      //    resolves against the INITIAL font size, never the declared root
      //    one, so those four breakpoints were never affected by this bug.
      // Custom properties ARE converted: `--radius: .625rem` feeds
      // `calc(var(--radius) + 8px)`, so leaving it would defeat the fix. Every
      // custom property here is declared on #mesh-scroll, so nothing outside
      // this stylesheet can consume one.
      const REM = /(-?(?:\d+\.?\d*|\.\d+))rem\b/g;
      root.walkDecls((decl) => {
        if (decl.value.indexOf("rem") === -1) return;
        for (let p: postcss.Container | undefined = decl.parent as postcss.Container; p; p = p.parent as postcss.Container) {
          if (p.type === "atrule") {
            const at = p as postcss.AtRule;
            if (/^(font-face|counter-style|font-feature-values)$/.test(at.name)) return;
          }
          // There was briefly a second exemption here, for a sidebar breakout
          // correction in embed.css that had to stay tied to Material's
          // responsive root. `hide: navigation` on the home page removed the
          // sidebar and with it the correction, so the exemption guarded
          // nothing and was deleted rather than left as a special case for a
          // case that no longer exists. If that correction ever returns, so
          // must an exemption for it — converting it against a fixed 16px
          // basis would freeze it at the wrong width on two of Material's
          // three root steps.
        }
        decl.value = decl.value.replace(REM, (_m, n: string) => {
          const px = parseFloat(n) * 16;
          return `${parseFloat(px.toFixed(4))}px`;
        });
      });

      // ---- namespace @keyframes -----------------------------------------
      // Selector scoping does NOT confine keyframes: an @keyframes name is a
      // document-global identifier, so `@keyframes pulse` in this bundle
      // silently redefines any other `pulse` on the page. That is not
      // hypothetical — Material 9.7.1 also defines `pulse`, and this
      // stylesheet loads after it, so ours was winning for the whole home
      // page. Tailwind contributes spin/pulse/bounce/ping/enter/exit too.
      //
      // Renaming them here, plus every animation shorthand and animation-name
      // that references one. Names not defined in this file are left alone.
      const kf = new Set<string>();
      root.walkAtRules((at) => {
        if (/keyframes$/.test(at.name)) kf.add(at.params.trim());
      });
      const NS = "mesh-";
      root.walkAtRules((at) => {
        if (/keyframes$/.test(at.name) && kf.has(at.params.trim())) {
          at.params = NS + at.params.trim();
        }
      });
      if (kf.size) {
        const names = [...kf].sort((a, b) => b.length - a.length).map(
          (n) => n.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")
        );
        const ref = new RegExp(`(^|[\\s,])(${names.join("|")})(?=$|[\\s,])`, "g");
        root.walkDecls((decl) => {
          // CUSTOM PROPERTIES TOO, and this was the bug: Tailwind does not put
          // the keyframe name in the `animation` declaration. It defines
          // `--animate-bounce: bounce 1s infinite` and then the utility says
          // `animation: var(--animate-bounce)`. Renaming only the @keyframes
          // block and the `animation:` declaration left every --animate-*
          // pointing at a name that no longer existed, which silently killed
          // animate-bounce and animate-pulse — including the threshold slide's
          // scroll arrow. Any declaration can carry a keyframe name; the
          // token-boundary match below is what keeps unrelated values intact.
          const isAnim =
            decl.prop === "animation" ||
            decl.prop === "animation-name" ||
            decl.prop.startsWith("--");
          if (!isAnim) return;
          decl.value = decl.value.replace(ref, (_m, pre, name) => pre + NS + name);
        });
      }

      // CROSS-CHECK: every keyframe name referenced must resolve to a block we
      // emitted. This is the assertion that would have caught the regression
      // above at build time instead of on the live site.
      {
        const defined = new Set<string>();
        root.walkAtRules((at) => {
          if (/keyframes$/.test(at.name)) defined.add(at.params.trim());
        });
        const dangling = new Set<string>();
        root.walkDecls((decl) => {
          if (
            decl.prop !== "animation" &&
            decl.prop !== "animation-name" &&
            !decl.prop.startsWith("--animate")
          ) {
            return;
          }
          for (const name of kf) {
            const bare = new RegExp(`(^|[\\s,])${name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}(?=$|[\\s,])`);
            if (bare.test(decl.value) && !defined.has(name)) dangling.add(`${decl.prop}: ${decl.value}`);
          }
        });
        if (dangling.size) {
          throw new Error(
            "keyframe rename left dangling references:\n  " +
              [...dangling].join("\n  ") +
              "\nEvery name used in an animation or --animate-* value must have a matching @keyframes."
          );
        }
      }

      // ---- scope every selector -----------------------------------------
      root.walkRules((rule) => {
        // @keyframes children are percentage steps, not selectors.
        for (let p: postcss.Container | undefined = rule.parent as postcss.Container; p; p = p.parent as postcss.Container) {
          if (p.type === "atrule" && /keyframes$/.test((p as postcss.AtRule).name)) return;
        }
        rule.selectors = rule.selectors.map((sel) => {
          const s = sel.trim();
          if (!s || s.startsWith(SCOPE)) return s;
          // Document-level selectors collapse ONTO the root: this is what
          // moves `:root { --color-* }` and preflight's `body { margin: 0 }`
          // out of the document and into our element.
          if (s === ":root" || s === "html" || s === "body" || s === ":host") return SCOPE;
          if (s.startsWith(":root")) return SCOPE + s.slice(":root".length);
          if (s.startsWith("html") && !/^html[\w-]/.test(s)) return SCOPE + s.slice(4);
          if (s.startsWith("body") && !/^body[\w-]/.test(s)) return SCOPE + s.slice(4);
          return `${SCOPE} ${s}`;
        });
      });
    },
  };
  return {
    name: "mesh-scroll-scope-css",
    async writeBundle(opts, bundle) {
      const dir = opts.dir ?? path.dirname(opts.file ?? "");
      for (const file of Object.values(bundle)) {
        if (file.type !== "asset" || !file.fileName.endsWith(".css")) continue;
        const target = path.join(dir, file.fileName);
        const css = fs.readFileSync(target, "utf8");
        const out = await postcss([scoper as postcss.AcceptedPlugin]).process(css, {
          from: undefined,
        });
        fs.writeFileSync(target, out.css);
        const scoped = out.css.split(SCOPE).length - 1;
        console.log(`  scoped ${file.fileName}: ${scoped} selectors confined to ${SCOPE}`);
      }
    },
  };
}

/**
 * Emit the section's total height into the stylesheet.
 *
 * The docs page has to reserve this height BEFORE the 173KB of JS arrives, or
 * the page grows under the reader and the scroll position jumps. The number is
 * a function of the beat weights, so hardcoding it into home.html would put a
 * second copy of the arithmetic somewhere that cannot see script.ts and would
 * silently drift the first time a weight changes.
 *
 * Instead the build reads it from the same module the driver uses and writes
 * it into the CSS, which is loaded eagerly. One source of truth, and the
 * placeholder physically cannot disagree with the animation.
 *
 * Matches Stage's own layout: header 70vh + section (100 + travel*100)vh +
 * closing spacer 25vh.
 */
function emitReservedHeight(): Plugin {
  return {
    name: "mesh-scroll-reserve-height",
    // SEQUENTIAL, and it matters: writeBundle is a PARALLEL rollup hook, so
    // this append and scopeCss's read-modify-write raced. The append landed
    // first and was then clobbered by the scoper writing back the copy it had
    // already read — the build logged success and shipped a stylesheet with no
    // reserved height in it. sequential makes rollup await the earlier hooks.
    writeBundle: {
      sequential: true,
      async handler(opts, bundle) {
      // Imported here rather than at module scope so the config itself stays
      // synchronous — an async defineConfig picks a different overload and
      // stops type-checking.
      // Both the number AND the "does the shipped bundle render a hero"
      // decision come from script.ts, so removing the hero changes the
      // reservation with no second edit here.
      const { pageHeightVh, EMBED_SHOWS_HEADER } = await import("./demo/script");
      const vh = pageHeightVh(EMBED_SHOWS_HEADER);
      const dir = opts.dir ?? "";
      for (const file of Object.values(bundle)) {
        if (file.type !== "asset" || !file.fileName.endsWith(".css")) continue;
        const target = path.join(dir, file.fileName);
        // GATED ON THE SAME BREAKPOINT AS THE LOADER in docs/overrides/
        // home.html — the two must agree, and neither can read the other, so
        // they are cross-referenced by comment. Reserving the height on a
        // viewport that will never fetch the bundle would produce exactly the
        // failure the reservation exists to prevent: 2175vh of nothing. Below
        // the breakpoint the section collapses to the placeholder's own
        // height, which is one screen of B1's copy.
        fs.appendFileSync(
          target,
          // display:block is the other half of the mobile guard — the base
          // rule in embed.css hides the section, and this is the only thing
          // that shows it. One media query governs both existence and the
          // reservation, so they can never disagree.
          `\n@media (min-width:${MIN_WIDTH}px){#mesh-scroll{display:block;min-height:${vh}vh}}\n` +
            `#mesh-scroll[data-mesh-scroll-mounted="1"] .mesh-scroll-placeholder{display:none}\n`
        );
        console.log(
          `  reserved height: ${vh}vh written into ${file.fileName} (>= ${MIN_WIDTH}px only)`
        );
      }
      },
    },
  };
}

/**
 * Size breakdown by origin, so the shipping decision is made on measurements
 * rather than on a guess. Per-group gzip is each group's rendered code
 * compressed on its own: the parts do NOT sum to the whole (shared dictionary
 * across the real bundle does better), so treat them as proportions.
 */
function sizeReport(): Plugin {
  const group = (id: string) => {
    const m = id.replace(/\\/g, "/").match(/node_modules\/((?:@[^/]+\/)?[^/]+)/);
    if (!m) return id.includes("/demo/") ? "our code (demo)" : "our code (meshui)";
    const pkg = m[1];
    if (pkg === "react" || pkg === "react-dom" || pkg === "scheduler") return "react";
    if (pkg.startsWith("@xyflow")) return "react flow";
    if (pkg === "dagre" || pkg === "graphlib" || pkg === "lodash") return "dagre";
    return `other: ${pkg}`;
  };
  return {
    name: "mesh-scroll-size-report",
    writeBundle(_opts, bundle) {
      const rows = new Map<string, { bytes: number; code: string[] }>();
      for (const file of Object.values(bundle)) {
        if (file.type !== "chunk") continue;
        for (const [id, mod] of Object.entries(file.modules)) {
          const g = group(id);
          const r = rows.get(g) ?? { bytes: 0, code: [] };
          r.bytes += mod.renderedLength;
          if (mod.code) r.code.push(mod.code);
          rows.set(g, r);
        }
      }
      const zlib = require("zlib") as typeof import("zlib");
      const out = [...rows.entries()]
        .map(([name, r]) => ({
          name,
          raw: r.bytes,
          gzip: zlib.gzipSync(Buffer.from(r.code.join("\n"))).length,
        }))
        .sort((a, b) => b.gzip - a.gzip);
      const pad = (s: string, n: number) => s.padEnd(n);
      console.log("\n  JS breakdown (per-group gzip is standalone, see note)");
      for (const r of out) {
        console.log(
          `    ${pad(r.name, 20)} ${String((r.raw / 1024).toFixed(1)).padStart(7)} kB raw  ${String((r.gzip / 1024).toFixed(1)).padStart(6)} kB gz`
        );
      }
      const total = out.reduce((n, r) => n + r.raw, 0);
      console.log(`    ${pad("TOTAL (raw sum)", 20)} ${(total / 1024).toFixed(1)} kB\n`);
    },
  };
}

export default defineConfig({
  // Relative asset URLs: the stylesheet must find ./fonts/*.woff2 wherever the
  // pair is deployed, not at the site root.
  base: "./",
  // No public/ copy: the SPA's logo.svg is not part of this artifact.
  publicDir: false,
  plugins: [react(), tailwindcss(), scopeCss(), emitReservedHeight(), sizeReport()],
  resolve: {
    alias: { "@": path.resolve(__dirname, ".") },
  },
  define: {
    // React reads this; without it the IIFE ships the dev build.
    "process.env.NODE_ENV": JSON.stringify("production"),
  },
  build: {
    outDir: "demo/dist",
    emptyOutDir: true,
    cssCodeSplit: false,
    // No hashes: the docs site references these by a stable path.
    rollupOptions: {
      input: path.resolve(__dirname, "demo/embed.tsx"),
      output: {
        format: "iife",
        entryFileNames: "mesh-scroll.js",
        assetFileNames: (info) => {
          const n = info.names?.[0] ?? "";
          if (n.endsWith(".css")) return "mesh-scroll.css";
          if (n.endsWith(".woff2")) return "fonts/[name][extname]";
          return "[name][extname]";
        },
        inlineDynamicImports: true,
      },
    },
  },
});
