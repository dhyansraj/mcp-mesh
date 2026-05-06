/**
 * Cancel-route registration visibility tests (W5 — PR review finding).
 *
 * Cancel-mid-flight is a primary control-plane signal for long-running
 * jobs. Before the fix, registration failures landed at `console.warn`
 * — operators who only watched `error`-level logs would never see the
 * regression and the agent would silently degrade to lease-expiry
 * cancellation.
 *
 * This file verifies the escalation:
 *   - failures land at `console.error`;
 *   - the message includes the underlying reason so the failure mode
 *     is debuggable from logs alone.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import type { FastMCP } from "fastmcp";
import { registerCancelRoute } from "../jobs-cancel-route.js";

describe("registerCancelRoute — visibility", () => {
  let errorSpy: ReturnType<typeof vi.spyOn>;
  let warnSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
  });
  afterEach(() => {
    errorSpy.mockRestore();
    warnSpy.mockRestore();
  });

  it("logs at console.error (not warn) when getApp() throws, including the reason", () => {
    const stubServer = {
      getApp: () => {
        throw new Error("FastMCP server not started");
      },
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
    } as unknown as FastMCP;

    const ok = registerCancelRoute(stubServer);
    expect(ok).toBe(false);

    // Escalated to error, NOT warn.
    expect(errorSpy).toHaveBeenCalledOnce();
    expect(warnSpy).not.toHaveBeenCalled();

    // Reason is included so operators can debug from logs alone.
    const msg = errorSpy.mock.calls[0][0] as string;
    expect(msg).toContain("cancel route NOT registered");
    expect(msg).toContain("FastMCP server not started");
  });

  it("logs at console.error when getApp() returns null", () => {
    const stubServer = {
      getApp: () => null,
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
    } as unknown as FastMCP;

    const ok = registerCancelRoute(stubServer);
    expect(ok).toBe(false);

    expect(errorSpy).toHaveBeenCalledOnce();
    expect(warnSpy).not.toHaveBeenCalled();
    const msg = errorSpy.mock.calls[0][0] as string;
    expect(msg).toContain("cancel route NOT registered");
    expect(msg).toContain("returned null");
  });

  it("logs at console.error when app.post() raises, including the reason", () => {
    const stubServer = {
      getApp: () => ({
        post: () => {
          throw new Error("hono internal: route conflict");
        },
      }),
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
    } as unknown as FastMCP;

    const ok = registerCancelRoute(stubServer);
    expect(ok).toBe(false);

    expect(errorSpy).toHaveBeenCalledOnce();
    expect(warnSpy).not.toHaveBeenCalled();
    const msg = errorSpy.mock.calls[0][0] as string;
    expect(msg).toContain("cancel route NOT registered");
    expect(msg).toContain("hono internal: route conflict");
  });

  it("returns true and does not log anything when registration succeeds", () => {
    const postSpy = vi.fn();
    const stubServer = {
      getApp: () => ({ post: postSpy }),
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
    } as unknown as FastMCP;

    const ok = registerCancelRoute(stubServer);
    expect(ok).toBe(true);
    expect(postSpy).toHaveBeenCalledWith(
      "/jobs/:job_id/cancel",
      expect.any(Function),
    );
    expect(errorSpy).not.toHaveBeenCalled();
    expect(warnSpy).not.toHaveBeenCalled();
  });
});
