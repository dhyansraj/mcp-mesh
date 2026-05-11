/**
 * Bearer-token credential for an outbound A2A call (issue #917).
 *
 * Provide either `token` (literal) or `tokenEnv` (the name of an
 * environment variable). Resolution happens at header-build time so
 * rotating the env var between calls picks up the new value without
 * reconstructing the surrounding A2AClient. Mirrors
 * `mesh._a2a_consumer.A2ABearer` (Python) and `io.mcpmesh.a2a.A2ABearer`
 * (Java).
 */
import { A2AAuthError } from "./errors.js";

export interface A2ABearerConfig {
  /** Literal bearer token. Mutually exclusive with `tokenEnv`. */
  token?: string;
  /** Env-var name to read the token from on each call. Mutually exclusive with `token`. */
  tokenEnv?: string;
}

export class A2ABearer {
  private readonly token?: string;
  private readonly tokenEnv?: string;

  constructor(config: A2ABearerConfig) {
    if (!config.token && !config.tokenEnv) {
      throw new A2AAuthError(
        "A2ABearer: must specify either 'token' or 'tokenEnv'",
      );
    }
    if (config.token && config.tokenEnv) {
      throw new A2AAuthError(
        "A2ABearer: 'token' and 'tokenEnv' are mutually exclusive",
      );
    }
    if (config.token !== undefined && config.token.trim() === "") {
      throw new A2AAuthError("A2ABearer: 'token' must be non-blank");
    }
    if (config.tokenEnv !== undefined && config.tokenEnv.trim() === "") {
      throw new A2AAuthError("A2ABearer: 'tokenEnv' must be non-blank");
    }
    this.token = config.token;
    this.tokenEnv = config.tokenEnv;
  }

  /**
   * Build the value for the `Authorization` header at call time.
   *
   * Reads the env var (when configured) on every call so a rotated
   * credential is honoured mid-process.
   */
  authorizationHeader(): string {
    let resolved = this.token;
    if (resolved === undefined && this.tokenEnv) {
      resolved = process.env[this.tokenEnv];
    }
    if (!resolved || resolved.trim() === "") {
      throw new A2AAuthError(
        `A2ABearer: no token resolved (token=${this.token ? "set" : "unset"}, ` +
          `tokenEnv=${this.tokenEnv ?? "<unset>"})`,
      );
    }
    return `Bearer ${resolved}`;
  }
}

/**
 * Helper: normalise the user-friendly union (`A2ABearer | A2ABearerConfig`)
 * into a concrete `A2ABearer` instance, or `undefined` for "no auth".
 *
 * Lets the consumer-side `addTool({ a2aConfig: { auth: { tokenEnv: "X" } } })`
 * shortcut work without forcing the user to `new A2ABearer(...)` every time.
 */
export function resolveBearer(
  auth: A2ABearer | A2ABearerConfig | undefined,
): A2ABearer | undefined {
  if (auth === undefined) return undefined;
  if (auth instanceof A2ABearer) return auth;
  return new A2ABearer(auth);
}
