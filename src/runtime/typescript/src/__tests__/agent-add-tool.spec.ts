/**
 * `addTool` registration-time validation tests (Phase 1 — MeshJob substrate).
 *
 * Targets the misuse-detection layer in `agent.ts`'s `addTool` —
 * specifically the `meshJobParamIndex` invariants from the BLOCKER
 * review finding on PR #883:
 *
 *   - position 0 is reserved for the `args` payload, so the controller
 *     can only land at sig pos 1+;
 *   - non-integer values (NaN, 1.5, etc.) silently skipped controller
 *     injection before the fix → user saw `null` where they expected
 *     a `JobController` and got a cryptic `TypeError` at first await;
 *   - the upper bound (10) is a sanity check for typos.
 *
 * The test stubs FastMCP minimally and overrides `_autoStart` on the
 * prototype to keep the auto-scheduled startup from spinning up an HTTP
 * server during the test run.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { z } from "zod";
import type { JobController } from "@mcpmesh/core";
import { MeshAgent } from "../agent.js";
import { spliceJobController } from "../inbound-job-dispatch.js";

// Minimal FastMCP stub: `addTool` is the only surface `addTool`
// validation reaches BEFORE throwing. `start`, `getApp`, etc. would
// only run inside `_autoStart` — which we stub out below.
function makeFastMCPStub() {
  return {
    addTool: vi.fn(),
    start: vi.fn(),
    getApp: vi.fn(),
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
  } as any;
}

// Spy on `_autoStart` so the auto-scheduled `process.nextTick(...)`
// call inside the constructor doesn't actually start an HTTP server /
// reach out to a registry. The validation we're testing happens
// synchronously inside `addTool`, before any auto-start.
let autoStartSpy: ReturnType<typeof vi.spyOn> | null = null;

beforeEach(() => {
  autoStartSpy = vi
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    .spyOn(MeshAgent.prototype as any, "_autoStart")
    .mockImplementation(async () => {
      /* no-op */
    });
});

afterEach(() => {
  if (autoStartSpy) {
    autoStartSpy.mockRestore();
    autoStartSpy = null;
  }
});

describe("addTool — meshJobParamIndex validation", () => {
  function newAgent(): MeshAgent {
    return new MeshAgent(makeFastMCPStub(), {
      name: "test-agent",
      httpPort: 0,
    });
  }

  it("rejects 0 (position 0 is reserved for args)", () => {
    const agent = newAgent();
    expect(() =>
      agent.addTool({
        name: "bad-zero",
        task: true,
        parameters: z.object({}),
        meshJobParamIndex: 0,
        execute: async () => "x",
      }),
    ).toThrow(/meshJobParamIndex must be an integer >= 1.*got: 0/);
  });

  it("rejects negative values", () => {
    const agent = newAgent();
    expect(() =>
      agent.addTool({
        name: "bad-neg",
        task: true,
        parameters: z.object({}),
        meshJobParamIndex: -1,
        execute: async () => "x",
      }),
    ).toThrow(/meshJobParamIndex must be an integer >= 1.*got: -1/);
  });

  it("rejects NaN", () => {
    const agent = newAgent();
    expect(() =>
      agent.addTool({
        name: "bad-nan",
        task: true,
        parameters: z.object({}),
        meshJobParamIndex: Number.NaN,
        execute: async () => "x",
      }),
    ).toThrow(/meshJobParamIndex must be an integer >= 1.*got: NaN/);
  });

  it("rejects non-integer (1.5)", () => {
    const agent = newAgent();
    expect(() =>
      agent.addTool({
        name: "bad-frac",
        task: true,
        parameters: z.object({}),
        meshJobParamIndex: 1.5,
        execute: async () => "x",
      }),
    ).toThrow(/meshJobParamIndex must be an integer >= 1.*got: 1\.5/);
  });

  it("rejects values beyond a sane upper bound (typo guard)", () => {
    const agent = newAgent();
    expect(() =>
      agent.addTool({
        name: "bad-big",
        task: true,
        parameters: z.object({}),
        meshJobParamIndex: 99,
        execute: async () => "x",
      }),
    ).toThrow(/meshJobParamIndex must be an integer >= 1.*got: 99/);
  });

  it("accepts 1 (most common case — no deps, just a controller)", () => {
    const agent = newAgent();
    expect(() =>
      agent.addTool({
        name: "ok-one",
        task: true,
        parameters: z.object({}),
        meshJobParamIndex: 1,
        execute: async () => "x",
      }),
    ).not.toThrow();
  });

  it("accepts 3 (controller after a couple of deps)", () => {
    const agent = newAgent();
    expect(() =>
      agent.addTool({
        name: "ok-three",
        task: true,
        parameters: z.object({}),
        dependencies: ["a", "b"],
        meshJobParamIndex: 3,
        execute: async () => "x",
      }),
    ).not.toThrow();
  });
});

describe("addTool — meshJobDepIndex validation", () => {
  function newAgent(): MeshAgent {
    return new MeshAgent(makeFastMCPStub(), {
      name: "test-agent-depidx",
      httpPort: 0,
    });
  }

  it("rejects negative values", () => {
    const agent = newAgent();
    expect(() =>
      agent.addTool({
        name: "bad-neg",
        parameters: z.object({}),
        dependencies: ["a"],
        meshJobDepIndex: -1,
        execute: async () => "x",
      }),
    ).toThrow(/meshJobDepIndex must be a non-negative integer.*got: -1/);
  });

  it("rejects NaN", () => {
    const agent = newAgent();
    expect(() =>
      agent.addTool({
        name: "bad-nan",
        parameters: z.object({}),
        dependencies: ["a"],
        meshJobDepIndex: Number.NaN,
        execute: async () => "x",
      }),
    ).toThrow(/meshJobDepIndex must be a non-negative integer.*got: NaN/);
  });

  it("rejects fractional values", () => {
    const agent = newAgent();
    expect(() =>
      agent.addTool({
        name: "bad-frac",
        parameters: z.object({}),
        dependencies: ["a", "b"],
        meshJobDepIndex: 0.5,
        execute: async () => "x",
      }),
    ).toThrow(/meshJobDepIndex must be a non-negative integer.*got: 0\.5/);
  });

  it("rejects out-of-range values (>= depCount) with the original range error", () => {
    const agent = newAgent();
    expect(() =>
      agent.addTool({
        name: "bad-oor",
        parameters: z.object({}),
        dependencies: ["a"], // length 1
        meshJobDepIndex: 5,
        execute: async () => "x",
      }),
    ).toThrow(/out of range — the tool declares 1 dependencies/);
  });

  it("accepts 0 (first dep is the MeshJob slot)", () => {
    const agent = newAgent();
    expect(() =>
      agent.addTool({
        name: "ok-zero",
        parameters: z.object({}),
        dependencies: ["a", "b"],
        meshJobDepIndex: 0,
        execute: async () => "x",
      }),
    ).not.toThrow();
  });
});

// =============================================================================
// W1 — splice helper (de-duplicated splice loop)
// =============================================================================

describe("spliceJobController helper", () => {
  // The helper is purely positional — pass primitive sentinels so
  // the assertions don't depend on McpMeshTool / JobController types.
  const C = "<<controller>>" as unknown as JobController;

  it("returns just [payload] when no deps and no MeshJob slot", () => {
    expect(spliceJobController({ p: 1 }, [], null, undefined)).toEqual([
      { p: 1 },
    ]);
  });

  it("appends deps after payload when no meshJobParamIndex", () => {
    expect(
      spliceJobController({ p: 1 }, ["d0", "d1"], C, undefined),
    ).toEqual([{ p: 1 }, "d0", "d1"]);
  });

  it("places controller at sig pos 1 when no deps and meshJobParamIndex=1", () => {
    expect(spliceJobController({ p: 1 }, [], C, 1)).toEqual([{ p: 1 }, C]);
  });

  it("interleaves: meshJobParamIndex=2 with two deps shifts the second dep past the controller", () => {
    // signature: (args, dep0, controller, dep1)
    expect(
      spliceJobController({ p: 1 }, ["d0", "d1"], C, 2),
    ).toEqual([{ p: 1 }, "d0", C, "d1"]);
  });

  it("trailing slot: meshJobParamIndex=3 with one dep pads with null and places controller at the trailing position", () => {
    // signature: (args, dep0, ?, controller) — pos 2 has no dep, pads null.
    expect(spliceJobController({ p: 1 }, ["d0"], C, 3)).toEqual([
      { p: 1 },
      "d0",
      null,
      C,
    ]);
  });

  it("uses null for the controller slot when caller passes null", () => {
    // The wrapper passes `null` when the call is NOT running under a job
    // context — the helper must still reserve the slot at meshJobParamIndex.
    expect(spliceJobController({ p: 1 }, ["d0"], null, 1)).toEqual([
      { p: 1 },
      null,
      "d0",
    ]);
  });
});

// =============================================================================
// W4 — worker-isolation force-disable warning visibility
// =============================================================================

describe("addTool — W4 worker-isolation force-disable warning", () => {
  let warnSpy: ReturnType<typeof vi.spyOn>;
  const originalEnv = process.env.MCP_MESH_TOOL_ISOLATION;

  beforeEach(() => {
    warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
  });
  afterEach(() => {
    warnSpy.mockRestore();
    if (originalEnv === undefined) {
      delete process.env.MCP_MESH_TOOL_ISOLATION;
    } else {
      process.env.MCP_MESH_TOOL_ISOLATION = originalEnv;
    }
  });

  function newAgent(): MeshAgent {
    return new MeshAgent(makeFastMCPStub(), {
      name: "test-agent-w4",
      httpPort: 0,
    });
  }

  it("does NOT warn when isolation env is unset (default)", () => {
    delete process.env.MCP_MESH_TOOL_ISOLATION;
    const agent = newAgent();
    agent.addTool({
      name: "task-tool",
      task: true,
      parameters: z.object({}),
      execute: async () => "x",
    });
    const isolationCall = warnSpy.mock.calls.find((c) =>
      String(c[0]).includes("worker isolation"),
    );
    expect(isolationCall).toBeUndefined();
  });

  it("warns when MCP_MESH_TOOL_ISOLATION=true is set explicitly for a task: true tool", () => {
    process.env.MCP_MESH_TOOL_ISOLATION = "true";
    const agent = newAgent();
    agent.addTool({
      name: "task-tool",
      task: true,
      parameters: z.object({}),
      execute: async () => "x",
    });
    const isolationCall = warnSpy.mock.calls.find((c) =>
      String(c[0]).includes("worker isolation is disabled"),
    );
    expect(isolationCall).toBeDefined();
    expect(String(isolationCall![0])).toContain("'task-tool'");
    expect(String(isolationCall![0])).toContain("task: true");
  });

  it("warns for meshJobDepIndex consumer tools too", () => {
    process.env.MCP_MESH_TOOL_ISOLATION = "true";
    const agent = newAgent();
    agent.addTool({
      name: "consumer-tool",
      parameters: z.object({}),
      dependencies: ["producer"],
      meshJobDepIndex: 0,
      execute: async () => "x",
    });
    const isolationCall = warnSpy.mock.calls.find((c) =>
      String(c[0]).includes("worker isolation is disabled"),
    );
    expect(isolationCall).toBeDefined();
    expect(String(isolationCall![0])).toContain("'consumer-tool'");
    expect(String(isolationCall![0])).toContain("meshJobDepIndex: 0");
  });

  it("does NOT warn when isolation env is explicitly set to 'false'", () => {
    process.env.MCP_MESH_TOOL_ISOLATION = "false";
    const agent = newAgent();
    agent.addTool({
      name: "task-tool",
      task: true,
      parameters: z.object({}),
      execute: async () => "x",
    });
    const isolationCall = warnSpy.mock.calls.find((c) =>
      String(c[0]).includes("worker isolation"),
    );
    expect(isolationCall).toBeUndefined();
  });

  it("does NOT warn for non-job-bound tools regardless of env", () => {
    process.env.MCP_MESH_TOOL_ISOLATION = "true";
    const agent = newAgent();
    agent.addTool({
      name: "regular-tool",
      parameters: z.object({}),
      execute: async () => "x",
    });
    const isolationCall = warnSpy.mock.calls.find((c) =>
      String(c[0]).includes("worker isolation"),
    );
    expect(isolationCall).toBeUndefined();
  });
});
