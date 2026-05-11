/**
 * Bearer-token authentication gate for `mesh.a2a.mount(...)` surfaces (spec §6).
 *
 * Mounted as Express middleware on the `POST {path}` route only — the agent
 * card endpoint (`GET {path}/.well-known/agent.json`) is always reachable
 * without auth (spec §6.2 + conformance checklist) so clients can discover
 * the authentication scheme before authenticating.
 *
 * Phase 1 semantics:
 * 1. The producer MUST require an `Authorization: Bearer <token>` header.
 * 2. The producer MUST reject headers that:
 *    - are missing entirely;
 *    - have a non-`Bearer` scheme (case-insensitive prefix check);
 *    - have an empty token after the `Bearer ` prefix (whitespace-only counts as empty).
 * 3. The producer MUST NOT validate the token value. Value-level validation
 *    is Phase 2+ (spec §6.2 + Appendix B item 4).
 *
 * Error shape (spec §6.3): HTTP 401 with a JSON-RPC envelope carrying
 * `error.code = -32001` and `id = null` (the request body is never parsed
 * at this stage). The `-32001` code sits in the implementation-defined
 * `-32000` … `-32099` server-error range and matches the Python / Java
 * producers exactly for cross-runtime parity.
 */
import type { NextFunction, Request, RequestHandler, Response } from "express";

/** Implementation-defined server-error code for authentication failures. */
export const JSONRPC_AUTH_ERROR = -32001;

const BEARER_PREFIX = "Bearer ";

/**
 * Build the Express middleware that enforces the bearer-token presence
 * check. The middleware is only mounted when the surface declared
 * `auth: "bearer"` — mounts without `auth` get no middleware so the dispatch
 * route is reachable without authentication.
 */
export function buildBearerAuthMiddleware(): RequestHandler {
  return function bearerAuthMiddleware(
    req: Request,
    res: Response,
    next: NextFunction
  ): void {
    const authz = req.headers["authorization"];
    if (typeof authz !== "string" || authz.length === 0) {
      writeAuthError(
        res,
        "Authentication required: missing Authorization: Bearer <token> header"
      );
      return;
    }
    // Case-insensitive prefix check on "Bearer ".
    if (
      authz.length < BEARER_PREFIX.length ||
      authz.substring(0, BEARER_PREFIX.length).toLowerCase() !== BEARER_PREFIX.toLowerCase()
    ) {
      writeAuthError(
        res,
        "Authentication required: missing Authorization: Bearer <token> header"
      );
      return;
    }
    const token = authz.substring(BEARER_PREFIX.length).trim();
    if (token.length === 0) {
      writeAuthError(
        res,
        "Authentication required: empty bearer token in Authorization header"
      );
      return;
    }
    // Phase 1: presence check only — DO NOT validate token value.
    next();
  };
}

function writeAuthError(res: Response, message: string): void {
  res.status(401).type("application/json").send(
    JSON.stringify({
      jsonrpc: "2.0",
      error: { code: JSONRPC_AUTH_ERROR, message },
      id: null,
    })
  );
}
