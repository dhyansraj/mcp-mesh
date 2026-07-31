/**
 * Issue #1442: two declarations may not advertise the same MCP tool name.
 *
 * `def.name` is the wire name — the heartbeat ships it as the tool's
 * `function_name` and a client's `tools/call` sends it straight back as
 * `params.name`. `addTool` validated the capability grammar but never checked
 * the tool NAME, and both registration sinks are last-wins: `this.tools` is a
 * plain `Map.set`, and fastmcp's own `addTool` filters out the previous entry.
 * A second tool under an existing name therefore made the first one vanish from
 * `tools/list` while the registry kept advertising it.
 *
 * The guard's discriminator is the DECLARATION (published capability + handler
 * source), not the definition object's reference — the PR #1445 lesson: the
 * re-registration paths are precisely the ones that hand over a fresh object
 * for an unchanged declaration.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { z } from "zod";
import { MeshAgent } from "../agent.js";

function makeFastMCPStub() {
  return {
    addTool: vi.fn(),
    start: vi.fn(),
    getApp: vi.fn(),
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
  } as any;
}

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

describe("addTool — duplicate advertised tool name (issue #1442)", () => {
  function newAgent(): MeshAgent {
    return new MeshAgent(makeFastMCPStub(), {
      name: "test-agent-dupname",
      httpPort: 0,
    });
  }

  it("rejects a second, different declaration under the same tool name", () => {
    const agent = newAgent();
    agent.addTool({
      name: "analyze",
      capability: "analyze-text",
      parameters: z.object({}),
      execute: async () => "text",
    });

    expect(() =>
      agent.addTool({
        name: "analyze",
        capability: "analyze-image",
        parameters: z.object({}),
        execute: async () => "image",
      }),
    ).toThrow(/duplicate MCP tool name 'analyze'/);
  });

  it("names both colliding declarations in the error", () => {
    const agent = newAgent();
    agent.addTool({
      name: "search",
      capability: "search-docs",
      parameters: z.object({}),
      execute: async () => "docs",
    });

    let message = "";
    try {
      agent.addTool({
        name: "search",
        capability: "search-people",
        parameters: z.object({}),
        execute: async () => "people",
      });
    } catch (err) {
      message = String(err);
    }
    expect(message).toContain("'search'");
    expect(message).toContain("search-docs");
    expect(message).toContain("search-people");
  });

  it("rejects a same-capability tool whose handler differs", () => {
    // Same published capability, different implementation — still two tools
    // fighting over one wire name.
    const agent = newAgent();
    agent.addTool({
      name: "greet",
      parameters: z.object({}),
      execute: async () => "hello",
    });

    expect(() =>
      agent.addTool({
        name: "greet",
        parameters: z.object({}),
        execute: async () => "goodbye",
      }),
    ).toThrow(/duplicate MCP tool name 'greet'/);
  });

  it("does not register the rejected tool with fastmcp", () => {
    const stub = makeFastMCPStub();
    const agent = new MeshAgent(stub, {
      name: "test-agent-dupname-nofastmcp",
      httpPort: 0,
    });
    agent.addTool({
      name: "analyze",
      parameters: z.object({}),
      execute: async () => "first",
    });
    expect(() =>
      agent.addTool({
        name: "analyze",
        parameters: z.object({}),
        execute: async () => "second",
      }),
    ).toThrow();

    // Exactly one fastmcp registration — the guard runs before anything is
    // handed to the server.
    expect(stub.addTool).toHaveBeenCalledTimes(1);
  });

  it("allows distinct tool names", () => {
    const agent = newAgent();
    expect(() => {
      agent.addTool({
        name: "greet",
        parameters: z.object({}),
        execute: async () => "hi",
      });
      agent.addTool({
        name: "farewell",
        parameters: z.object({}),
        execute: async () => "bye",
      });
    }).not.toThrow();
  });

  // ── Idempotent re-registration is NOT a collision (the #1445 regression) ──

  it("tolerates re-registering the exact same definition object", () => {
    const agent = newAgent();
    const def = {
      name: "greet",
      capability: "greet",
      parameters: z.object({}),
      execute: async () => "hi",
    };
    agent.addTool(def);
    expect(() => agent.addTool(def)).not.toThrow();
  });

  it("tolerates an equivalent declaration built from a fresh object", () => {
    // A module re-evaluated (test-runner module reset, dual CJS/ESM load)
    // rebuilds the definition AND the handler closure. Reference identity
    // would boot-fail that; the declaration identity does not.
    const agent = newAgent();
    const build = () => ({
      name: "greet",
      capability: "greet",
      parameters: z.object({}),
      execute: async () => "hi",
    });
    const first = build();
    const second = build();
    expect(first).not.toBe(second);
    expect(first.execute).not.toBe(second.execute);

    agent.addTool(first);
    expect(() => agent.addTool(second)).not.toThrow();
  });

  it("tolerates a re-registration that only changes non-wire metadata", () => {
    const agent = newAgent();
    const execute = async () => "hi";
    agent.addTool({
      name: "greet",
      capability: "greet",
      description: "first pass",
      parameters: z.object({}),
      execute,
    });
    expect(() =>
      agent.addTool({
        name: "greet",
        capability: "greet",
        description: "second pass",
        parameters: z.object({}),
        execute,
      }),
    ).not.toThrow();
  });

  it("guards worker mode too", () => {
    // Worker mode returns early from addTool (no fastmcp, no metadata), but
    // the tool name still keys `_workerToolMap`, so the same collision applies.
    const agent = newAgent();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (agent as any)._workerMode = true;
    agent.addTool({
      name: "analyze",
      parameters: z.object({}),
      execute: async () => "first",
    });
    expect(() =>
      agent.addTool({
        name: "analyze",
        parameters: z.object({}),
        execute: async () => "second",
      }),
    ).toThrow(/duplicate MCP tool name 'analyze'/);
  });
});

// =============================================================================
// The identity has to cover the WHOLE wire shape, not just the handler body.
// Two declarations can share an `execute` source and still publish different
// schemas / dependencies / tags / versions — and `Function.prototype.toString`
// collapses to "[native code]" for bound and native functions, which would make
// every one of those look like the same declaration.
// =============================================================================

describe("addTool — declaration identity covers the wire shape (#1442)", () => {
  function newAgent(): MeshAgent {
    return new MeshAgent(makeFastMCPStub(), {
      name: "test-agent-identity",
      httpPort: 0,
    });
  }

  const sharedExecute = async () => "x";

  function addWith(agent: MeshAgent, extra: Record<string, unknown>) {
    agent.addTool({
      name: "tool",
      parameters: z.object({}),
      execute: sharedExecute,
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      ...(extra as any),
    });
  }

  it("distinguishes declarations that differ only in input schema", () => {
    const agent = newAgent();
    agent.addTool({
      name: "tool",
      parameters: z.object({ a: z.string() }),
      execute: sharedExecute,
    });
    expect(() =>
      agent.addTool({
        name: "tool",
        parameters: z.object({ b: z.number() }),
        execute: sharedExecute,
      }),
    ).toThrow(/duplicate MCP tool name 'tool'/);
  });

  it("distinguishes declarations that differ only in dependencies", () => {
    const agent = newAgent();
    addWith(agent, { dependencies: ["alpha"] });
    expect(() => addWith(agent, { dependencies: ["beta"] })).toThrow(
      /duplicate MCP tool name 'tool'/,
    );
  });

  it("distinguishes declarations that differ only in tags", () => {
    const agent = newAgent();
    addWith(agent, { tags: ["one"] });
    expect(() => addWith(agent, { tags: ["two"] })).toThrow(
      /duplicate MCP tool name 'tool'/,
    );
  });

  it("distinguishes declarations that differ only in version", () => {
    const agent = newAgent();
    addWith(agent, { version: "1.0.0" });
    expect(() => addWith(agent, { version: "2.0.0" })).toThrow(
      /duplicate MCP tool name 'tool'/,
    );
  });

  it("distinguishes bound handlers, whose source text is '[native code]'", () => {
    // Both handlers stringify to "function () { [native code] }" — the source
    // text carries NO information here, so the wire fields are the only thing
    // left to tell the two declarations apart.
    const agent = newAgent();
    const boundA = (async () => "a").bind(null);
    const boundB = (async () => "b").bind(null);
    expect(boundA.toString()).toBe(boundB.toString());

    agent.addTool({
      name: "tool",
      capability: "cap",
      parameters: z.object({ a: z.string() }),
      execute: boundA,
    });
    expect(() =>
      agent.addTool({
        name: "tool",
        capability: "cap",
        parameters: z.object({ b: z.number() }),
        execute: boundB,
      }),
    ).toThrow(/duplicate MCP tool name 'tool'/);
  });

  it("still tolerates a wire-identical redeclaration", () => {
    const agent = newAgent();
    const decl = () => ({
      name: "tool",
      capability: "cap",
      version: "1.0.0",
      tags: ["t"],
      dependencies: ["alpha"],
      parameters: z.object({ a: z.string() }),
      execute: async () => "x",
    });
    agent.addTool(decl());
    expect(() => agent.addTool(decl())).not.toThrow();
  });
});

// =============================================================================
// A failed registration must not leave the name claimed — otherwise fixing the
// declaration and retrying is refused by the guard. Python gets this via
// `unregister_mesh_tool`; this is the TS parity.
// =============================================================================

describe("addTool — a rejected declaration does not claim the name (#1442)", () => {
  function newAgent(): MeshAgent {
    return new MeshAgent(makeFastMCPStub(), {
      name: "test-agent-claim-late",
      httpPort: 0,
    });
  }

  it("a tool rejected by a LATER validation leaves the name free", () => {
    const agent = newAgent();
    // `task: true` with a sync execute throws — after the duplicate-name check.
    expect(() =>
      agent.addTool({
        name: "greet",
        task: true,
        parameters: z.object({}),
        execute: function () {
          return "x";
        },
      }),
    ).toThrow(/requires an async execute function/);

    // The corrected declaration must be accepted, not refused as a duplicate.
    expect(() =>
      agent.addTool({
        name: "greet",
        task: true,
        parameters: z.object({}),
        execute: async () => "x",
      }),
    ).not.toThrow();
  });

  it("a tool rejected by meshJobDepIndex validation leaves the name free", () => {
    const agent = newAgent();
    expect(() =>
      agent.addTool({
        name: "consume",
        parameters: z.object({}),
        dependencies: ["alpha"],
        meshJobDepIndex: 5,
        execute: async () => "x",
      }),
    ).toThrow(/out of range/);

    // The natural fix for an out-of-range index is to declare the dependency
    // it was pointing at — which changes the wire shape, so a claim left over
    // from the rejected attempt would refuse this as a duplicate.
    expect(() =>
      agent.addTool({
        name: "consume",
        parameters: z.object({}),
        dependencies: ["alpha", "beta", "gamma", "delta", "epsilon", "zeta"],
        meshJobDepIndex: 5,
        execute: async () => "x",
      }),
    ).not.toThrow();
  });
});

// =============================================================================
// addLlmProvider registers with FastMCP directly, never through addTool — so it
// needs the same guard. `llmProvider` defaults the tool name to "process_chat",
// so two providers with no explicit `name` both claim it.
// =============================================================================

describe("addLlmProvider — duplicate advertised tool name (#1442)", () => {
  function newAgent(): MeshAgent {
    return new MeshAgent(makeFastMCPStub(), {
      name: "test-agent-llmprovider",
      httpPort: 0,
    });
  }

  it("rejects two providers that both default to 'process_chat'", () => {
    const agent = newAgent();
    agent.addLlmProvider({
      model: "anthropic/claude-sonnet-4-5",
      capability: "llm-claude",
    });
    expect(() =>
      agent.addLlmProvider({
        model: "openai/gpt-4o-mini",
        capability: "llm-gpt",
      }),
    ).toThrow(/duplicate MCP tool name 'process_chat'/);
  });

  it("does not register the rejected provider with fastmcp", () => {
    const stub = makeFastMCPStub();
    const agent = new MeshAgent(stub, {
      name: "test-agent-llmprovider-nofastmcp",
      httpPort: 0,
    });
    agent.addLlmProvider({
      model: "anthropic/claude-sonnet-4-5",
      capability: "llm-claude",
    });
    expect(() =>
      agent.addLlmProvider({
        model: "openai/gpt-4o-mini",
        capability: "llm-gpt",
      }),
    ).toThrow();
    expect(stub.addTool).toHaveBeenCalledTimes(1);
  });

  it("allows two providers under explicitly distinct names", () => {
    const agent = newAgent();
    expect(() => {
      agent.addLlmProvider({
        model: "anthropic/claude-sonnet-4-5",
        capability: "llm-claude",
        name: "claude_chat",
      });
      agent.addLlmProvider({
        model: "openai/gpt-4o-mini",
        capability: "llm-gpt",
        name: "gpt_chat",
      });
    }).not.toThrow();
  });

  it("tolerates the same provider config registered twice", () => {
    const agent = newAgent();
    const config = {
      model: "anthropic/claude-sonnet-4-5",
      capability: "llm-claude",
    };
    agent.addLlmProvider({ ...config });
    expect(() => agent.addLlmProvider({ ...config })).not.toThrow();
  });

  it("the error names addLlmProvider, not addTool", () => {
    // The check is shared with `addTool`; the message must still point at the
    // API the caller actually invoked.
    const agent = newAgent();
    agent.addLlmProvider({
      model: "anthropic/claude-sonnet-4-5",
      capability: "llm-claude",
    });
    expect(() =>
      agent.addLlmProvider({
        model: "openai/gpt-4o-mini",
        capability: "llm-gpt",
      }),
    ).toThrow(/^addLlmProvider: duplicate MCP tool name/);
  });

  it("addTool's error still names addTool", () => {
    const agent = newAgent();
    agent.addTool({
      name: "greet",
      parameters: z.object({}),
      execute: async () => "a",
    });
    expect(() =>
      agent.addTool({
        name: "greet",
        parameters: z.object({}),
        execute: async () => "b",
      }),
    ).toThrow(/^addTool: duplicate MCP tool name/);
  });

  it("a provider collides with a same-named addTool declaration", () => {
    // Cross-surface: the wire name is one namespace regardless of which entry
    // point claimed it.
    const agent = newAgent();
    agent.addTool({
      name: "process_chat",
      capability: "my-chat",
      parameters: z.object({}),
      execute: async () => "x",
    });
    expect(() =>
      agent.addLlmProvider({
        model: "anthropic/claude-sonnet-4-5",
        capability: "llm-claude",
      }),
    ).toThrow(/duplicate MCP tool name 'process_chat'/);
  });
});

// =============================================================================
// The three `__mesh_job_*` helper names are framework-reserved. When a user
// tool owns one, the helper must not register over it on the FastMCP server.
// =============================================================================

describe("jobs helper tools — do not clobber a user tool (#1442)", () => {
  it("skips only the contested helper, on the server as well as the catalog", () => {
    const registered: string[] = [];
    const stub = {
      addTool: vi.fn((tool: { name: string }) => {
        registered.push(tool.name);
      }),
      start: vi.fn(),
      getApp: vi.fn(),
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
    } as any;
    const agent = new MeshAgent(stub, {
      name: "test-agent-jobshelper",
      httpPort: 0,
    });
    // `registryUrl` is resolved from the environment, not an AgentConfig field.
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (agent as any).config.registryUrl = "http://registry:8000";

    agent.addTool({
      name: "__mesh_job_status",
      capability: "my_status",
      parameters: z.object({}),
      execute: async () => "mine",
    });
    registered.length = 0;

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (agent as any).registerJobsHelperTools();

    expect(registered).not.toContain("__mesh_job_status");
    expect(registered).toContain("__mesh_job_result");
    expect(registered).toContain("__mesh_job_cancel");

    // The user's tool still owns the name in the catalog.
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    expect((agent as any).tools.get("__mesh_job_status").capability).toBe(
      "my_status",
    );
  });

  it("a helper registered FIRST blocks a later conflicting addTool", () => {
    // The reverse order. `registerJobsHelperTools` runs from `_autoStart`,
    // which is process.nextTick-scheduled and awaits the port probe — so any
    // `addTool` made after an `await` in user startup code lands after the
    // helpers. Without recording the helper names, that `addTool` passed the
    // guard and clobbered the helper on the FastMCP server (fastmcp's addTool
    // filters out the previous entry); the catalog's `tools.has` check only
    // protected the heartbeat view.
    const stub = makeFastMCPStub();
    const agent = new MeshAgent(stub, {
      name: "test-agent-jobshelper-reverse",
      httpPort: 0,
    });
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (agent as any).config.registryUrl = "http://registry:8000";

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (agent as any).registerJobsHelperTools();

    expect(() =>
      agent.addTool({
        name: "__mesh_job_status",
        capability: "my_status",
        parameters: z.object({}),
        execute: async () => "mine",
      }),
    ).toThrow(/duplicate MCP tool name '__mesh_job_status'/);
  });

  it("a second helper registration pass is idempotent, not a collision", () => {
    // Same declaration, same names — re-running the pass must not throw.
    const stub = makeFastMCPStub();
    const agent = new MeshAgent(stub, {
      name: "test-agent-jobshelper-twice",
      httpPort: 0,
    });
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (agent as any).config.registryUrl = "http://registry:8000";

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (agent as any).registerJobsHelperTools();
    expect(() => {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      (agent as any).registerJobsHelperTools();
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
    }).not.toThrow();
  });

  it("registers all three when uncontested", () => {
    const registered: string[] = [];
    const stub = {
      addTool: vi.fn((tool: { name: string }) => {
        registered.push(tool.name);
      }),
      start: vi.fn(),
      getApp: vi.fn(),
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
    } as any;
    const agent = new MeshAgent(stub, {
      name: "test-agent-jobshelper-clean",
      httpPort: 0,
    });
    // `registryUrl` is resolved from the environment, not an AgentConfig field.
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (agent as any).config.registryUrl = "http://registry:8000";

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (agent as any).registerJobsHelperTools();

    expect(registered).toEqual(
      expect.arrayContaining([
        "__mesh_job_status",
        "__mesh_job_result",
        "__mesh_job_cancel",
      ]),
    );
  });
});
