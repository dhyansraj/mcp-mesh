/**
 * Service views (RFC #1280) — TypeScript runtime.
 *
 * Cross-runtime contract (mirrors the Java uc37 suite):
 *
 *  - CONSUMER VIEW: a `mesh.serviceView(...)` entry in a tool's `dependencies`
 *    array occupies ONE positional slot but expands into N ordinary edges (one
 *    per method, NAME-SORTED, in-place). The framework injects a facade at that
 *    slot; each facade method delegates to its edge's own resolved proxy and
 *    rebinds independently. The flat edge array is what ships / settles /
 *    resolves — zero wire change; a view-free tool is byte-identical.
 *
 *  - PRODUCER SUGAR: `agent.addService("prefix", { ... })` publishes each entry
 *    (name-sorted) as an ordinary tool with capability `prefix.<method>`.
 *
 * Covers: expansion order (explicit + view + explicit; multi-view; name-sort),
 * settle keys per edge, payload carries N edges with required flags, facade
 * delegation + rebinding, required refusal (direct + job flavors), the
 * minAvailable floor (below/at, settle-aware wait), unresolved optional method
 * error, all validation throws, producer addService, and serviceView-in-route.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { z } from "zod";
import { UserError } from "fastmcp";

// Mock only makeJobController (wraps a napi handle hitting the registry). The
// REAL readJobHeaders runs so the job-dispatch classification path is exercised.
const h = vi.hoisted(() => {
  const releaseLeaseMock = vi.fn(async () => {});
  const failMock = vi.fn(async () => {});
  const makeJobControllerMock = vi.fn(() => ({
    releaseLease: releaseLeaseMock,
    fail: failMock,
  }));
  return { releaseLeaseMock, failMock, makeJobControllerMock };
});

vi.mock("../inbound-job-dispatch.js", async (importActual) => {
  const actual = await importActual<typeof import("../inbound-job-dispatch.js")>();
  return {
    ...actual,
    makeJobController:
      h.makeJobControllerMock as unknown as typeof actual.makeJobController,
  };
});

import { MeshAgent } from "../agent.js";
import { RouteRegistry, route } from "../route.js";
import { mount as a2aMount } from "../a2a/producer/index.js";
import { ClaimDispatcher } from "../claim-dispatcher.js";
import { MeshJobSubmitter } from "../mesh-job-submitter.js";
import { normalizeSchemaWithPolicy } from "../schema-normalize.js";
import {
  serviceView,
  isServiceView,
  assertNoServiceViewDeps,
  MeshServiceUnavailableError,
} from "../service-view.js";
import {
  getSettleState,
  resetSettleStateForTests,
} from "../settle.js";

function makeFastMCPStub() {
  return {
    addTool: vi.fn(),
    start: vi.fn(),
    getApp: vi.fn(),
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
  } as any;
}

let autoStartSpy: ReturnType<typeof vi.spyOn> | null = null;
let warnSpy: ReturnType<typeof vi.spyOn> | null = null;
const savedEnv: Record<string, string | undefined> = {};
let agentCounter = 0;

beforeEach(() => {
  h.releaseLeaseMock.mockClear();
  h.makeJobControllerMock.mockClear();
  autoStartSpy = vi
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    .spyOn(MeshAgent.prototype as any, "_autoStart")
    .mockImplementation(async () => {
      /* no-op */
    });
  warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {
    /* swallow */
  });
  savedEnv.MCP_MESH_SETTLE_TIMEOUT = process.env.MCP_MESH_SETTLE_TIMEOUT;
  savedEnv.MCP_MESH_TOOL_ISOLATION = process.env.MCP_MESH_TOOL_ISOLATION;
  process.env.MCP_MESH_TOOL_ISOLATION = "false";
  // Settle immediately by default so an unresolved edge is genuinely unresolved.
  // Floor-wait tests override with a positive budget.
  process.env.MCP_MESH_SETTLE_TIMEOUT = "0";
  resetSettleStateForTests();
  RouteRegistry.reset();
});

afterEach(() => {
  autoStartSpy?.mockRestore();
  autoStartSpy = null;
  warnSpy?.mockRestore();
  warnSpy = null;
  for (const [key, value] of Object.entries(savedEnv)) {
    if (value === undefined) delete process.env[key];
    else process.env[key] = value;
  }
  resetSettleStateForTests();
  RouteRegistry.reset();
});

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function newAgent(fastmcp: any): MeshAgent {
  return new MeshAgent(fastmcp, {
    name: `view-agent-${agentCounter++}`,
    httpPort: 0,
  });
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function captureExecute(fastmcp: any, idx = 0): (args: unknown) => Promise<string> {
  return fastmcp.addTool.mock.calls[idx][0].execute as (
    args: unknown,
  ) => Promise<string>;
}

/** Inject a fake callable proxy at a tool's flat edge slot. */
function injectEdge(
  agent: MeshAgent,
  toolName: string,
  edgeIndex: number,
  impl: (args?: Record<string, unknown>, options?: unknown) => Promise<unknown>,
): void {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  (agent as any).resolvedDeps.set(`${toolName}:dep_${edgeIndex}`, impl);
}

function removeEdge(agent: MeshAgent, toolName: string, edgeIndex: number): void {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  (agent as any).resolvedDeps.delete(`${toolName}:dep_${edgeIndex}`);
}

/** Read the flat normalized-edge array the tool ships to the registry. */
function edgesOf(
  agent: MeshAgent,
  toolName: string,
): Array<{ capability: string; required?: boolean; tags: unknown }> {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  return (agent as any).tools.get(toolName).dependencies;
}

describe("serviceView() factory + brand", () => {
  it("brands the returned value", () => {
    const v = serviceView({ methods: { a: "cap.a" } });
    expect(isServiceView(v)).toBe(true);
    expect(isServiceView({ methods: {} })).toBe(false);
    expect(isServiceView("cap.a")).toBe(false);
    expect(isServiceView(null)).toBe(false);
  });
});

describe("expansion order + slot layout", () => {
  it("explicit + view + explicit: edges expand in-place, view = one facade slot", async () => {
    const fastmcp = makeFastMCPStub();
    const agent = newAgent(fastmcp);
    const Media = serviceView({
      // Declared out of order to prove name-sorting.
      methods: { thumbnail: "media.thumbnail", caption: "media.caption" },
    });
    const seen: unknown[] = [];
    agent.addTool({
      name: "process",
      parameters: z.object({}),
      dependencies: ["audit_log", Media, "metrics"],
      execute: async (
        _args: unknown,
        audit: unknown,
        media: unknown,
        metrics: unknown,
      ) => {
        seen.push(audit, media, metrics);
        return "ok";
      },
    });

    // Flat edges: audit(0), caption(1), thumbnail(2), metrics(3) — view methods
    // NAME-SORTED and expanded in-place at the view's array position.
    expect(edgesOf(agent, "process").map((d) => d.capability)).toEqual([
      "audit_log",
      "media.caption",
      "media.thumbnail",
      "metrics",
    ]);

    // Wire up the two explicit deps + both view edges.
    injectEdge(agent, "process", 0, async () => "audit-proxy");
    injectEdge(agent, "process", 1, async (a) => ({ cap: "caption", a }));
    injectEdge(agent, "process", 2, async (a) => ({ cap: "thumbnail", a }));
    injectEdge(agent, "process", 3, async () => "metrics-proxy");

    await captureExecute(fastmcp)({});
    const [audit, media, metrics] = seen as [
      (a?: Record<string, unknown>) => Promise<unknown>,
      Record<string, (a?: Record<string, unknown>) => Promise<unknown>>,
      (a?: Record<string, unknown>) => Promise<unknown>,
    ];

    // Explicit slots receive their own proxies; the view slot is a facade.
    expect(await audit()).toBe("audit-proxy");
    expect(await metrics()).toBe("metrics-proxy");
    expect(typeof media.caption).toBe("function");
    expect(typeof media.thumbnail).toBe("function");
    expect(await media.caption({ text: "hi" })).toEqual({
      cap: "caption",
      a: { text: "hi" },
    });
    expect(await media.thumbnail({ id: "x" })).toEqual({
      cap: "thumbnail",
      a: { id: "x" },
    });
  });

  it("multiple views expand into disjoint contiguous edge ranges", async () => {
    const fastmcp = makeFastMCPStub();
    const agent = newAgent(fastmcp);
    const ViewA = serviceView({ methods: { b: "svc.b", a: "svc.a" } });
    const ViewB = serviceView({ methods: { c: "svc.c" } });
    const seen: unknown[] = [];
    agent.addTool({
      name: "multi",
      parameters: z.object({}),
      dependencies: [ViewA, ViewB],
      execute: async (_args: unknown, va: unknown, vb: unknown) => {
        seen.push(va, vb);
        return "ok";
      },
    });

    expect(edgesOf(agent, "multi").map((d) => d.capability)).toEqual([
      "svc.a", // ViewA edge 0
      "svc.b", // ViewA edge 1
      "svc.c", // ViewB edge 2
    ]);

    injectEdge(agent, "multi", 0, async () => "A.a");
    injectEdge(agent, "multi", 1, async () => "A.b");
    injectEdge(agent, "multi", 2, async () => "B.c");

    await captureExecute(fastmcp)({});
    const [va, vb] = seen as [
      Record<string, () => Promise<unknown>>,
      Record<string, () => Promise<unknown>>,
    ];
    expect(Object.keys(va).sort()).toEqual(["a", "b"]);
    expect(Object.keys(vb)).toEqual(["c"]);
    expect(await va.a()).toBe("A.a");
    expect(await va.b()).toBe("A.b");
    expect(await vb.c()).toBe("B.c");
  });

  it("view-free tool is byte-identical (slot index === edge index)", async () => {
    const fastmcp = makeFastMCPStub();
    const agent = newAgent(fastmcp);
    agent.addTool({
      name: "plain",
      parameters: z.object({}),
      dependencies: ["a", { capability: "b", required: true }],
      execute: async () => "ok",
    });
    const edges = edgesOf(agent, "plain");
    expect(edges.map((d) => d.capability)).toEqual(["a", "b"]);
    expect(edges[1].required).toBe(true);
  });
});

describe("wire payload + settle keys", () => {
  it("payload carries N edges with per-method required flags", () => {
    const fastmcp = makeFastMCPStub();
    const agent = newAgent(fastmcp);
    const View = serviceView({
      methods: {
        caption: { capability: "media.caption", required: true, tags: ["+fast"] },
        thumbnail: "media.thumbnail",
      },
    });
    agent.addTool({
      name: "gen",
      parameters: z.object({}),
      dependencies: [View],
      execute: async () => "ok",
    });
    const edges = edgesOf(agent, "gen");
    expect(edges.map((d) => d.capability)).toEqual([
      "media.caption",
      "media.thumbnail",
    ]);
    // required=true only on the caption edge; thumbnail stays soft (undefined).
    expect(edges[0].required).toBe(true);
    expect(edges[1].required).toBeUndefined();
    expect(edges[0].tags).toEqual(["+fast"]);
  });

  it("registers a settle key per edge (agent settles only when ALL resolve)", () => {
    const fastmcp = makeFastMCPStub();
    const agent = newAgent(fastmcp);
    const View = serviceView({ methods: { a: "svc.a", b: "svc.b" } });
    process.env.MCP_MESH_SETTLE_TIMEOUT = "30";
    resetSettleStateForTests();
    agent.addTool({
      name: "svt",
      parameters: z.object({}),
      dependencies: [View],
      execute: async () => "ok",
    });
    const settle = getSettleState();
    expect(settle.isSettled()).toBe(false);
    // Resolve edge 0 only → still unsettled (edge 1 pending).
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (agent as any).handleDependencyAvailable(
      "svc.a",
      "http://localhost:19999",
      "fn",
      "prov",
      "svt",
      0,
    );
    expect(settle.isSettled()).toBe(false);
    // Resolve edge 1 → last declared key → eager latch flips.
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (agent as any).handleDependencyAvailable(
      "svc.b",
      "http://localhost:19999",
      "fn",
      "prov",
      "svt",
      1,
    );
    expect(settle.isSettled()).toBe(true);
  });
});

describe("facade delegation + rebinding", () => {
  it("reads the CURRENT per-edge proxy at call time (rebinding-free)", async () => {
    const fastmcp = makeFastMCPStub();
    const agent = newAgent(fastmcp);
    const View = serviceView({ methods: { chat: "llm.chat" } });
    const seen: unknown[] = [];
    agent.addTool({
      name: "talk",
      parameters: z.object({}),
      dependencies: [View],
      execute: async (_a: unknown, v: unknown) => {
        seen.push(v);
        return "ok";
      },
    });
    injectEdge(agent, "talk", 0, async () => "provider-1");
    await captureExecute(fastmcp)({});
    const facade = seen[0] as Record<string, () => Promise<unknown>>;
    expect(await facade.chat()).toBe("provider-1");

    // Simulate a rebind: dependency_available swaps the edge proxy.
    injectEdge(agent, "talk", 0, async () => "provider-2");
    expect(await facade.chat()).toBe("provider-2");

    // Simulate dependency_unavailable: the edge is dropped → optional call
    // throws the null-proxy shape (TypeError).
    removeEdge(agent, "talk", 0);
    await expect(facade.chat()).rejects.toBeInstanceOf(TypeError);
  });
});

describe("required=true view method refusal", () => {
  it("direct tools/call refuses with dependency_unavailable", async () => {
    const fastmcp = makeFastMCPStub();
    const agent = newAgent(fastmcp);
    const View = serviceView({
      methods: { caption: { capability: "media.caption", required: true } },
    });
    const ran: unknown[] = [];
    agent.addTool({
      name: "req_direct",
      parameters: z.object({}),
      dependencies: [View],
      execute: async () => {
        ran.push(true);
        return "ran";
      },
    });
    let thrown: unknown;
    try {
      await captureExecute(fastmcp)({});
    } catch (err) {
      thrown = err;
    }
    expect(thrown).toBeInstanceOf(UserError);
    expect(JSON.parse((thrown as Error).message)).toEqual({
      error: "dependency_unavailable",
      capability: "media.caption",
    });
    expect(ran).toHaveLength(0);
    expect(h.releaseLeaseMock).not.toHaveBeenCalled();
  });

  it("inbound JOB dispatch releases the lease (never throws)", async () => {
    const fastmcp = makeFastMCPStub();
    const agent = newAgent(fastmcp);
    const View = serviceView({
      methods: { render: { capability: "media.render", required: true } },
    });
    const ran: unknown[] = [];
    agent.addTool({
      name: "req_job",
      task: true,
      parameters: z.object({}),
      dependencies: [View],
      execute: async () => {
        ran.push(true);
        return "ran";
      },
    });
    const result = await captureExecute(fastmcp)({
      _mesh_headers: { "x-mesh-job-id": "job-9", "x-mesh-claim-epoch": "2" },
    });
    expect(result).toBe("");
    expect(ran).toHaveLength(0);
    expect(h.makeJobControllerMock).toHaveBeenCalledTimes(1);
    const ctorArgs = h.makeJobControllerMock.mock.calls[0] as unknown as unknown[];
    expect(ctorArgs[0]).toBe("job-9");
    expect(ctorArgs[3]).toBe(2);
    expect(h.releaseLeaseMock).toHaveBeenCalledTimes(1);
    const releaseArgs = h.releaseLeaseMock.mock.calls[0] as unknown as unknown[];
    expect(String(releaseArgs[0])).toContain("media.render");
  });

  it("required view edge does not refuse once resolved", async () => {
    const fastmcp = makeFastMCPStub();
    const agent = newAgent(fastmcp);
    const View = serviceView({
      methods: { caption: { capability: "media.caption", required: true } },
    });
    agent.addTool({
      name: "req_ok",
      parameters: z.object({}),
      dependencies: [View],
      execute: async (_a: unknown, v: unknown) => {
        const facade = v as Record<string, () => Promise<unknown>>;
        return (await facade.caption()) as string;
      },
    });
    injectEdge(agent, "req_ok", 0, async () => "captioned");
    // String results pass through unchanged (wrappedExecute returns strings as-is).
    expect(await captureExecute(fastmcp)({})).toBe("captioned");
  });
});

describe("minAvailable floor", () => {
  it("at floor → delegates; below floor (settled) → MeshServiceUnavailableError", async () => {
    const fastmcp = makeFastMCPStub();
    const agent = newAgent(fastmcp);
    const View = serviceView({
      methods: { a: "svc.a", b: "svc.b" },
      minAvailable: 1,
      name: "MyView",
    });
    const seen: unknown[] = [];
    agent.addTool({
      name: "floortool",
      parameters: z.object({}),
      dependencies: [View],
      execute: async (_a: unknown, v: unknown) => {
        seen.push(v);
        return "ok";
      },
    });
    // Resolve one of two methods → floor (1) satisfied.
    injectEdge(agent, "floortool", 0, async () => "A");
    await captureExecute(fastmcp)({});
    const facade = seen[0] as Record<string, () => Promise<unknown>>;
    // The resolved method delegates; the unresolved-but-floor-satisfied method
    // throws the null-proxy shape (optional edge) rather than the floor error.
    expect(await facade.a()).toBe("A");
    await expect(facade.b()).rejects.toBeInstanceOf(TypeError);

    // Drop below the floor (settled → no wait) → every call throws the floor error.
    removeEdge(agent, "floortool", 0);
    let err: unknown;
    try {
      await facade.a();
    } catch (e) {
      err = e;
    }
    expect(err).toBeInstanceOf(MeshServiceUnavailableError);
    const mse = err as MeshServiceUnavailableError;
    expect(mse.service).toBe("MyView");
    expect(mse.available).toBe(0);
    expect(mse.total).toBe(2);
    expect(mse.floor).toBe(1);
  });

  it("below floor: waking on a CROSS edge (resolve b while blocked) returns promptly", async () => {
    // The old serial enforceFloor awaited each pending edge in name order, so a
    // call would block on edge 'a' even after edge 'b' resolved and satisfied
    // the floor. The race-based enforceFloor wakes on ANY pending edge.
    const fastmcp = makeFastMCPStub();
    const agent = newAgent(fastmcp);
    process.env.MCP_MESH_SETTLE_TIMEOUT = "30";
    resetSettleStateForTests();
    const View = serviceView({
      methods: { a: "svc.a", b: "svc.b" },
      minAvailable: 1,
    });
    // Build the facade directly so the tool's own settle-wait doesn't interfere.
    const { edges, slots } = (
      await import("../service-view.js")
    ).expandDependencies([View], "wait_tool");
    const settle = getSettleState();
    slots.forEach((s) => {
      if (s.kind === "view") {
        for (const m of s.methods) {
          settle.registerDeclared(`wait_tool:dep_${m.edgeIndex}`);
        }
      }
    });
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const depsArray = (agent as any)._buildDepSlots(
      "wait_tool",
      slots,
      edges,
      undefined,
      settle,
    );
    const facade = depsArray[0] as Record<string, () => Promise<unknown>>;
    expect(settle.isSettled()).toBe(false);

    // Call method 'b' while BELOW the floor (0 resolved). enforceFloor races
    // BOTH pending edges. Resolving 'b' (edge 1) — a DIFFERENT key than 'a'
    // which sorts first — must wake the wait and delegate promptly.
    const before = settle.waitCount;
    const p = facade.b();
    // Let enforceFloor register its waiters before we resolve.
    await new Promise((r) => setImmediate(r));
    injectEdge(agent, "wait_tool", 1, async () => "B");
    settle.markResolved("wait_tool:dep_1");
    // Floor satisfied by edge 'b' → the call delegates to 'b' without waiting
    // for the still-pending 'a' or the full 30s window.
    expect(await p).toBe("B");
    // A bounded wait actually occurred (never a fixed sleep once settled).
    expect(settle.waitCount).toBeGreaterThan(before);
  });
});

describe("serviceView validation (throws at construction)", () => {
  it("empty methods map", () => {
    expect(() => serviceView({ methods: {} })).toThrow(/at least one method/);
  });
  it("blank capability", () => {
    expect(() => serviceView({ methods: { a: "" } })).toThrow(/blank capability/);
    expect(() =>
      serviceView({ methods: { a: { capability: "   " } } }),
    ).toThrow(/blank capability/);
  });
  it("minAvailable < 0", () => {
    expect(() =>
      serviceView({ methods: { a: "svc.a" }, minAvailable: -1 }),
    ).toThrow(/minAvailable must be an integer >= 0/);
  });
  it("minAvailable > method count", () => {
    expect(() =>
      serviceView({ methods: { a: "svc.a" }, minAvailable: 2 }),
    ).toThrow(/exceeds the number of methods/);
  });
});

describe("addTool validation (views)", () => {
  it("meshJobDepIndex pointing at a view slot throws", () => {
    const fastmcp = makeFastMCPStub();
    const agent = newAgent(fastmcp);
    const View = serviceView({ methods: { a: "svc.a" } });
    expect(() =>
      agent.addTool({
        name: "bad_mj",
        parameters: z.object({}),
        dependencies: [View],
        meshJobDepIndex: 0,
        execute: async () => "ok",
      }),
    ).toThrow(/points at a mesh.serviceView slot/);
  });

  it("a producer-shaped object (no capability) in dependencies throws", () => {
    const fastmcp = makeFastMCPStub();
    const agent = newAgent(fastmcp);
    expect(() =>
      agent.addTool({
        name: "bad_dep",
        parameters: z.object({}),
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        dependencies: [{ execute: async () => "x" } as any],
        execute: async () => "ok",
      }),
    ).toThrow(/without a 'capability'/);
  });
});

describe("serviceView rejected on non-facade surfaces", () => {
  it("shared guard rejects a view for any surface label", () => {
    const View = serviceView({ methods: { a: "svc.a" } });
    expect(() => assertNoServiceViewDeps([View], "mesh.route")).toThrow(
      /mesh.route does not support mesh.serviceView/,
    );
    expect(() => assertNoServiceViewDeps(["ok", View], "mesh.a2a.mount")).toThrow(
      /mesh.a2a.mount does not support mesh.serviceView/,
    );
    // No views → no throw.
    expect(() => assertNoServiceViewDeps(["a", { capability: "b" }], "x")).not.toThrow();
  });

  it("mesh.route rejects a view in route deps", () => {
    const View = serviceView({ methods: { a: "svc.a" } });
    expect(() =>
      route(
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        [View as any],
        async () => {
          /* noop */
        },
      ),
    ).toThrow(/does not support mesh.serviceView/);
  });

  it("mesh.a2a.mount rejects a view in surface deps", () => {
    const View = serviceView({ methods: { a: "svc.a" } });
    expect(() =>
      a2aMount(
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        {} as any,
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        { path: "/a2a", skillId: "s", dependencies: [View] } as any,
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        (async () => ({})) as any,
      ),
    ).toThrow(/mesh.a2a.mount does not support mesh.serviceView/);
  });
});

describe("view-bound worker isolation", () => {
  it("warns at registration that isolation is force-disabled when the env is set", () => {
    process.env.MCP_MESH_TOOL_ISOLATION = "true"; // override the beforeEach "false"
    const fastmcp = makeFastMCPStub();
    const agent = newAgent(fastmcp);
    const View = serviceView({ methods: { a: "svc.a" } });
    agent.addTool({
      name: "isotool",
      parameters: z.object({}),
      dependencies: [View],
      execute: async () => "ok",
    });
    const warned = warnSpy!.mock.calls
      .map((c) => String(c[0]))
      .some(
        (m) =>
          m.includes("isotool") &&
          m.includes("serviceView facade") &&
          m.includes("isolation is disabled"),
      );
    expect(warned).toBe(true);
  });

  it("does NOT warn when isolation is off (the default here)", () => {
    // beforeEach pins MCP_MESH_TOOL_ISOLATION="false".
    const fastmcp = makeFastMCPStub();
    const agent = newAgent(fastmcp);
    const View = serviceView({ methods: { a: "svc.a" } });
    agent.addTool({
      name: "noiso",
      parameters: z.object({}),
      dependencies: [View],
      execute: async () => "ok",
    });
    const warned = warnSpy!.mock.calls
      .map((c) => String(c[0]))
      .some((m) => m.includes("noiso") && m.includes("serviceView facade"));
    expect(warned).toBe(false);
  });
});

describe("dependencyKwargs slot→edge remap", () => {
  it("a slot AFTER a view shifts correctly (view kwargs applied to each edge)", () => {
    const fastmcp = makeFastMCPStub();
    const agent = newAgent(fastmcp);
    const View = serviceView({ methods: { a: "svc.a", b: "svc.b" } });
    agent.addTool({
      name: "kwt",
      parameters: z.object({}),
      dependencies: ["dep", View, "dep2"],
      dependencyKwargs: [{ timeout: 10 }, { timeout: 20 }, { timeout: 30 }],
      execute: async () => "ok",
    });
    // Slots: dep(k0), View(k1 → both edges), dep2(k2). Edge kwargs:
    // [dep=10, svc.a=20, svc.b=20, dep2=30].
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const kwargs = (agent as any).tools.get("kwt").dependencyKwargs;
    expect(kwargs.map((k: { timeout: number }) => k.timeout)).toEqual([
      10, 20, 20, 30,
    ]);
  });

  it("view-free tools pass dependencyKwargs through unchanged", () => {
    const fastmcp = makeFastMCPStub();
    const agent = newAgent(fastmcp);
    const kw = [{ timeout: 5 }, { timeout: 6 }];
    agent.addTool({
      name: "kwplain",
      parameters: z.object({}),
      dependencies: ["a", "b"],
      dependencyKwargs: kw,
      execute: async () => "ok",
    });
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    expect((agent as any).tools.get("kwplain").dependencyKwargs).toBe(kw);
  });
});

describe("claim path with a required view edge (#1268 gate)", () => {
  it("requiredProbe reports the unresolved required view method; released via dispatcher", async () => {
    const fastmcp = makeFastMCPStub();
    const agent = newAgent(fastmcp);
    const View = serviceView({
      methods: { render: { capability: "media.render", required: true } },
    });
    const ran: unknown[] = [];
    agent.addTool({
      name: "renderjob",
      capability: "renderjob",
      task: true,
      parameters: z.object({}),
      dependencies: [View],
      execute: async () => {
        ran.push(true);
        return "ran";
      },
    });
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const th = (agent as any)._taskHandlers.get("renderjob") as {
      handler: (p: Record<string, unknown>, c: unknown) => Promise<unknown>;
      requiredProbe?: () => string | null;
    };
    expect(th.requiredProbe).toBeDefined();
    // The required VIEW method edge feeds the claim gate.
    expect(th.requiredProbe!()).toBe("media.render");

    // Drive the dispatcher's pre-invoke guard: an unresolved required edge
    // releases the lease and never runs the handler.
    const dispatcher = new ClaimDispatcher(
      "renderjob",
      "inst-1",
      "http://registry:8000",
      th.handler as never,
      undefined,
      th.requiredProbe,
    );
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    await (dispatcher as any)._dispatch({ id: "job-1", submitted_payload: {} });
    expect(h.releaseLeaseMock).toHaveBeenCalledTimes(1);
    expect(h.failMock).not.toHaveBeenCalled();
    expect(ran).toHaveLength(0);

    // Once the required view edge resolves, the probe clears.
    injectEdge(agent, "renderjob", 0, async () => "rendered");
    expect(th.requiredProbe!()).toBeNull();
  });
});

describe("view + meshJobDepIndex (job slot AFTER the view)", () => {
  it("edge-shift math: submitter at the job slot, facade at the view slot", async () => {
    const fastmcp = makeFastMCPStub();
    const agent = newAgent(fastmcp);
    process.env.MCP_MESH_SETTLE_TIMEOUT = "30";
    resetSettleStateForTests();
    const View = serviceView({ methods: { a: "svc.a", b: "svc.b" } });
    const seen: unknown[] = [];
    agent.addTool({
      name: "mjv",
      parameters: z.object({}),
      // Authored slots: [View(slot 0), "jobcap"(slot 1)].
      dependencies: [View, "jobcap"],
      meshJobDepIndex: 1, // the jobcap slot (edge index 2 after the view's 2 edges)
      execute: async (_a: unknown, view: unknown, job: unknown) => {
        seen.push(view, job);
        return "ok";
      },
    });
    // Flat edges: svc.a(0), svc.b(1), jobcap(2).
    expect(edgesOf(agent, "mjv").map((d) => d.capability)).toEqual([
      "svc.a",
      "svc.b",
      "jobcap",
    ]);

    // Settle keys skip the MeshJob EDGE (index 2): resolving the two view edges
    // is sufficient to settle (proving meshJobEdgeIndex shifted past the view).
    const settle = getSettleState();
    expect(settle.isSettled()).toBe(false);
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (agent as any).handleDependencyAvailable("svc.a", "http://x", "fn", "p", "mjv", 0);
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (agent as any).handleDependencyAvailable("svc.b", "http://x", "fn", "p", "mjv", 1);
    expect(settle.isSettled()).toBe(true);

    await captureExecute(fastmcp)({});
    const [view, job] = seen as [
      Record<string, () => Promise<unknown>>,
      MeshJobSubmitter,
    ];
    expect(Object.keys(view).sort()).toEqual(["a", "b"]);
    expect(job).toBeInstanceOf(MeshJobSubmitter);
    // The submitter targets the capability at the shifted edge (jobcap).
    expect(job.capability).toBe("jobcap");
  });
});

describe("#1231 unwired-slot warning for view edges", () => {
  it("warns once when a view method edge is null after settling", async () => {
    process.env.MCP_MESH_SETTLE_TIMEOUT = "0"; // settled immediately
    resetSettleStateForTests();
    const fastmcp = makeFastMCPStub();
    const agent = newAgent(fastmcp);
    const View = serviceView({ methods: { caption: "media.caption" } });
    agent.addTool({
      name: "unwired",
      parameters: z.object({}),
      dependencies: [View],
      execute: async () => "ok",
    });
    // Build the facade (unresolved edge, settled) → warn once.
    await captureExecute(fastmcp)({});
    const warned = warnSpy!.mock.calls
      .map((c) => String(c[0]))
      .filter(
        (m) =>
          m.includes("service view") &&
          m.includes("caption") &&
          m.includes("media.caption") &&
          m.includes("still null after settling"),
      );
    expect(warned.length).toBeGreaterThanOrEqual(1);
  });
});

describe("view method schema matching (#547 parity)", () => {
  it("expectedSchema on a view method lands on the edge and yields canonical/hash", () => {
    const fastmcp = makeFastMCPStub();
    const agent = newAgent(fastmcp);
    const View = serviceView({
      methods: {
        caption: {
          capability: "media.caption",
          expectedSchema: z.object({ caption: z.string() }),
          matchMode: "strict",
        },
      },
    });
    agent.addTool({
      name: "schematool",
      parameters: z.object({}),
      dependencies: [View],
      execute: async () => "ok",
    });
    const edge = edgesOf(agent, "schematool")[0] as unknown as {
      capability: string;
      expectedSchemaRaw?: object;
      matchMode?: string;
    };
    expect(edge.capability).toBe("media.caption");
    expect(edge.expectedSchemaRaw).toBeDefined();
    expect(edge.matchMode).toBe("strict");
    // The payload builder feeds expectedSchemaRaw through this exact call to
    // derive expectedSchemaCanonical/hash (agent.ts startHeartbeat).
    const r = normalizeSchemaWithPolicy(
      edge.expectedSchemaRaw!,
      "dependency on 'media.caption'",
      false,
      true,
    );
    expect(r.canonicalJson).toBeTruthy();
    expect(r.hash).toBeTruthy();
  });
});

describe("addService producer sugar", () => {
  it("publishes N tools name-sorted with capability prefix.method", () => {
    const fastmcp = makeFastMCPStub();
    const agent = newAgent(fastmcp);
    agent.addService("media", {
      // Out of order to prove name-sorting.
      thumbnail: async () => ({ url: "u" }),
      caption: async (args: { text: string }) => ({ caption: args.text }),
    });
    // Registered in NAME-SORTED order: caption, then thumbnail.
    const names = fastmcp.addTool.mock.calls.map(
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      (c: any[]) => c[0].name,
    );
    expect(names).toEqual(["media.caption", "media.thumbnail"]);
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    expect((agent as any).tools.get("media.caption").capability).toBe(
      "media.caption",
    );
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    expect((agent as any).tools.get("media.thumbnail").capability).toBe(
      "media.thumbnail",
    );
  });

  it("object form carries addTool passthrough (tags/version/description)", () => {
    const fastmcp = makeFastMCPStub();
    const agent = newAgent(fastmcp);
    agent.addService("svc", {
      m: {
        execute: async () => "ok",
        tags: ["fast"],
        version: "2.1.0",
        description: "does m",
        parameters: z.object({ x: z.number() }),
      },
    });
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const meta = (agent as any).tools.get("svc.m");
    expect(meta.tags).toEqual(["fast"]);
    expect(meta.version).toBe("2.1.0");
    expect(meta.description).toBe("does m");
  });

  it("function shorthand works and runs through the wrapped execute", async () => {
    const fastmcp = makeFastMCPStub();
    const agent = newAgent(fastmcp);
    agent.addService("svc", {
      echo: async (args: { v: string }) => ({ echoed: args.v }),
    });
    const execute = captureExecute(fastmcp);
    expect(await execute({ v: "hi" })).toBe(JSON.stringify({ echoed: "hi" }));
  });

  it("rejects an invalid prefix", () => {
    const fastmcp = makeFastMCPStub();
    const agent = newAgent(fastmcp);
    expect(() =>
      agent.addService("1bad", { m: async () => "x" }),
    ).toThrow(/not a valid capability name/);
    expect(() =>
      agent.addService("", { m: async () => "x" }),
    ).toThrow(/non-empty capability prefix/);
  });

  it("rejects a method whose derived capability is invalid", () => {
    const fastmcp = makeFastMCPStub();
    const agent = newAgent(fastmcp);
    expect(() =>
      agent.addService("svc", { "bad name": async () => "x" }),
    ).toThrow(/is not a valid capability name/);
  });

  it("rejects a serviceView passed as a producer method", () => {
    const fastmcp = makeFastMCPStub();
    const agent = newAgent(fastmcp);
    const View = serviceView({ methods: { a: "svc.a" } });
    expect(() =>
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      agent.addService("svc", { a: View as any }),
    ).toThrow(/is a mesh.serviceView/);
  });

  it("rejects a method that is neither a function nor an execute object", () => {
    const fastmcp = makeFastMCPStub();
    const agent = newAgent(fastmcp);
    expect(() =>
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      agent.addService("svc", { a: { tags: ["x"] } as any }),
    ).toThrow(/must be an execute function/);
  });

  it("accepts dotted prefixes (segment-wise grammar)", () => {
    const fastmcp = makeFastMCPStub();
    const agent = newAgent(fastmcp);
    agent.addService("acme.media", { caption: async () => "c" });
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    expect((agent as any).tools.get("acme.media.caption").capability).toBe(
      "acme.media.caption",
    );
  });

  it("is atomic: an invalid method mid-map registers NOTHING (item 7)", () => {
    const fastmcp = makeFastMCPStub();
    const agent = newAgent(fastmcp);
    expect(() =>
      agent.addService("svc", {
        good: async () => "ok",
        "bad name": async () => "x", // invalid derived capability
      }),
    ).toThrow(/is not a valid capability name/);
    // 'svc.good' must NOT have been registered — validation runs before any addTool.
    expect(fastmcp.addTool).not.toHaveBeenCalled();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    expect((agent as any).tools.has("svc.good")).toBe(false);
  });

  it("throws when a derived capability collides with an existing tool (item 9)", () => {
    const fastmcp = makeFastMCPStub();
    const agent = newAgent(fastmcp);
    agent.addTool({
      name: "svc.caption",
      parameters: z.object({}),
      execute: async () => "existing",
    });
    expect(() =>
      agent.addService("svc", { caption: async () => "new" }),
    ).toThrow(/already registered/);
  });
});
