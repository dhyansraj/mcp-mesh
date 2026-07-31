/**
 * Positional-injection safety property: an UNRESOLVED dependency must not
 * shift the other dependencies into the wrong parameter slots.
 *
 * mcp-mesh injects dependencies positionally — `dependencies[i]` pairs with
 * the i-th dependency-typed parameter in declaration order. The property this
 * file pins is the one that makes positional injection safe to ship:
 *
 *   An unresolved dependency leaves ITS OWN slot null and every other
 *   dependency still lands in its own slot.
 *
 * If this did not hold, a single provider going down would silently rewire
 * every downstream parameter (dep 2's proxy arriving as parameter `depB`),
 * which is a far worse failure than a null.
 *
 * Cross-runtime seam — the same property is pinned by:
 *   - Python: `test_12_dependency_injector.py::TestUnifiedPositionalInjection::
 *     test_unresolved_middle_dependency_does_not_shift` (and the mixed
 *     MeshJob variant).
 *   - Java: `MeshToolWrapperUnresolvedDepPositionTest`.
 *
 * In TypeScript the property holds by construction: `_buildDepSlots` is an
 * index-preserving `depSlots.map()` reading `resolvedDeps.get(
 * `${toolName}:dep_${edgeIndex}`) ?? null`, and the dependency events are
 * keyed by `depIndex` (never by "next free position"). These tests exercise
 * that end-to-end through the real `addTool` wrapper so a future refactor
 * that filters/compacts the slot array (e.g. `.filter(Boolean)`) fails here.
 *
 * ## Why this file now covers `route` and `a2a` too (issue #1401)
 *
 * Until 3.4.0 `mesh.route()` and `mesh.a2a.mount()` handed the handler a
 * capability-KEYED object, for which slot preservation was vacuous: omitting
 * an unresolved key from a map cannot move any other key. Under positional
 * injection an omission shifts every later dependency into the wrong slot —
 * the exact defect #1390 pinned — so `RouteRegistry.getDependenciesForRoute`
 * must build the array with an index-preserving `map()` over the DECLARED
 * dependencies and never by collecting the resolved ones. That is now load
 * bearing for all three surfaces, so all three are pinned here.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { z } from "zod";
import { MeshAgent, __resetUnwiredSlotWarnedForTests } from "../agent.js";
import { PROXY_DISPATCH_META } from "../proxy.js";
import { MeshJobSubmitter } from "../mesh-job-submitter.js";
import { route, RouteRegistry } from "../route.js";
import { resetSettleStateForTests } from "../settle.js";
import { A2ATaskStore } from "../a2a/producer/task-store.js";
import {
  buildDispatcherMiddleware,
  type A2AHandler,
} from "../a2a/producer/dispatcher.js";
import type { A2ASurfaceMetadata } from "../a2a/producer/registry.js";
import type { McpMeshTool } from "../types.js";
import type { Request, Response, NextFunction } from "express";

function makeFastMCPStub() {
  return {
    addTool: vi.fn(),
    start: vi.fn(),
    getApp: vi.fn(),
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
  } as any;
}

/** Capability a resolved proxy is bound to, read off its dispatch meta. */
function capabilityOf(dep: unknown): string | null {
  if (dep === null || dep === undefined) return null;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const meta = (dep as any)[PROXY_DISPATCH_META];
  return meta ? (meta.capability as string) : null;
}

let autoStartSpy: ReturnType<typeof vi.spyOn> | null = null;
let warnSpy: ReturnType<typeof vi.spyOn> | null = null;
let logSpy: ReturnType<typeof vi.spyOn> | null = null;
const savedEnv: Record<string, string | undefined> = {};

beforeEach(() => {
  autoStartSpy = vi
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    .spyOn(MeshAgent.prototype as any, "_autoStart")
    .mockImplementation(async () => {
      /* no-op */
    });
  warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {
    /* swallow the #1231 unwired-slot warning */
  });
  logSpy = vi.spyOn(console, "log").mockImplementation(() => {
    /* swallow dependency-available chatter */
  });
  savedEnv.MCP_MESH_SETTLE_TIMEOUT = process.env.MCP_MESH_SETTLE_TIMEOUT;
  savedEnv.MCP_MESH_TOOL_ISOLATION = process.env.MCP_MESH_TOOL_ISOLATION;
  savedEnv.MCP_MESH_REGISTRY_URL = process.env.MCP_MESH_REGISTRY_URL;
  // Inline execution so the user function receives the REAL proxy objects
  // (the worker-isolation path re-creates proxies inside the worker).
  process.env.MCP_MESH_TOOL_ISOLATION = "false";
  // No settle grace — the middle dep is genuinely unresolved, not late.
  process.env.MCP_MESH_SETTLE_TIMEOUT = "0";
  resetSettleStateForTests();
  RouteRegistry.reset();
  __resetUnwiredSlotWarnedForTests();
});

afterEach(() => {
  autoStartSpy?.mockRestore();
  autoStartSpy = null;
  warnSpy?.mockRestore();
  warnSpy = null;
  logSpy?.mockRestore();
  logSpy = null;
  for (const [key, value] of Object.entries(savedEnv)) {
    if (value === undefined) delete process.env[key];
    else process.env[key] = value;
  }
  resetSettleStateForTests();
  RouteRegistry.reset();
  __resetUnwiredSlotWarnedForTests();
});

describe("unresolved middle dependency does not shift", () => {
  it("inbound path: positions 0 and 2 keep their proxies, position 1 stays null", async () => {
    const fastmcp = makeFastMCPStub();
    const agent = new MeshAgent(fastmcp, {
      name: "no-shift-agent",
      httpPort: 0,
    });

    const received: unknown[] = [];
    agent.addTool({
      name: "fan_out",
      parameters: z.object({}),
      dependencies: [
        { capability: "cap_a" },
        { capability: "cap_b" },
        { capability: "cap_c" },
      ],
      execute: async (
        _args: unknown,
        dep0: unknown,
        dep1: unknown,
        dep2: unknown,
      ) => {
        // Capture arity too: a compacted array would arrive as
        // (args, proxyA, proxyC) — dep2 undefined, not null.
        received.push(dep0, dep1, dep2);
        return "ok";
      },
    });

    // Resolve ONLY dep 0 and dep 2. dep 1 (cap_b) never resolves.
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (agent as any).handleDependencyAvailable(
      "cap_a",
      "http://provider-a:9001",
      "fn_a",
      "agent-a",
      "fan_out",
      0,
    );
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (agent as any).handleDependencyAvailable(
      "cap_c",
      "http://provider-c:9003",
      "fn_c",
      "agent-c",
      "fan_out",
      2,
    );

    const execute = fastmcp.addTool.mock.calls[0][0].execute as (
      args: unknown,
    ) => Promise<string>;
    expect(await execute({})).toBe("ok");

    const [dep0, dep1, dep2] = received;
    expect(capabilityOf(dep0)).toBe("cap_a");
    // The unresolved dep leaves its OWN slot null — it does not consume
    // cap_c's proxy by sliding up.
    expect(dep1).toBeNull();
    expect(capabilityOf(dep2)).toBe("cap_c");
    // Explicitly rule out compaction: dep2 must be a real value, and the
    // slot count must equal the declared dependency count.
    expect(dep2).not.toBeUndefined();
    expect(received).toHaveLength(3);
  });

  it("inbound path: leading and trailing unresolved deps hold their own slots", async () => {
    const fastmcp = makeFastMCPStub();
    const agent = new MeshAgent(fastmcp, {
      name: "edges-agent",
      httpPort: 0,
    });

    const received: unknown[] = [];
    agent.addTool({
      name: "edges",
      parameters: z.object({}),
      dependencies: [
        { capability: "cap_a" },
        { capability: "cap_b" },
        { capability: "cap_c" },
      ],
      execute: async (
        _args: unknown,
        dep0: unknown,
        dep1: unknown,
        dep2: unknown,
      ) => {
        received.push(dep0, dep1, dep2);
        return "ok";
      },
    });

    // Only the MIDDLE dep resolves — the first and last stay null.
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (agent as any).handleDependencyAvailable(
      "cap_b",
      "http://provider-b:9002",
      "fn_b",
      "agent-b",
      "edges",
      1,
    );

    const execute = fastmcp.addTool.mock.calls[0][0].execute as (
      args: unknown,
    ) => Promise<string>;
    await execute({});

    expect(received[0]).toBeNull();
    expect(capabilityOf(received[1])).toBe("cap_b");
    expect(received[2]).toBeNull();
  });

  it("a dependency going unavailable nulls only its own slot", async () => {
    const fastmcp = makeFastMCPStub();
    const agent = new MeshAgent(fastmcp, {
      name: "flap-agent",
      httpPort: 0,
    });

    const received: unknown[] = [];
    agent.addTool({
      name: "flap",
      parameters: z.object({}),
      dependencies: [
        { capability: "cap_a" },
        { capability: "cap_b" },
        { capability: "cap_c" },
      ],
      execute: async (
        _args: unknown,
        dep0: unknown,
        dep1: unknown,
        dep2: unknown,
      ) => {
        received.length = 0;
        received.push(dep0, dep1, dep2);
        return "ok";
      },
    });

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const a = agent as any;
    a.handleDependencyAvailable("cap_a", "http://a:9001", "fn_a", "agent-a", "flap", 0);
    a.handleDependencyAvailable("cap_b", "http://b:9002", "fn_b", "agent-b", "flap", 1);
    a.handleDependencyAvailable("cap_c", "http://c:9003", "fn_c", "agent-c", "flap", 2);

    const execute = fastmcp.addTool.mock.calls[0][0].execute as (
      args: unknown,
    ) => Promise<string>;
    await execute({});
    expect(received.map(capabilityOf)).toEqual(["cap_a", "cap_b", "cap_c"]);

    // The middle provider drops out mid-flight.
    a.handleDependencyUnavailable("cap_b", "flap", 1);
    await execute({});

    expect(capabilityOf(received[0])).toBe("cap_a");
    expect(received[1]).toBeNull();
    expect(capabilityOf(received[2])).toBe("cap_c");
  });

  it("claim-dispatch path: unresolved middle dep does not shift either", async () => {
    const fastmcp = makeFastMCPStub();
    const agent = new MeshAgent(fastmcp, {
      name: "claim-no-shift-agent",
      httpPort: 0,
    });

    const received: unknown[] = [];
    agent.addTool({
      name: "task_fan_out",
      task: true,
      parameters: z.object({}),
      dependencies: [
        { capability: "cap_a" },
        { capability: "cap_b" },
        { capability: "cap_c" },
      ],
      execute: async (
        _args: unknown,
        dep0: unknown,
        dep1: unknown,
        dep2: unknown,
      ) => {
        received.push(dep0, dep1, dep2);
        return "ok";
      },
    });

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const a = agent as any;
    a.handleDependencyAvailable("cap_a", "http://a:9001", "fn_a", "agent-a", "task_fan_out", 0);
    a.handleDependencyAvailable("cap_c", "http://c:9003", "fn_c", "agent-c", "task_fan_out", 2);

    // The claim path builds its own deps array (`liveDeps`) — assert it
    // preserves positions identically to the inbound path.
    const { handler } = a._taskHandlers.get("task_fan_out");
    expect(await handler({}, {} as never)).toBe("ok");

    expect(capabilityOf(received[0])).toBe("cap_a");
    expect(received[1]).toBeNull();
    expect(capabilityOf(received[2])).toBe("cap_c");
  });

  it("mixed MeshJob + unresolved McpMeshTool: submitter keeps its own slot", async () => {
    // Mirrors Python's `test_unresolved_mixed_mesh_tool_with_mesh_job`: a
    // MeshJob slot is built locally (never resolved by an event), so an
    // unresolved McpMeshTool sibling must not disturb it — and vice versa.
    // The MeshJob slot builds a submitter bound to the resolved registry URL,
    // which comes from the environment (not AgentConfig).
    process.env.MCP_MESH_REGISTRY_URL = "http://registry.local:8000";
    const fastmcp = makeFastMCPStub();
    const agent = new MeshAgent(fastmcp, {
      name: "mixed-agent",
      httpPort: 0,
    });

    const received: unknown[] = [];
    agent.addTool({
      name: "mixed",
      parameters: z.object({}),
      dependencies: [
        { capability: "run_workflow" }, // dep 0 → MeshJob slot
        { capability: "missing_tool" }, // dep 1 → unresolved McpMeshTool
        { capability: "cap_c" }, // dep 2 → resolved McpMeshTool
      ],
      meshJobDepIndex: 0,
      execute: async (
        _args: unknown,
        job: unknown,
        tool: unknown,
        dep2: unknown,
      ) => {
        received.push(job, tool, dep2);
        return "ok";
      },
    });

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (agent as any).handleDependencyAvailable(
      "cap_c",
      "http://c:9003",
      "fn_c",
      "agent-c",
      "mixed",
      2,
    );

    const execute = fastmcp.addTool.mock.calls[0][0].execute as (
      args: unknown,
    ) => Promise<string>;
    await execute({});

    expect(received[0]).toBeInstanceOf(MeshJobSubmitter);
    expect((received[0] as MeshJobSubmitter).capability).toBe("run_workflow");
    expect(received[1]).toBeNull();
    expect(capabilityOf(received[2])).toBe("cap_c");
  });
});

// ────────────────────────────────────────────────────────────────────────
// mesh.route() — issue #1401
// ────────────────────────────────────────────────────────────────────────

/** Named stand-in proxies; identity is what the assertions compare. */
function namedProxy(capability: string): McpMeshTool {
  const fn = (async () => capability) as unknown as McpMeshTool;
  Object.defineProperty(fn, "capability", { value: capability });
  return fn;
}

function capName(dep: unknown): string | null {
  if (dep === null || dep === undefined) return null;
  return (dep as { capability?: string }).capability ?? null;
}

describe("mesh.route: unresolved middle dependency does not shift (#1401)", () => {
  it("positions 0 and 2 keep their proxies, position 1 stays null", async () => {
    const handler = vi.fn();
    const middleware = route(
      [{ capability: "cap_a" }, { capability: "cap_b" }, { capability: "cap_c" }],
      handler
    ) as ReturnType<typeof route> & { _meshRouteId: string };

    const registry = RouteRegistry.getInstance();
    // Resolve ONLY dep 0 and dep 2 — dep 1 never resolves.
    registry.setDependency(middleware._meshRouteId, 0, namedProxy("cap_a"));
    registry.setDependency(middleware._meshRouteId, 2, namedProxy("cap_c"));

    const req = { method: "GET", path: "/x", headers: {} } as unknown as Request;
    const res = {} as Response;
    await middleware(req, res, vi.fn() as NextFunction);

    const deps = handler.mock.calls[0][2] as Array<McpMeshTool | null>;
    // Rule out compaction: a `.filter(Boolean)` build would produce length 2
    // with cap_c sitting at index 1.
    expect(deps).toHaveLength(3);
    expect(capName(deps[0])).toBe("cap_a");
    expect(deps[1]).toBeNull();
    expect(capName(deps[2])).toBe("cap_c");
    expect(deps[2]).not.toBeUndefined();
  });

  it("leading and trailing unresolved deps hold their own slots", async () => {
    const handler = vi.fn();
    const middleware = route(
      [{ capability: "cap_a" }, { capability: "cap_b" }, { capability: "cap_c" }],
      handler
    ) as ReturnType<typeof route> & { _meshRouteId: string };

    RouteRegistry.getInstance().setDependency(
      middleware._meshRouteId,
      1,
      namedProxy("cap_b")
    );

    const req = { method: "GET", path: "/x", headers: {} } as unknown as Request;
    await middleware(req, {} as Response, vi.fn() as NextFunction);

    const deps = handler.mock.calls[0][2] as Array<McpMeshTool | null>;
    expect(deps).toHaveLength(3);
    expect(deps[0]).toBeNull();
    expect(capName(deps[1])).toBe("cap_b");
    expect(deps[2]).toBeNull();
  });

  it("a dependency going unavailable nulls only its own slot", async () => {
    const handler = vi.fn();
    const middleware = route(
      [{ capability: "cap_a" }, { capability: "cap_b" }, { capability: "cap_c" }],
      handler
    ) as ReturnType<typeof route> & { _meshRouteId: string };

    const registry = RouteRegistry.getInstance();
    registry.setDependency(middleware._meshRouteId, 0, namedProxy("cap_a"));
    registry.setDependency(middleware._meshRouteId, 1, namedProxy("cap_b"));
    registry.setDependency(middleware._meshRouteId, 2, namedProxy("cap_c"));

    const req = { method: "GET", path: "/x", headers: {} } as unknown as Request;
    await middleware(req, {} as Response, vi.fn() as NextFunction);
    expect(
      (handler.mock.calls[0][2] as Array<McpMeshTool | null>).map(capName)
    ).toEqual(["cap_a", "cap_b", "cap_c"]);

    // The middle provider drops out mid-flight.
    registry.removeDependency(middleware._meshRouteId, 1);
    await middleware(req, {} as Response, vi.fn() as NextFunction);

    const deps = handler.mock.calls[1][2] as Array<McpMeshTool | null>;
    expect(capName(deps[0])).toBe("cap_a");
    expect(deps[1]).toBeNull();
    expect(capName(deps[2])).toBe("cap_c");
  });
});

// ────────────────────────────────────────────────────────────────────────
// mesh.a2a.mount() — issue #1401, driven through a real tasks/send
// ────────────────────────────────────────────────────────────────────────

describe("mesh.a2a.mount: unresolved middle dependency does not shift (#1401)", () => {
  it("positions 0 and 2 keep their proxies, position 1 stays null", async () => {
    const registry = RouteRegistry.getInstance();
    const declared = [
      { capability: "cap_a" },
      { capability: "cap_b" },
      { capability: "cap_c" },
    ];
    const routeId = registry.registerRoute("A2A", "/agents/t", declared);
    registry.setDependency(routeId, 0, namedProxy("cap_a"));
    registry.setDependency(routeId, 2, namedProxy("cap_c"));

    const surface: A2ASurfaceMetadata = {
      path: "/agents/t",
      skillId: "t",
      skillName: "T",
      description: "",
      tags: [],
      dependencies: declared.map((d) => ({ ...d, tags: [] })),
      auth: "",
      routeId,
    };

    let received: Array<McpMeshTool | null> | null = null;
    const handler: A2AHandler = async (deps) => {
      received = deps as Array<McpMeshTool | null>;
      return "ok";
    };

    const middleware = buildDispatcherMiddleware({
      surface,
      handler,
      taskStore: new A2ATaskStore(),
      routeRegistry: registry,
    });

    const req = {
      body: {
        jsonrpc: "2.0",
        id: "1",
        method: "tasks/send",
        params: { id: "task-1", message: { role: "user" } },
      },
      headers: {},
    } as unknown as Request;
    const res = {
      status() { return this; },
      type() { return this; },
      send() { return this; },
    } as unknown as Response;

    await middleware(req, res, vi.fn() as NextFunction);

    expect(received).not.toBeNull();
    const deps = received as unknown as Array<McpMeshTool | null>;
    expect(deps).toHaveLength(3);
    expect(capName(deps[0])).toBe("cap_a");
    expect(deps[1]).toBeNull();
    expect(capName(deps[2])).toBe("cap_c");
  });
});
