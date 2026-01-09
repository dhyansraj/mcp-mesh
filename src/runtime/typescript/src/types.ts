/**
 * Type definitions for @mcpmesh/sdk
 */

import type { z } from "zod";

// Re-export types from core
export type {
  JsAgentHandle,
  JsMeshEvent,
  JsAgentSpec,
  JsToolSpec,
} from "@mcpmesh/core";

/**
 * Configuration for a MeshAgent.
 *
 * Environment variables take precedence over config values:
 * - MCP_MESH_AGENT_NAME: Override agent name
 * - MCP_MESH_HTTP_HOST: Override host (auto-detected if not set)
 * - MCP_MESH_HTTP_PORT: Override port
 * - MCP_MESH_NAMESPACE: Override namespace
 * - MCP_MESH_REGISTRY_URL: Override registry URL
 * - MCP_MESH_HEALTH_INTERVAL: Override heartbeat interval
 */
export interface AgentConfig {
  /** Unique agent name/identifier. Env: MCP_MESH_AGENT_NAME */
  name: string;
  /** Agent version (semver). Defaults to "1.0.0" */
  version?: string;
  /** Human-readable description */
  description?: string;
  /** HTTP port for this agent. Env: MCP_MESH_HTTP_PORT */
  port: number;
  /** HTTP host announced to registry. Env: MCP_MESH_HTTP_HOST (auto-detected if not set) */
  host?: string;
  /** Namespace for isolation. Env: MCP_MESH_NAMESPACE. Defaults to "default" */
  namespace?: string;
  /** Registry URL. Env: MCP_MESH_REGISTRY_URL. Defaults to "http://localhost:8000" */
  registryUrl?: string;
  /** Heartbeat interval in seconds. Env: MCP_MESH_HEALTH_INTERVAL. Defaults to 5 */
  heartbeatInterval?: number;
}

/**
 * Resolved configuration with all defaults applied.
 */
export type ResolvedAgentConfig = Required<AgentConfig>;

/**
 * Tool definition for MeshAgent.
 */
export interface MeshToolDef<T extends z.ZodType = z.ZodType> {
  /** Tool name (used in MCP protocol) */
  name: string;
  /** Capability name for mesh discovery. Defaults to tool name */
  capability?: string;
  /** Human-readable description */
  description?: string;
  /** Tags for filtering (e.g., ["tools", "math"]) */
  tags?: string[];
  /** Version of this capability. Defaults to "1.0.0" */
  version?: string;
  /** Zod schema for input parameters */
  parameters: T;
  /** Tool implementation */
  execute: (args: z.infer<T>) => Promise<string> | string;
}

/**
 * Internal metadata for a registered tool.
 */
export interface ToolMeta {
  capability: string;
  version: string;
  tags: string[];
  description: string;
  inputSchema?: string;
}
