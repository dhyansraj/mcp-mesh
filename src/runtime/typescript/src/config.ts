/**
 * Configuration utilities for MCP Mesh agents.
 *
 * All configuration resolution is delegated to Rust core for consistency
 * across all language SDKs. Priority: ENV > config > defaults
 */

import { randomBytes } from "crypto";
import type { AgentConfig, ResolvedAgentConfig } from "./types.js";
import {
  resolveConfig as rustResolveConfig,
  resolveConfigInt,
} from "@mcpmesh/core";

/**
 * Generate a short UUID suffix (8 hex chars) for agent IDs.
 */
export function generateAgentIdSuffix(): string {
  return randomBytes(4).toString("hex");
}

/**
 * Resolve configuration with environment variable precedence via Rust core.
 *
 * All resolution is delegated to Rust core to ensure consistent behavior
 * across Python and TypeScript SDKs.
 *
 * Priority (handled by Rust): ENV > config > defaults
 *
 * Environment variables:
 * - MCP_MESH_AGENT_NAME: Override agent name
 * - MCP_MESH_HTTP_HOST: Override host (auto-detected if not set)
 * - MCP_MESH_HTTP_PORT: Override port
 * - MCP_MESH_NAMESPACE: Override namespace
 * - MCP_MESH_REGISTRY_URL: Override registry URL
 * - MCP_MESH_HEALTH_INTERVAL: Override heartbeat interval
 */
export function resolveConfig(config: AgentConfig): ResolvedAgentConfig {
  // All config resolution via Rust core - ensures consistent ENV > param > default
  const resolvedName = rustResolveConfig("agent_name", config.name);
  const resolvedPort = resolveConfigInt("http_port", config.port) ?? config.port;
  const resolvedHost = rustResolveConfig("http_host", config.host ?? null);
  const resolvedNamespace = rustResolveConfig(
    "namespace",
    config.namespace ?? null
  );
  const resolvedRegistryUrl = rustResolveConfig(
    "registry_url",
    config.registryUrl ?? null
  );
  const resolvedHeartbeatInterval =
    resolveConfigInt("health_interval", config.heartbeatInterval ?? null) ?? 5;

  return {
    name: resolvedName,
    version: config.version ?? "1.0.0",
    description: config.description ?? "",
    port: resolvedPort,
    host: resolvedHost,
    namespace: resolvedNamespace,
    registryUrl: resolvedRegistryUrl,
    heartbeatInterval: resolvedHeartbeatInterval,
  };
}
