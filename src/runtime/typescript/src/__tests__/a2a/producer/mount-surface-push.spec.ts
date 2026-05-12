/**
 * Regression tests for issue #938 — `mesh.a2a.mount(...)` after `startAgent()`
 * must push the updated `agent_type` + `surfaces` to the Rust core so the next
 * heartbeat envelope reflects the new state (parity with Python's
 * per-heartbeat `_build_a2a_surfaces` in `heartbeat_preparation.py:371-389`).
 *
 * Prior to #938 the SDK computed `agentType` / `surfacesJson` ONCE at
 * `startAgent(spec)` time inside `ApiRuntime.start()` /
 * `MeshExpress.startHeartbeat()`. Mounts registered after the first
 * heartbeat were silently dropped — `agent_type` stayed pinned to its
 * pre-mount value (`api` / `mcp_agent`) and the `surfaces[]` array on the
 * registry stayed empty.
 *
 * The fix wires every `mesh.a2a.mount(...)` call to invoke
 * `ApiRuntime.pushSurfacesUpdate()`, which forwards the freshly-built
 * `(agentType, surfacesJson)` pair into the napi binding's
 * `JsAgentHandle.updateSurfaces(...)`. Smart-diffed inside the Rust runtime
 * so re-mounting an identical surface is a no-op.
 *
 * These tests verify the wiring at the SDK boundary (mock
 * `pushSurfacesUpdate` and assert the call). End-to-end verification that
 * the Rust runtime forces a full heartbeat lives in
 * `src/runtime/core/src/handle.rs::test_handle_update_surfaces*`.
 */
import { describe, it, expect, beforeEach, vi } from "vitest";
import express from "express";

import { A2AProducerRegistry } from "../../../a2a/producer/registry.js";
import { RouteRegistry } from "../../../route.js";

// Mock the api-runtime singleton with both `scheduleStart` AND
// `pushSurfacesUpdate` so we can assert the latter is invoked from
// `mesh.a2a.mount()`. The default mount.spec.ts mock only stubs
// `scheduleStart`, exercising the typeof-guarded fallback path; this file
// exercises the wired path.
const scheduleStartSpy = vi.fn();
const pushSurfacesUpdateSpy = vi.fn();

vi.mock("../../../api-runtime.js", () => ({
  getApiRuntime: () => ({
    scheduleStart: scheduleStartSpy,
    pushSurfacesUpdate: pushSurfacesUpdateSpy,
  }),
}));

// Import AFTER vi.mock so the mock applies.
import { mount } from "../../../a2a/producer/mount.js";

describe("mesh.a2a.mount → pushSurfacesUpdate (#938)", () => {
  beforeEach(() => {
    A2AProducerRegistry.reset();
    RouteRegistry.reset();
    scheduleStartSpy.mockReset();
    pushSurfacesUpdateSpy.mockReset();
  });

  it("invokes pushSurfacesUpdate after registering the surface", () => {
    const app = express();
    mount(
      app,
      { path: "/agents/date", skillId: "get-date" },
      async () => ({ date: "today" }),
    );

    expect(pushSurfacesUpdateSpy).toHaveBeenCalledTimes(1);
    // Sanity: scheduleStart still fires (canonical mount-before-start path
    // still works).
    expect(scheduleStartSpy).toHaveBeenCalledTimes(1);
  });

  it("invokes pushSurfacesUpdate AFTER the surface lands in the registry (push sees fresh state)", () => {
    const app = express();
    let snapshotAtPush: ReturnType<
      typeof A2AProducerRegistry.prototype.buildAgentSpecContribution
    > | null = null;

    pushSurfacesUpdateSpy.mockImplementation(() => {
      snapshotAtPush = A2AProducerRegistry.getInstance().buildAgentSpecContribution("api");
    });

    mount(
      app,
      { path: "/agents/date", skillId: "get-date" },
      async () => ({}),
    );

    expect(snapshotAtPush).not.toBeNull();
    expect(snapshotAtPush!.agentType).toBe("a2a");
    expect(snapshotAtPush!.surfacesJson).toBeDefined();
    const parsed = JSON.parse(snapshotAtPush!.surfacesJson!);
    expect(Array.isArray(parsed)).toBe(true);
    expect(parsed).toHaveLength(1);
    expect(parsed[0]).toMatchObject({
      path: "/agents/date",
      skill_id: "get-date",
    });
  });

  it("invokes pushSurfacesUpdate once per mount call (deferred-mount scenario)", () => {
    const app = express();
    // First mount — canonical path (mount before startAgent).
    mount(app, { path: "/agents/a", skillId: "skill-a" }, async () => ({}));
    expect(pushSurfacesUpdateSpy).toHaveBeenCalledTimes(1);

    // Second mount — simulates a deferred mount fired AFTER first heartbeat.
    // Without #938's fix, this was silently dropped; with the fix it
    // pushes the updated surfaces[] (now 2 entries) into the Rust core.
    mount(app, { path: "/agents/b", skillId: "skill-b" }, async () => ({}));
    expect(pushSurfacesUpdateSpy).toHaveBeenCalledTimes(2);

    // Snapshot the current registry state — both surfaces should be there.
    const contribution = A2AProducerRegistry.getInstance().buildAgentSpecContribution("api");
    expect(contribution.agentType).toBe("a2a");
    const parsed = JSON.parse(contribution.surfacesJson!);
    expect(parsed).toHaveLength(2);
    expect(parsed.map((s: Record<string, unknown>) => s.path).sort()).toEqual([
      "/agents/a",
      "/agents/b",
    ]);
  });
});

describe("A2AProducerRegistry.buildAgentSpecContribution (#938)", () => {
  beforeEach(() => {
    A2AProducerRegistry.reset();
    RouteRegistry.reset();
  });

  it("returns nonA2aType when no surfaces registered", () => {
    const result = A2AProducerRegistry.getInstance().buildAgentSpecContribution("api");
    expect(result.agentType).toBe("api");
    expect(result.surfacesJson).toBeUndefined();
  });

  it("returns 'mcp_agent' when nonA2aType='mcp_agent' and no surfaces", () => {
    const result = A2AProducerRegistry.getInstance().buildAgentSpecContribution("mcp_agent");
    expect(result.agentType).toBe("mcp_agent");
    expect(result.surfacesJson).toBeUndefined();
  });

  it("flips to 'a2a' and emits surfacesJson when surfaces are registered", () => {
    A2AProducerRegistry.getInstance().register({
      path: "/agents/x",
      skillId: "skill-x",
      skillName: "Skill X",
      description: "",
      tags: [],
      dependencies: [],
      auth: "",
      routeId: "route-x",
    });

    const result = A2AProducerRegistry.getInstance().buildAgentSpecContribution("api");
    expect(result.agentType).toBe("a2a");
    expect(result.surfacesJson).toBeDefined();
    const parsed = JSON.parse(result.surfacesJson!);
    expect(parsed).toHaveLength(1);
    expect(parsed[0]).toMatchObject({
      path: "/agents/x",
      skill_id: "skill-x",
      name: "Skill X",
    });
  });

  it("preserves insertion order across multiple surfaces", () => {
    const reg = A2AProducerRegistry.getInstance();
    reg.register({
      path: "/agents/first",
      skillId: "first",
      skillName: "first",
      description: "",
      tags: [],
      dependencies: [],
      auth: "",
      routeId: "r1",
    });
    reg.register({
      path: "/agents/second",
      skillId: "second",
      skillName: "second",
      description: "",
      tags: [],
      dependencies: [],
      auth: "",
      routeId: "r2",
    });

    const result = reg.buildAgentSpecContribution("api");
    const parsed = JSON.parse(result.surfacesJson!);
    expect(parsed).toHaveLength(2);
    expect(parsed[0].path).toBe("/agents/first");
    expect(parsed[1].path).toBe("/agents/second");
  });
});
