/**
 * Issue #972: TS-side A2A producer/consumer flag detection.
 *
 * Each runtime path stamps the flags differently:
 * - MCP-agent path (`agent.ts`):
 *     * `a2aProducer`: always false (mesh.a2a.mount() not used by this path
 *       in v1 — out of scope follow-up).
 *     * `a2aConsumer`: walks `this.tools` and trips when any tool registers
 *       with `a2aConfig` (the marker stamped at registration time).
 * - Express path (`express.ts`) / API-runtime path (`api-runtime.ts`):
 *     * `a2aProducer`: derived from
 *       `A2AProducerRegistry.buildAgentSpecContribution(...).a2aProducer`.
 *     * `a2aConsumer`: always false (mesh.route() consumes capabilities via
 *       a different mechanism — no a2aConfig marker on this path in v1).
 *
 * Tests cover the per-path detection of the four combinations.
 */
import { describe, it, expect, beforeEach } from "vitest";

import { A2AProducerRegistry } from "../a2a/producer/registry.js";

// ─────────────────────────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────────────────────────

function resetProducerRegistry(): void {
  // Vacate any state leaked from earlier tests in the suite. The class
  // exposes a static `reset()` that nulls the singleton, ensuring the next
  // `getInstance()` call returns a fresh empty registry.
  A2AProducerRegistry.reset();
}

// ─────────────────────────────────────────────────────────────────────
// Express / API-runtime path — `buildAgentSpecContribution` returns the
// producer flag directly; consumer is hard-coded false on that path.
// ─────────────────────────────────────────────────────────────────────

describe("Issue #972 — A2AProducerRegistry.buildAgentSpecContribution producer flag", () => {
  beforeEach(() => {
    resetProducerRegistry();
  });

  it("returns a2aProducer=false when no surfaces are registered", () => {
    const reg = A2AProducerRegistry.getInstance();
    const out = reg.buildAgentSpecContribution("api");
    expect(out.a2aProducer).toBe(false);
    expect(out.agentType).toBe("api");
    expect(out.surfacesJson).toBeUndefined();
  });

  it("returns a2aProducer=true once at least one surface is registered", () => {
    const reg = A2AProducerRegistry.getInstance();
    reg.register({
      path: "/agents/x",
      skillId: "x",
      skillName: "X",
      description: "",
      tags: [],
      dependencies: [],
      auth: "",
      routeId: "rt-1",
    });
    const out = reg.buildAgentSpecContribution("api");
    expect(out.a2aProducer).toBe(true);
    expect(out.agentType).toBe("a2a");
    expect(out.surfacesJson).toBeDefined();
  });

  it("nonA2aType fallback ('mcp_agent') is honored when no surfaces", () => {
    const reg = A2AProducerRegistry.getInstance();
    const out = reg.buildAgentSpecContribution("mcp_agent");
    expect(out.a2aProducer).toBe(false);
    expect(out.agentType).toBe("mcp_agent");
  });
});

// ─────────────────────────────────────────────────────────────────────
// MCP-agent path — consumer flag is derived from the tool map. We can't
// boot the full agent, so we exercise the detection predicate directly
// with the same shape `agent.ts` builds.
// ─────────────────────────────────────────────────────────────────────

describe("Issue #972 — MCP-agent path consumer detection", () => {
  interface FakeToolMeta {
    a2aConsumer?: boolean;
  }

  function detectA2aConsumer(tools: Map<string, FakeToolMeta>): boolean {
    // Mirrors the inline detection inside `agent.ts::startHeartbeat`. Kept
    // separate here so the test can run without a full agent boot.
    for (const t of tools.values()) {
      if (t.a2aConsumer === true) return true;
    }
    return false;
  }

  it("neither — empty tool map → a2aConsumer=false", () => {
    expect(detectA2aConsumer(new Map())).toBe(false);
  });

  it("producer-only — tool without a2aConsumer marker → false", () => {
    const tools = new Map<string, FakeToolMeta>([["t1", {}]]);
    expect(detectA2aConsumer(tools)).toBe(false);
  });

  it("consumer-only — tool with a2aConsumer=true → true", () => {
    const tools = new Map<string, FakeToolMeta>([["t1", { a2aConsumer: true }]]);
    expect(detectA2aConsumer(tools)).toBe(true);
  });

  it("bridge — mix of a2aConsumer and plain tools → true", () => {
    const tools = new Map<string, FakeToolMeta>([
      ["t1", {}],
      ["t2", { a2aConsumer: true }],
    ]);
    expect(detectA2aConsumer(tools)).toBe(true);
  });
});
