/**
 * MeshAgent implementation for MCP Mesh.
 *
 * Provides the core agent functionality including:
 * - Registration with mesh registry via Rust core
 * - Heartbeat management
 * - Tool/capability discovery
 * - Dependency injection for tool functions
 * - Graceful shutdown
 */

import type { FastMCP } from "fastmcp";
import type { z } from "zod";
import { zodToJsonSchema } from "zod-to-json-schema";
import {
  startAgent,
  type JsAgentSpec,
  type JsAgentHandle,
  type JsToolSpec,
  type JsDependencySpec,
} from "@mcpmesh/core";

import type {
  AgentConfig,
  ResolvedAgentConfig,
  MeshToolDef,
  ToolMeta,
  McpMeshAgent,
  NormalizedDependency,
} from "./types.js";
import { resolveConfig, generateAgentIdSuffix } from "./config.js";
import { createProxy, normalizeDependency } from "./proxy.js";

// Internal: pending agent for auto-start
let pendingAgent: MeshAgent | null = null;
let autoStartScheduled = false;

// Schedule auto-start after module loading completes
function scheduleAutoStart(): void {
  if (autoStartScheduled) return;
  autoStartScheduled = true;

  process.nextTick(() => {
    if (pendingAgent) {
      pendingAgent._autoStart().catch((err) => {
        console.error("MCP Mesh auto-start failed:", err);
        process.exit(1);
      });
    }
  });
}

/**
 * MeshAgent wraps a FastMCP server with MCP Mesh capabilities.
 *
 * It provides:
 * - Automatic registration with the mesh registry
 * - Heartbeat management via Rust core
 * - Tool/capability discovery
 * - Dependency injection for tool functions
 */
export class MeshAgent {
  private server: FastMCP;
  private config: ResolvedAgentConfig;
  private agentId: string;
  private tools: Map<string, ToolMeta> = new Map();
  private handle: JsAgentHandle | null = null;
  private started = false;

  /**
   * Resolved dependencies: capability -> proxy
   * Updated when dependency_available/unavailable events arrive.
   */
  private resolvedDeps: Map<string, McpMeshAgent> = new Map();

  constructor(server: FastMCP, config: AgentConfig) {
    this.server = server;

    // Resolve config with env var precedence: ENV > config > defaults
    this.config = resolveConfig(config);

    // Generate unique agent ID with suffix (e.g., "calculator-a1b2c3d4")
    this.agentId = `${this.config.name}-${generateAgentIdSuffix()}`;

    // Register as pending agent for auto-start
    pendingAgent = this;
    scheduleAutoStart();
  }

  /**
   * Add a tool to the agent.
   *
   * This registers the tool with both fastmcp (for MCP protocol) and
   * the mesh (for capability discovery). If the tool has dependencies,
   * they will be injected positionally at runtime.
   */
  addTool<T extends z.ZodType>(def: MeshToolDef<T>): this {
    const toolName = def.name;
    const execute = def.execute;

    // Normalize dependencies
    const normalizedDeps: NormalizedDependency[] = (def.dependencies ?? []).map(
      normalizeDependency
    );

    // Create wrapper that injects dependencies positionally
    const wrappedExecute = async (args: z.infer<T>): Promise<string> => {
      // Build positional deps array
      const depsArray: (McpMeshAgent | null)[] = normalizedDeps.map(
        (dep) => this.resolvedDeps.get(dep.capability) ?? null
      );

      // Call original with args + positional deps
      const result = await execute(args, ...depsArray);
      return result;
    };

    // Register with fastmcp
    this.server.addTool({
      name: toolName,
      description: def.description,
      parameters: def.parameters,
      execute: wrappedExecute,
    });

    // Store mesh metadata with JSON Schema for LLM tool resolution
    const inputSchema = this.convertZodToJsonSchema(def.parameters);
    this.tools.set(toolName, {
      capability: def.capability ?? toolName,
      version: def.version ?? "1.0.0",
      tags: def.tags ?? [],
      description: def.description ?? "",
      inputSchema: JSON.stringify(inputSchema),
      dependencies: normalizedDeps,
      dependencyKwargs: def.dependencyKwargs,
    });

    return this;
  }

  /**
   * Convert Zod schema to JSON Schema.
   */
  private convertZodToJsonSchema(schema: z.ZodType): object {
    return zodToJsonSchema(schema, { $refStrategy: "none" });
  }

  /**
   * Internal: Start the agent (called by auto-start mechanism).
   */
  async _autoStart(): Promise<void> {
    if (this.started) return;
    this.started = true;

    console.log(`Starting MCP Mesh agent: ${this.agentId}`);

    // 1. Start HTTP server via fastmcp
    // Note: fastmcp.start() is async and starts the server
    // Use stateless mode so meshctl can call without sessions
    await this.server.start({
      transportType: "httpStream",
      httpStream: {
        port: this.config.port,
        host: "0.0.0.0", // Listen on all interfaces so external IPs work
        stateless: true,
      },
    });

    console.log(`Agent listening on port ${this.config.port}`);

    // 2. Start heartbeat to registry via Rust core
    await this.startHeartbeat();

    // 3. Install signal handlers for graceful shutdown
    this.installSignalHandlers();
  }

  /**
   * Install signal handlers for graceful shutdown.
   * Ensures agent unregisters from registry on SIGINT/SIGTERM.
   */
  private installSignalHandlers(): void {
    let shuttingDown = false;

    const shutdownHandler = (signal: string) => {
      if (shuttingDown) return;
      shuttingDown = true;

      console.log(
        `\nReceived ${signal}, shutting down agent ${this.agentId}...`
      );

      // Use setImmediate to avoid blocking the async runtime
      setImmediate(async () => {
        try {
          await this.shutdown();
          console.log(`Agent ${this.agentId} unregistered from registry`);
        } catch (err) {
          console.error("Error during shutdown:", err);
        }
        process.exit(0);
      });
    };

    process.on("SIGINT", () => shutdownHandler("SIGINT"));
    process.on("SIGTERM", () => shutdownHandler("SIGTERM"));
  }

  /**
   * Start the Rust core heartbeat loop.
   */
  private async startHeartbeat(): Promise<void> {
    // Build the agent spec for Rust core
    const tools: JsToolSpec[] = Array.from(this.tools.entries()).map(
      ([name, meta]) => ({
        functionName: name,
        capability: meta.capability,
        version: meta.version,
        tags: meta.tags,
        description: meta.description,
        // Pass dependencies to Rust core for registry resolution
        dependencies: meta.dependencies.map(
          (dep): JsDependencySpec => ({
            capability: dep.capability,
            tags: dep.tags,
            version: dep.version,
          })
        ),
        inputSchema: meta.inputSchema,
      })
    );

    const spec: JsAgentSpec = {
      name: this.agentId,
      version: this.config.version,
      description: this.config.description,
      registryUrl: this.config.registryUrl,
      httpPort: this.config.port,
      httpHost: this.config.host,
      namespace: this.config.namespace,
      tools,
      heartbeatInterval: this.config.heartbeatInterval,
    };

    // Start the agent via Rust core
    this.handle = startAgent(spec);

    // Count total dependencies
    const totalDeps = tools.reduce((sum, t) => sum + t.dependencies.length, 0);
    console.log(
      `Registered ${tools.length} capabilities with registry (${totalDeps} dependencies)`
    );

    // Start event loop (runs in background)
    this.runEventLoop();
  }

  /**
   * Run the event loop to handle mesh events.
   */
  private async runEventLoop(): Promise<void> {
    if (!this.handle) return;

    while (true) {
      try {
        const event = await this.handle.nextEvent();

        switch (event.eventType) {
          case "agent_registered":
            console.log(`Agent registered with ID: ${event.agentId}`);
            break;

          case "registration_failed":
            console.error(`Registration failed: ${event.error}`);
            break;

          case "dependency_available":
            this.handleDependencyAvailable(
              event.capability!,
              event.endpoint!,
              event.functionName!,
              event.agentId!
            );
            break;

          case "dependency_unavailable":
            this.handleDependencyUnavailable(event.capability!);
            break;

          case "dependency_changed":
            // Handle as available with new endpoint
            this.handleDependencyAvailable(
              event.capability!,
              event.endpoint!,
              event.functionName!,
              event.agentId!
            );
            break;

          case "registry_connected":
            console.log("Connected to registry");
            break;

          case "registry_disconnected":
            console.warn(`Disconnected from registry: ${event.reason}`);
            break;

          case "shutdown":
            console.log("Agent shutting down");
            return;

          default:
            // Handle other events as needed
            break;
        }
      } catch (err) {
        console.error("Event loop error:", err);
        break;
      }
    }
  }

  /**
   * Handle dependency_available event.
   * Creates or updates proxy for the capability.
   */
  private handleDependencyAvailable(
    capability: string,
    endpoint: string,
    functionName: string,
    agentId: string
  ): void {
    // Find kwargs for this dependency (from any tool that uses it)
    let kwargs = undefined;
    for (const meta of this.tools.values()) {
      if (meta.dependencyKwargs?.[capability]) {
        kwargs = meta.dependencyKwargs[capability];
        break;
      }
    }

    // Create proxy
    const proxy = createProxy(endpoint, capability, functionName, kwargs);
    this.resolvedDeps.set(capability, proxy);

    console.log(
      `Dependency available: ${capability} at ${endpoint} (agent: ${agentId})`
    );
  }

  /**
   * Handle dependency_unavailable event.
   * Removes proxy for the capability.
   */
  private handleDependencyUnavailable(capability: string): void {
    this.resolvedDeps.delete(capability);
    console.log(`Dependency unavailable: ${capability}`);
  }

  /**
   * Get a resolved dependency proxy by capability name.
   */
  getDependency(capability: string): McpMeshAgent | null {
    return this.resolvedDeps.get(capability) ?? null;
  }

  /**
   * Get all resolved dependencies.
   */
  getAllDependencies(): Map<string, McpMeshAgent> {
    return new Map(this.resolvedDeps);
  }

  /**
   * Get the agent handle for advanced operations.
   */
  getHandle(): JsAgentHandle | null {
    return this.handle;
  }

  /**
   * Get the resolved configuration.
   */
  getConfig(): ResolvedAgentConfig {
    return this.config;
  }

  /**
   * Get the agent ID.
   */
  getAgentId(): string {
    return this.agentId;
  }

  /**
   * Shutdown the agent gracefully.
   */
  async shutdown(): Promise<void> {
    if (this.handle) {
      await this.handle.shutdown();
      this.handle = null;
    }
  }
}

/**
 * Create a MeshAgent wrapping a FastMCP server.
 *
 * This is the main entry point for creating MCP Mesh agents.
 *
 * @example
 * ```typescript
 * const agent = mesh(server, {
 *   name: "calculator",
 *   port: 9002,
 * });
 * ```
 */
export function mesh(server: FastMCP, config: AgentConfig): MeshAgent {
  return new MeshAgent(server, config);
}
