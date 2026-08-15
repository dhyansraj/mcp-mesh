// A BUILD SHIPS PRODUCTION, whatever the shell it was started from believed.
//
// Vite reads process.env.NODE_ENV from its environment and only defaults it
// when unset, so a build inherits whatever the caller had. vitest sets
// NODE_ENV=test across its whole process tree, and the two tests that shell out
// to `vite build` were therefore leaving a 1,087,205 B development bundle in
// dist/ where the production one is 722,653 B — and dist/ is the directory
// //go:embed compiles into the meshui binary. Nothing downstream could see it:
// the stylesheet is byte-identical either way, so every size and content check
// in the suite passed against the wrong bundle for as long as it existed.
//
// ASSIGNING THE VARIABLE IS NOT THE SAME AS DEFINING IT FOR THE BUNDLE, and the
// difference is not cosmetic. Vite derives isProduction from this variable AFTER
// it loads a config file, and isProduction is what puts "production" into
// resolve.conditions — which is how every dependency that publishes split entry
// points picks one. A `define` only rewrites the expression in code that reads
// it: with only a define, React came out correct and the dashboard bundle was
// still 882,126 B, because the packages that switch by export condition had all
// resolved their development builds. The same measurement on the docs-site React
// bundle is 562,474 B against 546,096 B. Vite's own diagnostic for NODE_ENV in a
// .env file says to set it in the config instead; this is that.
//
// ONE IMPLEMENTATION FOR ALL THREE CONFIGS. vite.config.ts, vite.demo.config.ts
// and vite.static.config.ts each redistribute the same fonts and each have the
// same exposure, and a rule this subtle written out three times is a rule that
// will hold in two places. Pinned inside the configs rather than at each caller
// so it also holds for `make ui-build` and `make docs-scroll-build`, which are
// the paths that actually feed the binary and the docs site.

/**
 * Pin NODE_ENV to production for the duration of a build.
 *
 * BUILD ONLY, ON PURPOSE. The dev server wants React's development build, and
 * vitest loads vite.config.ts to run the suite — neither may be forced.
 *
 * Call this at the top of a config factory, before returning the config object:
 * Vite reads the variable once the factory has returned, so the assignment has
 * to happen while it is still running. That is also why every config here is a
 * factory rather than a plain object — a plain object gives the pin nowhere to
 * run.
 */
export function pinProductionBuild(command: string): void {
  if (command === "build") process.env.NODE_ENV = "production";
}
