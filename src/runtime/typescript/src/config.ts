/**
 * Configuration utilities for MCP Mesh agents.
 *
 * Handles environment variable resolution with proper priority:
 * ENV > config > defaults
 */

import { randomBytes } from "crypto";
import type { AgentConfig, ResolvedAgentConfig } from "./types.js";
import { resolveExternalHost } from "./host-resolver.js";

/**
 * Get environment variable as string, or return default.
 */
export function getEnvString(key: string, defaultValue: string): string {
  return process.env[key] ?? defaultValue;
}

/**
 * Get environment variable as integer, or return default.
 */
export function getEnvInt(key: string, defaultValue: number): number {
  const value = process.env[key];
  if (value) {
    const parsed = parseInt(value, 10);
    if (!isNaN(parsed)) {
      return parsed;
    }
  }
  return defaultValue;
}

/**
 * Generate a short UUID suffix (8 hex chars) for agent IDs.
 */
export function generateAgentIdSuffix(): string {
  return randomBytes(4).toString("hex");
}

/**
 * Resolve configuration with environment variable precedence.
 *
 * Priority: ENV > config > defaults
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
  const resolvedName = getEnvString("MCP_MESH_AGENT_NAME", config.name);
  const resolvedPort = getEnvInt("MCP_MESH_HTTP_PORT", config.port);
  const resolvedHost = resolveExternalHost(config.host);
  const resolvedNamespace = getEnvString(
    "MCP_MESH_NAMESPACE",
    config.namespace ?? "default"
  );
  const resolvedRegistryUrl = getEnvString(
    "MCP_MESH_REGISTRY_URL",
    config.registryUrl ?? "http://localhost:8000"
  );
  const resolvedHeartbeatInterval = getEnvInt(
    "MCP_MESH_HEALTH_INTERVAL",
    config.heartbeatInterval ?? 5
  );

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
