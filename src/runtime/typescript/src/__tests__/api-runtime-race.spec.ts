/**
 * Regression test for PR #938 W2 — race window in `ApiRuntime.start()`.
 *
 * `start()` does async work (TLS prep, tracing init) between the moment
 * `scheduleStart()` flips `this.starting = true` and the moment
 * `this.handle = startAgent(spec)` lands. A `mesh.a2a.mount(...)` fired
 * during that gap was previously dropped on the floor:
 *
 *   - `pushSurfacesUpdate()` early-returned on `!this.handle`
 *   - The startup-time spec was already built (snapshot of the registry
 *     BEFORE the deferred mount landed), so `startAgent(spec)` registered
 *     a stale surfaces[] payload
 *
 * The fix: `pushSurfacesUpdate()` sets a `pendingSurfacesPush` flag when
 * `start()` is in flight (handle still null, `starting === true`).
 * `start()` flushes the flag right after `this.handle = startAgent(spec)`.
 * Smart-diffed inside the Rust runtime so the redundant push is a no-op
 * when the snapshot already captured the mount.
 *
 * We mock `@mcpmesh/core` so this test never binds the real napi runtime,
 * and we mock `prepareTls`/`initTracing` so `start()` doesn't touch the
 * filesystem or Redis. The race fixture introduces a controlled
 * `setImmediate` gap inside the mocked `initTracing` so we can fire
 * `pushSurfacesUpdate()` at the exact race window.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";

// ─── Mock @mcpmesh/core BEFORE importing api-runtime ────────────────────
const updateSurfacesSpy = vi.fn().mockResolvedValue(true);
const startAgentSpy = vi.fn();
const nextEventBlocker = new Promise<never>(() => {}); // never resolves

vi.mock("@mcpmesh/core", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@mcpmesh/core")>();
  return {
    ...actual,
    startAgent: (spec: unknown) => startAgentSpy(spec),
    autoDetectIp: () => "127.0.0.1",
    resolveConfig: (key: string, fallback: unknown) => {
      // Minimal config resolution — return fallback or null for everything
      // so `start()` proceeds with defaults.
      if (key === "agent_name") return "test-api";
      return fallback ?? null;
    },
    resolveConfigInt: (_key: string, fallback: unknown) => fallback ?? null,
  };
});

// Mock tls-config so prepareTls/cleanupTls don't touch the filesystem.
vi.mock("../tls-config.js", () => ({
  getTlsConfigCached: () => ({ enabled: false }),
  prepareTls: vi.fn(),
  cleanupTls: vi.fn(),
}));

// Mock tracing so initTracing doesn't try to bind Redis. Crucially, we
// inject a `setImmediate` boundary INSIDE initTracing so the test can
// schedule a `pushSurfacesUpdate()` call at the precise race window —
// after `scheduleStart` flips `this.starting = true` but before
// `this.handle = startAgent(spec)` runs.
let initTracingResolve: (() => void) | null = null;
vi.mock("../tracing.js", () => ({
  initTracing: vi.fn(async () => {
    // Park here — the test resolves us once it has fired the racing
    // `pushSurfacesUpdate()`. This deterministically holds the gap
    // open instead of relying on real-world async timing.
    await new Promise<void>((resolve) => {
      initTracingResolve = resolve;
    });
  }),
}));

import { ApiRuntime } from "../api-runtime.js";
import { A2AProducerRegistry } from "../a2a/producer/registry.js";
import { RouteRegistry } from "../route.js";

describe("ApiRuntime — pushSurfacesUpdate race window (#938 W2)", () => {
  // Snapshot signal listeners so we can restore them after each test —
  // `ApiRuntime.start()` registers SIGINT/SIGTERM handlers that capture
  // the per-instance `this.handle` via closure. After `ApiRuntime.reset()`
  // those handlers reference a stale handle (or a torn-down vi mock) and
  // fire on vitest's teardown signal. Remove our additions to keep the
  // test process clean.
  type SignalListener = (...args: unknown[]) => void;
  let sigintBefore: SignalListener[];
  let sigtermBefore: SignalListener[];

  beforeEach(() => {
    sigintBefore = process.listeners("SIGINT") as unknown as SignalListener[];
    sigintBefore = [...sigintBefore];
    sigtermBefore = process.listeners("SIGTERM") as unknown as SignalListener[];
    sigtermBefore = [...sigtermBefore];
    A2AProducerRegistry.reset();
    RouteRegistry.reset();
    updateSurfacesSpy.mockClear();
    startAgentSpy.mockReset();
    initTracingResolve = null;

    // Build a stub handle that captures updateSurfaces calls. nextEvent
    // returns a never-resolving promise so the event loop parks
    // immediately — we don't exercise it here.
    startAgentSpy.mockImplementation(() => ({
      updateSurfaces: updateSurfacesSpy,
      updatePort: vi.fn().mockResolvedValue(true),
      updateTools: vi.fn().mockResolvedValue(true),
      nextEvent: () => nextEventBlocker,
      shutdown: vi.fn().mockResolvedValue(undefined),
      isShutdownRequested: () => false,
    }));

    // Reset the singleton so each test gets a clean ApiRuntime.
    ApiRuntime.reset();
  });

  afterEach(() => {
    // Unblock any parked initTracing in case a test bailed early.
    if (initTracingResolve) {
      initTracingResolve();
    }
    ApiRuntime.reset();
    // Strip signal listeners we registered (see snapshot in beforeEach).
    const currentSigint = process.listeners("SIGINT") as unknown as SignalListener[];
    for (const l of currentSigint) {
      if (!sigintBefore.includes(l)) {
        process.removeListener("SIGINT", l);
      }
    }
    const currentSigterm = process.listeners("SIGTERM") as unknown as SignalListener[];
    for (const l of currentSigterm) {
      if (!sigtermBefore.includes(l)) {
        process.removeListener("SIGTERM", l);
      }
    }
  });

  it("flushes a pushSurfacesUpdate fired during the start() async gap", async () => {
    const runtime = ApiRuntime.getInstance();

    // Kick off start(). It will park inside the mocked initTracing,
    // holding the race window open until we resolve `initTracingResolve`.
    const startPromise = runtime.start();

    // Yield the event loop so start() advances past `this.starting = true`
    // and into the `await initTracing(...)` await point.
    await new Promise((r) => setImmediate(r));

    // Sanity: handle still null (start is parked inside initTracing),
    // and startAgent has NOT been called yet.
    expect(startAgentSpy).not.toHaveBeenCalled();

    // Simulate a deferred mount landing in the race window — register
    // a surface in the producer registry, then fire pushSurfacesUpdate.
    A2AProducerRegistry.getInstance().register({
      path: "/agents/late",
      skillId: "late-skill",
      skillName: "Late Skill",
      description: "",
      tags: [],
      dependencies: [],
      auth: "",
      routeId: "route-late",
    });
    runtime.pushSurfacesUpdate();

    // Without the W2 fix, this push is silently dropped:
    //   - `handle === null` so the early-return triggers
    //   - `pendingSurfacesPush` doesn't exist, so no flush
    //
    // With the fix, the push is queued via `pendingSurfacesPush = true`
    // and replayed after `this.handle = startAgent(spec)` is set.

    // Unblock initTracing so start() proceeds to startAgent + flush.
    initTracingResolve!();
    initTracingResolve = null;

    await startPromise;

    // The startup-time snapshot would have included the late-mounted
    // surface (it landed BEFORE startAgent was called in our fixture
    // here — the gap is between scheduleStart and startAgent). So the
    // initial startAgent call already advertises the late surface AND
    // the W2 flush replays it (smart-diffed by the Rust runtime).
    //
    // The behavior we assert is the FLUSH — `updateSurfaces` is called
    // exactly once after the handle is set, with the late surface in
    // the payload.
    expect(updateSurfacesSpy).toHaveBeenCalledTimes(1);
    const [agentType, surfacesJson] = updateSurfacesSpy.mock.calls[0];
    expect(agentType).toBe("a2a");
    const parsed = JSON.parse(surfacesJson as string);
    expect(parsed).toHaveLength(1);
    expect(parsed[0]).toMatchObject({
      path: "/agents/late",
      skill_id: "late-skill",
    });
  });

  it("does NOT flush when no pushSurfacesUpdate fired during the gap", async () => {
    const runtime = ApiRuntime.getInstance();

    const startPromise = runtime.start();
    await new Promise((r) => setImmediate(r));

    // No racing push — just let start() complete.
    initTracingResolve!();
    initTracingResolve = null;
    await startPromise;

    // `pendingSurfacesPush` stayed false, so no flush after handle is set.
    expect(updateSurfacesSpy).not.toHaveBeenCalled();
  });

  it("is a no-op when called BEFORE scheduleStart (starting=false, handle=null)", () => {
    const runtime = ApiRuntime.getInstance();

    // Cold runtime — neither started nor starting. Push is a true no-op:
    // the eventual `start()` will pick up the registry state via
    // `buildAgentSpecContribution()` at startup time.
    runtime.pushSurfacesUpdate();

    expect(updateSurfacesSpy).not.toHaveBeenCalled();
    expect(startAgentSpy).not.toHaveBeenCalled();
  });
});
