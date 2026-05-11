/**
 * Handle to a long-running A2A task — returned by `A2AClient.submit`
 * (issue #917).
 *
 * Provides direct task lifecycle methods (`status`, `wait`, `cancel`)
 * AND a convenience `bridge(jobController)` that mirrors A2A polling
 * state into a mesh `JobController` for the typical
 * `addTool({ task: true, a2aConfig: { ... } })` consumer pattern.
 *
 * Mirrors `mesh._a2a_consumer.A2AJob` (Python) and
 * `io.mcpmesh.a2a.A2AJob` (Java).
 */
import { JobController, awaitJobCancel } from "@mcpmesh/core";
import {
  A2AClient,
  type A2AResponse,
  type A2ATaskEnvelope,
  POLL_BACKOFF_FACTOR,
  extractArtifactText,
  isCanceledState,
  isTerminalState,
  maybeJsonParse,
  readProgress,
  readState,
  readStatusMessage,
} from "./a2a-client.js";
import {
  A2AJobCanceledError,
  A2AJobFailedError,
  A2ATimeoutError,
} from "./errors.js";

export class A2AJob {
  private readonly client: A2AClient;
  readonly taskId: string;
  readonly initialState: string;
  private readonly initialResult: A2ATaskEnvelope;

  constructor(
    client: A2AClient,
    taskId: string,
    initialState: string,
    initialResult: A2ATaskEnvelope,
  ) {
    this.client = client;
    this.taskId = taskId;
    this.initialState = initialState;
    this.initialResult = initialResult;
  }

  /** POST `tasks/get` once and return the raw `result` envelope. */
  async status(): Promise<A2ATaskEnvelope> {
    return this.client.tasksGet(this.taskId);
  }

  /**
   * POST `tasks/cancel`. Idempotent — already-terminal tasks should
   * return cleanly per A2A v1.0; transport-level errors are logged
   * and swallowed so callers can still raise `A2AJobCanceledError`
   * or similar.
   */
  async cancel(reason?: string): Promise<void> {
    try {
      await this.client.tasksCancel(this.taskId, reason);
    } catch (err) {
      // Mirror the Python+Java posture (best-effort): the remote may
      // have already terminated the task. Log and move on so callers
      // can still raise A2AJobCanceledError or similar.
      console.info(
        `A2A tasks/cancel: remote raised for task ${this.taskId} on ` +
          `${this.client.url} (may already be terminal): ` +
          `${(err as Error)?.message ?? String(err)}`,
      );
    }
  }

  /**
   * Poll `tasks/get` until terminal; return `A2AResponse` on completed.
   *
   * Throws `A2AJobFailedError` on `state=failed`,
   * `A2AJobCanceledError` on `state=canceled`, `A2ATimeoutError` if
   * the deadline elapses.
   */
  async wait(timeoutMs?: number): Promise<A2AResponse> {
    const timeout = timeoutMs ?? this.client.timeoutMs;
    if (timeout <= 0) {
      throw new Error("A2AJob.wait: timeoutMs must be > 0");
    }

    if (isTerminalState(this.initialState)) {
      return this._terminalToResponseOrThrow(this.initialResult);
    }

    const deadline = Date.now() + timeout;
    let intervalMs = this.client.pollIntervalMs;
    while (Date.now() < deadline) {
      await sleep(Math.min(intervalMs, Math.max(1, deadline - Date.now())));
      if (Date.now() >= deadline) break;
      const result = await this.status();
      const state = readState(result);
      if (isTerminalState(state)) {
        return this._terminalToResponseOrThrow(result);
      }
      intervalMs = Math.min(
        this.client.pollIntervalMaxMs,
        Math.floor(intervalMs * POLL_BACKOFF_FACTOR),
      );
    }

    throw new A2ATimeoutError(
      `A2A task '${this.taskId}' on ${this.client.url} did not reach ` +
        `terminal state within ${timeout}ms`,
    );
  }

  /**
   * Mirror A2A polling into the supplied `JobController` until terminal.
   * Returns the final artifact value: parsed JSON when the artifact
   * text is valid JSON, otherwise the raw text. Empty artifacts return
   * an empty string.
   *
   * Cancel handling: races each iteration's sleep against
   * `awaitJobCancel(jobId)` so a mesh-side cancel arriving DURING a
   * sleep wakes us immediately instead of waiting for the next poll
   * boundary. On detection POSTs `tasks/cancel` upstream so the
   * producer stops billing for the work, then throws
   * `A2AJobCanceledError` so the framework's `task: true` wrapper
   * records a canceled outcome.
   */
  async bridge(controller: JobController): Promise<unknown> {
    if (controller == null) {
      throw new Error("A2AJob.bridge: controller must be non-null");
    }
    const jobId = controller.jobId;
    const cancelPromise = awaitJobCancel(jobId);

    const mirrorState = { lastProgress: undefined as number | undefined, lastMessage: undefined as string | undefined };
    if (this.initialResult) {
      await this._mirrorProgress(controller, this.initialResult, mirrorState);
    }
    if (isTerminalState(this.initialState)) {
      return this._terminalToArtifactOrThrow(this.initialResult);
    }

    let cancelObserved = false;
    // ONE shared AbortController fans out the cancelPromise resolution
    // to every per-iteration `raceSleep` listener. Without this the
    // polling loop would attach a fresh `.then` to cancelPromise on
    // every iteration — for a 30-min job at sub-second polling that's
    // hundreds of accumulated handlers on a never-resolving promise,
    // i.e. linear memory creep. AbortController makes the fan-out O(1).
    const cancelAbort = new AbortController();
    cancelPromise
      .then(() => {
        cancelObserved = true;
        cancelAbort.abort();
      })
      .catch((err: unknown) => {
        // awaitJobCancel rejects only when the napi binding itself
        // fails (binding loss mid-job). If we ignored the rejection
        // the polling loop would never observe a cancel signal and
        // could poll the A2A backend until the user-supplied deadline.
        // Treat as a degraded-but-recoverable cancel signal so the
        // bridge fails fast and propagates `tasks/cancel` upstream.
        console.warn(
          `[a2a-job] bridge: awaitJobCancel observer failed for task ` +
            `${this.taskId} (treating as degraded cancel): ` +
            `${(err as Error)?.message ?? String(err)}`,
        );
        cancelObserved = true;
        cancelAbort.abort();
      });

    let intervalMs = this.client.pollIntervalMs;
    while (true) {
      if (cancelObserved) {
        await this._propagateCancelUpstream("mesh-side cancel");
        throw new A2AJobCanceledError(
          `A2A task ${this.taskId} canceled by mesh-side request`,
        );
      }

      let result: A2ATaskEnvelope;
      try {
        result = await this.status();
      } catch (err) {
        // tasks/get itself failed (network error, HTTP 5xx, malformed
        // envelope, ...). The upstream producer is almost certainly
        // still running — best-effort POST tasks/cancel so it stops
        // billing for work whose result we'll never observe.
        await this._propagateCancelUpstream("consumer poll failed");
        throw new A2AJobFailedError(
          `A2A status poll failed for task ${this.taskId}: ` +
            `${(err as Error)?.message ?? String(err)}`,
          err,
        );
      }

      const state = readState(result);
      await this._mirrorProgress(controller, result, mirrorState);
      if (isTerminalState(state)) {
        return this._terminalToArtifactOrThrow(result);
      }

      // Race the sleep against the cancel signal — if cancel fires
      // mid-sleep we wake immediately and propagate on the next loop
      // iteration without wasting one more `tasks/get` round trip.
      await raceSleep(intervalMs, cancelAbort.signal);
      intervalMs = Math.min(
        this.client.pollIntervalMaxMs,
        Math.floor(intervalMs * POLL_BACKOFF_FACTOR),
      );
    }
  }

  // --- helpers -------------------------------------------------------------

  private async _mirrorProgress(
    controller: JobController,
    result: A2ATaskEnvelope,
    state: { lastProgress: number | undefined; lastMessage: string | undefined },
  ): Promise<void> {
    const progress = readProgress(result);
    const message = readStatusMessage(result);
    if (progress === undefined && message === undefined) {
      return;
    }
    if (progress === state.lastProgress && message === state.lastMessage) {
      return;
    }
    // Coerce missing progress to last-known or 0.0 — the controller
    // requires a number, but the consumer surface allows message-only
    // events. Clamp to [0, 1] — updateProgress expects a normalized
    // fraction; raw A2A producer progress values are advisory.
    const rawP =
      progress !== undefined
        ? progress
        : state.lastProgress !== undefined
          ? state.lastProgress
          : 0.0;
    const clamped = Math.min(1.0, Math.max(0.0, rawP));
    try {
      await controller.updateProgress(clamped, message ?? null);
    } catch (err) {
      // Do NOT advance lastProgress / lastMessage on delivery failure
      // — leaving them stale ensures the next poll's equality check
      // sees a delta and retries the update.
      console.warn(
        `[a2a-job] bridge: controller.updateProgress failed ` +
          `(task=${this.taskId}, progress=${progress}, msg=${message}) — ` +
          `will retry on next poll: ${(err as Error)?.message ?? String(err)}`,
      );
      return;
    }
    if (progress !== undefined) state.lastProgress = progress;
    state.lastMessage = message;
  }

  private async _propagateCancelUpstream(reason: string): Promise<void> {
    try {
      await this.client.tasksCancel(this.taskId, reason);
    } catch (err) {
      console.debug(
        `[a2a-job] bridge: upstream cancel after ${reason} also failed ` +
          `(task=${this.taskId}): ${(err as Error)?.message ?? String(err)}`,
      );
    }
  }

  private _terminalToResponseOrThrow(result: A2ATaskEnvelope): A2AResponse {
    const state = readState(result);
    if (state.toLowerCase() === "completed") {
      return this.client.buildResponse(this.taskId, result);
    }
    const msg =
      readStatusMessage(result) ?? `A2A task ${this.taskId} state=${state}`;
    if (isCanceledState(state)) {
      throw new A2AJobCanceledError(msg);
    }
    throw new A2AJobFailedError(msg);
  }

  private _terminalToArtifactOrThrow(result: A2ATaskEnvelope): unknown {
    const state = readState(result);
    if (state.toLowerCase() === "completed") {
      const text = extractArtifactText(result);
      if (!text) return text;
      return maybeJsonParse(text);
    }
    const msg =
      readStatusMessage(result) ?? `A2A task ${this.taskId} state=${state}`;
    if (isCanceledState(state)) {
      throw new A2AJobCanceledError(msg);
    }
    throw new A2AJobFailedError(msg);
  }
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * Sleep for `ms` OR until `signal` aborts — whichever is first. The
 * abort wakes us early; the timer is cleared in either path so we
 * don't leak handles. Uses an `AbortSignal` instead of a raw promise
 * so the polling loop can attach ONE upstream listener (the
 * AbortController) and fan out to per-iteration `raceSleep` calls
 * without accumulating handlers on a long-running cancelPromise.
 */
function raceSleep(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    if (signal.aborted) {
      resolve();
      return;
    }
    const onAbort = () => {
      clearTimeout(timer);
      resolve();
    };
    const timer = setTimeout(() => {
      signal.removeEventListener("abort", onAbort);
      resolve();
    }, ms);
    signal.addEventListener("abort", onAbort, { once: true });
  });
}
