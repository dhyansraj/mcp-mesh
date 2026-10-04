/**
 * Issue #1593 (#1250 round-trip contract): a TS producer returning
 * `null`/`undefined` must reach the wire the way a Python `None` return does
 * — an EMPTY content array (FastMCP TS builds `{content: []}` from a
 * nullish execute result) — so every consumer reads it back as null. It used
 * to be collapsed to text `""`, indistinguishable from a real `""` return.
 * `""`, `[]` and `{}` keep their exact text blocks.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { z } from "zod";
import { MeshAgent } from "../agent.js";
import { RouteRegistry } from "../route.js";
import { resetSettleStateForTests } from "../settle.js";
import { extractContent } from "../proxy.js";

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

/**
 * FastMCP TS's own conversion of an execute return — a hand copy of the
 * `maybeStringResult` branch in node_modules/fastmcp/dist/chunk-LWU5CQGW.js
 * (`=== void 0 || === null` → `{content: []}`; string → one text block).
 */
function toWire(ret: unknown): { content: Array<{ type: string; text: string }> } {
  if (ret === undefined || ret === null) return { content: [] };
  return { content: [{ type: "text", text: ret as string }] };
}

async function wireFor(value: unknown, name: string) {
  const fastmcp = { addTool: vi.fn(), start: vi.fn(), getApp: vi.fn() };
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  new MeshAgent(fastmcp as any, { name: `env-${name}`, httpPort: 0 }).addTool({
    name,
    parameters: z.object({}),
    execute: async () => value as never,
  });
  const execute = fastmcp.addTool.mock.calls[0][0].execute as (a: unknown) => Promise<unknown>;
  return toWire(await execute({}));
}

describe("producer empty-return envelope (#1250 parity)", () => {
  it("null serializes to empty content and round-trips as null", async () => {
    const wire = await wireFor(null, "ret_null");
    expect(wire.content).toEqual([]);
    expect(extractContent(wire)).toBeNull();
  });

  it("undefined serializes to empty content and round-trips as null", async () => {
    await Promise.resolve();
    const wire = await wireFor(undefined, "ret_undef");
    expect(wire.content).toEqual([]);
    expect(extractContent(wire)).toBeNull();
  });

  it('"" stays a text block and round-trips as ""', async () => {
    const wire = await wireFor("", "ret_empty_str");
    expect(wire.content).toEqual([{ type: "text", text: "" }]);
    expect(extractContent(wire)).toBe("");
  });

  it("[] and {} keep their exact text blocks", async () => {
    expect((await wireFor([], "ret_list")).content).toEqual([{ type: "text", text: "[]" }]);
    await Promise.resolve();
    expect((await wireFor({}, "ret_obj")).content).toEqual([{ type: "text", text: "{}" }]);
  });
});
