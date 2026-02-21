/**
 * Unit tests for route.ts
 *
 * Tests mesh.route() Express middleware and RouteRegistry.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import type { Request, Response, NextFunction } from "express";
import { route, routeWithConfig, RouteRegistry } from "../route.js";
import type { McpMeshTool } from "../types.js";

// Mock createProxy from proxy.ts
vi.mock("../proxy.js", () => ({
  normalizeDependency: vi.fn((dep) => {
    if (typeof dep === "string") {
      return { capability: dep, tags: [] };
    }
    return {
      capability: dep.capability,
      tags: dep.tags ?? [],
      version: dep.version,
    };
  }),
  createProxy: vi.fn((endpoint, capability, functionName) => {
    // Create mock McpMeshTool
    const mockProxy = async (args?: Record<string, unknown>) => {
      return JSON.stringify({ result: "mock", args });
    };
    Object.defineProperties(mockProxy, {
      endpoint: { value: endpoint },
      capability: { value: capability },
      functionName: { value: functionName },
      isAvailable: { value: true },
      callTool: { value: async () => "mock" },
    });
    return mockProxy as McpMeshTool;
  }),
  runWithPropagatedHeaders: vi.fn(async (_headers, fn) => fn()),
  runWithTraceContext: vi.fn(async (_ctx, fn) => fn()),
}));

// Mock tracing functions used by route.ts
vi.mock("../tracing.js", () => ({
  PROPAGATE_HEADERS: [],
  matchesPropagateHeader: vi.fn(() => false),
  parseTraceContext: vi.fn(() => null),
  generateSpanId: vi.fn(() => "mock-span-id"),
  generateTraceId: vi.fn(() => "mock-trace-id"),
  publishTraceSpan: vi.fn(async () => false),
}));

describe("RouteRegistry", () => {
  beforeEach(() => {
    // Reset registry before each test
    RouteRegistry.reset();
  });

  describe("getInstance", () => {
    it("should return singleton instance", () => {
      const instance1 = RouteRegistry.getInstance();
      const instance2 = RouteRegistry.getInstance();

      expect(instance1).toBe(instance2);
    });
  });

  describe("registerRoute", () => {
    it("should register a route with dependencies", () => {
      const registry = RouteRegistry.getInstance();

      const routeId = registry.registerRoute("POST", "/compute", [
        { capability: "calculator" },
        { capability: "logger", tags: ["async"] },
      ]);

      expect(routeId).toMatch(/^route_\d+_POST:\/compute$/);

      const route = registry.getRoute(routeId);
      expect(route).toBeDefined();
      expect(route?.method).toBe("POST");
      expect(route?.path).toBe("/compute");
      expect(route?.dependencies).toHaveLength(2);
      expect(route?.dependencies[0].capability).toBe("calculator");
      expect(route?.dependencies[1].capability).toBe("logger");
      expect(route?.dependencies[1].tags).toEqual(["async"]);
    });

    it("should generate unique route IDs", () => {
      const registry = RouteRegistry.getInstance();

      const id1 = registry.registerRoute("GET", "/a", []);
      const id2 = registry.registerRoute("GET", "/b", []);
      const id3 = registry.registerRoute("POST", "/a", []);

      expect(id1).not.toBe(id2);
      expect(id2).not.toBe(id3);
      expect(id1).not.toBe(id3);
    });

    it("should handle string dependencies", () => {
      const registry = RouteRegistry.getInstance();

      const routeId = registry.registerRoute("GET", "/test", [
        "service-a",
        "service-b",
      ]);

      const route = registry.getRoute(routeId);
      expect(route?.dependencies[0].capability).toBe("service-a");
      expect(route?.dependencies[1].capability).toBe("service-b");
    });
  });

  describe("getRoutes", () => {
    it("should return all registered routes", () => {
      const registry = RouteRegistry.getInstance();

      registry.registerRoute("GET", "/a", ["svc1"]);
      registry.registerRoute("POST", "/b", ["svc2"]);

      const routes = registry.getRoutes();
      expect(routes).toHaveLength(2);
    });
  });

  describe("dependency management", () => {
    it("should set and get dependencies", () => {
      const registry = RouteRegistry.getInstance();
      const routeId = registry.registerRoute("GET", "/test", ["calculator"]);

      // Create mock proxy
      const mockProxy = (() => Promise.resolve("test")) as unknown as McpMeshTool;
      Object.defineProperties(mockProxy, {
        endpoint: { value: "http://localhost:8000" },
        capability: { value: "calculator" },
        functionName: { value: "add" },
        isAvailable: { value: true },
      });

      // Set dependency
      registry.setDependency(routeId, 0, mockProxy);

      // Get dependency
      const dep = registry.getDependency(routeId, 0);
      expect(dep).toBe(mockProxy);
    });

    it("should return null for unset dependencies", () => {
      const registry = RouteRegistry.getInstance();
      const routeId = registry.registerRoute("GET", "/test", ["calculator"]);

      const dep = registry.getDependency(routeId, 0);
      expect(dep).toBeNull();
    });

    it("should remove dependencies", () => {
      const registry = RouteRegistry.getInstance();
      const routeId = registry.registerRoute("GET", "/test", ["calculator"]);

      const mockProxy = (() => Promise.resolve("test")) as unknown as McpMeshTool;
      registry.setDependency(routeId, 0, mockProxy);
      registry.removeDependency(routeId, 0);

      const dep = registry.getDependency(routeId, 0);
      expect(dep).toBeNull();
    });

    it("should get dependencies for route as object", () => {
      const registry = RouteRegistry.getInstance();
      const routeId = registry.registerRoute("GET", "/test", [
        "calculator",
        "logger",
      ]);

      const mockCalc = (() => Promise.resolve("calc")) as unknown as McpMeshTool;
      Object.defineProperties(mockCalc, { capability: { value: "calculator" } });

      registry.setDependency(routeId, 0, mockCalc);
      // Leave logger unset

      const deps = registry.getDependenciesForRoute(routeId);
      expect(deps.calculator).toBe(mockCalc);
      expect(deps.logger).toBeNull();
    });

    it("should clear all dependencies", () => {
      const registry = RouteRegistry.getInstance();
      const routeId = registry.registerRoute("GET", "/test", ["calculator"]);

      const mockProxy = (() => Promise.resolve("test")) as unknown as McpMeshTool;
      registry.setDependency(routeId, 0, mockProxy);
      registry.clearAllDependencies();

      const dep = registry.getDependency(routeId, 0);
      expect(dep).toBeNull();
    });
  });
});

describe("route()", () => {
  beforeEach(() => {
    RouteRegistry.reset();
  });

  it("should create Express middleware", () => {
    const handler = vi.fn();
    const middleware = route([{ capability: "calculator" }], handler);

    expect(typeof middleware).toBe("function");
    expect(middleware.length).toBe(3); // (req, res, next)
  });

  it("should attach mesh metadata to middleware", () => {
    const handler = vi.fn();
    const middleware = route([{ capability: "calculator" }], handler) as ReturnType<typeof route> & {
      _meshRouteId: string;
      _meshDependencies: Array<{ capability: string; tags: string[] }>;
    };

    expect(middleware._meshRouteId).toBeDefined();
    expect(middleware._meshDependencies).toBeDefined();
    expect(middleware._meshDependencies[0].capability).toBe("calculator");
  });

  it("should call handler with dependencies", async () => {
    const handler = vi.fn();
    const middleware = route(["calculator"], handler);

    // Create mock request/response/next
    const mockReq = {} as Request;
    const mockRes = {} as Response;
    const mockNext = vi.fn() as NextFunction;

    // Call middleware
    await middleware(mockReq, mockRes, mockNext);

    // Handler should be called with req, res, and deps object
    expect(handler).toHaveBeenCalledTimes(1);
    expect(handler).toHaveBeenCalledWith(
      mockReq,
      mockRes,
      expect.objectContaining({ calculator: null }) // No deps resolved yet
    );
  });

  it("should inject resolved dependencies", async () => {
    const registry = RouteRegistry.getInstance();
    const handler = vi.fn();
    const middleware = route(["calculator"], handler) as ReturnType<typeof route> & {
      _meshRouteId: string;
    };

    // Set up resolved dependency
    const mockCalc = (async () => "result") as unknown as McpMeshTool;
    registry.setDependency(middleware._meshRouteId, 0, mockCalc);

    // Create mock request/response/next
    const mockReq = {} as Request;
    const mockRes = {} as Response;
    const mockNext = vi.fn() as NextFunction;

    // Call middleware
    await middleware(mockReq, mockRes, mockNext);

    // Handler should receive the resolved dependency
    expect(handler).toHaveBeenCalledWith(
      mockReq,
      mockRes,
      expect.objectContaining({ calculator: mockCalc })
    );
  });

  it("should call next() on error", async () => {
    const error = new Error("Test error");
    const handler = vi.fn().mockRejectedValue(error);
    const middleware = route(["calculator"], handler);

    const mockReq = {} as Request;
    const mockRes = {} as Response;
    const mockNext = vi.fn() as NextFunction;

    await middleware(mockReq, mockRes, mockNext);

    expect(mockNext).toHaveBeenCalledWith(error);
  });

  it("should support handler with next function", async () => {
    const handler = vi.fn((_req, _res, _deps, next) => {
      next();
    });
    const middleware = route(["calculator"], handler);

    const mockReq = {} as Request;
    const mockRes = {} as Response;
    const mockNext = vi.fn() as NextFunction;

    await middleware(mockReq, mockRes, mockNext);

    expect(handler).toHaveBeenCalledWith(
      mockReq,
      mockRes,
      expect.any(Object),
      mockNext
    );
  });
});

describe("routeWithConfig()", () => {
  beforeEach(() => {
    RouteRegistry.reset();
  });

  it("should create middleware from config object", () => {
    const handler = vi.fn();
    const middleware = routeWithConfig(
      {
        dependencies: [{ capability: "calculator" }],
        dependencyKwargs: [{ timeout: 60 }],
      },
      handler
    );

    expect(typeof middleware).toBe("function");
  });

  it("should register route with kwargs", () => {
    const handler = vi.fn();
    const middleware = routeWithConfig(
      {
        dependencies: ["calculator"],
        dependencyKwargs: [{ timeout: 60, maxAttempts: 3 }],
      },
      handler
    ) as ReturnType<typeof routeWithConfig> & { _meshRouteId: string };

    const registry = RouteRegistry.getInstance();
    const route = registry.getRoute(middleware._meshRouteId);

    expect(route?.dependencyKwargs).toEqual([{ timeout: 60, maxAttempts: 3 }]);
  });
});

describe("mesh.route integration", () => {
  beforeEach(() => {
    RouteRegistry.reset();
  });

  it("should work with multiple dependencies", async () => {
    const registry = RouteRegistry.getInstance();
    const handler = vi.fn();

    const middleware = route(
      [
        { capability: "calculator" },
        { capability: "logger", tags: ["async"] },
        "formatter",
      ],
      handler
    ) as ReturnType<typeof route> & { _meshRouteId: string };

    // Set up some dependencies
    const mockCalc = (async () => "calc") as unknown as McpMeshTool;
    const mockLogger = (async () => "log") as unknown as McpMeshTool;
    registry.setDependency(middleware._meshRouteId, 0, mockCalc);
    registry.setDependency(middleware._meshRouteId, 1, mockLogger);
    // formatter left unresolved

    const mockReq = {} as Request;
    const mockRes = {} as Response;
    const mockNext = vi.fn() as NextFunction;

    await middleware(mockReq, mockRes, mockNext);

    expect(handler).toHaveBeenCalledWith(
      mockReq,
      mockRes,
      expect.objectContaining({
        calculator: mockCalc,
        logger: mockLogger,
        formatter: null,
      })
    );
  });

  it("should handle empty dependencies", async () => {
    const handler = vi.fn();
    const middleware = route([], handler);

    const mockReq = {} as Request;
    const mockRes = {} as Response;
    const mockNext = vi.fn() as NextFunction;

    await middleware(mockReq, mockRes, mockNext);

    expect(handler).toHaveBeenCalledWith(mockReq, mockRes, {});
  });
});
