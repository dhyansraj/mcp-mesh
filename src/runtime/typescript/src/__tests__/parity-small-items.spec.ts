/**
 * Issue #1593 small parity items:
 *   - MeshAgent.getDependency(capability) returns the first RESOLVED slot,
 *     not the first declaring slot (which may be null).
 *   - MeshExpress carries the #1314 rebuild guard MeshAgent and the API
 *     runtime have: an identical re-emitted dependency_available does not
 *     rebuild the proxy; removal re-arms it.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import express from "express";
import { z } from "zod";
import { MeshAgent } from "../agent.js";
import { MeshExpress } from "../express.js";
import { RouteRegistry } from "../route.js";
import { resetSettleStateForTests } from "../settle.js";

let autoStartSpy: ReturnType<typeof vi.spyOn> | null = null;

beforeEach(() => {
  autoStartSpy = vi
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    .spyOn(MeshAgent.prototype as any, "_autoStart")
    .mockImplementation(async () => {});
  vi.spyOn(console, "log").mockImplementation(() => {});
  vi.spyOn(console, "warn").mockImplementation(() => {});
  resetSettleStateForTests();
  RouteRegistry.reset();
});

afterEach(async () => {
  await new Promise<void>((resolve) => process.nextTick(resolve));
  autoStartSpy?.mockRestore();
  vi.restoreAllMocks();
  resetSettleStateForTests();
  RouteRegistry.reset();
});

describe("MeshAgent.getDependency (#1593)", () => {
  it("skips an unresolved earlier slot and returns the first resolved one", () => {
    const fastmcp = { addTool: vi.fn(), start: vi.fn(), getApp: vi.fn() };
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const agent = new MeshAgent(fastmcp as any, { name: "getdep", httpPort: 0 });
    const exec = async (_a: unknown, _x: unknown = null, _y: unknown = null) => "ok";
    agent.addTool({ name: "first", parameters: z.object({}), dependencies: ["cap"], execute: exec });
    agent.addTool({ name: "second", parameters: z.object({}), dependencies: ["other", "cap"], execute: exec });

    expect(agent.getDependency("cap")).toBeNull();

    // Resolve only second's slot 1 — first's slot 0 stays null.
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (agent as any).handleDependencyAvailable(
      "cap", "http://p:1", "fn", "prov", "second", 1,
    );
    expect(agent.getDependency("cap")).not.toBeNull();
    expect(agent.getDependency("cap")).toBe(agent.getDependencyByKey("second", 1));
  });
});

describe("MeshExpress #1314 rebuild guard (#1593)", () => {
  it("does not rebuild on an identical re-emit, and rebuilds after removal", () => {
    const gateway = new MeshExpress(express(), { name: "guard-api", httpPort: 0 });
    const registry = RouteRegistry.getInstance();
    const routeId = registry.registerRoute("GET", "/x", ["cap"]);
    const setSpy = vi.spyOn(registry, "setDependency");
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const g = gateway as any;

    g.handleDependencyAvailable(registry, "cap", "http://p:1", "fn", "prov", routeId, 0);
    g.handleDependencyAvailable(registry, "cap", "http://p:1", "fn", "prov", routeId, 0);
    expect(setSpy).toHaveBeenCalledTimes(1);

    // A changed endpoint is a real change and rebuilds.
    g.handleDependencyAvailable(registry, "cap", "http://p:2", "fn", "prov", routeId, 0);
    expect(setSpy).toHaveBeenCalledTimes(2);

    // Removal re-arms the guard.
    g.handleDependencyUnavailable(registry, "cap", routeId, 0);
    g.handleDependencyAvailable(registry, "cap", "http://p:2", "fn", "prov", routeId, 0);
    expect(setSpy).toHaveBeenCalledTimes(3);

    // Capability fallback path (no position info) is guarded too.
    g.handleDependencyAvailable(registry, "cap", "http://p:2", "fn", "prov");
    expect(setSpy).toHaveBeenCalledTimes(3);
  });
});
