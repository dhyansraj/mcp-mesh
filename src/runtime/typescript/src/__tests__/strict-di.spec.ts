/**
 * Issue #1593: TS dependency/parameter arity diagnostic + MCP_MESH_STRICT_DI.
 *
 * Acceptance is the Python runtime: an excess-dependency mismatch warns by
 * default and raises at registration time when MCP_MESH_STRICT_DI is truthy
 * (true/1/yes/on, case-insensitive). Signatures whose arity cannot be known
 * (rest parameters) are never diagnosed.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { z } from "zod";
import { MeshAgent } from "../agent.js";
import { RouteRegistry } from "../route.js";
import { getSettleState, resetSettleStateForTests } from "../settle.js";
import {
  StrictDIError,
  declaredParameters,
  parameterLabel,
  isStrictDiEnabled,
  __resetStrictDiCacheForTests,
} from "../strict-di.js";

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
let errorSpy: ReturnType<typeof vi.spyOn> | null = null;
const savedStrict = process.env.MCP_MESH_STRICT_DI;

beforeEach(() => {
  autoStartSpy = vi
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    .spyOn(MeshAgent.prototype as any, "_autoStart")
    .mockImplementation(async () => {});
  warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
  errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
  delete process.env.MCP_MESH_STRICT_DI;
  __resetStrictDiCacheForTests();
  resetSettleStateForTests();
  RouteRegistry.reset();
});

afterEach(async () => {
  await new Promise<void>((resolve) => process.nextTick(resolve));
  autoStartSpy?.mockRestore();
  warnSpy?.mockRestore();
  errorSpy?.mockRestore();
  if (savedStrict === undefined) delete process.env.MCP_MESH_STRICT_DI;
  else process.env.MCP_MESH_STRICT_DI = savedStrict;
  __resetStrictDiCacheForTests();
  resetSettleStateForTests();
  RouteRegistry.reset();
});

function arityWarnings(): string[] {
  return (warnSpy?.mock.calls ?? [])
    .map((c) => String(c[0]))
    .filter((m) => m.includes("will not be injected"));
}

function newAgent(name: string) {
  const fastmcp = makeFastMCPStub();
  return new MeshAgent(fastmcp, { name, httpPort: 0 });
}

describe("declaredParameters", () => {
  it("counts default-valued parameters that Function.length skips", () => {
    const fn = async (_a: unknown, _b: unknown = null, _c = 1) => _c;
    expect(fn.length).toBe(1);
    expect(declaredParameters(fn)).toHaveLength(3);
  });

  it("returns null for a rest parameter (unbounded arity)", () => {
    expect(declaredParameters(async (_a: unknown, ..._r: unknown[]) => 0)).toBeNull();
  });

  it("handles destructured args with nested commas and defaults", () => {
    const fn = async (
      { a, b = [1, 2] }: { a: number; b?: number[] },
      dep: unknown = { x: "(,)" },
    ) => [a, b, dep];
    const params = declaredParameters(fn)!;
    expect(params).toHaveLength(2);
    expect(parameterLabel(params[1])).toBe("dep");
  });

  it("handles single-identifier arrows, function expressions and methods", () => {
    // eslint-disable-next-line @typescript-eslint/no-unused-vars
    expect(declaredParameters((x: unknown) => x)).toHaveLength(1);
    expect(declaredParameters(function named(a: unknown, b: unknown) { return [a, b]; })).toHaveLength(2);
    const obj = { m(a: unknown, b: unknown, c: unknown) { return [a, b, c]; } };
    expect(declaredParameters(obj.m)).toHaveLength(3);
    expect(declaredParameters(async () => 0)).toEqual([]);
  });

  it("returns null for code that reads `arguments` (ES5 rest, forwarding wrappers)", () => {
    const es5 = new Function(
      "args",
      "var deps = Array.prototype.slice.call(arguments, 1); return deps;",
    );
    expect(declaredParameters(es5)).toBeNull();
    // memoize/once-style wrapper: zero declared params, forwards everything.
    const memoize = (fn: (...a: unknown[]) => unknown) =>
      // eslint-disable-next-line prefer-rest-params
      function (this: unknown) { return fn.apply(this, arguments as unknown as unknown[]); };
    expect(declaredParameters(memoize((a: unknown) => a))).toBeNull();
  });

  it("returns null when the scanned count is below fn.length", () => {
    const fn = (a: unknown, b: unknown) => [a, b];
    Object.defineProperty(fn, "length", { value: 5 });
    expect(declaredParameters(fn)).toBeNull();
  });

  it("returns null for a regex literal in the parameter list", () => {
    expect(declaredParameters(new Function("args", "re = /\\)/", "dep", "return dep"))).toBeNull();
  });

  it("returns null for a template literal with a substitution", () => {
    expect(
      declaredParameters(new Function("args", "t = `${'(' + `)`}`", "dep", "return dep")),
    ).toBeNull();
  });

  it("returns null for computed and string-literal method keys", () => {
    const computed = { [Symbol.for("x")](args: unknown, dep: unknown) { return [args, dep]; } };
    expect(declaredParameters(computed[Symbol.for("x")])).toBeNull();
    const quoted = { "a(b"(args: unknown, dep: unknown) { return [args, dep]; } };
    expect(declaredParameters(quoted["a(b"])).toBeNull();
  });

  it("returns null for bound/native functions", () => {
    expect(declaredParameters(Math.max)).toBeNull();
    expect(declaredParameters(function f(a: unknown) { return a; }.bind(null))).toBeNull();
  });
});

describe("MCP_MESH_STRICT_DI truthy parsing (Python TRUTHY_RULE)", () => {
  for (const v of ["true", "TRUE", "1", "yes", "on", "On"]) {
    it(`'${v}' enables strict mode`, () => {
      process.env.MCP_MESH_STRICT_DI = v;
      __resetStrictDiCacheForTests();
      expect(isStrictDiEnabled()).toBe(true);
    });
  }
  for (const v of ["false", "0", "no", "off", "maybe", ""]) {
    it(`'${v}' leaves strict mode off`, () => {
      process.env.MCP_MESH_STRICT_DI = v;
      __resetStrictDiCacheForTests();
      expect(isStrictDiEnabled()).toBe(false);
    });
  }
});

describe("excess-dependency diagnostic (#1593)", () => {
  it("warns (permissive) when dependencies exceed execute parameters", () => {
    newAgent("arity-warn").addTool({
      name: "over_declared",
      parameters: z.object({}),
      dependencies: ["alpha", "beta", "gamma"],
      execute: async (_args: unknown, alpha: unknown) => String(alpha),
    });
    const warnings = arityWarnings();
    expect(warnings).toHaveLength(1);
    expect(warnings[0]).toContain("Tool 'over_declared' has 3 dependencies");
    expect(warnings[0]).toContain("only 1 injectable parameter");
    expect(warnings[0]).toContain("dependencies[0] 'alpha' → parameter 'alpha'");
    expect(warnings[0]).toContain('["beta","gamma"]');
  });

  it("throws StrictDIError at addTool under MCP_MESH_STRICT_DI", () => {
    process.env.MCP_MESH_STRICT_DI = "true";
    __resetStrictDiCacheForTests();
    const agent = newAgent("arity-strict");
    expect(() =>
      agent.addTool({
        name: "over_declared",
        parameters: z.object({}),
        dependencies: ["alpha", "beta"],
        execute: async (_args: unknown) => "x",
      }),
    ).toThrow(StrictDIError);
    expect(arityWarnings()).toHaveLength(0);
  });

  it("does not diagnose matched arity, default-valued slots or rest params", () => {
    process.env.MCP_MESH_STRICT_DI = "true";
    __resetStrictDiCacheForTests();
    const agent = newAgent("arity-ok");
    agent.addTool({
      name: "matched",
      parameters: z.object({}),
      dependencies: ["alpha", "beta"],
      execute: async (_args: unknown, a: unknown = null, b: unknown = null) =>
        String([a, b]),
    });
    agent.addTool({
      name: "rest",
      parameters: z.object({}),
      dependencies: ["alpha", "beta"],
      execute: async (_args: unknown, ...deps: unknown[]) => String(deps),
    });
    agent.addTool({
      name: "no_deps",
      parameters: z.object({}),
      execute: async () => "x",
    });
    expect(arityWarnings()).toHaveLength(0);
  });

  it("never counts the A2AClient against dependencies (it is appended after them)", async () => {
    process.env.MCP_MESH_STRICT_DI = "true";
    __resetStrictDiCacheForTests();
    // (args, alpha, a2a): alpha is injected, the client lands in `a2a`.
    newAgent("arity-a2a").addTool({
      name: "a2a_tool",
      parameters: z.object({}),
      dependencies: ["alpha"],
      a2aConfig: { url: "http://localhost:1/a2a" },
      execute: async (_args: unknown, alpha: unknown, a2a: unknown) =>
        String([alpha, a2a]),
    });
    expect(arityWarnings()).toHaveLength(0);
    await Promise.resolve();

    // (args, alpha): alpha is still injected correctly; the client simply
    // goes unread. Not excess DI — no StrictDIError, only a plain warning.
    expect(() =>
      newAgent("arity-a2a-2").addTool({
        name: "a2a_tool_short",
        parameters: z.object({}),
        dependencies: ["alpha"],
        a2aConfig: { url: "http://localhost:1/a2a" },
        execute: async (_args: unknown, alpha: unknown) => String(alpha),
      }),
    ).not.toThrow();
    expect(arityWarnings()).toHaveLength(0);
    const a2aWarnings = (warnSpy?.mock.calls ?? [])
      .map((c) => String(c[0]))
      .filter((m) => m.includes("no execute parameter receives the A2AClient"));
    expect(a2aWarnings).toHaveLength(1);
    expect(a2aWarnings[0]).toContain("a2a_tool_short");
  });

  it("does not register surplus dependencies as settle keys", () => {
    process.env.MCP_MESH_SETTLE_TIMEOUT = "10";
    resetSettleStateForTests();
    newAgent("arity-settle").addTool({
      name: "surplus",
      parameters: z.object({}),
      dependencies: ["alpha", "beta"],
      execute: async (_args: unknown, alpha: unknown) => String(alpha),
    });
    const state = getSettleState();
    expect(state.isSettled()).toBe(false);
    state.markResolved("surplus:dep_0");
    // dep_1 can never be injected, so it must not hold the agent unsettled.
    expect(state.isSettled()).toBe(true);
    delete process.env.MCP_MESH_SETTLE_TIMEOUT;
  });

  it("does not cache an A2A client when strict mode rejects the tool", async () => {
    process.env.MCP_MESH_STRICT_DI = "true";
    __resetStrictDiCacheForTests();
    const agent = newAgent("arity-orphan");
    expect(() =>
      agent.addTool({
        name: "orphan",
        parameters: z.object({}),
        dependencies: ["alpha", "beta"],
        a2aConfig: { url: "http://localhost:1/a2a" },
        execute: async (_args: unknown, alpha: unknown) => String(alpha),
      }),
    ).toThrow(StrictDIError);
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    expect((agent as any)._a2aClients.size).toBe(0);
  });
});
