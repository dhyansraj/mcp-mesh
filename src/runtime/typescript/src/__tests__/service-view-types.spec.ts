/**
 * Strict-mode COMPILE test for the documented service-view consumer idiom
 * (RFC #1280). The failure mode this guards against: "docs show code that
 * doesn't compile." The project's `tsc --noEmit` (strict) type-checks this file,
 * so if the documented idiom in service-view.ts's `MeshServiceFacade` JSDoc ever
 * stops compiling, the build breaks here.
 *
 * The idiom functions below are never INVOKED (they'd construct a real
 * MeshAgent); they exist purely so the compiler checks their bodies. Vitest runs
 * the trivial assertion so this counts as a spec.
 */
import { describe, it, expect } from "vitest";
import { z } from "zod";
import { mesh, type MeshServiceFacade, type McpMeshTool } from "../index.js";

// ── The canonical documented idiom, verbatim: un-annotated params + a cast on
// the view slot at point of use. Must compile under strictFunctionTypes. ──────
function _documentedConsumerIdiom(): void {
  const server = {} as unknown as import("fastmcp").FastMCP;
  const agent = mesh(server, { name: "example", httpPort: 0 });

  const Media = mesh.serviceView({
    methods: {
      caption: { capability: "media.caption", required: true, tags: ["+fast"] },
      thumbnail: "media.thumbnail",
    },
    minAvailable: 1,
  });

  agent.addTool({
    name: "process",
    parameters: z.object({ text: z.string() }),
    dependencies: ["audit_log", Media],
    execute: async (args, auditLog, media) => {
      const svc = media as MeshServiceFacade<typeof Media>;
      // Both spec method keys are typed on the facade, callable with the
      // McpMeshTool signature (args?, options?) => Promise<unknown>.
      const cap = await svc.caption({ text: args.text });
      await svc.thumbnail();
      // Ordinary McpMeshTool deps are consumed with the same cast idiom.
      const audit = auditLog as McpMeshTool | null;
      if (audit) await audit({ event: "captioned" });
      return cap;
    },
  });
}

// ── The facade type maps each method key to a callable (compile-time only). ───
type _MediaFacade = MeshServiceFacade<
  ReturnType<
    typeof mesh.serviceView<{ methods: { caption: "media.caption" } }>
  >
>;
const _facadeMethodIsCallable: _MediaFacade["caption"] = async () => undefined;

describe("service-view documented idiom compiles under strict", () => {
  it("type-checks the consumer idiom (compile-only)", () => {
    expect(typeof _documentedConsumerIdiom).toBe("function");
    expect(typeof _facadeMethodIsCallable).toBe("function");
  });
});
