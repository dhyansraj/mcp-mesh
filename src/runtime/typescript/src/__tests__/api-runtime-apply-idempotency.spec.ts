/**
 * #1314 — idempotency guard on the ApiRuntime (@mesh.route / Express gateway)
 * dependency-apply path.
 *
 * ApiRuntime consumes the SAME reconciling napi core as MeshAgent
 * (`this.handle.nextEvent()`), which re-emits `dependency_available` for every
 * believed-delivered edge on an independent ~10s tick. Without a guard each
 * gateway agent would call `createProxy` and rewire the RouteRegistry on every
 * tick. The guard records the last-applied signature
 * `(endpoint, functionName, kwargs, agentId)` per depKey and skips the rebuild
 * when an incoming apply carries the same signature; a genuine change still
 * rebuilds, and removal clears the signature so a re-add rebuilds.
 *
 * These drive the REAL private `handleDependencyAvailable` /
 * `handleDependencyUnavailable` against a stub `this` (only
 * `appliedDepSignatures` is read/written) with a real RouteRegistry passed as
 * the explicit `registry` argument — no napi runtime needed.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import type { MockInstance } from "vitest";

import { ApiRuntime } from "../api-runtime.js";
import { RouteRegistry } from "../route.js";
import { resetSettleStateForTests } from "../settle.js";
import * as proxyModule from "../proxy.js";
import type { McpMeshTool } from "../types.js";

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const handleAvailable = (ApiRuntime.prototype as any).handleDependencyAvailable;
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const handleUnavailable = (ApiRuntime.prototype as any)
  .handleDependencyUnavailable;

describe("ApiRuntime dependency-apply idempotency (#1314)", () => {
  let createProxySpy: MockInstance;
  let registry: RouteRegistry;
  let routeId: string;
  let stub: { appliedDepSignatures: Map<string, string> };

  beforeEach(() => {
    RouteRegistry.reset();
    resetSettleStateForTests();
    registry = RouteRegistry.getInstance();
    routeId = registry.registerRoute("GET", "/report", ["calculator"], [
      { timeout: 30 },
    ]);
    stub = { appliedDepSignatures: new Map<string, string>() };

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

  function apply(endpoint: string, agentId: string): void {
    handleAvailable.call(
      stub,
      registry,
      "calculator",
      endpoint,
      "fn",
      agentId,
      routeId,
      0,
    );
  }

  it("skips rebuild when the re-emit carries an identical signature", () => {
    apply("http://p:8080", "agent-1");
    expect(createProxySpy).toHaveBeenCalledTimes(1);
    const firstProxy = registry.getDependency(routeId, 0);
    expect(firstProxy).not.toBeNull();

    // Identical re-emit → no createProxy, proxy identity unchanged.
    apply("http://p:8080", "agent-1");
    expect(createProxySpy).toHaveBeenCalledTimes(1);
    expect(registry.getDependency(routeId, 0)).toBe(firstProxy);
  });

  it("rebuilds when the endpoint changes", () => {
    apply("http://p:8080", "agent-1");
    const firstProxy = registry.getDependency(routeId, 0);

    apply("http://p:9090", "agent-1");
    expect(createProxySpy).toHaveBeenCalledTimes(2);
    expect(registry.getDependency(routeId, 0)).not.toBe(firstProxy);
  });

  it("rebuilds when only the agentId changes (composes with #1315)", () => {
    apply("http://p:8080", "agent-1");
    const firstProxy = registry.getDependency(routeId, 0);

    apply("http://p:8080", "agent-2");
    expect(createProxySpy).toHaveBeenCalledTimes(2);
    expect(registry.getDependency(routeId, 0)).not.toBe(firstProxy);
  });

  it("rebuilds after removal even when the same signature returns", () => {
    apply("http://p:8080", "agent-1");
    const firstProxy = registry.getDependency(routeId, 0);
    expect(createProxySpy).toHaveBeenCalledTimes(1);

    handleUnavailable.call(stub, registry, "calculator", routeId, 0);
    expect(registry.getDependency(routeId, 0)).toBeNull();
    expect(stub.appliedDepSignatures.has(`${routeId}:dep_0`)).toBe(false);

    apply("http://p:8080", "agent-1");
    expect(createProxySpy).toHaveBeenCalledTimes(2);
    expect(registry.getDependency(routeId, 0)).not.toBe(firstProxy);
  });
});
