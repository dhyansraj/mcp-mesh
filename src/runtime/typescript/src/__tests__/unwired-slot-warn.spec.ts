/**
 * Unwired typed-dependency-slot diagnostics (issue #1231).
 *
 * "N/N deps resolved" is registry provider-matching, not slot injection: a
 * typed dependency slot can resolve at the registry yet never receive an
 * injected proxy, leaving the parameter silently null. The deps array is
 * rebuilt PER CALL, so the diagnostic must warn ONCE per tool+slot (a
 * per-call warning would spam) and only AFTER the settle latch has flipped
 * (during settling the proxy may still land).
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { z } from "zod";
import { MeshAgent, __resetUnwiredSlotWarnedForTests } from "../agent.js";
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

let autoStartSpy: ReturnType<typeof vi.spyOn> | null = null;
let warnSpy: ReturnType<typeof vi.spyOn> | null = null;
const savedEnv: Record<string, string | undefined> = {};

beforeEach(() => {
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
  // Disable the settle grace so the agent is settled immediately — a null
  // slot here is genuinely unwired, exactly the case the warning targets.
  process.env.MCP_MESH_SETTLE_TIMEOUT = "0";
  resetSettleStateForTests();
  RouteRegistry.reset();
  __resetUnwiredSlotWarnedForTests();
});

afterEach(() => {
  if (autoStartSpy) {
    autoStartSpy.mockRestore();
    autoStartSpy = null;
  }
  if (warnSpy) {
    warnSpy.mockRestore();
    warnSpy = null;
  }
  for (const [key, value] of Object.entries(savedEnv)) {
    if (value === undefined) delete process.env[key];
    else process.env[key] = value;
  }
  resetSettleStateForTests();
  RouteRegistry.reset();
  __resetUnwiredSlotWarnedForTests();
});

function unwiredWarnings(): string[] {
  return (warnSpy?.mock.calls ?? [])
    .map((call) => String(call[0]))
    .filter((msg) => msg.includes("resolved but no proxy was injected"));
}

describe("unwired typed-slot warning (#1231)", () => {
  it("warns ONCE per tool+slot across multiple calls, not per-call", async () => {
    const fastmcp = makeFastMCPStub();
    const agent = new MeshAgent(fastmcp, {
      name: "unwired-agent",
      httpPort: 0,
    });
    agent.addTool({
      name: "consumer_tool",
      parameters: z.object({}),
      dependencies: [{ capability: "missing_cap" }],
      // Defensive user idiom — the dep slot is never resolved, so it stays
      // null on every call.
      execute: async (_args: unknown, dep: unknown) =>
        dep ? "wired" : "unwired",
    });
    const execute = fastmcp.addTool.mock.calls[0][0].execute as (
      args: unknown,
    ) => Promise<string>;

    for (let i = 0; i < 3; i++) {
      expect(await execute({})).toBe("unwired");
    }

    const warnings = unwiredWarnings();
    expect(warnings).toHaveLength(1);
    expect(warnings[0]).toContain("missing_cap");
    expect(warnings[0]).toContain("consumer_tool");
    expect(warnings[0]).toContain("slot 0");
  });

  it("does not warn when the slot actually wires", async () => {
    const fastmcp = makeFastMCPStub();
    const agent = new MeshAgent(fastmcp, {
      name: "wired-agent",
      httpPort: 0,
    });
    agent.addTool({
      name: "wired_tool",
      parameters: z.object({}),
      dependencies: [{ capability: "present_cap" }],
      execute: async (_args: unknown, dep: unknown) =>
        dep ? "wired" : "unwired",
    });
    const execute = fastmcp.addTool.mock.calls[0][0].execute as (
      args: unknown,
    ) => Promise<string>;

    // Resolve the dependency so a real proxy lands in the slot.
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (agent as any).handleDependencyAvailable(
      "present_cap",
      "http://localhost:19999",
      "remote_fn",
      "provider-agent",
      "wired_tool",
      0,
    );

    expect(await execute({})).toBe("wired");
    expect(unwiredWarnings()).toHaveLength(0);
  });
});
