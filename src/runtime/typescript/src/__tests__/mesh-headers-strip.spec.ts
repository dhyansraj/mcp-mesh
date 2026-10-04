/**
 * Issue #1593: `_mesh_headers` is transport metadata and must never reach a
 * tool's arguments, whatever it carries. Python pops the key unconditionally
 * (`arguments.pop("_mesh_headers", None)`).
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { z } from "zod";
import { MeshAgent } from "../agent.js";
import { llm } from "../llm.js";
import { RouteRegistry } from "../route.js";
import { resetSettleStateForTests } from "../settle.js";

let autoStartSpy: ReturnType<typeof vi.spyOn> | null = null;
const savedIsolation = process.env.MCP_MESH_TOOL_ISOLATION;

beforeEach(() => {
  autoStartSpy = vi
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    .spyOn(MeshAgent.prototype as any, "_autoStart")
    .mockImplementation(async () => {});
  process.env.MCP_MESH_TOOL_ISOLATION = "false";
  resetSettleStateForTests();
  RouteRegistry.reset();
});

afterEach(async () => {
  await new Promise<void>((resolve) => process.nextTick(resolve));
  autoStartSpy?.mockRestore();
  if (savedIsolation === undefined) delete process.env.MCP_MESH_TOOL_ISOLATION;
  else process.env.MCP_MESH_TOOL_ISOLATION = savedIsolation;
  resetSettleStateForTests();
  RouteRegistry.reset();
});

async function argsSeenBy(name: string, inbound: Record<string, unknown>) {
  const fastmcp = { addTool: vi.fn(), start: vi.fn(), getApp: vi.fn() };
  let seen: Record<string, unknown> = {};
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  new MeshAgent(fastmcp as any, { name: `strip-${name}`, httpPort: 0 }).addTool({
    name,
    parameters: z.object({ q: z.string() }),
    execute: async (args) => {
      seen = args as Record<string, unknown>;
      return "ok";
    },
  });
  const execute = fastmcp.addTool.mock.calls[0][0].execute as (a: unknown) => Promise<unknown>;
  await execute(inbound);
  return seen;
}

describe("_mesh_headers is always stripped from tool args", () => {
  it("a map of only non-allowlisted headers", async () => {
    const seen = await argsSeenBy("only_foreign", {
      q: "x",
      _mesh_headers: { "x-not-allowlisted": "v" },
    });
    expect(seen).toEqual({ q: "x" });
  });

  it("an empty map", async () => {
    const seen = await argsSeenBy("empty_map", { q: "x", _mesh_headers: {} });
    expect(seen).toEqual({ q: "x" });
  });

  it("a null or non-object value", async () => {
    expect(await argsSeenBy("null_value", { q: "x", _mesh_headers: null })).toEqual({ q: "x" });
    await Promise.resolve();
    expect(await argsSeenBy("string_value", { q: "x", _mesh_headers: "junk" })).toEqual({ q: "x" });
  });

  it("mesh.llm tools strip a null _mesh_headers too", async () => {
    let seen: Record<string, unknown> = {};
    const tool = llm({
      name: "strip_llm",
      provider: { capability: "llm" },
      parameters: z.object({ q: z.string() }),
      execute: async (args) => {
        seen = args as Record<string, unknown>;
        return "ok";
      },
    });
    process.env.MCP_MESH_SETTLE_TIMEOUT = "0";
    resetSettleStateForTests();
    await tool.execute({ q: "x", _mesh_headers: null });
    delete process.env.MCP_MESH_SETTLE_TIMEOUT;
    expect(seen).toEqual({ q: "x" });
  });
});
