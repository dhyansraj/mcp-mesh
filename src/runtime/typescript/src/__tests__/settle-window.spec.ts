/**
 * Settling-window dependency grace tests (issue #1193).
 *
 * Cross-runtime contract (mirrors the Python/Java suites):
 *
 *  (a) a call firing while a declared dep is unresolved waits — bounded by
 *      the remaining settle budget — and proceeds EARLY when the
 *      `dependency_available` event lands (event-driven, never a sleep);
 *  (b) on timeout the call proceeds with `null` exactly as today
 *      (defensive user code untouched);
 *  (c)/(d) the settled latch is permanent (window expiry OR all declared
 *      deps resolved) — subsequent calls never wait;
 *  (e) `MCP_MESH_SETTLE_TIMEOUT=0` disables the grace entirely;
 *  (h) the settled steady-state call path never touches the wait
 *      primitives.
 *
 * Route coverage: RouteRegistry declaration/resolution/rename keep the
 * settle state's keys aligned with remapped route IDs.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { z } from "zod";
import { MeshAgent } from "../agent.js";
import { RouteRegistry } from "../route.js";
import {
  SETTLE_TIMEOUT_DEFAULT_SECONDS,
  getSettleState,
  getSettleTimeoutSeconds,
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
const savedEnv: Record<string, string | undefined> = {};

beforeEach(() => {
  autoStartSpy = vi
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    .spyOn(MeshAgent.prototype as any, "_autoStart")
    .mockImplementation(async () => {
      /* no-op */
    });
  savedEnv.MCP_MESH_SETTLE_TIMEOUT = process.env.MCP_MESH_SETTLE_TIMEOUT;
  savedEnv.MCP_MESH_TOOL_ISOLATION = process.env.MCP_MESH_TOOL_ISOLATION;
  // Run tool bodies inline — worker isolation is orthogonal to the settle
  // grace (the wait happens before the isolation branch either way).
  process.env.MCP_MESH_TOOL_ISOLATION = "false";
  delete process.env.MCP_MESH_SETTLE_TIMEOUT;
  resetSettleStateForTests();
  RouteRegistry.reset();
});

afterEach(() => {
  if (autoStartSpy) {
    autoStartSpy.mockRestore();
    autoStartSpy = null;
  }
  for (const [key, value] of Object.entries(savedEnv)) {
    if (value === undefined) delete process.env[key];
    else process.env[key] = value;
  }
  resetSettleStateForTests();
  RouteRegistry.reset();
});

function setBudget(seconds: string): void {
  process.env.MCP_MESH_SETTLE_TIMEOUT = seconds;
  resetSettleStateForTests();
}

/**
 * Register a one-dep tool and return its FastMCP-registered execute fn.
 * The tool's user function follows the defensive `if (dep)` idiom.
 */
function registerTool(toolName = "settle_tool", capability = "db_cap") {
  const fastmcp = makeFastMCPStub();
  const agent = new MeshAgent(fastmcp, { name: "settle-agent", httpPort: 0 });
  agent.addTool({
    name: toolName,
    parameters: z.object({}),
    dependencies: [{ capability }],
    execute: async (_args: unknown, dep: unknown) =>
      dep ? "resolved" : "degraded",
  });
  const execute = fastmcp.addTool.mock.calls[0][0].execute as (
    args: unknown,
  ) => Promise<string>;
  return { agent, execute };
}

function resolveDep(
  agent: MeshAgent,
  toolName: string,
  capability: string,
  depIndex = 0,
): void {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  (agent as any).handleDependencyAvailable(
    capability,
    "http://localhost:19999",
    "remote_fn",
    "provider-agent",
    toolName,
    depIndex,
  );
}

describe("settle timeout knob", () => {
  it("defaults to 20 seconds", () => {
    expect(getSettleTimeoutSeconds()).toBe(SETTLE_TIMEOUT_DEFAULT_SECONDS);
    expect(SETTLE_TIMEOUT_DEFAULT_SECONDS).toBe(20);
  });

  it("honors a float env override and caches it per process", () => {
    setBudget("3.5");
    expect(getSettleTimeoutSeconds()).toBe(3.5);
    process.env.MCP_MESH_SETTLE_TIMEOUT = "99";
    expect(getSettleTimeoutSeconds()).toBe(3.5); // cached
  });

  it("falls back to the default on negative values", () => {
    setBudget("-5");
    expect(getSettleTimeoutSeconds()).toBe(SETTLE_TIMEOUT_DEFAULT_SECONDS);
  });
});

describe("MCP tool execute wrapper", () => {
  it("(a) proceeds early with the real proxy when resolution arrives mid-wait", async () => {
    setBudget("10");
    const { agent, execute } = registerTool();

    setTimeout(() => resolveDep(agent, "settle_tool", "db_cap"), 200);

    const start = Date.now();
    const result = await execute({});
    const elapsedMs = Date.now() - start;

    expect(result).toBe("resolved");
    // Unblocked by the event, not the 10s budget ceiling.
    expect(elapsedMs).toBeLessThan(5000);
    expect(getSettleState().waitCount).toBeGreaterThanOrEqual(1);
  });

  it("(b) proceeds with null at budget expiry — defensive user code runs", async () => {
    setBudget("0.3");
    const { execute } = registerTool();

    const start = Date.now();
    const result = await execute({});
    const elapsedMs = Date.now() - start;

    expect(result).toBe("degraded");
    expect(elapsedMs).toBeGreaterThanOrEqual(200); // actually waited
  });

  it("(c) settled by window expiry → latch is permanent, no more waits", async () => {
    setBudget("0.1");
    const { execute } = registerTool();
    await new Promise((resolve) => setTimeout(resolve, 150));

    for (let i = 0; i < 2; i++) {
      const start = Date.now();
      expect(await execute({})).toBe("degraded");
      expect(Date.now() - start).toBeLessThan(50);
    }
    const state = getSettleState();
    expect(state.isSettled()).toBe(true);
    expect(state.waitCount).toBe(0);
  });

  it("(d) settled by all-declared-resolved → eager latch, no waits", async () => {
    setBudget("10");
    const { agent, execute } = registerTool();
    resolveDep(agent, "settle_tool", "db_cap");

    const state = getSettleState();
    expect(state.isSettled()).toBe(true);

    const start = Date.now();
    expect(await execute({})).toBe("resolved");
    expect(Date.now() - start).toBeLessThan(50);
    expect(state.waitCount).toBe(0);
  });

  it("tracks the agent-level union: one unresolved dep keeps the agent unsettled", async () => {
    setBudget("0.3");
    const fastmcp = makeFastMCPStub();
    const agent = new MeshAgent(fastmcp, { name: "settle-agent", httpPort: 0 });
    agent.addTool({
      name: "tool_a",
      parameters: z.object({}),
      dependencies: [{ capability: "cap_a" }],
      execute: async (_args: unknown, dep: unknown) => (dep ? "a-resolved" : "a-degraded"),
    });
    agent.addTool({
      name: "tool_b",
      parameters: z.object({}),
      dependencies: [{ capability: "cap_b" }],
      execute: async (_args: unknown, dep: unknown) => (dep ? "b-resolved" : "b-degraded"),
    });
    const executeA = fastmcp.addTool.mock.calls[0][0].execute;
    const executeB = fastmcp.addTool.mock.calls[1][0].execute;

    resolveDep(agent, "tool_a", "cap_a");
    const state = getSettleState();
    expect(state.isSettled()).toBe(false); // cap_b still unresolved

    // tool_a's dep is resolved — no wait even though unsettled.
    let start = Date.now();
    expect(await executeA({})).toBe("a-resolved");
    expect(Date.now() - start).toBeLessThan(50);

    // tool_b's dep is unresolved — it waits toward the budget.
    start = Date.now();
    expect(await executeB({})).toBe("b-degraded");
    expect(Date.now() - start).toBeGreaterThanOrEqual(200);
  });

  it("anchors the settle window at first dependency declaration, not process start", async () => {
    setBudget("0.3");
    // Idle past the would-be window BEFORE any dependency declaration —
    // with an import/reset-time anchor this would (incorrectly) expire it.
    await new Promise((resolve) => setTimeout(resolve, 350));

    const { execute } = registerTool();
    expect(getSettleState().isSettled()).toBe(false);

    const start = Date.now();
    expect(await execute({})).toBe("degraded");
    // Waited toward the freshly-anchored budget.
    expect(Date.now() - start).toBeGreaterThanOrEqual(200);
  });

  it("a caller-supplied mock dependency never waits (documented mock contract)", async () => {
    setBudget("5");
    const fastmcp = makeFastMCPStub();
    const agent = new MeshAgent(fastmcp, { name: "settle-agent", httpPort: 0 });
    agent.addTool({
      name: "tool_a",
      parameters: z.object({}),
      dependencies: [{ capability: "cap_a" }],
      execute: async (_args: unknown, dep: unknown) =>
        dep ? "a-resolved" : "a-degraded",
    });
    agent.addTool({
      name: "tool_b",
      parameters: z.object({}),
      dependencies: [{ capability: "cap_b" }],
      execute: async (_args: unknown, dep: unknown) =>
        dep ? "b-resolved" : "b-degraded",
    });
    const executeA = fastmcp.addTool.mock.calls[0][0].execute;

    // Caller supplies cap_a explicitly; cap_b stays unresolved so the
    // agent is still UNSETTLED — proving the per-slot skip, not the latch.
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    agent.setMockDependency("cap_a", (async () => "mock") as any);
    const state = getSettleState();
    expect(state.isSettled()).toBe(false);

    const start = Date.now();
    expect(await executeA({})).toBe("a-resolved"); // mock injected
    expect(Date.now() - start).toBeLessThan(50);
    expect(state.waitCount).toBe(0);
  });

  it("(e) MCP_MESH_SETTLE_TIMEOUT=0 disables the grace entirely", async () => {
    setBudget("0");
    const { execute } = registerTool();

    const start = Date.now();
    expect(await execute({})).toBe("degraded");
    expect(Date.now() - start).toBeLessThan(50);
    const state = getSettleState();
    expect(state.isSettled()).toBe(true);
    expect(state.waitCount).toBe(0);
  });

  it("(h) the settled steady-state path never touches the wait primitives", async () => {
    setBudget("10");
    const { agent, execute } = registerTool();
    resolveDep(agent, "settle_tool", "db_cap");

    const state = getSettleState();
    expect(state.isSettled()).toBe(true);
    const waitForSpy = vi.spyOn(state, "waitFor");
    const awaitPendingSpy = vi.spyOn(state, "awaitPending");

    for (let i = 0; i < 3; i++) {
      await execute({});
    }

    expect(waitForSpy).not.toHaveBeenCalled();
    expect(awaitPendingSpy).not.toHaveBeenCalled();
    expect(state.waitCount).toBe(0);
  });
});

describe("RouteRegistry settle integration", () => {
  it("declares route deps and resolves them through setDependency", () => {
    setBudget("10");
    const registry = RouteRegistry.getInstance();
    const routeId = registry.registerRoute("POST", "/compute", [
      { capability: "calculator" },
    ]);

    const state = getSettleState();
    expect(state.isSettled()).toBe(false);
    expect(state.isResolved(`${routeId}:dep_0`)).toBe(false);

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    registry.setDependency(routeId, 0, {} as any);
    expect(state.isResolved(`${routeId}:dep_0`)).toBe(true);
    // Single declared dep resolved → agent settles eagerly.
    expect(state.isSettled()).toBe(true);
  });

  it("keeps settle keys aligned when route IDs are remapped", () => {
    setBudget("10");
    const registry = RouteRegistry.getInstance();
    const placeholderId = registry.registerRoute("UNKNOWN", "UNKNOWN", [
      { capability: "calculator" },
    ]);

    registry.updateRouteInfo(placeholderId, "POST", "/compute");

    const state = getSettleState();
    // Resolution arrives under the remapped ID — must still flip the
    // (renamed) declared key and settle the agent.
    registry.setDependency("POST:/compute", 0, {} as any); // eslint-disable-line @typescript-eslint/no-explicit-any
    expect(state.isResolved("POST:/compute:dep_0")).toBe(true);
    expect(state.isSettled()).toBe(true);
  });

  it("releases a displaced waiter on rename key collision (chains to survivor)", async () => {
    setBudget("10");
    const state = getSettleState();
    state.registerDeclared("old:dep_0");
    state.registerDeclared("POST:/compute:dep_0");

    // A call is already waiting under the OLD key when the rename lands
    // on a key that has its own waiter (collision).
    const displaced = state.waitFor("old:dep_0", "calculator");
    const survivor = state.waitFor("POST:/compute:dep_0", "calculator");
    state.renameDeclared("old:dep_0", "POST:/compute:dep_0");

    state.markResolved("POST:/compute:dep_0");

    const winner = await Promise.race([
      Promise.all([displaced, survivor]).then(() => "released"),
      new Promise((resolve) => setTimeout(resolve, 1000, "stuck")),
    ]);
    expect(winner).toBe("released");
  });

  it("releases a renamed waiter immediately when the new key already resolved", async () => {
    setBudget("10");
    const state = getSettleState();
    state.registerDeclared("old:dep_0");

    const displaced = state.waitFor("old:dep_0", "calculator");
    state.markResolved("POST:/compute:dep_0");
    state.renameDeclared("old:dep_0", "POST:/compute:dep_0");

    const winner = await Promise.race([
      displaced.then(() => "released"),
      new Promise((resolve) => setTimeout(resolve, 1000, "stuck")),
    ]);
    expect(winner).toBe("released");
  });

  it("a waiting route call unblocks when the dependency resolves", async () => {
    setBudget("10");
    const registry = RouteRegistry.getInstance();
    const routeId = registry.registerRoute("GET", "/data", [
      { capability: "store" },
    ]);
    const state = getSettleState();

    setTimeout(
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      () => registry.setDependency(routeId, 0, { live: true } as any),
      150,
    );

    const start = Date.now();
    await state.waitFor(`${routeId}:dep_0`, "store");
    const elapsedMs = Date.now() - start;

    expect(elapsedMs).toBeLessThan(5000);
    expect(registry.getDependency(routeId, 0)).toEqual({ live: true });
  });
});
