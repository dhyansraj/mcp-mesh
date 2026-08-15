// The licence travels with the fonts, into every artifact that carries them.
//
// SIL Open Font License 1.1, clause 2: the copyright notice and the licence go
// wherever the font software is redistributed, "in original or modified form".
// Three builds here redistribute fonts/*.woff2 — the dashboard, which is
// compiled whole into the meshui binary by //go:embed all:dist, and the two
// docs-site bundles, which are published as files. A notice that exists only in
// the source tree is reachable by whoever clones the repo and by nobody who
// receives what it builds.
//
// Nothing would carry a .txt file on its own: no stylesheet references it and
// no module imports it, so it is emitted deliberately or not at all.
//
// ONE COPY ON DISK, and it is the authored one. The alternative was a second
// checked-in copy under public/, which Vite copies verbatim and which would
// therefore need no plugin — but it would sit away from the payloads, and the
// copy a reader edits when the fonts are next replaced is the one next to the
// files. That is how two copies start disagreeing about which version of which
// font they describe. Emitting the authored file makes the shipped bytes equal
// to it by construction; __tests__/dashboard-fonts.test.ts asserts they are.
import fs from "node:fs";
import path from "node:path";
import type { Plugin } from "vite";

/** Authored beside the payloads it describes, on ground both bundles share. */
const NOTICE = path.resolve(__dirname, "fonts", "OFL.txt");

/**
 * Emit fonts/OFL.txt into the build output.
 *
 * `dir` is where that particular build puts its woff2 files, so the notice
 * lands beside them rather than somewhere a reader has to already know about.
 * Defaults to the build's asset directory, which is where Vite's own asset
 * pipeline puts anything a stylesheet points at.
 */
export function shipFontLicence(dir?: string): Plugin {
  let target = dir;
  return {
    name: "ship-font-licence",
    configResolved(config) {
      target ??= config.build.assetsDir;
    },
    generateBundle() {
      let source: Buffer;
      try {
        source = fs.readFileSync(NOTICE);
      } catch {
        // Failing the build is the point. The fonts would otherwise ship
        // without the notice the licence requires, and a missing file is not
        // something a build log makes anyone look at.
        this.error(
          `${path.relative(process.cwd(), NOTICE)} is missing, and this build ships ` +
            "the fonts it covers. The SIL Open Font License requires the notice to " +
            "be included with every redistribution of the font software, so put the " +
            "file back rather than removing this plugin."
        );
        return;
      }
      this.emitFile({
        type: "asset",
        fileName: path.posix.join(target ?? "", "OFL.txt"),
        source,
      });
    },
  };
}
