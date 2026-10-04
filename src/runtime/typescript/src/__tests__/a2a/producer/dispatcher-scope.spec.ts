/**
 * Issue #1593: `mesh.a2a.mount` handlers must run with the same inbound
 * scaffolding `mesh.route` gives route handlers (Python attaches the
 * app-wide FastAPITracingMiddleware to A2A apps and its @mesh.a2a DI wrapper
 * waits for the settle window):
 *   - the settle wait for still-unresolved declared dependencies (#1193)
 *   - the inbound trace context (X-Trace-ID / X-Parent-Span)
 *   - the allowlisted propagated headers
 * on BOTH the JSON-RPC (`tasks/send`) and SSE (`tasks/sendSubscribe`) paths.
 */
import { describe, it, expect, beforeEach, afterEach } from "vitest";
import type { Request, Response } from "express";

import { RouteRegistry } from "../../../route.js";
import { A2ATaskStore } from "../../../a2a/producer/task-store.js";
import {
  buildDispatcherMiddleware,
  buildSendSubscribeStream,
  type A2AHandler,
  type DispatcherDeps,
} from "../../../a2a/producer/dispatcher.js";
import type { A2ASurfaceMetadata } from "../../../a2a/producer/registry.js";
import {
  getCurrentPropagatedHeaders,
  getCurrentTraceContext,
} from "../../../proxy.js";
import { resetSettleStateForTests } from "../../../settle.js";

const savedSettle = process.env.MCP_MESH_SETTLE_TIMEOUT;

beforeEach(() => {
  RouteRegistry.reset();
  delete process.env.MCP_MESH_SETTLE_TIMEOUT;
  resetSettleStateForTests();
});

afterEach(() => {
  if (savedSettle === undefined) delete process.env.MCP_MESH_SETTLE_TIMEOUT;
  else process.env.MCP_MESH_SETTLE_TIMEOUT = savedSettle;
  resetSettleStateForTests();
  RouteRegistry.reset();
});

function makeDeps(handler: A2AHandler, capabilities: string[] = []): DispatcherDeps {
  const routeRegistry = RouteRegistry.getInstance();
  const path = "/agents/scope";
  const routeId = routeRegistry.registerRoute(
    "A2A",
    path,
    capabilities.map((capability) => ({ capability })),
  );
  const surface: A2ASurfaceMetadata = {
    path,
    skillId: "scope-skill",
    skillName: "Scope",
    description: "scope",
    tags: [],
    dependencies: capabilities.map((capability) => ({ capability })) as never,
    auth: "",
    routeId,
  };
  return { surface, handler, taskStore: new A2ATaskStore(), routeRegistry };
}

async function send(
  deps: DispatcherDeps,
  headers: Record<string, string> = {},
): Promise<Record<string, unknown>> {
  let body = "";
  const res = {
    status() {
      return this;
    },
    type() {
      return this;
    },
    send(b: string) {
      body = b;
      return this;
    },
  } as unknown as Response;
  const req = {
    body: { jsonrpc: "2.0", id: 1, method: "tasks/send", params: { id: "t1" } },
    headers,
  } as unknown as Request;
  await buildDispatcherMiddleware(deps)(req, res, () => {});
  return JSON.parse(body) as Record<string, unknown>;
}

describe("a2a dispatcher inbound trace + propagated-header scope", () => {
  const inbound = {
    "x-trace-id": "trace-abc",
    "x-parent-span": "span-parent",
    // Always allowlisted (infra header), independent of MCP_MESH_PROPAGATE_HEADERS.
    "x-mesh-timeout": "42",
  };

  it("tasks/send handler sees the inbound trace id and propagated headers", async () => {
    let seenTrace: unknown = "unset";
    let seenHeaders: Record<string, string> = {};
    const deps = makeDeps(async () => {
      seenTrace = getCurrentTraceContext();
      seenHeaders = getCurrentPropagatedHeaders();
      return "ok";
    });
    await send(deps, inbound);
    expect(seenTrace).not.toBeNull();
    expect((seenTrace as { traceId: string }).traceId).toBe("trace-abc");
    // Downstream calls parent on THIS handler's span, not the caller's.
    expect((seenTrace as { parentSpanId: string }).parentSpanId).not.toBe(
      "span-parent",
    );
    expect(seenHeaders["x-mesh-timeout"]).toBe("42");
  });

  it("tasks/send without inbound trace headers still runs in a fresh trace", async () => {
    let seenTrace: unknown = null;
    const deps = makeDeps(async () => {
      seenTrace = getCurrentTraceContext();
      return "ok";
    });
    await send(deps);
    expect(seenTrace).not.toBeNull();
    expect((seenTrace as { traceId: string }).traceId).toMatch(/\S+/);
  });

  it("tasks/sendSubscribe handler sees the inbound trace id and propagated headers", async () => {
    let seenTrace: unknown = null;
    let seenHeaders: Record<string, string> = {};
    const deps = makeDeps(async () => {
      seenTrace = getCurrentTraceContext();
      seenHeaders = getCurrentPropagatedHeaders();
      return "ok";
    });
    await buildSendSubscribeStream(1, { id: "t2" }, deps, inbound);
    expect((seenTrace as { traceId: string } | null)?.traceId).toBe("trace-abc");
    expect(seenHeaders["x-mesh-timeout"]).toBe("42");
  });
});

describe("a2a dispatcher settle gating (#1193)", () => {
  it("tasks/send waits for an unresolved declared dependency during settling", async () => {
    process.env.MCP_MESH_SETTLE_TIMEOUT = "10";
    resetSettleStateForTests();
    let seen: unknown = "unset";
    const deps = makeDeps(async ([dep]) => {
      seen = dep;
      return "ok";
    }, ["date_service"]);
    const proxy = { live: true };
    setTimeout(
      () => deps.routeRegistry.setDependency(deps.surface.routeId, 0, proxy as never),
      150,
    );
    const start = Date.now();
    await send(deps);
    expect(Date.now() - start).toBeGreaterThanOrEqual(100);
    expect(Date.now() - start).toBeLessThan(5000);
    expect(seen).toEqual(proxy);
  });

  it("tasks/sendSubscribe waits for an unresolved declared dependency during settling", async () => {
    process.env.MCP_MESH_SETTLE_TIMEOUT = "10";
    resetSettleStateForTests();
    let seen: unknown = "unset";
    const deps = makeDeps(async ([dep]) => {
      seen = dep;
      return "ok";
    }, ["date_service"]);
    const proxy = { live: true };
    setTimeout(
      () => deps.routeRegistry.setDependency(deps.surface.routeId, 0, proxy as never),
      150,
    );
    await buildSendSubscribeStream(1, { id: "t3" }, deps, {});
    expect(seen).toEqual(proxy);
  });
});
