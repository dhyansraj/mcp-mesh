/**
 * Error hierarchy for the A2A consumer surface (issue #917).
 *
 * Mirrors `_a2a_consumer.A2AJobFailed` / `A2AJobCanceled` (Python) and
 * `A2AException` / `A2AJobFailedException` / `A2AJobCanceledException`
 * (Java). Each subclass sets `name` explicitly so `instanceof` works
 * across module boundaries (ES module dual-loading, multiple SDK
 * copies under monorepo workspaces).
 */
export class A2AError extends Error {
  constructor(message: string, public readonly cause?: unknown) {
    super(message);
    this.name = "A2AError";
  }
}

export class A2ATimeoutError extends A2AError {
  constructor(message: string, cause?: unknown) {
    super(message, cause);
    this.name = "A2ATimeoutError";
  }
}

export class A2AAuthError extends A2AError {
  constructor(message: string, cause?: unknown) {
    super(message, cause);
    this.name = "A2AAuthError";
  }
}

export class A2AJobError extends A2AError {
  constructor(message: string, cause?: unknown) {
    super(message, cause);
    this.name = "A2AJobError";
  }
}

export class A2AJobFailedError extends A2AJobError {
  constructor(message: string, cause?: unknown) {
    super(message, cause);
    this.name = "A2AJobFailedError";
  }
}

export class A2AJobCanceledError extends A2AJobError {
  constructor(message: string, cause?: unknown) {
    super(message, cause);
    this.name = "A2AJobCanceledError";
  }
}
