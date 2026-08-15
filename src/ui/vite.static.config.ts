// Build config for the PRERENDERED docs-site bundle.
//
// Deliberately a thin file: every plugin comes from vite.demo.config.ts, so the
// CSS scoper, the reserved-height emitter and the size report are ONE
// implementation shared by both bundles. Forking the scoper would have been the
// easy move and a bad one — it is 200 lines of hard-won rules about @layer,
// rem and keyframe namespacing, and two copies would diverge silently the first
// time one of them was fixed.
//
// The two bundles differ in exactly three ways:
//   entry     demo/static.ts   (vanilla driver)  vs  demo/embed.tsx  (React)
//   outDir    demo/dist-static                   vs  demo/dist
//   plugins   no @vitejs/plugin-react — there is no JSX left to transform
//
// Filenames are intentionally IDENTICAL to the React bundle's, so switching
// which one ships is a one-line change in the Makefile rather than an edit to
// the docs loader.
//
//   npx vite build --config vite.static.config.ts
//
// The entry imports demo/generated/graph.json, which demo/emit.tsx must have
// written first — see the docs-scroll-prerender target, which every build target
// here depends on.
import { defineConfig } from "vite";
import tailwindcss from "@tailwindcss/vite";
import path from "path";

import { scopeCss, emitReservedHeight, sizeReport } from "./vite.demo.config";
import { shipFontLicence } from "./vite.fonts";
import { pinProductionBuild } from "./vite.env";

// A FACTORY, NOT A PLAIN OBJECT, so the production pin has somewhere to run —
// see vite.env.ts. Nothing this bundle imports switches on export condition
// today, so the two builds are byte-identical with and without the pin; it is
// here because THIS is the artifact the docs site publishes and the thing that
// makes the pin matter is a dependency nobody has added yet. Uniform across all
// three configs is also the only version of this rule anyone can check.
export default defineConfig(({ command }) => {
  pinProductionBuild(command);

  return {
    base: "./",
    publicDir: false,
    // shipFontLicence takes the directory this bundle puts its woff2 files in,
    // so the licence is published next to the fonts it covers. THIS is the
    // bundle the docs site serves — the artifact gate in
    // .github/workflows/docs.yml lists fonts/OFL.txt for exactly this reason.
    plugins: [
      tailwindcss(),
      scopeCss(),
      emitReservedHeight(),
      sizeReport(),
      shipFontLicence("fonts"),
    ],
    resolve: {
      alias: { "@": path.resolve(__dirname, ".") },
    },
    build: {
      outDir: "demo/dist-static",
      emptyOutDir: true,
      cssCodeSplit: false,
      rollupOptions: {
        input: path.resolve(__dirname, "demo/static.ts"),
        output: {
          format: "iife" as const,
          entryFileNames: "mesh-scroll.js",
          assetFileNames: (info: { names?: string[] }) => {
            const n = info.names?.[0] ?? "";
            if (n.endsWith(".css")) return "mesh-scroll.css";
            if (n.endsWith(".woff2")) return "fonts/[name][extname]";
            return "[name][extname]";
          },
          inlineDynamicImports: true,
        },
      },
    },
  };
});
