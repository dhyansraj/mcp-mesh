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
import { createProxy, normalizeDependency, runWithTraceContext } from "./proxy.js";
import {
  initTracing,
  generateTraceId,
  generateSpanId,
  publishTraceSpan,
  type TraceContext,
  type AgentMetadata,
} from "./tracing.js";

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
  private tracingEnabled = false;

  /**
   * Resolved dependencies: composite key -> proxy
   * Key format: "${toolName}:dep_${depIndex}" (e.g., "myTool:dep_0")
   * Updated when dependency_available/unavailable events arrive.
   *
   * This allows multiple tools to depend on the same capability with
   * different tags/settings without overwriting each other.
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
    const depEndpoints = normalizedDeps.map((d) => d.capability);

    // Create wrapper that injects dependencies positionally and handles tracing
    const wrappedExecute = async (args: z.infer<T>): Promise<string> => {
      // Build positional deps array using composite keys (toolName:dep_index)
      const depsArray: (McpMeshAgent | null)[] = normalizedDeps.map(
        (_, depIndex) => this.resolvedDeps.get(`${toolName}:dep_${depIndex}`) ?? null
      );
      const injectedCount = depsArray.filter((d) => d !== null).length;

      // Extract trace context from arguments (injected by upstream proxy)
      // This is the fallback mechanism since fastmcp doesn't expose HTTP headers
      let incomingTraceId: string | null = null;
      let incomingParentSpan: string | null = null;
      let cleanArgs = args;

      if (args && typeof args === "object") {
        const argsObj = args as Record<string, unknown>;
        if (typeof argsObj._trace_id === "string") {
          incomingTraceId = argsObj._trace_id;
        }
        if (typeof argsObj._parent_span === "string") {
          incomingParentSpan = argsObj._parent_span;
        }
        // Remove trace context from args before passing to tool
        if (incomingTraceId || incomingParentSpan) {
          const { _trace_id, _parent_span, ...rest } = argsObj;
          cleanArgs = rest as z.infer<T>;
        }
      }

      // Use incoming trace context or generate new one
      const traceId = incomingTraceId ?? generateTraceId();
      const spanId = generateSpanId();
      const parentSpanId = incomingParentSpan ?? null;
      const traceContext: TraceContext = { traceId, parentSpanId: spanId };

      const startTime = Date.now() / 1000;
      let success = true;
      let error: string | null = null;
      let resultType = "string";

      try {
        // Run tool execution within trace context using AsyncLocalStorage
        // This ensures trace context is properly propagated to all async operations
        // and isolated between concurrent requests
        const result = await runWithTraceContext(traceContext, async () => {
          return await execute(cleanArgs, ...depsArray);
        });
        return result;
      } catch (err) {
        success = false;
        error = err instanceof Error ? err.message : String(err);
        throw err;
      } finally {
        // Publish span (fire and forget)
        if (this.tracingEnabled) {
          const endTime = Date.now() / 1000;
          const durationMs = (endTime - startTime) * 1000;

          publishTraceSpan({
            traceId,
            spanId,
            parentSpan: parentSpanId,
            functionName: toolName,
            startTime,
            endTime,
            durationMs,
            success,
            error,
            resultType,
            argsCount: 0,
            kwargsCount: typeof cleanArgs === "object" ? Object.keys(cleanArgs as object).length : 0,
            dependencies: depEndpoints,
            injectedDependencies: injectedCount,
            meshPositions: [],
          }).catch(() => {
            // Silently ignore publish errors
          });
        }
      }
    };

    // Register with fastmcp
    // Use passthrough() to allow trace context fields (_trace_id, _parent_span)
    // to pass through Zod validation without being stripped
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const schema = def.parameters as any;
    const parametersWithPassthrough = typeof schema.passthrough === "function"
      ? schema.passthrough()
      : def.parameters;
    this.server.addTool({
      name: toolName,
      description: def.description,
      parameters: parametersWithPassthrough,
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

    // 0. Initialize distributed tracing
    const agentMetadata: AgentMetadata = {
      agentId: this.agentId,
      agentName: this.config.name,
      agentNamespace: this.config.namespace,
      agentHostname: this.config.host,
      agentIp: this.config.host,
      agentPort: this.config.port,
      agentEndpoint: `http://${this.config.host}:${this.config.port}`,
    };
    this.tracingEnabled = await initTracing(agentMetadata);

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
   * Creates or updates proxy for each tool+index that matches this capability.
   *
   * Uses composite keys (toolName:dep_index) to support multiple tools depending
   * on the same capability with different tags/settings.
   */
  private handleDependencyAvailable(
    capability: string,
    endpoint: string,
    functionName: string,
    agentId: string
  ): void {
    let matchCount = 0;

    // Iterate through all tools and their dependencies
    for (const [toolName, meta] of this.tools.entries()) {
      if (!meta.dependencies) continue;

      // Find all dependencies in this tool that match the capability
      meta.dependencies.forEach((dep, depIndex) => {
        if (dep.capability === capability) {
          // Get kwargs for this specific dependency index
          const kwargs = meta.dependencyKwargs?.[depIndex];

          // Create proxy with composite key
          const depKey = `${toolName}:dep_${depIndex}`;
          const proxy = createProxy(endpoint, capability, functionName, kwargs);
          this.resolvedDeps.set(depKey, proxy);
          matchCount++;
        }
      });
    }

    console.log(
      `Dependency available: ${capability} at ${endpoint} (agent: ${agentId}, ${matchCount} tool bindings)`
    );
  }

  /**
   * Handle dependency_unavailable event.
   * Removes proxies for all tool+index that match this capability.
   */
  private handleDependencyUnavailable(capability: string): void {
    let removeCount = 0;

    // Iterate through all tools and their dependencies
    for (const [toolName, meta] of this.tools.entries()) {
      if (!meta.dependencies) continue;

      meta.dependencies.forEach((dep, depIndex) => {
        if (dep.capability === capability) {
          const depKey = `${toolName}:dep_${depIndex}`;
          this.resolvedDeps.delete(depKey);
          removeCount++;
        }
      });
    }

    console.log(`Dependency unavailable: ${capability} (${removeCount} tool bindings removed)`);
  }

  /**
   * Get a resolved dependency proxy by capability name.
   * Returns the first matching proxy if multiple tools depend on the same capability.
   *
   * For more precise lookup, use getDependencyByKey with composite key "toolName:dep_index".
   */
  getDependency(capability: string): McpMeshAgent | null {
    // Find first matching capability in any tool
    for (const [toolName, meta] of this.tools.entries()) {
      if (!meta.dependencies) continue;
      const depIndex = meta.dependencies.findIndex((d) => d.capability === capability);
      if (depIndex >= 0) {
        return this.resolvedDeps.get(`${toolName}:dep_${depIndex}`) ?? null;
      }
    }
    return null;
  }

  /**
   * Get a resolved dependency proxy by composite key.
   *
   * @param toolName - The tool name
   * @param depIndex - The dependency index within that tool
   * @returns The proxy or null if not available
   */
  getDependencyByKey(toolName: string, depIndex: number): McpMeshAgent | null {
    return this.resolvedDeps.get(`${toolName}:dep_${depIndex}`) ?? null;
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
