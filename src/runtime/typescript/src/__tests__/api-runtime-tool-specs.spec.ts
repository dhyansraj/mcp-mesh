/**
 * Issue #1593: the auto-start API runtime and MeshExpress must register the
 * same `mesh.route()` declaration identically. The API-runtime path used to
 * drop expectedSchemaCanonical / expectedSchemaHash / matchMode and hardcode
 * the agent version.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { z } from "zod";

const startAgentSpy = vi.fn();
const nextEventBlocker = new Promise<never>(() => {});

vi.mock("@mcpmesh/core", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@mcpmesh/core")>();
  return {
    ...actual,
    startAgent: (spec: unknown) => startAgentSpy(spec),
    autoDetectIp: () => "127.0.0.1",
    resolveConfig: (key: string, fallback: unknown) =>
      key === "agent_name" ? "test-api" : (fallback ?? null),
    resolveConfigInt: (_key: string, fallback: unknown) => fallback ?? null,
  };
});

vi.mock("../tls-config.js", () => ({
  getTlsConfigCached: () => ({ enabled: false }),
  prepareTls: vi.fn(),
  cleanupTls: vi.fn(),
}));

vi.mock("../tracing.js", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../tracing.js")>();
  return { ...actual, initTracing: vi.fn(async () => false) };
});

import { ApiRuntime } from "../api-runtime.js";
import { A2AProducerRegistry } from "../a2a/producer/registry.js";
import { RouteRegistry } from "../route.js";
import { buildRouteToolSpecs } from "../route-tool-specs.js";

type SignalListener = (...args: unknown[]) => void;
let sigintBefore: SignalListener[] = [];
let sigtermBefore: SignalListener[] = [];

beforeEach(() => {
  sigintBefore = [...(process.listeners("SIGINT") as unknown as SignalListener[])];
  sigtermBefore = [...(process.listeners("SIGTERM") as unknown as SignalListener[])];
  A2AProducerRegistry.reset();
  RouteRegistry.reset();
  startAgentSpy.mockReset();
  startAgentSpy.mockImplementation(() => ({
    updateSurfaces: vi.fn().mockResolvedValue(true),
    updatePort: vi.fn().mockResolvedValue(true),
    updateTools: vi.fn().mockResolvedValue(true),
    nextEvent: () => nextEventBlocker,
    shutdown: vi.fn().mockResolvedValue(undefined),
    isShutdownRequested: () => false,
  }));
  ApiRuntime.reset();
});

afterEach(() => {
  ApiRuntime.reset();
  for (const [sig, before] of [
    ["SIGINT", sigintBefore],
    ["SIGTERM", sigtermBefore],
  ] as const) {
    for (const l of process.listeners(sig) as unknown as SignalListener[]) {
      if (!before.includes(l)) process.removeListener(sig, l);
    }
  }
});

function registerSchemaRoute(): void {
  RouteRegistry.getInstance().registerRoute("GET", "/employees", [
    {
      capability: "employee_lookup",
      expectedSchema: z.object({ name: z.string(), id: z.number() }),
      matchMode: "strict",
    },
  ]);
}

describe("route tool specs parity (#1593)", () => {
  it("buildRouteToolSpecs carries the expected-schema fields", () => {
    registerSchemaRoute();
    const [tool] = buildRouteToolSpecs(RouteRegistry.getInstance().getRoutes());
    const dep = tool.dependencies![0];
    expect(dep.capability).toBe("employee_lookup");
    expect(dep.expectedSchemaCanonical).toEqual(expect.any(String));
    expect(dep.expectedSchemaHash).toEqual(expect.any(String));
    expect(dep.matchMode).toBe("strict");
  });

  it("the auto-start API runtime registers those fields and the configured version", async () => {
    registerSchemaRoute();
    const runtime = ApiRuntime.getInstance();
    runtime.configure({ version: "2.3.4" });
    await runtime.start();

    expect(startAgentSpy).toHaveBeenCalledTimes(1);
    const spec = startAgentSpy.mock.calls[0][0] as {
      version: string;
      tools: ReturnType<typeof buildRouteToolSpecs>;
    };
    expect(spec.version).toBe("2.3.4");
    expect(spec.tools).toEqual(
      buildRouteToolSpecs(RouteRegistry.getInstance().getRoutes()),
    );
    const dep = spec.tools[0].dependencies![0];
    expect(dep.expectedSchemaHash).toEqual(expect.any(String));
    expect(dep.matchMode).toBe("strict");
  });

  it("defaults the API runtime agent version to 1.0.0", async () => {
    RouteRegistry.getInstance().registerRoute("GET", "/x", ["cap"]);
    await ApiRuntime.getInstance().start();
    expect((startAgentSpy.mock.calls[0][0] as { version: string }).version).toBe("1.0.0");
  });
});
