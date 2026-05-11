/**
 * A2A producer barrel (issue #933).
 *
 * Re-exports the public surface user code reaches for:
 * - {@link mount} — the `mesh.a2a.mount(...)` entry point
 * - {@link A2AMountConfig} — the mount config shape
 * - {@link A2ADependencies} / {@link A2AHandler} — handler typing helpers
 *
 * Internal classes (`A2AProducerRegistry`, `A2ATaskStore`, dispatcher
 * builders) are exported for advanced wiring / testability — they aren't
 * promoted on the top-level `mesh.a2a` namespace.
 */

// Public mount API
export { mount, __getA2ATaskStore, __buildCardRenderContextForTests } from "./mount.js";

// Public types
export type {
  A2AMountConfig,
  A2ASurfaceMetadata,
} from "./registry.js";
export {
  A2AProducerRegistry,
} from "./registry.js";

export type {
  A2ADependencies,
  A2AHandler,
  DispatcherDeps,
  SseStreamPlan,
} from "./dispatcher.js";
export {
  buildDispatcherMiddleware,
  buildSendSubscribeStream,
  buildResubscribeStream,
  buildCompletedTask,
  buildFailedTask,
  buildWorkingTask,
  buildCanceledTask,
  buildTaskFromStatus,
  buildTaskFromLiveStatus,
  buildStatusUpdateFrame,
  buildArtifactUpdateFrame,
  projectLiveStatus,
  stringifyResult,
  JSONRPC_PARSE_ERROR,
  JSONRPC_INVALID_REQUEST,
  JSONRPC_METHOD_NOT_FOUND,
  JSONRPC_INVALID_PARAMS,
} from "./dispatcher.js";

export type { CardRenderContext } from "./card-builder.js";
export {
  buildAgentCard,
  DEFAULT_INPUT_MODES,
  DEFAULT_OUTPUT_MODES,
} from "./card-builder.js";

export type { TaskRecord } from "./task-store.js";
export {
  A2ATaskStore,
  TERMINAL_EVICTION_MS,
} from "./task-store.js";

export {
  buildBearerAuthMiddleware,
  JSONRPC_AUTH_ERROR,
} from "./auth-filter.js";

export {
  buildSseDispatcherMiddleware,
  renderSsePlan,
  POLL_INTERVAL_MILLIS,
  KEEPALIVE_MILLIS,
  MAX_STREAM_MILLIS,
  MAX_CONSECUTIVE_STATUS_FAILURES,
} from "./sse-emitter.js";

export {
  A2APublicUrlCache,
  buildLocalFallbackUrl,
} from "./public-url-cache.js";

export {
  A2A_SUBMITTED,
  A2A_WORKING,
  A2A_COMPLETED,
  A2A_FAILED,
  A2A_CANCELED,
  fromMesh,
  isTerminal,
  isMeshTerminal,
  meshStatusOf,
} from "./state-translator.js";
