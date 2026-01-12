/**
 * Typed error classes for mesh.llm() operations.
 *
 * These errors provide specific context about different failure modes,
 * matching Python's error class hierarchy.
 */

/**
 * Error thrown when the agentic loop reaches max iterations without completing.
 */
export class MaxIterationsError extends Error {
  readonly name = "MaxIterationsError";

  constructor(
    /** Number of iterations that were executed */
    public readonly iterations: number,
    /** The last response from the LLM before reaching the limit */
    public readonly lastResponse: unknown,
    /** The message history at the time of the error */
    public readonly messages?: unknown[]
  ) {
    super(`Max iterations (${iterations}) reached without completing the task`);
  }
}

/**
 * Error thrown when a tool execution fails during the agentic loop.
 */
export class ToolExecutionError extends Error {
  readonly name = "ToolExecutionError";

  constructor(
    /** Name of the tool that failed */
    public readonly toolName: string,
    /** The underlying error that caused the failure */
    public readonly cause: Error,
    /** Arguments that were passed to the tool */
    public readonly args?: Record<string, unknown>
  ) {
    super(`Tool '${toolName}' failed: ${cause.message}`);
  }
}

/**
 * Error thrown when the LLM API returns an error response.
 */
export class LLMAPIError extends Error {
  readonly name = "LLMAPIError";

  constructor(
    /** HTTP status code from the API */
    public readonly statusCode: number,
    /** Response body from the API */
    public readonly body: string,
    /** The provider that returned the error */
    public readonly provider?: string
  ) {
    super(`LLM API error (${statusCode}): ${body}`);
  }
}

/**
 * Error thrown when response parsing/validation fails.
 */
export class ResponseParseError extends Error {
  readonly name = "ResponseParseError";

  constructor(
    /** The raw content that failed to parse */
    public readonly rawContent: string,
    /** The underlying parse/validation error */
    public readonly cause: Error,
    /** The expected schema (if using structured output) */
    public readonly expectedSchema?: unknown
  ) {
    super(`Failed to parse LLM response: ${cause.message}`);
  }
}

/**
 * Error thrown when the LLM provider is not available.
 */
export class ProviderUnavailableError extends Error {
  readonly name = "ProviderUnavailableError";

  constructor(
    /** The provider specification that could not be resolved */
    public readonly providerSpec: unknown,
    /** Additional details about why resolution failed */
    public readonly reason?: string
  ) {
    super(
      `LLM provider unavailable${reason ? `: ${reason}` : ""}. ` +
        `Provider spec: ${JSON.stringify(providerSpec)}`
    );
  }
}
