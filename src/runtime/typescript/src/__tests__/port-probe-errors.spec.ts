/**
 * Tests for the bind-probe error policy (PR #1197 review follow-up to
 * issue #1194): only a genuine `EADDRINUSE` conflict may trigger the
 * auto-assign fallback. Any other bind failure (`EACCES` privileged port,
 * host errors, ...) must REJECT so callers surface the real problem
 * instead of a misleading "port in use" warning.
 *
 * `net` is mocked: a real `EACCES` is environment-dependent (root and
 * modern macOS can bind low ports), so the error path is simulated.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { EventEmitter } from "node:events";

const probeControl = vi.hoisted(() => ({
  errorFor: (_port: number): NodeJS.ErrnoException | null => null,
  autoAssignPort: 45678,
}));

vi.mock("net", () => {
  return {
    createServer: () => {
      const server = new EventEmitter() as any;
      let boundPort = 0;
      server.listen = (port: number, _host: string, cb?: () => void) => {
        const err = probeControl.errorFor(port);
        if (err) {
          queueMicrotask(() => server.emit("error", err));
        } else {
          boundPort = port === 0 ? probeControl.autoAssignPort : port;
          queueMicrotask(() => cb?.());
        }
        return server;
      };
      server.close = (cb?: () => void) => {
        cb?.();
        return server;
      };
      server.address = () => ({ port: boundPort });
      return server;
    },
  };
});

import {
  isPortBindable,
  resolveBindPort,
  resolveStartupBindPort,
} from "../config.js";

function errnoError(code: string): NodeJS.ErrnoException {
  const err = new Error(`listen ${code}`) as NodeJS.ErrnoException;
  err.code = code;
  return err;
}

beforeEach(() => {
  probeControl.errorFor = () => null;
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("isPortBindable error policy", () => {
  it("resolves true when the probe bind succeeds", async () => {
    await expect(isPortBindable(8080, "0.0.0.0")).resolves.toBe(true);
  });

  it("resolves false ONLY for EADDRINUSE", async () => {
    probeControl.errorFor = () => errnoError("EADDRINUSE");
    await expect(isPortBindable(8080, "0.0.0.0")).resolves.toBe(false);
  });

  it("rejects with the underlying error for EACCES", async () => {
    probeControl.errorFor = () => errnoError("EACCES");
    await expect(isPortBindable(80, "0.0.0.0")).rejects.toMatchObject({
      code: "EACCES",
    });
  });

  it("rejects with the underlying error for host failures", async () => {
    probeControl.errorFor = () => errnoError("EADDRNOTAVAIL");
    await expect(isPortBindable(8080, "203.0.113.1")).rejects.toMatchObject({
      code: "EADDRNOTAVAIL",
    });
  });
});

describe("resolveBindPort error policy", () => {
  it("falls back to an OS-assigned port for a genuine EADDRINUSE", async () => {
    // Conflict on the configured port; the port-0 fallback bind succeeds.
    probeControl.errorFor = (port) =>
      port === 8080 ? errnoError("EADDRINUSE") : null;

    const resolved = await resolveBindPort(8080, "0.0.0.0");

    expect(resolved.fellBack).toBe(true);
    expect(resolved.port).toBe(probeControl.autoAssignPort);
  });

  it("propagates EACCES instead of silently falling back", async () => {
    probeControl.errorFor = () => errnoError("EACCES");

    await expect(resolveBindPort(80, "0.0.0.0")).rejects.toMatchObject({
      code: "EACCES",
    });
  });
});

describe("resolveStartupBindPort error policy", () => {
  it("surfaces non-conflict bind failures without a PORT CONFLICT warning", async () => {
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    probeControl.errorFor = () => errnoError("EACCES");

    await expect(resolveStartupBindPort(80, "agent")).rejects.toMatchObject({
      code: "EACCES",
    });
    expect(warnSpy).not.toHaveBeenCalled();
  });
});
