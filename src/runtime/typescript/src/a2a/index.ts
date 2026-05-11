/**
 * A2A consumer surface barrel — re-exports the public types and
 * runtime classes the SDK consumer reaches for via
 * `import { A2AClient, A2ABearer } from "@mcpmesh/sdk"` (issue #917).
 */
export {
  A2AClient,
  type A2AClientConfig,
  type A2AMessage,
  type A2AResponse,
  type A2ATaskEnvelope,
  DEFAULT_TIMEOUT_MS,
  DEFAULT_POLL_INTERVAL_MS,
  DEFAULT_POLL_INTERVAL_MAX_MS,
  POLL_BACKOFF_FACTOR,
  isTerminalState,
  isCanceledState,
} from "./a2a-client.js";
export { A2AJob } from "./a2a-job.js";
export { A2AStream } from "./a2a-stream.js";
export type { A2AEvent, A2AEventKind } from "./a2a-event.js";
export { A2ABearer, type A2ABearerConfig } from "./a2a-bearer.js";
export {
  A2AError,
  A2ATimeoutError,
  A2AAuthError,
  A2AJobError,
  A2AJobFailedError,
  A2AJobCanceledError,
} from "./errors.js";
