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
  JsDependencySpec,
} from "@mcpmesh/core";

/**
 * Dependency specification for mesh tool DI.
 *
 * Can be specified as a simple string (capability name) or
 * a full object with tags and version filters.
 *
 * @example
 * ```typescript
 * // Simple: just capability name
 * dependencies: ["date-service"]
 *
 * // With filters
 * dependencies: [
 *   { capability: "data-service", tags: ["+fast"] },
 *   { capability: "formatter", version: ">=2.0.0" }
 * ]
 * ```
 */
export type DependencySpec =
  | string
  | {
      /** Capability name to depend on */
      capability: string;
      /** Tags for filtering (e.g., ["+fast", "-deprecated"]) */
      tags?: string[];
      /** Version constraint (e.g., ">=2.0.0") */
      version?: string;
    };

/**
 * Normalized dependency specification (after processing).
 */
export interface NormalizedDependency {
  capability: string;
  tags: string[];
  version?: string;
}

/**
 * Resolved dependency info from registry.
 */
export interface ResolvedDependency {
  /** Capability name */
  capability: string;
  /** Agent ID providing this capability */
  agentId: string;
  /** Endpoint URL (e.g., "http://10.0.0.5:8000") */
  endpoint: string;
  /** Function name to call */
  functionName: string;
}

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
 * Proxy configuration for a dependency.
 */
export interface DependencyKwargs {
  /** Request timeout in seconds. Defaults to 30 */
  timeout?: number;
  /** Number of retry attempts. Defaults to 1 */
  retryCount?: number;
  /** Enable streaming responses. Defaults to false */
  streaming?: boolean;
  /** Require session affinity. Defaults to false */
  sessionRequired?: boolean;
}

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
  /**
   * Dependencies required by this tool.
   * Injected positionally as McpMeshAgent params after args.
   *
   * @example
   * ```typescript
   * dependencies: ["time-service", "calculator"],
   * execute: async (
   *   { query },
   *   timeSvc: McpMeshAgent | null = null,  // dependencies[0]
   *   calc: McpMeshAgent | null = null      // dependencies[1]
   * ) => { ... }
   * ```
   */
  dependencies?: DependencySpec[];
  /**
   * Per-dependency configuration.
   * Keys are capability names, values are proxy settings.
   */
  dependencyKwargs?: Record<string, DependencyKwargs>;
  /**
   * Tool implementation.
   *
   * @param args - Parsed arguments matching the Zod schema
   * @param deps - Dependency proxies injected positionally (McpMeshAgent | null)
   *
   * @example
   * ```typescript
   * execute: async (
   *   { query },
   *   timeSvc: McpMeshAgent | null = null,
   *   calc: McpMeshAgent | null = null
   * ) => {
   *   if (timeSvc) {
   *     const time = await timeSvc();
   *   }
   *   return "result";
   * }
   * ```
   */
  execute: (
    args: z.infer<T>,
    ...deps: (McpMeshAgent | null)[]
  ) => Promise<string> | string;
}

/**
 * Proxy for calling remote MCP agents.
 *
 * Dependencies are injected as McpMeshAgent instances.
 * Always check for null (dependency may be unavailable).
 *
 * @example
 * ```typescript
 * execute: async (
 *   { query },
 *   dateSvc: McpMeshAgent | null = null
 * ) => {
 *   if (!dateSvc) return "Date service unavailable";
 *   const date = await dateSvc({ format: "ISO" });
 *   return `Today is ${date}`;
 * }
 * ```
 */
export interface McpMeshAgent {
  /**
   * Call the bound tool with arguments.
   * Returns the tool result as a string.
   */
  (args?: Record<string, unknown>): Promise<string>;

  /**
   * Call a specific tool by name.
   */
  callTool(toolName: string, args?: Record<string, unknown>): Promise<string>;

  /**
   * Get the endpoint URL for this dependency.
   */
  readonly endpoint: string;

  /**
   * Get the capability name.
   */
  readonly capability: string;

  /**
   * Get the function name to call.
   */
  readonly functionName: string;

  /**
   * Check if the proxy is connected/available.
   */
  readonly isAvailable: boolean;
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
  /** Normalized dependencies for this tool */
  dependencies: NormalizedDependency[];
  /** Per-dependency configuration */
  dependencyKwargs?: Record<string, DependencyKwargs>;
}
