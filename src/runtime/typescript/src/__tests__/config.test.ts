/**
 * Unit tests for config.ts
 *
 * Tests configuration resolution utilities for MCP Mesh TypeScript SDK.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { generateAgentIdSuffix, resolveConfig } from "../config.js";
import type { AgentConfig } from "../types.js";

// Mock the @mcpmesh/core module
vi.mock("@mcpmesh/core", () => ({
  resolveConfig: vi.fn((key: string, value: string | null) => {
    // Simulate Rust core behavior: return value if provided, else default
    if (key === "agent_name") return value ?? "default-agent";
    if (key === "http_host") return value ?? "10.0.0.1";
    if (key === "namespace") return value ?? "default";
    if (key === "registry_url") return value ?? "http://localhost:8000";
    return value ?? "";
  }),
  resolveConfigInt: vi.fn((key: string, value: number | null) => {
    if (key === "http_port") return value;
    if (key === "health_interval") return value ?? 5;
    return value;
  }),
}));

describe("generateAgentIdSuffix", () => {
  it("should generate an 8-character hex string", () => {
    const suffix = generateAgentIdSuffix();

    expect(suffix).toHaveLength(8);
    expect(suffix).toMatch(/^[0-9a-f]{8}$/);
  });

  it("should generate unique suffixes on each call", () => {
    const suffix1 = generateAgentIdSuffix();
    const suffix2 = generateAgentIdSuffix();
    const suffix3 = generateAgentIdSuffix();

    expect(suffix1).not.toBe(suffix2);
    expect(suffix2).not.toBe(suffix3);
    expect(suffix1).not.toBe(suffix3);
  });

  it("should generate 1000 unique suffixes without collision", () => {
    const suffixes = new Set<string>();

    for (let i = 0; i < 1000; i++) {
      suffixes.add(generateAgentIdSuffix());
    }

    expect(suffixes.size).toBe(1000);
  });
});

describe("resolveConfig", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("should resolve config with all values provided", () => {
    const config: AgentConfig = {
      name: "test-agent",
      version: "2.0.0",
      description: "Test description",
      port: 9000,
      host: "192.168.1.100",
      namespace: "production",
      registryUrl: "http://registry.example.com:8000",
      heartbeatInterval: 10,
    };

    const resolved = resolveConfig(config);

    expect(resolved.name).toBe("test-agent");
    expect(resolved.version).toBe("2.0.0");
    expect(resolved.description).toBe("Test description");
    expect(resolved.port).toBe(9000);
    expect(resolved.host).toBe("192.168.1.100");
    expect(resolved.namespace).toBe("production");
    expect(resolved.registryUrl).toBe("http://registry.example.com:8000");
    expect(resolved.heartbeatInterval).toBe(10);
  });

  it("should use defaults for optional values not provided", () => {
    const config: AgentConfig = {
      name: "minimal-agent",
      port: 8080,
    };

    const resolved = resolveConfig(config);

    expect(resolved.name).toBe("minimal-agent");
    expect(resolved.version).toBe("1.0.0");
    expect(resolved.description).toBe("");
    expect(resolved.port).toBe(8080);
    expect(resolved.host).toBe("10.0.0.1"); // Auto-detected by Rust
    expect(resolved.namespace).toBe("default");
    expect(resolved.registryUrl).toBe("http://localhost:8000");
    expect(resolved.heartbeatInterval).toBe(5);
  });

  it("should delegate to Rust core for config resolution", async () => {
    const { resolveConfig: rustResolveConfig, resolveConfigInt } = await import(
      "@mcpmesh/core"
    );

    const config: AgentConfig = {
      name: "rust-test",
      port: 7777,
    };

    resolveConfig(config);

    // Verify Rust core functions were called
    expect(rustResolveConfig).toHaveBeenCalledWith("agent_name", "rust-test");
    expect(rustResolveConfig).toHaveBeenCalledWith("http_host", null);
    expect(rustResolveConfig).toHaveBeenCalledWith("namespace", null);
    expect(rustResolveConfig).toHaveBeenCalledWith("registry_url", null);
    expect(resolveConfigInt).toHaveBeenCalledWith("http_port", 7777);
    expect(resolveConfigInt).toHaveBeenCalledWith("health_interval", null);
  });

  it("should handle null/undefined optional values", () => {
    const config: AgentConfig = {
      name: "null-test",
      port: 5000,
      host: undefined,
      namespace: undefined,
      registryUrl: undefined,
      heartbeatInterval: undefined,
    };

    const resolved = resolveConfig(config);

    // Should use Rust core defaults
    expect(resolved.host).toBe("10.0.0.1");
    expect(resolved.namespace).toBe("default");
    expect(resolved.registryUrl).toBe("http://localhost:8000");
    expect(resolved.heartbeatInterval).toBe(5);
  });
});

describe("ResolvedAgentConfig", () => {
  it("should have all required fields after resolution", () => {
    const config: AgentConfig = {
      name: "complete-test",
      port: 3000,
    };

    const resolved = resolveConfig(config);

    // All fields should be defined (Required<AgentConfig>)
    expect(resolved.name).toBeDefined();
    expect(resolved.version).toBeDefined();
    expect(resolved.description).toBeDefined();
    expect(resolved.port).toBeDefined();
    expect(resolved.host).toBeDefined();
    expect(resolved.namespace).toBeDefined();
    expect(resolved.registryUrl).toBeDefined();
    expect(resolved.heartbeatInterval).toBeDefined();
  });
});
