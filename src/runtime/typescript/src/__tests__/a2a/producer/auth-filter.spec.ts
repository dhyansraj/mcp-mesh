/**
 * Unit tests for `auth-filter.ts` (spec §6.2 + §6.3).
 *
 * Coverage:
 * - `Bearer <token>` header → `next()`
 * - Empty / whitespace-only token after `Bearer ` → 401 + `-32001`
 * - Missing `Authorization` header → 401 + `-32001`
 * - Wrong scheme (`Basic ...`) → 401 + `-32001`
 * - Phase 1 invariant: presence-only — token VALUE is NOT validated
 *   (Appendix B item 4).
 *
 * Mirrors Java's `MeshA2AAuthFilterTest`.
 *
 * Note: the "mount with no auth + card endpoint always public" assertions
 * are covered in `mount.spec.ts` (it's a wiring concern, not the
 * filter's own behaviour).
 */
import { describe, it, expect, vi } from "vitest";
import type { Request, Response, NextFunction } from "express";

import {
  buildBearerAuthMiddleware,
  JSONRPC_AUTH_ERROR,
} from "../../../a2a/producer/auth-filter.js";

interface CapturedResponse {
  status?: number;
  contentType?: string;
  body?: string;
}

function makeReq(headers: Record<string, string | undefined>): Request {
  return { headers } as unknown as Request;
}

function makeRes(captured: CapturedResponse): Response {
  return {
    status(code: number) {
      captured.status = code;
      return this;
    },
    type(t: string) {
      captured.contentType = t;
      return this;
    },
    send(body: string) {
      captured.body = body;
      return this;
    },
  } as unknown as Response;
}

describe("buildBearerAuthMiddleware (spec §6.2)", () => {
  /** Spec §6.2: valid `Bearer <token>` passes through to next(). */
  it("calls next() on valid Bearer token", () => {
    const mw = buildBearerAuthMiddleware();
    const captured: CapturedResponse = {};
    const req = makeReq({ authorization: "Bearer abc123" });
    const res = makeRes(captured);
    const next = vi.fn() as NextFunction;

    mw(req, res, next);

    expect(next).toHaveBeenCalledTimes(1);
    expect(captured.status).toBeUndefined();
    expect(captured.body).toBeUndefined();
  });

  /** Spec §6.2 — Appendix B item 4: presence only; never validate value. */
  it("does not validate the token value (Phase 1 presence-only)", () => {
    const mw = buildBearerAuthMiddleware();
    const captured: CapturedResponse = {};
    const req = makeReq({ authorization: "Bearer not-a-real-jwt-just-presence" });
    const res = makeRes(captured);
    const next = vi.fn() as NextFunction;

    mw(req, res, next);

    expect(next).toHaveBeenCalledTimes(1);
  });

  /** Spec §6.3: empty bearer token → 401 + -32001 JSON-RPC envelope. */
  it("returns 401 + -32001 on empty Bearer token", () => {
    const mw = buildBearerAuthMiddleware();
    const captured: CapturedResponse = {};
    const req = makeReq({ authorization: "Bearer " });
    const res = makeRes(captured);
    const next = vi.fn() as NextFunction;

    mw(req, res, next);

    expect(next).not.toHaveBeenCalled();
    expect(captured.status).toBe(401);
    expect(captured.contentType).toBe("application/json");
    const body = JSON.parse(captured.body ?? "{}");
    expect(body.jsonrpc).toBe("2.0");
    expect(body.error.code).toBe(JSONRPC_AUTH_ERROR);
    expect(body.error.code).toBe(-32001);
    expect(body.id).toBeNull();
  });

  /** Whitespace-only token after `Bearer ` → 401. */
  it("returns 401 on whitespace-only token", () => {
    const mw = buildBearerAuthMiddleware();
    const captured: CapturedResponse = {};
    const req = makeReq({ authorization: "Bearer    " });
    const res = makeRes(captured);
    const next = vi.fn() as NextFunction;

    mw(req, res, next);

    expect(next).not.toHaveBeenCalled();
    expect(captured.status).toBe(401);
  });

  /** Spec §6.3: missing Authorization header → 401. */
  it("returns 401 + -32001 when Authorization header missing", () => {
    const mw = buildBearerAuthMiddleware();
    const captured: CapturedResponse = {};
    const req = makeReq({});
    const res = makeRes(captured);
    const next = vi.fn() as NextFunction;

    mw(req, res, next);

    expect(next).not.toHaveBeenCalled();
    expect(captured.status).toBe(401);
    const body = JSON.parse(captured.body ?? "{}");
    expect(body.error.code).toBe(-32001);
  });

  /** Spec §6.3: wrong scheme (Basic) → 401. */
  it("returns 401 on non-Bearer scheme (Basic)", () => {
    const mw = buildBearerAuthMiddleware();
    const captured: CapturedResponse = {};
    const req = makeReq({ authorization: "Basic dXNlcjpwYXNz" });
    const res = makeRes(captured);
    const next = vi.fn() as NextFunction;

    mw(req, res, next);

    expect(next).not.toHaveBeenCalled();
    expect(captured.status).toBe(401);
    const body = JSON.parse(captured.body ?? "{}");
    expect(body.error.code).toBe(-32001);
  });

  /** Case-insensitive scheme match: "bearer xyz" (lowercase) is accepted. */
  it("accepts case-insensitive 'bearer ' scheme prefix", () => {
    const mw = buildBearerAuthMiddleware();
    const captured: CapturedResponse = {};
    const req = makeReq({ authorization: "bearer abc" });
    const res = makeRes(captured);
    const next = vi.fn() as NextFunction;

    mw(req, res, next);

    expect(next).toHaveBeenCalledTimes(1);
  });
});
