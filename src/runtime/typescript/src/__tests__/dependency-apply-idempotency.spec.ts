/**
 * #1314 — idempotency guard on the TS dependency-apply path.
 *
 * The Rust core re-emits `dependency_available` for every believed-delivered
 * edge on an independent ~10s wall-clock tick (self-heals dropped applies).
 * Without a guard the SDK would call `createProxy` and rewire `resolvedDeps`
 * on every tick — needless churn. The guard records the last-applied
 * resolution signature `(endpoint, functionName, kwargs, agentId)` per depKey
 * and skips the rebuild when an incoming apply carries the same signature.
 *
 * A genuine change (different endpoint / function / kwargs / agentId) must
 * still rebuild, and a removal must clear the signature so a later re-add
 * rebuilds.
 *
 * These drive the REAL private `handleDependencyAvailable` /
 * `handleDependencyUnavailable` against a stub `this` — the methods only touch
 * `this.tools`, `this.resolvedDeps` and `this.appliedDepSignatures` plus the
 * settle singleton, so no napi runtime is needed.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import type { MockInstance } from "vitest";

import { MeshAgent } from "../agent.js";
import { resetSettleStateForTests } from "../settle.js";
import * as proxyModule from "../proxy.js";
import type { McpMeshTool } from "../types.js";

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const handleAvailable = (MeshAgent.prototype as any).handleDependencyAvailable;
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const handleUnavailable = (MeshAgent.prototype as any)
  .handleDependencyUnavailable;

/** Minimal stub `this` mirroring the fields the two handlers read/write. */
function makeStub(kwargs?: unknown) {
  return {
    tools: new Map([
      [
        "myTool",
        {
          dependencyKwargs: [kwargs],
        },
      ],
    ]),
    resolvedDeps: new Map<string, McpMeshTool>(),
    appliedDepSignatures: new Map<string, string>(),
  };
}

const DEP_KEY = "myTool:dep_0";

describe("dependency-apply idempotency (#1314)", () => {
  let createProxySpy: MockInstance;

  beforeEach(() => {
    resetSettleStateForTests();
    // Each call returns a fresh, identity-distinct proxy so we can assert both
    // call-count AND that the stored proxy reference did not change.
    createProxySpy = vi
      .spyOn(proxyModule, "createProxy")
      .mockImplementation(
        () => (() => Promise.resolve("ok")) as unknown as McpMeshTool,
      );
    vi.spyOn(console, "log").mockImplementation(() => {});
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("skips rebuild when the re-emit carries an identical signature", () => {
    const stub = makeStub({ tags: ["a"] });

    handleAvailable.call(stub, "cap", "http://p:8080", "fn", "agent-1", "myTool", 0);
    expect(createProxySpy).toHaveBeenCalledTimes(1);
    const firstProxy = stub.resolvedDeps.get(DEP_KEY);
    expect(firstProxy).toBeDefined();

    // Identical re-emit → no createProxy, proxy identity unchanged.
    handleAvailable.call(stub, "cap", "http://p:8080", "fn", "agent-1", "myTool", 0);
    expect(createProxySpy).toHaveBeenCalledTimes(1);
    expect(stub.resolvedDeps.get(DEP_KEY)).toBe(firstProxy);
  });

  it("treats value-equal-but-distinct kwargs objects as the same signature", () => {
    // Two calls whose kwargs are structurally equal but reference-distinct
    // (as happens when the core re-parses the payload each tick).
    const stubA = makeStub({ tags: ["x"], timeout: 5 });
    handleAvailable.call(stubA, "cap", "http://p:8080", "fn", "agent-1", "myTool", 0);

    // Rewrite the stub's kwargs to a fresh, deep-equal object and re-fire.
    stubA.tools.set("myTool", {
      dependencyKwargs: [{ timeout: 5, tags: ["x"] }],
    });
    handleAvailable.call(stubA, "cap", "http://p:8080", "fn", "agent-1", "myTool", 0);

    expect(createProxySpy).toHaveBeenCalledTimes(1);
  });

  it("rebuilds when the endpoint changes", () => {
    const stub = makeStub({ tags: ["a"] });

    handleAvailable.call(stub, "cap", "http://p:8080", "fn", "agent-1", "myTool", 0);
    const firstProxy = stub.resolvedDeps.get(DEP_KEY);

    handleAvailable.call(stub, "cap", "http://p:9090", "fn", "agent-1", "myTool", 0);
    expect(createProxySpy).toHaveBeenCalledTimes(2);
    expect(stub.resolvedDeps.get(DEP_KEY)).not.toBe(firstProxy);
  });

  it("rebuilds when only the agentId changes (composes with #1315)", () => {
    const stub = makeStub({ tags: ["a"] });

    handleAvailable.call(stub, "cap", "http://p:8080", "fn", "agent-1", "myTool", 0);
    const firstProxy = stub.resolvedDeps.get(DEP_KEY);

    // Same endpoint/function/kwargs, different provider identity → rebuild.
    handleAvailable.call(stub, "cap", "http://p:8080", "fn", "agent-2", "myTool", 0);
    expect(createProxySpy).toHaveBeenCalledTimes(2);
    expect(stub.resolvedDeps.get(DEP_KEY)).not.toBe(firstProxy);
  });

  it("rebuilds after removal even when the same signature returns", () => {
    const stub = makeStub({ tags: ["a"] });

    handleAvailable.call(stub, "cap", "http://p:8080", "fn", "agent-1", "myTool", 0);
    const firstProxy = stub.resolvedDeps.get(DEP_KEY);
    expect(createProxySpy).toHaveBeenCalledTimes(1);

    // Removal clears both the proxy and the stored signature.
    handleUnavailable.call(stub, "cap", "myTool", 0);
    expect(stub.resolvedDeps.has(DEP_KEY)).toBe(false);
    expect(stub.appliedDepSignatures.has(DEP_KEY)).toBe(false);

    // Same signature re-add must rebuild (the guard was cleared on removal).
    handleAvailable.call(stub, "cap", "http://p:8080", "fn", "agent-1", "myTool", 0);
    expect(createProxySpy).toHaveBeenCalledTimes(2);
    expect(stub.resolvedDeps.get(DEP_KEY)).not.toBe(firstProxy);
  });
});
