/**
 * Tests for `addTool({ a2aConfig: ... })` integration in agent.ts
 * (issue #917).
 *
 * Targets the registration-time validation, A2AClient cache, and
 * heartbeat-build auto-tag injection. Doesn't bind to a real registry
 * — `_autoStart` is stubbed out, and we reach into the agent's
 * private fields to assert the cache state.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { z } from "zod";
import { MeshAgent } from "../../agent.js";
import { A2AClient } from "../../a2a/a2a-client.js";

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

function newAgent(name = "date-consumer"): MeshAgent {
  return new MeshAgent(makeFastMCPStub(), { name, httpPort: 0 });
}

describe("addTool({ a2aConfig }) — registration-time validation", () => {
  it("rejects empty url", () => {
    const agent = newAgent();
    expect(() =>
      agent.addTool({
        name: "bad",
        capability: "x",
        parameters: z.object({}),
        a2aConfig: { url: "" },
        execute: async () => "ok",
      }),
    ).toThrow(/url must be a non-empty string/);
  });

  it("rejects non-positive timeoutMs", () => {
    const agent = newAgent();
    expect(() =>
      agent.addTool({
        name: "bad",
        capability: "x",
        parameters: z.object({}),
        a2aConfig: { url: "http://x", timeoutMs: 0 },
        execute: async () => "ok",
      }),
    ).toThrow(/timeoutMs.*must be > 0/);
  });

  it("accepts a valid a2aConfig and registers the tool", () => {
    const agent = newAgent();
    expect(() =>
      agent.addTool({
        name: "current-date",
        capability: "current-date",
        tags: ["a2a-bridge"],
        parameters: z.object({}),
        a2aConfig: {
          url: "http://localhost:9090/agents/date",
          skillId: "get-date",
        },
        execute: async (_args, _a2a) => "ok",
      }),
    ).not.toThrow();
  });
});

describe("A2AClient cache", () => {
  it("returns the same A2AClient for two tools sharing the same config tuple", () => {
    const agent = newAgent();
    agent.addTool({
      name: "tool-a",
      capability: "current-date",
      parameters: z.object({}),
      a2aConfig: { url: "http://localhost:9090/agents/date", skillId: "get-date" },
      execute: async () => "ok",
    });
    agent.addTool({
      name: "tool-b",
      capability: "alt-date",
      parameters: z.object({}),
      a2aConfig: { url: "http://localhost:9090/agents/date", skillId: "get-date" },
      execute: async () => "ok",
    });
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const cache = (agent as any)._a2aClients as Map<string, A2AClient>;
    expect(cache.size).toBe(1);
    const onlyEntry = [...cache.values()][0];
    expect(onlyEntry).toBeInstanceOf(A2AClient);
  });

  it("returns separate clients for different urls", () => {
    const agent = newAgent();
    agent.addTool({
      name: "tool-a",
      capability: "x",
      parameters: z.object({}),
      a2aConfig: { url: "http://a/agents/x", skillId: "x" },
      execute: async () => "ok",
    });
    agent.addTool({
      name: "tool-b",
      capability: "x",
      parameters: z.object({}),
      a2aConfig: { url: "http://b/agents/x", skillId: "x" },
      execute: async () => "ok",
    });
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const cache = (agent as any)._a2aClients as Map<string, A2AClient>;
    expect(cache.size).toBe(2);
  });
});

describe("auto-tag injection at heartbeat-build time", () => {
  it("appends the agent name to the tool's tags when a2aConfig is set", async () => {
    const agent = newAgent("my-consumer");
    agent.addTool({
      name: "current-date",
      capability: "current-date",
      tags: ["a2a-bridge"],
      parameters: z.object({}),
      a2aConfig: { url: "http://x/agents/y", skillId: "y" },
      execute: async () => "ok",
    });
    // Reach into private state to inspect what heartbeat-build will ship.
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const tools = (agent as any).tools as Map<string, { tags: string[]; a2aConsumer?: boolean; a2aAgentName?: string }>;
    const meta = tools.get("current-date");
    expect(meta?.a2aConsumer).toBe(true);
    expect(meta?.a2aAgentName).toBe("my-consumer");
    // The original tags array stored in meta is unchanged (defensive copy
    // happens inside the heartbeat path); the on-the-wire tags receive
    // the auto-tag.
    expect(meta?.tags).toEqual(["a2a-bridge"]);
  });

  it("does NOT mark a2aConsumer when a2aConfig is absent", () => {
    const agent = newAgent();
    agent.addTool({
      name: "plain",
      capability: "plain",
      parameters: z.object({}),
      execute: async () => "ok",
    });
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const tools = (agent as any).tools as Map<string, { a2aConsumer?: boolean }>;
    expect(tools.get("plain")?.a2aConsumer).toBeFalsy();
  });
});
