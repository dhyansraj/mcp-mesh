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
import { isMainThread } from "node:worker_threads";
import {
  startAgent,
  type JsAgentSpec,
  type JsAgentHandle,
  type JsToolSpec,
  type JsDependencySpec,
  type JsLlmAgentSpec,
} from "@mcpmesh/core";

import type {
  AgentConfig,
  ResolvedAgentConfig,
  MeshToolDef,
  ToolMeta,
  McpMeshTool,
  NormalizedDependency,
  LlmProviderConfig,
} from "./types.js";
import { resolveConfig, generateAgentIdSuffix, findAvailablePort } from "./config.js";
import { enrichSchemaWithMediaTypes } from "./media-param.js";
import { createProxy, normalizeDependency, runWithTraceContext, runWithPropagatedHeaders, PROXY_DISPATCH_META } from "./proxy.js";
import {
  readJobHeaders,
  runWithJobContext,
  makeJobController,
  spliceJobController,
} from "./inbound-job-dispatch.js";
import { MeshJobSubmitter } from "./mesh-job-submitter.js";
import { ClaimDispatcher, type ClaimHandler } from "./claim-dispatcher.js";
import { registerJobHelperTools, type HelperToolMeta } from "./jobs-helper-tools.js";
import { registerCancelRoute } from "./jobs-cancel-route.js";
import {
  clusterStrictEnabled,
  normalizeSchemaWithPolicy,
} from "./schema-normalize.js";
import {
  initTracing,
  generateTraceId,
  generateSpanId,
  publishTraceSpan,
  matchesPropagateHeader,
  type TraceContext,
  type AgentMetadata,
} from "./tracing.js";
import {
  buildLlmAgentSpecs,
  handleLlmToolsUpdated,
  handleLlmProviderAvailable,
  handleLlmProviderUnavailable,
  LlmToolRegistry,
} from "./llm.js";
import { llmProvider, getLlmProviderMeta } from "./llm-provider.js";
import { findAndSetBasePath } from "./template.js";
import { getTlsOptions, getTlsConfigCached, prepareTls, cleanupTls } from "./tls-config.js";
import { closeHttpPool } from "./http-pool.js";
import { dispatch as poolDispatch, closePool } from "./tool-worker-pool.js";
import {
  A2AClient,
  A2ABearer,
  type A2AClientConfig,
} from "./a2a/index.js";

/**
 * Globally-set symbol that user agent code can check to detect whether it
 * is running inside a mesh tool-isolation worker. The mesh runtime sets
 * this on globalThis BEFORE importing the user module in worker mode.
 *
 * Use this to guard module-top-level side effects that should run only in
 * the main process — e.g. HTTP servers you start manually, OpenTelemetry
 * SDK init, prometheus registries, file watchers, etc.:
 *
 *   if (!globalThis[Symbol.for("@mcpmesh/sdk/in-worker")]) {
 *     await myCustomServer.listen(8081);
 *     myMetrics.start();
 *   }
 *
 * mesh's own setup (FastMCP server start, Express health endpoints,
 * registry heartbeat) is automatically guarded; users only need this
 * symbol if they have their own top-level side effects.
 */
export const IN_WORKER_SYMBOL = Symbol.for("@mcpmesh/sdk/in-worker");

// Worker-mode detection: when this module is loaded inside a worker_threads
// Worker, we skip all main-thread init (HTTP server, registry heartbeat, etc.)
// and only collect tool functions into _workerToolMap for the worker entry to
// invoke. The symbol is set by tool-worker-entry.ts before any user import.
const WORKER_MODE_SYMBOL = Symbol.for("@mcpmesh/sdk/worker-mode");
const _isWorkerMode =
  !isMainThread &&
  (globalThis as unknown as Record<symbol, boolean>)[WORKER_MODE_SYMBOL] === true;

// Module-level worker tool registry: populated by addTool() in worker mode,
// read by the worker entry via the __getWorkerToolMap() export. Module-level
// (not class-level) because the worker entry imports the SDK and needs a
// stable handle independent of which MeshAgent instance the user constructs.
const _workerToolMap = new Map<string, (...args: unknown[]) => unknown>();

/**
 * Internal: returns the worker-side tool map.
 *
 * Used exclusively by tool-worker-entry.ts after dynamic-importing the user
 * module. Not part of the public API.
 */
export function __getWorkerToolMap(): Map<string, (...args: unknown[]) => unknown> {
  return _workerToolMap;
}

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
  /**
   * Maps LLM provider tool names to their vendor (e.g., "process_chat" -> "anthropic").
   * TODO: Use for provider metrics, health checks, or exposing via getLlmProviderVendor() getter.
   * Currently populated by addLlmProvider() for future introspection needs.
   */
  private llmProviderVendors: Map<string, string> = new Map();
  private handle: JsAgentHandle | null = null;
  private httpsProxy?: import("node:https").Server;
  private started = false;
  private tracingEnabled = false;
  private shutdownRequested = false;

  /**
   * Resolved dependencies: composite key -> proxy
   * Key format: "${toolName}:dep_${depIndex}" (e.g., "myTool:dep_0")
   * Updated when dependency_available/unavailable events arrive.
   *
   * This allows multiple tools to depend on the same capability with
   * different tags/settings without overwriting each other.
   */
  private resolvedDeps: Map<string, McpMeshTool> = new Map();

  // True when this MeshAgent is constructed inside a worker_threads Worker.
  // In worker mode addTool() only stashes execute fns and skips all FastMCP /
  // registry / Rust core wiring (no Express port conflict, no double-register).
  private _workerMode = false;

  /**
   * Phase 1 MeshJob substrate: per-tool ClaimHandler for `task: true`
   * tools. Indexed by capability so the ClaimDispatcher can look up
   * the local handler without re-traversing the tools map. Populated
   * by addTool() at registration time; consumed by _autoStart() to
   * spawn one dispatcher per task tool.
   *
   * Issue #894: also carries the per-tool retryOn whitelist so the
   * dispatcher can pass it into `runWithJobContext` for the
   * release-lease-on-retry-eligible-throw path.
   */
  private _taskHandlers: Map<
    string,
    {
      handler: ClaimHandler;
      retryOn?: ReadonlyArray<new (...args: unknown[]) => Error>;
    }
  > = new Map();
  /**
   * Active claim dispatchers (one per task=true capability). Started
   * during _autoStart(); stopped during shutdown(). Empty for agents
   * that own no task=true tools.
   */
  private _claimDispatchers: ClaimDispatcher[] = [];

  /**
   * Issue #917: cache of `A2AClient` instances keyed by their
   * `(url, skillId, auth, timeoutMs)` tuple so multiple consumer
   * tools targeting the same backend share one outbound connection
   * pool. Closed via `close()` on agent shutdown.
   */
  private _a2aClients: Map<string, A2AClient> = new Map();

  /**
   * Issue #917: stable opaque IDs for `A2ABearer` instances used in
   * the A2AClient cache key. Bearer fields are private so we cannot
   * fingerprint by content (would also be a security risk — two
   * tools with distinct literal tokens must NEVER share a cache
   * entry). Identity-based keying is the safe default. `WeakMap`
   * lets bearers be GC'd when the registering tool is removed.
   */
  private _bearerIds: WeakMap<A2ABearer, string> = new WeakMap();
  private _nextBearerId = 0;

  constructor(server: FastMCP, config: AgentConfig) {
    if (_isWorkerMode) {
      // Worker thread: skip ALL init. Only addTool() runs (in worker-mode
      // branch) to populate the module-level _workerToolMap. The worker
      // entry imports the SDK + user module purely to discover tools — it
      // never calls server.start(), startAgent(), or scheduleAutoStart().
      this._workerMode = true;
      // Initialize required fields to satisfy "definitely assigned" without
      // triggering any side effects. None of these are read in worker mode.
      this.server = server;
      this.config = {
        name: config.name,
        version: "0.0.0",
        description: "",
        httpPort: 0,
        httpHost: "127.0.0.1",
        namespace: "default",
        registryUrl: "",
        heartbeatInterval: 0,
      };
      this.agentId = "";
      return;
    }

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

    // Phase 1 MeshJob substrate: validate `task: true` requires an
    // async function. Long-running tools need a Promise-based control
    // flow so the dispatch wrapper (Phase B) can await
    // `MeshJob.updateProgress()` / cancellation / outbound polling.
    // Fail loudly at `addTool` so the developer sees the misuse before
    // the agent even tries to register with the registry.
    //
    // Heuristic: AsyncFunction.constructor.name === "AsyncFunction".
    // We only flag the obvious sync case (an arrow/function literal)
    // — any function returning a Promise will pass this check, which
    // is the right relaxation for users who wrap their handler in a
    // Promise factory.
    if (def.task === true) {
      const ctorName = (execute as { constructor?: { name?: string } })
        ?.constructor?.name;
      if (ctorName !== "AsyncFunction") {
        // We can't reliably detect Promise-returning sync functions
        // without invoking them, but we CAN reject the unambiguous
        // "function() { ... }" case where the developer probably
        // forgot the `async` keyword.
        if (ctorName === "Function") {
          throw new Error(
            `addTool({ task: true }) requires an async execute function; ` +
              `tool '${toolName}' has a sync execute. Mark it 'async' or ` +
              `remove task: true.`
          );
        }
        // Other constructor names (GeneratorFunction, etc.) are
        // unusual; let them through with a console warning rather
        // than blocking — the dispatch wrapper will surface any actual
        // misuse at first invocation.
      }
    }

    // Phase 1 MeshJob substrate (consumer-side validation): if the
    // tool declares meshJobDepIndex, that index MUST be a non-negative
    // integer pointing to a valid dependency. Catch misuse at
    // registration so the developer doesn't see a confusing TypeError
    // at runtime when the wrapper tries to swap the dep proxy for a
    // submitter. Mirrors the meshJobParamIndex validation below —
    // NaN / fractional / negative values must fail-fast here too.
    if (def.meshJobDepIndex !== undefined) {
      const depCount = (def.dependencies ?? []).length;
      const v = def.meshJobDepIndex;
      const isInt = Number.isInteger(v) && v >= 0;
      if (!isInt) {
        throw new Error(
          `addTool({ meshJobDepIndex: ${v} }) for tool '${toolName}': ` +
            `meshJobDepIndex must be a non-negative integer (index into ` +
            `dependencies[]), got: ${v}`,
        );
      }
      if (v >= depCount) {
        throw new Error(
          `addTool({ meshJobDepIndex: ${v} }) for tool ` +
            `'${toolName}' is out of range — the tool declares ${depCount} ` +
            `dependencies. meshJobDepIndex must be a valid index into ` +
            `dependencies[].`,
        );
      }
    }

    // Phase 1 MeshJob substrate (producer-side validation): if the
    // tool declares meshJobParamIndex, that position MUST be a sane
    // integer >= 1. Position 0 is reserved for the args payload, so
    // the controller can only land at sig pos 1+. Without this
    // guard, values 0 / negative / NaN / non-integer silently skip
    // controller injection — the user's handler then sees `null`
    // where it expected a JobController and throws a confusing
    // `TypeError: Cannot read properties of null` at first await.
    //
    // Upper bound is a sanity check: > 10 almost certainly means a
    // typo (no real producer signature has that many params).
    if (def.meshJobParamIndex !== undefined) {
      const v = def.meshJobParamIndex;
      const ok = Number.isInteger(v) && v >= 1 && v <= 10;
      if (!ok) {
        throw new Error(
          `addTool({ meshJobParamIndex: ${v} }) for tool '${toolName}': ` +
            `meshJobParamIndex must be an integer >= 1 (position of MeshJob ` +
            `param after the args payload), got: ${v}`,
        );
      }
    }

    // Issue #894: validate retryOn at registration so misuse fails loud
    // before the agent talks to the registry. Mirror Python's
    // `mesh.decorators` validation in spirit:
    //   - retryOn requires task: true (without the job dispatch wrapper
    //     there's no controller to release a lease on, so the kwarg is
    //     meaningless);
    //   - entries must be Error constructor classes (typeof === "function").
    // We don't filter control-flow exceptions like Python's
    // KeyboardInterrupt / asyncio.CancelledError — JavaScript has no
    // direct equivalent, and AbortError-style cancellation is a legitimate
    // retry trigger for some users. They get to choose.
    if (def.retryOn !== undefined) {
      if (def.task !== true) {
        throw new Error(
          `addTool({ retryOn }) for tool '${toolName}': retryOn is only ` +
            `valid with task: true; remove retryOn or set task: true.`,
        );
      }
      if (!Array.isArray(def.retryOn)) {
        throw new Error(
          `addTool({ retryOn }) for tool '${toolName}': retryOn must be ` +
            `an array of Error constructor classes (e.g., [TypeError, MyError]).`,
        );
      }
      for (const entry of def.retryOn) {
        // Must be a function that has a prototype (i.e. an actual class
        // or a `function` declaration — not an arrow function), AND must
        // either be Error itself or a subclass. Arrow functions have
        // `prototype === undefined`, so `entry.prototype instanceof Error`
        // is `false` for them — they're rejected by the second check.
        // Without this, `err instanceof <arrow>` at dispatch time would
        // throw `TypeError: Right-hand side of instanceof is not callable`.
        if (typeof entry !== "function") {
          throw new Error(
            `addTool({ retryOn }) for tool '${toolName}': retryOn entries ` +
              `must be Error constructor classes (functions); got: ${String(entry)}`,
          );
        }
        if (entry !== Error && !(entry.prototype instanceof Error)) {
          throw new Error(
            `addTool({ retryOn }) for tool '${toolName}': retryOn entries ` +
              `must extend Error (or be Error itself); got: ${String(entry)}`,
          );
        }
      }
    }

    // Issue #917: validate a2aConfig at registration time so misuse fails
    // loud BEFORE the agent talks to the registry. Match the Python
    // `mesh.a2a_consumer` and Java `@A2AConsumer` startup-time checks.
    let a2aClient: A2AClient | null = null;
    if (def.a2aConfig !== undefined) {
      const cfg = def.a2aConfig;
      if (!cfg.url || cfg.url.trim() === "") {
        throw new Error(
          `addTool({ a2aConfig }) for tool '${toolName}': url must be ` +
            `a non-empty string.`,
        );
      }
      if (cfg.timeoutMs !== undefined) {
        if (!Number.isFinite(cfg.timeoutMs) || cfg.timeoutMs <= 0) {
          throw new Error(
            `addTool({ a2aConfig }) for tool '${toolName}': timeoutMs ` +
              `must be a finite positive number (got ${cfg.timeoutMs}).`,
          );
        }
      }
      if (cfg.pollIntervalMs !== undefined) {
        if (!Number.isFinite(cfg.pollIntervalMs) || cfg.pollIntervalMs <= 0) {
          throw new Error(
            `addTool({ a2aConfig }) for tool '${toolName}': ` +
              `pollIntervalMs must be a finite positive number ` +
              `(got ${cfg.pollIntervalMs}).`,
          );
        }
      }
      if (cfg.pollIntervalMaxMs !== undefined) {
        if (
          !Number.isFinite(cfg.pollIntervalMaxMs) ||
          cfg.pollIntervalMaxMs <= 0
        ) {
          throw new Error(
            `addTool({ a2aConfig }) for tool '${toolName}': ` +
              `pollIntervalMaxMs must be a finite positive number ` +
              `(got ${cfg.pollIntervalMaxMs}).`,
          );
        }
      }
      if (
        cfg.pollIntervalMs !== undefined &&
        cfg.pollIntervalMaxMs !== undefined &&
        cfg.pollIntervalMaxMs < cfg.pollIntervalMs
      ) {
        throw new Error(
          `addTool({ a2aConfig }) for tool '${toolName}': ` +
            `pollIntervalMaxMs (${cfg.pollIntervalMaxMs}) must be >= ` +
            `pollIntervalMs (${cfg.pollIntervalMs}).`,
        );
      }
      if (!this._workerMode) {
        const skillId = cfg.skillId ?? def.capability ?? toolName;
        a2aClient = this._getOrBuildA2AClient({
          url: cfg.url,
          skillId,
          auth: this._buildBearerFromConfig(cfg.auth),
          timeoutMs: cfg.timeoutMs,
          pollIntervalMs: cfg.pollIntervalMs,
          pollIntervalMaxMs: cfg.pollIntervalMaxMs,
        });
      }
    }

    // Worker mode: register the raw execute fn in the worker tool map and
    // skip FastMCP registration, dependency wiring, and metadata storage.
    // The worker entry will look up tools by name when handling dispatched
    // calls from the main thread.
    if (this._workerMode) {
      _workerToolMap.set(
        toolName,
        execute as unknown as (...args: unknown[]) => unknown
      );
      return this;
    }

    // Normalize dependencies
    const normalizedDeps: NormalizedDependency[] = (def.dependencies ?? []).map(
      normalizeDependency
    );
    const depEndpoints = normalizedDeps.map((d) => d.capability);

    // Capture for closures — these reads must be live at invocation
    // time (e.g. registryUrl/agentId aren't set yet at addTool time).
    const isTaskTool = def.task === true;
    const meshJobDepIndex = def.meshJobDepIndex;
    const meshJobParamIndex = def.meshJobParamIndex;
    // Issue #894: per-tool retryOn whitelist threaded into both
    // dispatch paths (inbound HTTP wrapper below + ClaimHandler
    // registered in this.taskHandlers). Captured here so the closure
    // sees a stable reference even if def is mutated post-registration.
    const retryOn = def.retryOn;

    // Phase 1 MeshJob substrate: when a job-bound tool exists AND the
    // user explicitly opted into worker isolation via env, log a single
    // warning at registration time. The wrapper force-disables
    // isolation for job-bound tools because controllers + the
    // AsyncLocalStorage / Rust task-local job context don't cross the
    // worker_threads boundary cleanly. Without this log the
    // force-disable was silent — users who set MCP_MESH_TOOL_ISOLATION
    // expected it to apply to every tool.
    const isJobBoundForLog = isTaskTool || meshJobDepIndex !== undefined;
    const isolationEnvSet =
      typeof process.env.MCP_MESH_TOOL_ISOLATION === "string" &&
      process.env.MCP_MESH_TOOL_ISOLATION.toLowerCase() !== "false";
    if (isJobBoundForLog && isolationEnvSet) {
      console.warn(
        `[mesh-tool] '${toolName}' has ` +
          (isTaskTool ? "task: true" : `meshJobDepIndex: ${meshJobDepIndex}`) +
          `; worker isolation is disabled for job-bound tools ` +
          `(controllers/AsyncLocalStorage don't cross worker boundaries). ` +
          `Set 'task: true' explicitly if you intend a producer.`,
      );
    }

    // Create wrapper that injects dependencies positionally and handles tracing
    const wrappedExecute = async (
      args: z.infer<T>,
    ): Promise<string> => {
      // Build positional deps array using composite keys (toolName:dep_index)
      // Phase 1 MeshJob substrate (consumer-side): if meshJobDepIndex is
      // set, swap the McpMeshTool proxy at that slot for a
      // MeshJobSubmitter targeting that dep's capability. We bind the
      // submitter to the live registryUrl/agentId so it can submit
      // jobs without needing access to the agent instance.
      const depsArray: (McpMeshTool | MeshJobSubmitter | null)[] = normalizedDeps.map(
        (dep, depIndex) => {
          if (depIndex === meshJobDepIndex) {
            // Build the submitter lazily per call so we always pick
            // up the current registryUrl (test harnesses sometimes
            // mutate it between calls).
            return new MeshJobSubmitter(
              dep.capability,
              this.agentId,
              this.config.registryUrl,
            );
          }
          return this.resolvedDeps.get(`${toolName}:dep_${depIndex}`) ?? null;
        },
      );
      const injectedCount = depsArray.filter((d) => d !== null).length;

      // Extract trace context from arguments (injected by upstream proxy)
      // This is the fallback mechanism since fastmcp doesn't expose HTTP headers
      let incomingTraceId: string | null = null;
      let incomingParentSpan: string | null = null;
      let cleanArgs = args;

      // Extract _mesh_headers from args for header propagation
      let propagatedHeaders: Record<string, string> = {};

      if (args && typeof args === "object") {
        const argsObj = args as Record<string, unknown>;
        if (typeof argsObj._trace_id === "string") {
          incomingTraceId = argsObj._trace_id;
        }
        if (typeof argsObj._parent_span === "string") {
          incomingParentSpan = argsObj._parent_span;
        }
        if (argsObj._mesh_headers && typeof argsObj._mesh_headers === "object") {
          const meshHeaders = argsObj._mesh_headers as Record<string, unknown>;
          // Filter against allowlist
          for (const [key, value] of Object.entries(meshHeaders)) {
            if (typeof value === "string" && matchesPropagateHeader(key)) {
              propagatedHeaders[key.toLowerCase()] = value;
            }
          }
        }
        // Remove trace context and mesh headers from args before passing to tool
        if (incomingTraceId || incomingParentSpan || Object.keys(propagatedHeaders).length > 0) {
          const { _trace_id, _parent_span, _mesh_headers, ...rest } = argsObj;
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

      // Tool isolation: dispatch user execute() onto a worker thread so
      // blocking/long-running calls don't stall the main loop (which serves
      // /health, /ready, FastMCP HTTP, and registry heartbeats). Mirrors the
      // Python implementation in _mcp_mesh/shared/tool_executor.py.
      // Default ON; set MCP_MESH_TOOL_ISOLATION=false to revert to inline
      // execution on the main loop (legacy behavior).
      //
      // Phase 1 MeshJob substrate: force-disable isolation for tools
      // that bind to a JobController or MeshJobSubmitter. The
      // controller/submitter wrap napi-rs handles plus
      // AsyncLocalStorage state that cannot be cleanly serialised
      // across the worker_threads boundary. Running inline on the
      // main loop is the right trade — task=true tools are
      // long-running by definition and benefit less from isolation
      // (their wall-clock time is dominated by the user's `await`s,
      // not CPU bursts that block the event loop).
      // Issue #917: A2A consumer tools force-disable isolation along
      // with job-bound tools. The framework-injected `A2AClient` wraps
      // an undici dispatcher handle that cannot be cleanly serialised
      // across the worker_threads boundary; running inline keeps the
      // cached client + connection pool intact across calls.
      const isA2aBound = a2aClient !== null;
      const isJobBound = isTaskTool || meshJobDepIndex !== undefined;
      const isolationEnabled =
        !isJobBound &&
        !isA2aBound &&
        (process.env.MCP_MESH_TOOL_ISOLATION ?? "true").toLowerCase() !== "false";

      try {
        let result: unknown;

        if (isolationEnabled) {
          // Build serializable depsConfig from depsArray. The worker rebuilds
          // its own proxies (with worker-local undici Agent) via createProxy
          // — Python parity, avoids cross-thread proxy state sharing.
          // Read from the non-enumerable Symbol stash so we don't rely on
          // public properties (which we keep non-enumerable to avoid leaking
          // endpoint/customHeaders via JSON.stringify).
          const depsConfig = depsArray.map((d, depIndex) => {
            if (d === null) return null;
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            const meta = (d as any)[PROXY_DISPATCH_META];
            if (!meta) {
              console.warn(
                `[mesh] tool '${toolName}' dependency at index ${depIndex} is missing PROXY_DISPATCH_META — ` +
                  `this proxy was not created via createProxy() and will arrive as null in the worker. ` +
                  `If you are constructing proxies manually, use createProxy() from @mcpmesh/sdk.`
              );
              return null;
            }
            return {
              endpoint: meta.endpoint as string,
              capability: meta.capability as string,
              functionName: meta.functionName as string,
              kwargs: (meta.kwargs ?? {}) as Record<string, unknown>,
            };
          });

          result = await poolDispatch({
            toolName,
            cleanArgs,
            depsConfig,
            traceContext,
            propagatedHeaders,
          });
        } else {
          // Legacy inline execution on the main thread. Preserved as a clean
          // fallback for users who explicitly opt out of isolation, AND used
          // unconditionally for job-bound tools (see isJobBound above).
          //
          // Phase 1 MeshJob substrate: when this tool is task=true and the
          // inbound headers carry X-Mesh-Job-Id, build a JobController,
          // splice it into the call args at meshJobParamIndex, and run the
          // user function inside both the JS-side ALS (CURRENT_JOB) and the
          // Rust-side task-local (withJobAsync) so cancel-registry binding
          // + outbound header injection work transparently.
          result = await runWithTraceContext(traceContext, async () => {
            return await runWithPropagatedHeaders(propagatedHeaders, async () => {
              if (isTaskTool) {
                const [jobId, deadlineSecs] = readJobHeaders(propagatedHeaders);
                let controller = null;
                if (jobId && this.config.registryUrl && this.agentId) {
                  try {
                    controller = makeJobController(
                      jobId,
                      this.agentId,
                      this.config.registryUrl,
                    );
                  } catch (err) {
                    // Don't silently fall back to a regular tool call —
                    // a `task: true` tool that needs a controller will
                    // misbehave (return a dict instead of completing the
                    // row, leaving the registry's job stuck in `working`
                    // until lease expiry). Surface the failure so the
                    // outer FastMCP handler reports it AND the inbound
                    // wrapper's catch (or its caller) can fail-fast.
                    console.error(
                      `[mesh-jobs] makeJobController failed for tool ` +
                        `'${toolName}' job=${jobId} agent=${this.agentId} ` +
                        `registry=${this.config.registryUrl}:`,
                      err,
                    );
                    throw err;
                  }
                }
                // Build the call args, splicing the controller (or null) at
                // meshJobParamIndex if specified. Position 0 is `args`; deps
                // begin at position 1. The MeshJob slot is orthogonal —
                // when meshJobParamIndex skips a position, deps shift past
                // it (caller's signature must reflect that).
                const callArgs = spliceJobController(
                  cleanArgs,
                  depsArray,
                  controller,
                  meshJobParamIndex,
                );
                // Issue #917: append the framework-cached A2AClient as
                // the trailing positional arg when this tool declares
                // a2aConfig. Mirrors the producer-side JobController
                // splice — A2AClient never participates in the
                // ordered-deps math, it always lands last.
                if (a2aClient !== null) {
                  callArgs.push(a2aClient);
                }
                return await runWithJobContext(
                  jobId,
                  deadlineSecs,
                  controller,
                  () =>
                    Promise.resolve(
                      (execute as (...a: unknown[]) => unknown)(...callArgs),
                    ),
                  retryOn,
                );
              }
              if (a2aClient !== null) {
                return await (execute as (...a: unknown[]) => unknown)(
                  cleanArgs,
                  ...(depsArray as (McpMeshTool | null)[]),
                  a2aClient,
                );
              }
              return await execute(cleanArgs, ...(depsArray as (McpMeshTool | null)[]));
            });
          });
        }

        // Auto-serialize non-string results (like Python SDK does).
        // NOTE: structuredContent removed in #917 — FastMCP TS rejects it via
        // strict zod schema (ContentResultZodSchema.strict()) even though
        // the field is part of the MCP spec. Re-enable when FastMCP TS
        // upstream accepts the field. Tracked in #925.
        if (typeof result === "string") {
          return result;
        } else if (result === undefined || result === null) {
          return "";
        } else {
          // Return JSON-stringified text only — every consumer parses
          // content[0].text back into an object anyway. FastMCP TS will
          // auto-build {content: [{type: "text", text: <string>}]} from
          // this bare string return, satisfying its strict schema.
          return JSON.stringify(result);
        }
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

    // Phase 1 MeshJob substrate: register a ClaimHandler for this
    // tool so the per-capability ClaimDispatcher (spawned in
    // _autoStart) can dispatch claimed jobs to the same execute fn
    // — without going through FastMCP's HTTP transport. The handler
    // builds the same callArgs shape the inbound wrapper does, but
    // gets the controller passed in directly (no header parsing
    // needed) and bypasses FastMCP's tool-call serialisation.
    if (isTaskTool) {
      const capability = def.capability ?? toolName;
      const handler: ClaimHandler = async (payload, controller) => {
        const liveDeps: (McpMeshTool | MeshJobSubmitter | null)[] = normalizedDeps.map(
          (dep, depIndex) => {
            if (depIndex === meshJobDepIndex) {
              return new MeshJobSubmitter(
                dep.capability,
                this.agentId,
                this.config.registryUrl,
              );
            }
            return this.resolvedDeps.get(`${toolName}:dep_${depIndex}`) ?? null;
          },
        );
        const callArgs = spliceJobController(
          payload,
          liveDeps,
          controller,
          meshJobParamIndex,
        );
        // Issue #917: A2A consumer tools dispatched via the claim
        // path get the same trailing A2AClient argument as the
        // inbound HTTP path.
        if (a2aClient !== null) {
          callArgs.push(a2aClient);
        }
        return await (execute as (...a: unknown[]) => unknown)(...callArgs);
      };
      this._taskHandlers.set(capability, { handler, retryOn });
    }

    // Store mesh metadata with JSON Schema for LLM tool resolution
    const inputSchema = this.convertZodToJsonSchema(def.parameters);
    enrichSchemaWithMediaTypes(inputSchema as Record<string, unknown>);
    // Issue #547: extract output schema if user supplied one. Zod cannot
    // infer return types from the handler signature, so this is opt-in.
    let outputSchemaRaw: object | undefined;
    if (def.outputSchema) {
      outputSchemaRaw = this.convertZodToJsonSchema(def.outputSchema);
    }
    this.tools.set(toolName, {
      capability: def.capability ?? toolName,
      version: def.version ?? "1.0.0",
      tags: def.tags ?? [],
      description: def.description ?? "",
      inputSchema: JSON.stringify(inputSchema),
      outputSchemaRaw,
      // Issue #547 Phase 4: per-tool override (default true = current behavior).
      outputSchemaStrict: def.outputSchemaStrict !== false,
      dependencies: normalizedDeps,
      dependencyKwargs: def.dependencyKwargs,
      // Phase 1 MeshJob substrate: stamp producer's long-running flag
      // so the heartbeat pipeline ships it to the registry. Consumers
      // read this to decide between job semantics and a regular
      // tools/call.
      task: def.task === true,
      meshJobParamIndex: def.meshJobParamIndex,
      meshJobDepIndex: def.meshJobDepIndex,
      // Issue #917: A2A consumer marker so heartbeat-build appends the
      // surrounding agent name to the tag list before shipping to the
      // registry. Captured here at addTool time so a downstream rename
      // of `this.config.name` doesn't desync the registered tag.
      a2aConsumer: def.a2aConfig !== undefined,
      a2aAgentName:
        def.a2aConfig !== undefined ? this.config.name : undefined,
    });

    return this;
  }

  /**
   * Add an LLM provider to the agent.
   *
   * This creates a zero-code LLM provider that other agents can use
   * via mesh delegation.
   *
   * @param config - LLM provider configuration
   * @returns This agent for chaining
   *
   * @example
   * ```typescript
   * agent.addLlmProvider({
   *   model: "anthropic/claude-sonnet-4-5",
   *   capability: "llm",
   *   tags: ["llm", "claude", "anthropic", "provider"],
   * });
   * ```
   */
  addLlmProvider(config: LlmProviderConfig): this {
    if (this._workerMode) {
      // LLM provider tools are registered with FastMCP directly (not via wrappedExecute),
      // so they don't go through the dispatch path. In worker mode there's no FastMCP
      // server running — just no-op and let the main thread handle LLM calls inline.
      return this;
    }

    // Create the LLM provider tool definition
    const toolDef = llmProvider(config);

    // Add to FastMCP server
    this.server.addTool({
      name: toolDef.name,
      description: toolDef.description,
      parameters: toolDef.parameters,
      execute: toolDef.execute,
    });

    // Get mesh metadata from the tool definition
    const meta = getLlmProviderMeta(toolDef);
    if (meta) {
      // Store mesh metadata with JSON Schema for registry
      const inputSchema = this.convertZodToJsonSchema(toolDef.parameters);
      this.tools.set(toolDef.name, {
        capability: meta.capability,
        version: meta.version,
        tags: meta.tags,
        description: toolDef.description,
        inputSchema: JSON.stringify(inputSchema),
        dependencies: [],
        dependencyKwargs: undefined,
      });

      // Store vendor for provider handler selection
      this.llmProviderVendors.set(toolDef.name, meta.vendor);
    }

    return this;
  }

  /**
   * Issue #917: build an `A2ABearer` (or undefined) from the
   * user-friendly auth config supported on `MeshA2AConfig.auth`. The
   * config can be either an `{ token, tokenEnv }` shorthand object OR
   * a pre-built `A2ABearer` instance the user constructed manually.
   *
   * Tightened to `instanceof A2ABearer` so a stray `{ token,
   * authorizationHeader: () => ... }` object cannot duck-type its way
   * past A2ABearer's validation (which catches blank tokens and
   * mutually-exclusive `token`/`tokenEnv`).
   */
  private _buildBearerFromConfig(
    auth: import("./types.js").MeshA2AConfig["auth"],
  ): A2ABearer | undefined {
    if (auth === undefined) return undefined;
    if (auth instanceof A2ABearer) return auth;
    return new A2ABearer(auth as { token?: string; tokenEnv?: string });
  }

  /**
   * Issue #917: cache `A2AClient` instances by their config tuple so
   * multiple consumer tools targeting the same backend share one
   * outbound connection pool. Auth instances participate in the cache
   * key by reference (same `A2ABearer` ref → same client); two
   * separately-constructed bearers — even ones holding identical
   * tokens — get separate clients. Identity-based keying is the safe
   * default: A2ABearer's private fields make content-fingerprinting
   * impossible from outside, and a content-derived key risks leaking
   * tool-A's bearer onto tool-B's outbound traffic.
   */
  private _bearerCacheKey(
    bearer: A2ABearer | import("./a2a/a2a-bearer.js").A2ABearerConfig | undefined,
  ): string {
    if (!bearer) return "none";
    // A2AClientConfig.auth permits a raw A2ABearerConfig too, but the
    // call site below always normalises via `_buildBearerFromConfig`
    // first, so in practice we only ever see real A2ABearer instances.
    // Defensively pass-through the config-shape case as a content-free
    // fallback key — never collide with the bearer-id namespace.
    if (!(bearer instanceof A2ABearer)) return "raw-config";
    let id = this._bearerIds.get(bearer);
    if (id === undefined) {
      id = `bearer-${this._nextBearerId++}`;
      this._bearerIds.set(bearer, id);
    }
    return id;
  }

  private _getOrBuildA2AClient(config: A2AClientConfig): A2AClient {
    const key = [
      config.url,
      config.skillId,
      this._bearerCacheKey(config.auth),
      config.timeoutMs ?? "default",
      config.pollIntervalMs ?? "default",
      config.pollIntervalMaxMs ?? "default",
    ].join("|");
    const existing = this._a2aClients.get(key);
    if (existing) return existing;
    const client = new A2AClient(config);
    this._a2aClients.set(key, client);
    return client;
  }

  /**
   * Convert Zod schema to JSON Schema.
   */
  private convertZodToJsonSchema(schema: z.ZodType): object {
    // $refStrategy: "root" preserves $ref + definitions for recursive Zod
    // schemas (e.g. z.lazy(...)). With "none", zod-to-json-schema can't expand
    // the cycle and falls back to {} (empty), which erases the recursion from
    // the canonical hash. Non-recursive shapes are unchanged because they have
    // no references to inline.
    return zodToJsonSchema(schema, { $refStrategy: "root" });
  }

  /**
   * Internal: Start the agent (called by auto-start mechanism).
   */
  async _autoStart(): Promise<void> {
    if (this.started) return;
    this.started = true;

    // Auto-detect template base path from agent's package.json location
    // This ensures file:// templates resolve correctly regardless of cwd
    findAndSetBasePath();

    // Handle httpPort=0: auto-assign an available port
    if (this.config.httpPort === 0) {
      const assignedPort = await findAvailablePort();
      this.config = { ...this.config, httpPort: assignedPort };
      console.log(`Auto-assigned port ${assignedPort} for agent`);
    }

    console.log(`Starting MCP Mesh agent: ${this.agentId}`);

    // Prepare TLS credentials (fetches from Vault if configured)
    prepareTls(this.agentId);

    // Resolve TLS config early so we can set the correct scheme
    const tlsOpts = getTlsOptions();
    const scheme = getTlsConfigCached().enabled ? "https" : "http";

    // 0. Initialize distributed tracing
    const agentMetadata: AgentMetadata = {
      agentId: this.agentId,
      agentName: this.config.name,
      agentNamespace: this.config.namespace,
      agentHostname: this.config.httpHost,
      agentIp: this.config.httpHost,
      agentPort: this.config.httpPort,
      agentEndpoint: `${scheme}://${this.config.httpHost}:${this.config.httpPort}`,
    };
    this.tracingEnabled = await initTracing(agentMetadata);

    // 1. Start HTTP server via fastmcp
    // Note: fastmcp.start() is async and starts the server
    // Use stateless mode so meshctl can call without sessions
    if (tlsOpts) {
      // TLS enabled: start fastmcp on an internal loopback port,
      // then create an HTTPS proxy on the advertised port that
      // terminates TLS/mTLS and forwards to the internal fastmcp HTTP server.
      const internalPort = await findAvailablePort();
      await this.server.start({
        transportType: "httpStream",
        httpStream: {
          port: internalPort,
          host: "127.0.0.1",
          stateless: true,
        },
      });

      const https = await import("node:https");
      const http = await import("node:http");
      const serverOpts = {
        ...tlsOpts,
        requestCert: true,
        rejectUnauthorized: true,
      };

      await new Promise<void>((resolve, reject) => {
        this.httpsProxy = https.createServer(serverOpts, (req, res) => {
          const proxyReq = http.request(
            {
              hostname: "127.0.0.1",
              port: internalPort,
              path: req.url,
              method: req.method,
              headers: req.headers,
            },
            (proxyRes) => {
              res.writeHead(proxyRes.statusCode!, proxyRes.headers);
              proxyRes.pipe(res);
            }
          );
          proxyReq.on("error", (err) => {
            res.writeHead(502);
            res.end(`Proxy error: ${err.message}`);
          });
          req.pipe(proxyReq);
        });
        this.httpsProxy.listen(
          this.config.httpPort,
          process.env.HOST ?? "0.0.0.0",
          () => {
            resolve();
          }
        );
        this.httpsProxy.on("error", reject);
      });

      console.log(
        `Agent listening on port ${this.config.httpPort} (HTTPS/mTLS, internal: ${internalPort})`
      );
    } else {
      // Plain HTTP - existing behavior
      await this.server.start({
        transportType: "httpStream",
        httpStream: {
          port: this.config.httpPort,
          host: process.env.HOST ?? "0.0.0.0",
          stateless: true,
        },
      });

      console.log(`Agent listening on port ${this.config.httpPort}`);
    }

    // 2. Register LLM tools from LlmToolRegistry
    this.registerLlmTools();

    // 2.5 Phase 1 MeshJob substrate: register the three framework
    // helper tools (`__mesh_job_status`/`_result`/`_cancel`) on
    // every TS agent regardless of whether it owns task=true tools.
    // Mirrors Python's JobsHelperToolsStep. Skipped when there's no
    // registry URL — the helpers can't function without it.
    this.registerJobsHelperTools();

    // 2.6 Phase 1 MeshJob substrate: mount POST /jobs/:job_id/cancel
    // on FastMCP's underlying Hono app so the registry's cancel
    // forwarder can fire the in-process cancel token. Best-effort —
    // failures here are logged, not fatal. When this agent owns
    // task: true tools and the route fails to register, escalate to
    // a second console.error so the operator can't miss the
    // cancel-mid-flight regression in logs.
    if (this.config.registryUrl) {
      const cancelRouteOk = registerCancelRoute(this.server);
      if (!cancelRouteOk && this._taskHandlers.size > 0) {
        console.error(
          `[mesh-jobs] agent ${this.agentId} owns ${this._taskHandlers.size} ` +
            `task: true tool(s) but the cancel route failed to register. ` +
            `Cancel requests for in-flight jobs will fall through to ` +
            `lease expiry — see the prior [mesh-jobs] error for the cause.`,
        );
      }
    }

    // 3. Start heartbeat to registry via Rust core
    await this.startHeartbeat();

    // 3.5 Phase 1 MeshJob substrate: spawn one ClaimDispatcher per
    // task=true tool so the agent can poll the registry's
    // /jobs/claim and dispatch claimed work locally. Started after
    // heartbeat so the registry already knows this replica when the
    // first claim arrives (eliminates the "claim before
    // registration" race).
    this.startClaimDispatchers();

    // 4. Install signal handlers for graceful shutdown
    this.installSignalHandlers();
  }

  /**
   * Phase 1 MeshJob substrate: register the three framework helper
   * tools on the FastMCP server AND in the agent's tool catalog so
   * the heartbeat ships them to the registry as visible capabilities.
   */
  private registerJobsHelperTools(): void {
    if (!this.config.registryUrl) {
      return;
    }
    let helpers: Map<string, HelperToolMeta>;
    try {
      helpers = registerJobHelperTools(this.server, this.config.registryUrl);
    } catch (err) {
      console.warn("[mesh-jobs] failed to register job helper tools:", err);
      return;
    }
    for (const [name, meta] of helpers.entries()) {
      // Don't overwrite a user-defined tool with the same name.
      if (this.tools.has(name)) continue;
      this.tools.set(name, {
        capability: meta.capability,
        version: meta.version,
        tags: meta.tags,
        description: meta.description,
        inputSchema: meta.inputSchema,
        outputSchemaStrict: true,
        dependencies: [],
        dependencyKwargs: undefined,
        task: meta.task,
      });
    }
  }

  /**
   * Phase 1 MeshJob substrate: spawn ClaimDispatchers for every
   * task=true tool registered. Skipped if no registry URL or no task
   * handlers are present.
   */
  private startClaimDispatchers(): void {
    if (!this.config.registryUrl) return;
    if (this._taskHandlers.size === 0) return;
    for (const [capability, entry] of this._taskHandlers.entries()) {
      const dispatcher = new ClaimDispatcher(
        capability,
        this.agentId,
        this.config.registryUrl,
        entry.handler,
        entry.retryOn,
      );
      dispatcher.start();
      this._claimDispatchers.push(dispatcher);
    }
  }

  /**
   * Register LLM tools from LlmToolRegistry.
   * This adds tool metadata for LLM tools created via mesh.llm().
   */
  private registerLlmTools(): void {
    const registry = LlmToolRegistry.getInstance();
    const configs = registry.getAllConfigs();

    for (const [, config] of configs) {
      // Only register if not already in tools map
      if (this.tools.has(config.name)) continue;

      this.tools.set(config.name, {
        capability: config.capability,
        version: config.version,
        tags: config.tags,
        description: config.description,
        inputSchema: config.inputSchema,
        dependencies: [], // LLM tools get their deps via llm_tools_updated events
        dependencyKwargs: undefined,
      });
    }
  }

  /**
   * Install signal handlers for graceful shutdown.
   * Ensures agent unregisters from registry on SIGINT/SIGTERM.
   *
   * Calls handle.shutdown() directly to trigger Rust core unregistration.
   * This causes nextEvent() to return with a "shutdown" event, breaking
   * the event loop cleanly. The shutdown is async but we don't await it
   * in the signal handler - the event loop handles the exit.
   */
  private installSignalHandlers(): void {
    const shutdownHandler = (signal: string) => {
      if (this.shutdownRequested) return;
      this.shutdownRequested = true;

      console.log(
        `\nReceived ${signal}, shutting down agent ${this.agentId}...`
      );

      // Close HTTPS proxy if it exists
      if (this.httpsProxy) {
        this.httpsProxy.close();
      }

      // Call shutdown directly - this triggers Rust core to unregister
      // and send a shutdown event that breaks the event loop
      if (this.handle) {
        this.handle.shutdown().then(() => {
          console.log(`Agent ${this.agentId} unregistered from registry`);
          process.exit(0);
        }).catch((err) => {
          console.error("Error during shutdown:", err);
          process.exit(1);
        });
      } else {
        process.exit(0);
      }
    };

    process.on("SIGINT", () => shutdownHandler("SIGINT"));
    process.on("SIGTERM", () => shutdownHandler("SIGTERM"));
  }

  /**
   * Start the Rust core heartbeat loop.
   */
  private async startHeartbeat(): Promise<void> {
    // Get LLM tool registry for llmFilter/llmProvider
    const llmRegistry = LlmToolRegistry.getInstance();

    // Issue #547 Phase 4: read cluster strict knob once; per-tool override
    // is read inside the loop below.
    const clusterStrict = clusterStrictEnabled();

    // Build the agent spec for Rust core
    const tools: JsToolSpec[] = Array.from(this.tools.entries()).map(
      ([name, meta]) => {
        // Check if this tool has LLM config
        const llmConfig = llmRegistry.getConfig(name);

        // Build llmFilter as JSON string (like Python does)
        let llmFilter: string | undefined;
        if (llmConfig?.filter && llmConfig.filter.length > 0) {
          llmFilter = JSON.stringify({
            filter: llmConfig.filter,
            filter_mode: llmConfig.filterMode,
          });
        }

        // Build llmProvider as JSON string (like Python does)
        let llmProvider: string | undefined;
        if (llmConfig?.provider && typeof llmConfig.provider === "object") {
          llmProvider = JSON.stringify({
            capability: llmConfig.provider.capability,
            tags: llmConfig.provider.tags ?? [],
          });
        }

        // Issue #547 / Phase 4: normalize via Rust core and apply verdict policy.
        // Throws on (effective) BLOCK to refuse agent startup; demoted BLOCKs
        // and WARNs are logged loudly and shipped in schemaWarnings.
        const toolStrict = meta.outputSchemaStrict !== false;
        let inputSchemaCanonical: string | undefined;
        let inputSchemaHash: string | undefined;
        let outputSchemaCanonical: string | undefined;
        let outputSchemaHash: string | undefined;
        const combinedWarnings: string[] = [];

        if (meta.inputSchema) {
          let inputRaw: object | undefined;
          try {
            inputRaw = JSON.parse(meta.inputSchema);
          } catch {
            // shouldn't happen, but fall through without normalizing
          }
          if (inputRaw) {
            const r = normalizeSchemaWithPolicy(
              inputRaw,
              `tool '${name}' input`,
              clusterStrict,
              toolStrict
            );
            inputSchemaCanonical = r.canonicalJson ?? undefined;
            inputSchemaHash = r.hash ?? undefined;
            combinedWarnings.push(...r.warnings);
          }
        }

        let outputSchemaJson: string | undefined;
        if (meta.outputSchemaRaw) {
          outputSchemaJson = JSON.stringify(meta.outputSchemaRaw);
          const r = normalizeSchemaWithPolicy(
            meta.outputSchemaRaw,
            `tool '${name}' output`,
            clusterStrict,
            toolStrict
          );
          outputSchemaCanonical = r.canonicalJson ?? undefined;
          outputSchemaHash = r.hash ?? undefined;
          combinedWarnings.push(...r.warnings);
        }

        // Issue #917: when this tool was registered with a2aConfig,
        // append the consumer agent's name to the tag list (defensive
        // copy — never mutate meta.tags). Skips when the agent has
        // no name (consumer-only / nameless agent) or when the tag
        // already appears, mirrors Java's
        // MeshToolRegistry.injectConsumerNameTags semantics.
        let effectiveTags = meta.tags;
        if (meta.a2aConsumer) {
          const agentName = meta.a2aAgentName;
          if (
            agentName &&
            agentName.trim() !== "" &&
            !meta.tags.includes(agentName)
          ) {
            effectiveTags = [...meta.tags, agentName];
          }
        }

        return {
          functionName: name,
          capability: meta.capability,
          version: meta.version,
          tags: effectiveTags,
          description: meta.description,
          // Pass dependencies to Rust core for registry resolution
          // Note: tags may contain nested arrays for OR alternatives (TagSpec[])
          // Serialize to JSON for Rust binding - preserves nested structure
          dependencies: meta.dependencies.map(
            (dep): JsDependencySpec => {
              // Issue #547: normalize per-dep expectedSchemaRaw. There's no
              // per-tool override on the consumer side (override is producer-
              // side); we still apply cluster strict so WARN→BLOCK works.
              let expectedCanonical: string | undefined;
              let expectedHash: string | undefined;
              if (dep.expectedSchemaRaw) {
                const r = normalizeSchemaWithPolicy(
                  dep.expectedSchemaRaw,
                  `dependency on '${dep.capability}'`,
                  clusterStrict,
                  true
                );
                expectedCanonical = r.canonicalJson ?? undefined;
                expectedHash = r.hash ?? undefined;
              }
              return {
                capability: dep.capability,
                tags: JSON.stringify(dep.tags ?? []),
                version: dep.version,
                expectedSchemaCanonical: expectedCanonical,
                expectedSchemaHash: expectedHash,
                matchMode: dep.matchMode,
              };
            }
          ),
          inputSchema: meta.inputSchema,
          outputSchema: outputSchemaJson,
          inputSchemaCanonical,
          inputSchemaHash,
          outputSchemaCanonical,
          outputSchemaHash,
          schemaWarnings: combinedWarnings.length > 0 ? combinedWarnings : undefined,
          // LLM filter/provider as JSON strings (matches Python format)
          llmFilter,
          llmProvider,
        };
      }
    );

    // Build LLM agent specs for tools using mesh.llm()
    const llmAgentSpecs = buildLlmAgentSpecs();
    const llmAgents: JsLlmAgentSpec[] | undefined =
      llmAgentSpecs.length > 0
        ? llmAgentSpecs.map((spec) => ({
            functionId: spec.functionId,
            provider: spec.provider,
            filter: spec.filter,
            filterMode: spec.filterMode,
            maxIterations: spec.maxIterations,
          }))
        : undefined;

    const spec: JsAgentSpec = {
      // Base name (shared across replicas, e.g., "fortuna"), unique ID via agentId.
      name: this.config.name,
      agentId: this.agentId,
      version: this.config.version,
      description: this.config.description,
      registryUrl: this.config.registryUrl,
      httpPort: this.config.httpPort,
      httpHost: this.config.httpHost,
      namespace: this.config.namespace,
      tools,
      llmAgents,
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
              event.agentId!,
              event.requestingFunction,
              event.depIndex
            );
            break;

          case "dependency_unavailable":
            this.handleDependencyUnavailable(
              event.capability!,
              event.requestingFunction,
              event.depIndex
            );
            break;

          case "dependency_changed":
            // Handle as available with new endpoint
            this.handleDependencyAvailable(
              event.capability!,
              event.endpoint!,
              event.functionName!,
              event.agentId!,
              event.requestingFunction,
              event.depIndex
            );
            break;

          case "registry_connected":
            console.log("Connected to registry");
            break;

          case "registry_disconnected":
            console.warn(`Disconnected from registry: ${event.reason}`);
            break;

          case "llm_tools_updated":
            // Handle LLM tools update
            if (event.functionId && event.tools) {
              handleLlmToolsUpdated(
                event.functionId,
                event.tools.map((t) => ({
                  functionName: t.functionName,
                  capability: t.capability,
                  endpoint: t.endpoint,
                  agentId: t.agentId,
                  inputSchema: t.inputSchema,
                }))
              );
            }
            break;

          case "llm_provider_available":
            // Handle LLM provider available
            // Note: functionId is inside providerInfo, not on event root
            if (event.providerInfo) {
              const funcId = event.functionId || event.providerInfo.functionId;
              if (funcId) {
                handleLlmProviderAvailable(funcId, {
                  agentId: event.providerInfo.agentId,
                  endpoint: event.providerInfo.endpoint,
                  functionName: event.providerInfo.functionName,
                  model: event.providerInfo.model,
                });
              }
            }
            break;

          case "llm_provider_unavailable":
            // Handle LLM provider unavailable
            if (event.functionId) {
              handleLlmProviderUnavailable(event.functionId);
            }
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
   * Creates proxy at the exact position specified by the event.
   *
   * The Rust core now sends events with requestingFunction and depIndex,
   * so we can directly create the proxy at the correct position without
   * needing to match by capability.
   */
  private handleDependencyAvailable(
    capability: string,
    endpoint: string,
    functionName: string,
    agentId: string,
    requestingFunction?: string,
    depIndex?: number
  ): void {
    // If we have position info, use it directly (new behavior)
    if (requestingFunction !== undefined && depIndex !== undefined) {
      const meta = this.tools.get(requestingFunction);
      const kwargs = meta?.dependencyKwargs?.[depIndex];

      const depKey = `${requestingFunction}:dep_${depIndex}`;
      const proxy = createProxy(endpoint, capability, functionName, kwargs);
      this.resolvedDeps.set(depKey, proxy);

      console.log(
        `Dependency available: ${capability} at ${endpoint} (tool: ${requestingFunction}, index: ${depIndex}, agent: ${agentId})`
      );
      return;
    }

    // Fallback for backward compatibility (old events without position info)
    // Iterate through all tools and their dependencies
    let matchCount = 0;
    for (const [toolName, meta] of this.tools.entries()) {
      if (!meta.dependencies) continue;

      meta.dependencies.forEach((dep, idx) => {
        if (dep.capability === capability) {
          const kwargs = meta.dependencyKwargs?.[idx];
          const depKey = `${toolName}:dep_${idx}`;
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
   * Removes proxy at the exact position specified by the event.
   */
  private handleDependencyUnavailable(
    capability: string,
    requestingFunction?: string,
    depIndex?: number
  ): void {
    // If we have position info, use it directly (new behavior)
    if (requestingFunction !== undefined && depIndex !== undefined) {
      const depKey = `${requestingFunction}:dep_${depIndex}`;
      this.resolvedDeps.delete(depKey);

      console.log(
        `Dependency unavailable: ${capability} (tool: ${requestingFunction}, index: ${depIndex})`
      );
      return;
    }

    // Fallback for backward compatibility (old events without position info)
    let removeCount = 0;
    for (const [toolName, meta] of this.tools.entries()) {
      if (!meta.dependencies) continue;

      meta.dependencies.forEach((dep, idx) => {
        if (dep.capability === capability) {
          const depKey = `${toolName}:dep_${idx}`;
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
  getDependency(capability: string): McpMeshTool | null {
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
  getDependencyByKey(toolName: string, depIndex: number): McpMeshTool | null {
    return this.resolvedDeps.get(`${toolName}:dep_${depIndex}`) ?? null;
  }

  /**
   * Get all resolved dependencies.
   */
  getAllDependencies(): Map<string, McpMeshTool> {
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
    // Phase 1 MeshJob substrate: stop claim dispatchers first so
    // they don't pull a fresh job mid-shutdown.
    for (const d of this._claimDispatchers) {
      try {
        await d.stop();
      } catch (err) {
        console.warn(`[mesh-jobs] error stopping claim dispatcher:`, err);
      }
    }
    this._claimDispatchers = [];
    // Issue #917: mark all cached A2AClients closed so any in-flight
    // user code raises cleanly instead of reusing a torn-down instance.
    // Close in parallel so one slow client doesn't block the others —
    // the undici Agent pool is shared via closeHttpPool() below.
    const closePromises = Array.from(this._a2aClients.values()).map((client) =>
      client.close().catch((err) => {
        console.warn("[mesh-a2a] Error closing A2AClient:", err);
        return null;
      }),
    );
    await Promise.allSettled(closePromises);
    this._a2aClients.clear();
    try {
      await closeHttpPool();
    } catch (err) {
      console.warn("Error closing HTTP pool:", err);
    }
    try {
      await closePool();
    } catch (err) {
      console.warn("Error closing tool worker pool:", err);
    }
    if (this.httpsProxy) {
      this.httpsProxy.close();
      this.httpsProxy = undefined;
    }
    if (this.handle) {
      await this.handle.shutdown();
      this.handle = null;
    }
    cleanupTls();
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
 *   httpPort: 9002,
 * });
 * ```
 */
export function mesh(server: FastMCP, config: AgentConfig): MeshAgent {
  return new MeshAgent(server, config);
}
