/**
 * Issue #1249: per-dependency `required` flag + route perimeter 503.
 *
 * Uses the REAL `normalizeDependency` (proxy.js) and the REAL route
 * middleware — no proxy mock — so the declaration → normalized-dep → wire
 * mapping and the perimeter check are genuinely exercised.
 */

import { describe, it, expect, vi, beforeEach, afterAll } from "vitest";
import type { Request, Response, NextFunction } from "express";
import { normalizeDependency } from "../proxy.js";
import { route, RouteRegistry } from "../route.js";
import { resetSettleStateForTests } from "../settle.js";
import type { McpMeshTool } from "../types.js";

// Disable the settling-window grace (#1193) so the perimeter is judged
// immediately (MCP_MESH_SETTLE_TIMEOUT=0 tuning case). The perimeter runs
// AFTER the settle wait, so with the grace on a still-settling dep would get
// its full window before being called unavailable — covered elsewhere.
const savedSettleTimeout = process.env.MCP_MESH_SETTLE_TIMEOUT;
beforeEach(() => {
  process.env.MCP_MESH_SETTLE_TIMEOUT = "0";
  resetSettleStateForTests();
  RouteRegistry.reset();
});
afterAll(() => {
  if (savedSettleTimeout === undefined) {
    delete process.env.MCP_MESH_SETTLE_TIMEOUT;
  } else {
    process.env.MCP_MESH_SETTLE_TIMEOUT = savedSettleTimeout;
  }
  resetSettleStateForTests();
});

function mockRes(): Response {
  return {
    status: vi.fn().mockReturnThis(),
    json: vi.fn().mockReturnThis(),
  } as unknown as Response;
}

describe("normalizeDependency required flag (#1249)", () => {
  it("carries required:true through to the normalized dep (napi wire seam)", () => {
    const norm = normalizeDependency({ capability: "weather-api", required: true });
    expect(norm.capability).toBe("weather-api");
    expect(norm.required).toBe(true);
    // The three JsDependencySpec builders map `dep.required ? true : undefined`,
    // so a true here becomes required:true on the napi DependencySpec.
    expect(norm.required ? true : undefined).toBe(true);
  });

  it("omits required when declared false (byte-identical soft-fail default)", () => {
    const norm = normalizeDependency({ capability: "weather-api", required: false });
    expect(norm.required).toBeUndefined();
    expect(norm.required ? true : undefined).toBeUndefined();
  });

  it("omits required when absent (default optional)", () => {
    const norm = normalizeDependency({ capability: "weather-api" });
    expect(norm.required).toBeUndefined();
  });

  it("string-form deps are always optional", () => {
    const norm = normalizeDependency("weather-api");
    expect(norm.required).toBeUndefined();
  });
});

describe("RouteRegistry stores required in route metadata (#1249)", () => {
  it("persists required:true on the declared route dep", () => {
    const registry = RouteRegistry.getInstance();
    const routeId = registry.registerRoute("GET", "/x", [
      { capability: "weather-api", required: true },
      { capability: "logger" },
    ]);
    const meta = registry.getRoute(routeId);
    expect(meta?.dependencies[0].required).toBe(true);
    expect(meta?.dependencies[1].required).toBeUndefined();
  });
});

describe("route perimeter 503 (#1249)", () => {
  it("returns 503 before user code when a required dep is unavailable", async () => {
    const handler = vi.fn();
    const middleware = route([{ capability: "calculator", required: true }], handler);

    const req = { method: "POST", path: "/compute", headers: {} } as unknown as Request;
    const res = mockRes();
    const next = vi.fn() as NextFunction;

    await middleware(req, res, next);

    expect(res.status).toHaveBeenCalledWith(503);
    expect(res.json).toHaveBeenCalledWith({
      error: "dependency_unavailable",
      capability: "calculator",
    });
    // User code must NOT run.
    expect(handler).not.toHaveBeenCalled();
    expect(next).not.toHaveBeenCalled();
  });

  it("runs the handler (no 503) when the required dep IS available", async () => {
    const registry = RouteRegistry.getInstance();
    const handler = vi.fn();
    const middleware = route(
      [{ capability: "calculator", required: true }],
      handler
    ) as ReturnType<typeof route> & { _meshRouteId: string };

    const mockCalc = (async () => "result") as unknown as McpMeshTool;
    registry.setDependency(middleware._meshRouteId, 0, mockCalc);

    const req = { method: "POST", path: "/compute", headers: {} } as unknown as Request;
    const res = mockRes();
    const next = vi.fn() as NextFunction;

    await middleware(req, res, next);

    expect(res.status).not.toHaveBeenCalled();
    expect(handler).toHaveBeenCalledWith(
      req,
      res,
      expect.objectContaining({ calculator: mockCalc })
    );
  });

  it("does NOT 503 for an unavailable OPTIONAL dep (soft-fail preserved)", async () => {
    const handler = vi.fn();
    const middleware = route([{ capability: "calculator" }], handler);

    const req = { method: "POST", path: "/compute", headers: {} } as unknown as Request;
    const res = mockRes();
    const next = vi.fn() as NextFunction;

    await middleware(req, res, next);

    expect(res.status).not.toHaveBeenCalled();
    // Handler runs with a null proxy — the existing degraded behavior.
    expect(handler).toHaveBeenCalledWith(
      req,
      res,
      expect.objectContaining({ calculator: null })
    );
  });

  it("does NOT 503 when a duplicate capability is live in the winning slot", async () => {
    // A capability declared twice collapses to one capability-keyed `deps`
    // slot (last resolution wins). The perimeter must judge the same slot the
    // handler sees — not a dead sibling index — so a live proxy means run.
    const registry = RouteRegistry.getInstance();
    const handler = vi.fn();
    const middleware = route(
      [
        { capability: "calculator", required: true }, // required, its index unresolved
        { capability: "calculator" }, // optional, this index is live → wins deps[cap]
      ],
      handler
    ) as ReturnType<typeof route> & { _meshRouteId: string };

    const mockCalc = (async () => "result") as unknown as McpMeshTool;
    registry.setDependency(middleware._meshRouteId, 1, mockCalc);

    const req = { method: "POST", path: "/compute", headers: {} } as unknown as Request;
    const res = mockRes();
    const next = vi.fn() as NextFunction;

    await middleware(req, res, next);

    expect(res.status).not.toHaveBeenCalled();
    expect(handler).toHaveBeenCalledWith(
      req,
      res,
      expect.objectContaining({ calculator: mockCalc })
    );
  });

  it("503s on the first unavailable required dep among a mix", async () => {
    const registry = RouteRegistry.getInstance();
    const handler = vi.fn();
    const middleware = route(
      [
        { capability: "logger" }, // optional, unresolved
        { capability: "calculator", required: true }, // required, resolved
        { capability: "weather-api", required: true }, // required, unresolved
      ],
      handler
    ) as ReturnType<typeof route> & { _meshRouteId: string };

    const mockCalc = (async () => "result") as unknown as McpMeshTool;
    registry.setDependency(middleware._meshRouteId, 1, mockCalc);

    const req = { method: "POST", path: "/compute", headers: {} } as unknown as Request;
    const res = mockRes();
    const next = vi.fn() as NextFunction;

    await middleware(req, res, next);

    expect(res.status).toHaveBeenCalledWith(503);
    expect(res.json).toHaveBeenCalledWith({
      error: "dependency_unavailable",
      capability: "weather-api",
    });
    expect(handler).not.toHaveBeenCalled();
  });
});
