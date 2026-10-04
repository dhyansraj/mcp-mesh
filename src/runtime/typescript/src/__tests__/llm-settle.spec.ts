/**
 * Issue #1593 (Python #1456 parity): a `mesh.llm` consumer called while the
 * agent is still settling waits — bounded by the remaining settle budget —
 * for its provider to resolve instead of running with no provider.
 */
import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { z } from "zod";

import {
  llm,
  llmSettleKey,
  LlmToolRegistry,
  handleLlmProviderAvailable,
} from "../llm.js";
import { getSettleState, resetSettleStateForTests } from "../settle.js";

const saved = process.env.MCP_MESH_SETTLE_TIMEOUT;

beforeEach(() => {
  LlmToolRegistry.reset();
  resetSettleStateForTests();
});

afterEach(() => {
  if (saved === undefined) delete process.env.MCP_MESH_SETTLE_TIMEOUT;
  else process.env.MCP_MESH_SETTLE_TIMEOUT = saved;
  LlmToolRegistry.reset();
  resetSettleStateForTests();
});

function setBudget(seconds: string): void {
  process.env.MCP_MESH_SETTLE_TIMEOUT = seconds;
  resetSettleStateForTests();
}

function makeConsumer(name: string, seen: { provider?: unknown }) {
  return llm({
    name,
    provider: { capability: "llm" },
    parameters: z.object({}),
    execute: async () => {
      seen.provider = LlmToolRegistry.getInstance().getResolvedProvider(name);
      return "ok";
    },
  });
}

describe("mesh.llm provider settle gating", () => {
  it("declares the consumer's provider slot with the settle state", () => {
    setBudget("10");
    makeConsumer("declared_consumer", {});
    expect(getSettleState().isSettled()).toBe(false);
    expect(getSettleState().isResolved(llmSettleKey("declared_consumer"))).toBe(false);
  });

  it("waits for the provider to resolve mid-settle, then proceeds with it", async () => {
    setBudget("10");
    const seen: { provider?: unknown } = {};
    const tool = makeConsumer("waiting_consumer", seen);
    setTimeout(
      () =>
        handleLlmProviderAvailable("waiting_consumer", {
          agentId: "provider-1",
          endpoint: "http://provider:9000",
          functionName: "process_chat",
        }),
      150,
    );
    const start = Date.now();
    expect(await tool.execute({})).toBe("ok");
    const elapsed = Date.now() - start;
    expect(elapsed).toBeGreaterThanOrEqual(100);
    expect(elapsed).toBeLessThan(5000);
    expect(seen.provider).toMatchObject({ endpoint: "http://provider:9000" });
  });

  it("proceeds without a provider at budget expiry", async () => {
    setBudget("0.2");
    const seen: { provider?: unknown } = {};
    const tool = makeConsumer("expiring_consumer", seen);
    const start = Date.now();
    expect(await tool.execute({})).toBe("ok");
    expect(Date.now() - start).toBeGreaterThanOrEqual(150);
    expect(seen.provider).toBeUndefined();
  });

  it("never waits once the provider is already resolved", async () => {
    setBudget("10");
    const seen: { provider?: unknown } = {};
    const tool = makeConsumer("resolved_consumer", seen);
    handleLlmProviderAvailable("resolved_consumer", {
      agentId: "provider-1",
      endpoint: "http://provider:9000",
      functionName: "process_chat",
    });
    const before = getSettleState().waitCount;
    await tool.execute({});
    expect(getSettleState().waitCount).toBe(before);
  });
});
