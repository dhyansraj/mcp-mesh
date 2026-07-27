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
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { z } from "zod";
import { MeshAgent, __resetUnwiredSlotWarnedForTests } from "../agent.js";
import { PROXY_DISPATCH_META } from "../proxy.js";
import { MeshJobSubmitter } from "../mesh-job-submitter.js";
import { RouteRegistry } from "../route.js";
import { resetSettleStateForTests } from "../settle.js";

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
