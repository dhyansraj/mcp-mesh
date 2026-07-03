/**
 * DDDI resolver tests for the `MeshJob` injectable (Phase 1).
 *
 * These tests are the TypeScript instance of the cross-runtime test
 * seam specified in `MESHJOB_DDDI_CONTRACT.md` → "Equivalence across
 * SDKs". The same scenarios MUST be covered by the Python and Java
 * SDKs in their corresponding files
 * (`tests/test_resolver_meshjob.py` and `MeshJobResolverTest.java`).
 *
 * If any behaviour here changes, update the contract first, then
 * mirror across both other SDK test files. Each numbered scenario maps
 * to the checklist in the contract document.
 *
 * # TS-shape note
 *
 * Python's resolver classifies parameters by reflection on
 * `inspect.signature` + `typing.get_type_hints`. TypeScript erases
 * types at runtime, so the TS resolver's input is the explicit
 * `addTool({ dependencies, meshJobParamIndex })` declaration. The
 * scenarios below translate the contract's signature-shape examples
 * into the equivalent declarative form, then assert the same
 * `meshToolDeps[*].signaturePosition` and `meshJobParamIndex` outputs
 * the contract requires.
 */

import { describe, it, expect } from "vitest";
import {
  resolveMeshJobSignature,
  ResolverError,
  type ResolvedSignature,
} from "../resolver-meshjob.js";

// ===========================================================================
// Contract scenarios 1-5 (must mirror across all three SDK test seams)
// ===========================================================================

describe("Resolver contract scenarios", () => {
  it("scenario 1: MeshTool only — unchanged behaviour", () => {
    // Python equivalent: fn(name, dep_a: McpMeshTool, dep_b: McpMeshTool)
    // → mesh_tool_positions == [1, 2], no MeshJob.
    //
    // TS declarative form: dependencies ["dep_a", "dep_b"], no
    // meshJobParamIndex. `args` lives at signature position 0; deps
    // start at position 1.
    const result = resolveMeshJobSignature({
      dependencies: ["dep_a", "dep_b"],
    });

    expect(result.meshToolDeps).toEqual<ResolvedSignature["meshToolDeps"]>([
      { depIndex: 0, signaturePosition: 1 },
      { depIndex: 1, signaturePosition: 2 },
    ]);
    expect(result.meshJobParamIndex).toBeUndefined();
  });

  it("scenario 2: MeshJob only — no tools, MeshJob index recorded", () => {
    // Python: fn(user_id, job: MeshJob) → mesh_tool_positions == [],
    // mesh_job_param_index == 1.
    const result = resolveMeshJobSignature({
      dependencies: [],
      meshJobParamIndex: 1,
    });

    expect(result.meshToolDeps).toEqual([]);
    expect(result.meshJobParamIndex).toBe(1);
  });

  it("scenario 3: both, MeshJob in middle — MeshTool positions skip MeshJob", () => {
    // Python: plan_trip(
    //   user_id: str,                      # pos 0
    //   weather_lookup: McpMeshTool,       # pos 1 — MeshTool[0]
    //   job: MeshJob,                      # pos 2 — orthogonal
    //   flight_search: McpMeshTool,        # pos 3 — MeshTool[1]
    // )
    // → mesh_tool_positions == [1, 3] (NOT [1, 2]); the resolver MUST
    // NOT renumber tool slots when MeshJob is interleaved.
    const result = resolveMeshJobSignature({
      dependencies: ["weather_lookup", "flight_search"],
      meshJobParamIndex: 2,
    });

    expect(result.meshToolDeps).toEqual([
      { depIndex: 0, signaturePosition: 1 },
      { depIndex: 1, signaturePosition: 3 }, // 3, not 2 — MeshJob skipped
    ]);
    expect(result.meshJobParamIndex).toBe(2);
  });

  it("scenario 4: neither — no DDDI metadata", () => {
    // Python: fn(a, b) → empty resolution.
    const result = resolveMeshJobSignature({ dependencies: [] });

    expect(result.meshToolDeps).toEqual([]);
    expect(result.meshJobParamIndex).toBeUndefined();
  });

  it("scenario 5: MeshJob trailing — index = last signature position", () => {
    // Python: fn(a, b, tool: McpMeshTool, job: MeshJob)
    // → mesh_tool_positions == [2], mesh_job_param_index == 3.
    //
    // TS form: one dep, MeshJob at the end. Note: in TS the user-arg
    // shape is a single `args` object, so positions a/b are inside
    // args (signature pos 0). The MeshTool dep takes pos 1 and the
    // MeshJob takes pos 2 (the last slot).
    const result = resolveMeshJobSignature({
      dependencies: ["tool"],
      meshJobParamIndex: 2,
    });

    expect(result.meshToolDeps).toEqual([
      { depIndex: 0, signaturePosition: 1 },
    ]);
    expect(result.meshJobParamIndex).toBe(2);
  });
});

// ===========================================================================
// Contract edge cases — "Edge cases (REQUIRED)" in MESHJOB_DDDI_CONTRACT.md
// ===========================================================================

describe("Resolver edge cases", () => {
  it("multiple MeshJob params raises ResolverError with the contract wording", () => {
    // Phase 1: a tool function may declare at most one MeshJob param.
    // The resolver MUST reject with the exact wording the contract
    // specifies so the developer sees the misuse at registration time.
    expect(() =>
      resolveMeshJobSignature({
        dependencies: [],
        meshJobParamIndex: 1,
        meshJobParamNames: ["firstJob", "secondJob"],
      })
    ).toThrow(ResolverError);

    try {
      resolveMeshJobSignature({
        dependencies: [],
        meshJobParamIndex: 1,
        meshJobParamNames: ["firstJob", "secondJob"],
      });
    } catch (err) {
      const msg = (err as Error).message.toLowerCase();
      // Contract wording: "a tool function may declare at most one MeshJob parameter"
      expect(msg).toContain("at most one");
      expect(msg).toContain("meshjob");
      // Both offending names should appear so the developer can fix it.
      expect(msg).toContain("firstjob");
      expect(msg).toContain("secondjob");
    }
  });

  it("MeshJob first position — orthogonal at any signature index", () => {
    // Per contract: "MeshJob mixed with MeshTool at any position —
    // permitted". The resolver MUST NOT enforce a trailing-position
    // rule.
    const result = resolveMeshJobSignature({
      dependencies: ["dep_a"],
      meshJobParamIndex: 1, // MeshJob at sig pos 1, dep slides to pos 2
    });

    expect(result.meshToolDeps).toEqual([
      { depIndex: 0, signaturePosition: 2 },
    ]);
    expect(result.meshJobParamIndex).toBe(1);
  });

  it("explicit meshToolPositions — collision with MeshJob throws", () => {
    // Defensive: if the caller supplies both meshToolPositions and
    // meshJobParamIndex and they overlap, that's a contract violation
    // — fail loudly rather than silently overwrite.
    expect(() =>
      resolveMeshJobSignature({
        dependencies: ["x"],
        meshToolPositions: [2],
        meshJobParamIndex: 2,
      })
    ).toThrow(ResolverError);
  });

  it("explicit meshToolPositions — length mismatch throws", () => {
    expect(() =>
      resolveMeshJobSignature({
        dependencies: ["a", "b"],
        meshToolPositions: [1], // length 1 vs deps length 2
      })
    ).toThrow(ResolverError);
  });
});

// ===========================================================================
// Surface tests — the public exports + JS-side contextvar (job-context.ts)
// ===========================================================================

describe("MeshJob public surface", () => {
  it("MeshJob type marker is importable from the package types module", async () => {
    // Smoke test the export so a typo doesn't silently break the
    // public API. We dynamic-import to assert it parses; the
    // type-only import at the top of this file would be erased by
    // tsc and not fail at runtime if the export disappeared.
    const types = await import("../types.js");
    // MeshJob is an interface (erased at runtime) — verify it's at
    // least a key on the module type so consumers can `import type`
    // it. The runtime presence we care about is the resolver +
    // job-context, exercised by the other suites.
    expect(types).toBeDefined();
  });

  it("currentJob() returns null outside any active job scope", async () => {
    const { currentJob, remainingSeconds } = await import("../job-context.js");
    expect(currentJob()).toBeNull();
    expect(remainingSeconds()).toBeNull();
  });

  it("withJobAsync sets CURRENT_JOB visible to currentJob() inside the scope", async () => {
    const { currentJob, remainingSeconds, withJobAsync } = await import(
      "../job-context.js"
    );

    const inside = await withJobAsync(
      { jobId: "job-set", deadlineSecsRemaining: 12.5, claimEpoch: null },
      async () => {
        const cur = currentJob();
        expect(cur).not.toBeNull();
        expect(cur?.jobId).toBe("job-set");
        expect(remainingSeconds()).toBe(12.5);
        return "done";
      }
    );
    expect(inside).toBe("done");

    // Outside the scope: gone again.
    expect(currentJob()).toBeNull();
  });

  it("snapshot with no deadline returns null remainingSeconds", async () => {
    const { remainingSeconds, withJobAsync } = await import("../job-context.js");

    await withJobAsync(
      { jobId: "job-no-deadline", deadlineSecsRemaining: null, claimEpoch: null },
      async () => {
        expect(remainingSeconds()).toBeNull();
      }
    );
  });
});
