/**
 * Regression test for #1131 — TS data-plane resilience on a registry blip.
 *
 * The registry is the CONTROL plane. Once a dependency is resolved, its
 * endpoint is a DATA-plane address: a direct agent→agent connection that
 * stays valid even while the registry is unreachable. The Rust core never
 * resets topology on a registry disconnect, and its reconnect diff gate
 * re-emits only CHANGED dependencies — so any dep cleared on disconnect
 * would NEVER be re-emitted, permanently severing a still-valid connection.
 *
 * The correct, cross-runtime-consistent behavior (MeshAgent, Python ×3,
 * Java) is therefore to RETAIN resolved dependencies through a
 * `registry_disconnected` event and log only.
 *
 * Previously `ApiRuntime` and `MeshExpress` called
 * `registry.clearAllDependencies()` in their `registry_disconnected`
 * handlers. This test drives each runtime's real (private) `runEventLoop`
 * against a stub `this` that exposes a scripted core handle emitting
 * `registry_disconnected` followed by `shutdown`, and asserts a
 * pre-resolved dependency survives.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import type { MockInstance } from "vitest";

import { ApiRuntime } from "../api-runtime.js";
import { MeshExpress } from "../express.js";
import { RouteRegistry } from "../route.js";
import type { McpMeshTool } from "../types.js";

/**
 * Build a stub core handle whose `nextEvent()` replays the given event
 * sequence once, then parks forever. The runtimes' event loops exit on the
 * `shutdown` event, so each sequence must end with one.
 */
function stubHandle(events: Array<{ eventType: string; reason?: string }>) {
  let i = 0;
  return {
    nextEvent: async () => {
      if (i < events.length) return events[i++] as never;
      // Never resolve once the scripted events are exhausted.
      return new Promise<never>(() => {});
    },
  };
}

const DISCONNECT_THEN_SHUTDOWN = [
  { eventType: "registry_disconnected", reason: "connection reset" },
  { eventType: "shutdown" },
];

describe("registry_disconnected retains resolved dependencies (#1131)", () => {
  let warnSpy: MockInstance;

  beforeEach(() => {
    RouteRegistry.reset();
    // Silence the expected warn/log from the disconnect/shutdown handlers.
    // Keep the warn spy so we can assert the disconnect path actually ran —
    // a path-executed guard that fails if the `registry_disconnected` case is
    // ever skipped/removed (closes the vacuous-pass hole).
    warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    vi.spyOn(console, "log").mockImplementation(() => {});
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  function seedResolvedDep(): { routeId: string; proxy: McpMeshTool } {
    const registry = RouteRegistry.getInstance();
    const routeId = registry.registerRoute("GET", "/test", ["calculator"]);
    const proxy = (() => Promise.resolve("ok")) as unknown as McpMeshTool;
    registry.setDependency(routeId, 0, proxy);
    // Sanity: dep is resolved before the disconnect.
    expect(registry.getDependency(routeId, 0)).toBe(proxy);
    return { routeId, proxy };
  }

  it("ApiRuntime keeps the resolved dep after registry_disconnected", async () => {
    const { routeId, proxy } = seedResolvedDep();

    // Drive the REAL private event loop against a stub `this`. The loop only
    // reads `this.handle` and the RouteRegistry singleton, so we don't need
    // to construct the singleton (which would bind the napi runtime).
    const stubThis = { handle: stubHandle(DISCONNECT_THEN_SHUTDOWN) };
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const runEventLoop = (ApiRuntime.prototype as any).runEventLoop;
    await runEventLoop.call(stubThis);

    // Path-executed guard: the disconnect handler must have run (negative
    // control). If `registry_disconnected` is ever skipped/removed, the dep
    // could survive for an unrelated reason — this assertion fails loudly.
    expect(warnSpy).toHaveBeenCalledTimes(1);
    expect(warnSpy).toHaveBeenCalledWith(
      expect.stringContaining("API runtime disconnected"),
    );

    const registry = RouteRegistry.getInstance();
    expect(registry.getDependency(routeId, 0)).toBe(proxy);
  });

  it("MeshExpress keeps the resolved dep after registry_disconnected", async () => {
    const { routeId, proxy } = seedResolvedDep();

    const stubThis = { handle: stubHandle(DISCONNECT_THEN_SHUTDOWN) };
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const runEventLoop = (MeshExpress.prototype as any).runEventLoop;
    await runEventLoop.call(stubThis);

    // Path-executed guard: the disconnect handler must have run (negative
    // control). If `registry_disconnected` is ever skipped/removed, the dep
    // could survive for an unrelated reason — this assertion fails loudly.
    expect(warnSpy).toHaveBeenCalledTimes(1);
    expect(warnSpy).toHaveBeenCalledWith(
      expect.stringContaining("Disconnected from registry"),
    );

    const registry = RouteRegistry.getInstance();
    expect(registry.getDependency(routeId, 0)).toBe(proxy);
  });
});
