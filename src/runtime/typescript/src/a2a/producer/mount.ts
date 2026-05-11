/**
 * `mesh.a2a.mount(app, config, handler)` — wire an Express app as an A2A
 * v1.0 producer (issue #933).
 *
 * Mirrors Python's `mesh.a2a.mount(app, ...)` for FastAPI. The mount
 * function owns both the `POST {path}` dispatch route and the
 * `GET {path}/.well-known/agent.json` card route — having the wrapper own
 * the wiring removes the boilerplate of registering two routes per skill.
 *
 * Mount-time side effects:
 * 1. Validate the mount config (path non-empty + starts with `/`, skillId
 *    non-empty).
 * 2. Register the dependencies as a synthetic route in `RouteRegistry` so
 *    DDDI events from the Rust core wire up resolved `McpMeshTool` proxies
 *    keyed by capability name — same plumbing `mesh.route()` uses.
 * 3. Store surface metadata in {@link A2AProducerRegistry} for heartbeat,
 *    card render, and auth gate lookups.
 * 4. Wire `app.post(path, [auth?,] dispatcher)` for JSON-RPC dispatch.
 * 5. Wire `app.get(path + "/.well-known/agent.json", cardHandler)` for
 *    agent card discovery. The card endpoint is ALWAYS public regardless of
 *    `auth` (spec §6.2 + conformance checklist) so clients can discover the
 *    authentication scheme before authenticating.
 * 6. Trigger `getApiRuntime().scheduleStart()` if any dependencies are
 *    declared — mirrors `mesh.route()`'s auto-init.
 */
import type {
  Application,
  ErrorRequestHandler,
  NextFunction,
  Request,
  RequestHandler,
  Response,
} from "express";

import { resolveConfig } from "@mcpmesh/core";

import type { AgentConfig } from "../../types.js";
import { RouteRegistry } from "../../route.js";
import { normalizeDependency } from "../../proxy.js";
import { getApiRuntime } from "../../api-runtime.js";

import {
  A2AProducerRegistry,
  type A2AMountConfig,
  type A2ASurfaceMetadata,
} from "./registry.js";
import { A2ATaskStore } from "./task-store.js";
import {
  buildDispatcherMiddleware,
  type A2ADependencies,
  type A2AHandler,
} from "./dispatcher.js";
import { buildSseDispatcherMiddleware } from "./sse-emitter.js";
import { buildBearerAuthMiddleware } from "./auth-filter.js";
import { buildAgentCard, type CardRenderContext } from "./card-builder.js";
import {
  A2APublicUrlCache,
  buildLocalFallbackUrl,
} from "./public-url-cache.js";

/**
 * Process-wide task store shared by every mounted surface. A single Map
 * across the process is correct because `task_id` is globally unique
 * (UUID4 by default + spec-allowed client-provided id); collisions are
 * caught by the dispatcher's duplicate check.
 */
const SHARED_TASK_STORE = new A2ATaskStore();

/**
 * Static JSON-RPC parse-error envelope (spec §4.1 `-32700`). Returned with
 * HTTP 400 when Express's `express.json()` body parser rejects a malformed
 * request body before our dispatcher runs. The body is fixed (no per-request
 * id since the request was never parseable), so we hold it as a constant
 * rather than re-rendering on every error — mirrors Java's
 * `MeshA2ADispatcherController.PARSE_ERROR_BODY` (#934 W5 refactor).
 *
 * Without this envelope Express returns its default HTML 400 page when
 * body-parser fails — A2A clients sending malformed JSON would receive HTML
 * instead of a structured JSON-RPC error.
 */
const PARSE_ERROR_BODY = JSON.stringify({
  jsonrpc: "2.0",
  error: { code: -32700, message: "Parse error" },
  id: null,
});

/**
 * Detect a body-parser parse failure. Express 4 + 5's `express.json()`
 * surfaces malformed-JSON failures as a `SyntaxError` with
 * `type === "entity.parse.failed"` and `status === 400` (set by the
 * underlying `body-parser` package). We check both so the predicate stays
 * robust if Express ever ships a different SyntaxError subclass.
 */
function isBodyParserParseError(err: unknown): boolean {
  if (!err || typeof err !== "object") return false;
  const e = err as { type?: unknown; status?: unknown; statusCode?: unknown };
  if (e.type === "entity.parse.failed") return true;
  if (err instanceof SyntaxError) {
    const code = (typeof e.status === "number" ? e.status : e.statusCode);
    if (code === 400) return true;
  }
  return false;
}

/**
 * Build the path-scoped Express error handler that converts body-parser
 * parse failures into a `-32700 Parse error` JSON-RPC envelope. Falls
 * through (calls `next(err)`) for any other error so the host app's own
 * error pipeline still owns non-body-parser failures.
 *
 * Mounted at `app.use(config.path, ...)` so it only intercepts errors
 * under the producer route — global JSON parse failures on unrelated user
 * routes still get Express's default behavior.
 */
function buildParseErrorHandler(): ErrorRequestHandler {
  return function a2aParseErrorHandler(
    err: unknown,
    _req: Request,
    res: Response,
    next: NextFunction
  ): void {
    if (!isBodyParserParseError(err)) {
      next(err);
      return;
    }
    res.status(400).type("application/json").send(PARSE_ERROR_BODY);
  };
}

/**
 * The card-render context inferred lazily at first request — pulled from
 * the same env vars / agent config as `mesh.agent()` so the producer's
 * card name matches what the rest of the SDK advertises.
 *
 * Public-URL resolution order at card-render time (spec §2.4):
 *   1. Registry-stamped FQDN from {@link A2APublicUrlCache} keyed by
 *      `(path, skillId)`. Populated when the registry returns
 *      `surfaces[].public_url` on its heartbeat response (the Rust core
 *      does not currently emit this event to TS — see
 *      {@link A2APublicUrlCache} for the wiring status).
 *   2. Local-fallback `http://{host}:{port}{path}` built from the
 *      `MCP_MESH_HTTP_HOST` / `MCP_MESH_HTTP_PORT` env vars.
 *   3. Omitted (`undefined`) when neither is available — the card emits
 *      no `url` rather than a blank one (spec conformance checklist).
 */
function buildCardRenderContext(surface: A2ASurfaceMetadata): CardRenderContext {
  const agentName = resolveConfig("agent_name", null) || "agent";
  const cachedUrl = A2APublicUrlCache.getInstance().get(surface.path, surface.skillId);
  let publicUrl: string | undefined = cachedUrl;
  if (!publicUrl) {
    const httpHost = resolveConfig("http_host", null);
    const httpPortRaw = resolveConfig("http_port", null);
    const httpPort = httpPortRaw ? Number.parseInt(httpPortRaw, 10) : NaN;
    if (httpHost) {
      publicUrl = buildLocalFallbackUrl(
        httpHost,
        Number.isFinite(httpPort) ? httpPort : undefined,
        surface.path
      );
    }
  }
  // Mount-time we have no separate version env var beyond what `mesh()`
  // applies — default to "1.0.0" per spec §3.2.
  return {
    agentName,
    agentVersion: "1.0.0",
    agentDescription: undefined,
    publicUrl,
  };
}

/**
 * Public entry point. Mount an A2A v1.0 producer surface on an Express app.
 *
 * @param app     - Express application instance
 * @param config  - Mount configuration (path, skill id, dependencies, ...)
 * @param handler - User handler invoked on every `tasks/send` call. Receives
 *                  resolved `McpMeshTool` dependency proxies and the A2A
 *                  `tasks/send` `params` payload; returns a value (or
 *                  Promise of one) that the framework wraps into the A2A
 *                  `Task` envelope. Throw to surface as `state=failed`.
 *
 * @example
 * ```typescript
 * mesh.a2a.mount(app, {
 *   path: "/agents/date",
 *   skillId: "get-date",
 *   skillName: "Get Date",
 *   description: "Get current date/time via A2A protocol",
 *   tags: ["system", "date"],
 *   dependencies: ["date_service"],
 *   auth: "bearer",
 * }, async (deps, payload) => {
 *   const result = await deps.date_service.call({});
 *   return { date: result };
 * });
 * ```
 */
export function mount<D extends A2ADependencies = A2ADependencies>(
  app: Application,
  config: A2AMountConfig,
  handler: A2AHandler<D>
): void {
  // ── Validate ─────────────────────────────────────────────────────────
  if (!config.path || config.path.length === 0) {
    throw new Error("mesh.a2a.mount: config.path is required and must be non-empty");
  }
  if (!config.path.startsWith("/")) {
    throw new Error(`mesh.a2a.mount: config.path must start with '/': got '${config.path}'`);
  }
  if (config.path.length > 1 && config.path.endsWith("/")) {
    throw new Error(
      `mesh.a2a.mount: config.path must not end with '/': got '${config.path}' ` +
        `(trailing-slash normalization is implicit at request time)`
    );
  }
  if (!config.skillId || config.skillId.length === 0) {
    throw new Error("mesh.a2a.mount: config.skillId is required and must be non-empty");
  }
  if (config.auth !== undefined && config.auth !== "bearer") {
    throw new Error(
      `mesh.a2a.mount: config.auth must be undefined or "bearer" (Phase 1); got: ${String(config.auth)}`
    );
  }

  const dependencies = config.dependencies ?? [];
  const normalizedDeps = dependencies.map(normalizeDependency);

  // ── Register dependencies via RouteRegistry (DDDI) ───────────────────
  // The producer reuses the same dependency-resolution machinery as
  // mesh.route(). Each surface registers a synthetic route in
  // RouteRegistry with method/path placeholders; the Rust core's
  // dependency-resolution events then drive resolved McpMeshTool proxies
  // into the registry, keyed by capability name, which the dispatcher
  // pulls out via getDependenciesForRoute(routeId).
  const routeRegistry = RouteRegistry.getInstance();
  const routeId = routeRegistry.registerRoute(
    "A2A",
    config.path,
    dependencies
  );

  // Stable normalised surface metadata.
  const surface: A2ASurfaceMetadata = {
    path: config.path,
    skillId: config.skillId,
    skillName: config.skillName ?? config.skillId,
    description: config.description ?? "",
    tags: config.tags ? [...config.tags] : [],
    dependencies: normalizedDeps,
    auth: config.auth === "bearer" ? "bearer" : "",
    routeId,
  };

  // ── Register in A2AProducerRegistry ──────────────────────────────────
  A2AProducerRegistry.getInstance().register(surface);

  // ── Wire dispatch route ──────────────────────────────────────────────
  // Per spec §4.6 / §4.7, `tasks/sendSubscribe` and `tasks/resubscribe`
  // emit a `text/event-stream` body while the other three verbs emit a
  // JSON body. Two sibling middlewares share the same route: the SSE
  // middleware consumes the request when the body's `method` matches
  // either SSE verb and falls through (calls `next()`) otherwise. This
  // mirrors Java's MeshA2ADispatcherController split.
  const dispatcherDeps = {
    surface,
    handler: handler as A2AHandler,
    taskStore: SHARED_TASK_STORE,
    routeRegistry,
  };
  const sseDispatcher = buildSseDispatcherMiddleware(dispatcherDeps);
  const jsonDispatcher = buildDispatcherMiddleware(dispatcherDeps);

  const postHandlers: RequestHandler[] = [];
  if (surface.auth === "bearer") {
    postHandlers.push(buildBearerAuthMiddleware());
  }
  postHandlers.push(sseDispatcher);
  postHandlers.push(jsonDispatcher);
  app.post(config.path, ...postHandlers);

  // Path-scoped error handler: convert body-parser SyntaxError (malformed
  // JSON body) into a `-32700 Parse error` JSON-RPC envelope per spec §4.1.
  // Without this, `express.json()` rejects malformed bodies with Express's
  // default HTML 400 page — A2A clients would not see a structured error.
  // Scoping by path (`app.use(config.path, ...)`) keeps the handler from
  // intercepting parse errors on unrelated user routes mounted on the same
  // app.
  app.use(config.path, buildParseErrorHandler());

  // ── Wire agent-card route ────────────────────────────────────────────
  // The card endpoint is ALWAYS public regardless of `auth` (spec §6.2)
  // so clients can discover the authentication scheme before
  // authenticating.
  const cardPath = config.path + "/.well-known/agent.json";
  const cardHandler = buildCardHandler(surface);
  app.get(cardPath, cardHandler);
  // Trailing-slash tolerance per spec §3.1 — `{path}/.well-known/agent.json/`
  // returns the same card.
  app.get(cardPath + "/", cardHandler);

  // ── Trigger API runtime auto-init ────────────────────────────────────
  // Mirrors mesh.route()'s behavior: scheduling start on first mount with
  // dependencies lets all surfaces register before connecting to the mesh.
  // We trigger even without dependencies so surfaces with auth-only mounts
  // still surface on the heartbeat envelope (the api-runtime would
  // otherwise sit idle).
  getApiRuntime().scheduleStart();
}

/**
 * Build the Express handler for `GET {path}/.well-known/agent.json`. The
 * handler is bound to a single surface — multi-mount apps get one card
 * handler per surface, mirroring spec §3.2 (one card per skill).
 */
function buildCardHandler(surface: A2ASurfaceMetadata): RequestHandler {
  return function cardHandler(_req: Request, res: Response): void {
    const ctx = buildCardRenderContext(surface);
    const card = buildAgentCard(surface, ctx);
    res.status(200).type("application/json").send(JSON.stringify(card));
  };
}

/**
 * Expose the per-process task store for advanced wiring (e.g., Chunk 1B's
 * SSE emitter needs to mark records terminal). Not part of the public
 * surface — tests + framework internals only.
 */
export function __getA2ATaskStore(): A2ATaskStore {
  return SHARED_TASK_STORE;
}

/**
 * Side-effect-free helper for tests / advanced wiring: build a fresh
 * card-render context using the current env / agent config. Lets tests
 * pass a custom context into {@link buildAgentCard} without going through
 * the mounted route. When no surface is provided, the public-URL cache
 * is not consulted (tests can override via `overrides.publicUrl`).
 */
export function __buildCardRenderContextForTests(
  overrides?: Partial<CardRenderContext>,
  surface?: A2ASurfaceMetadata
): CardRenderContext {
  if (surface) {
    return { ...buildCardRenderContext(surface), ...overrides };
  }
  const agentName = resolveConfig("agent_name", null) || "agent";
  return {
    agentName,
    agentVersion: "1.0.0",
    agentDescription: undefined,
    publicUrl: undefined,
    ...overrides,
  };
}

// Re-export AgentConfig for symmetry with mesh.route(); user code that
// imports from the producer barrel may want to type the mount caller's
// surrounding agent config.
export type { AgentConfig };
