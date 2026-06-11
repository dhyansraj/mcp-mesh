/**
 * Tests for issue #1194: port bind conflicts must never produce a phantom
 * registration (registered port != bound port).
 *
 * The runtime resolves the bind port BEFORE the HTTP server and heartbeat
 * start: a configured port that is already in use falls back to an
 * OS-assigned port (adapt, don't crash), and the resolved port is what
 * flows into `config.httpPort` — the field the heartbeat registers.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { createServer, type Server } from "net";
import {
  findAvailablePort,
  isPortBindable,
  resolveBindPort,
  resolveStartupBindPort,
} from "../config.js";

const HOST = "127.0.0.1";

/** Occupy an OS-assigned port with a live listener and return it. */
async function occupyPort(): Promise<{ server: Server; port: number }> {
  return new Promise((resolve, reject) => {
    const server = createServer();
    server.once("error", reject);
    server.listen(0, HOST, () => {
      const address = server.address();
      if (address && typeof address === "object") {
        resolve({ server, port: address.port });
      } else {
        reject(new Error("Failed to get blocker address"));
      }
    });
  });
}

describe("resolveBindPort (issue #1194)", () => {
  let blocker: Server | null = null;
  let blockedPort = 0;

  beforeEach(async () => {
    const occupied = await occupyPort();
    blocker = occupied.server;
    blockedPort = occupied.port;
  });

  afterEach(async () => {
    if (blocker) {
      await new Promise<void>((resolve) => blocker!.close(() => resolve()));
      blocker = null;
    }
  });

  it("returns the configured port unchanged when it is free", async () => {
    // Find a free port, release it, then resolve it.
    const freePort = await findAvailablePort();
    const resolved = await resolveBindPort(freePort, HOST);
    expect(resolved.port).toBe(freePort);
    expect(resolved.fellBack).toBe(false);
  });

  it("falls back to an OS-assigned port when the configured port is in use", async () => {
    const resolved = await resolveBindPort(blockedPort, HOST);
    expect(resolved.fellBack).toBe(true);
    expect(resolved.port).not.toBe(blockedPort);
    expect(resolved.port).toBeGreaterThan(0);
    // The fallback port must itself be bindable (no phantom endpoint).
    expect(await isPortBindable(resolved.port, HOST)).toBe(true);
  });

  it("auto-assigns for configured port 0 without fallback semantics", async () => {
    const resolved = await resolveBindPort(0, HOST);
    expect(resolved.fellBack).toBe(false);
    expect(resolved.port).toBeGreaterThan(0);
  });

  it("isPortBindable reports an occupied port as not bindable", async () => {
    expect(await isPortBindable(blockedPort, HOST)).toBe(false);
  });
});

describe("resolveStartupBindPort (shared agent/express helper)", () => {
  let blocker: Server | null = null;
  let blockedPort = 0;
  let savedHost: string | undefined;

  beforeEach(async () => {
    const occupied = await occupyPort();
    blocker = occupied.server;
    blockedPort = occupied.port;
    // The helper probes the REAL bind host (process.env.HOST, default
    // 0.0.0.0). Pin it to loopback so the blocker and the probe agree.
    savedHost = process.env.HOST;
    process.env.HOST = HOST;
  });

  afterEach(async () => {
    if (savedHost === undefined) {
      delete process.env.HOST;
    } else {
      process.env.HOST = savedHost;
    }
    if (blocker) {
      await new Promise<void>((resolve) => blocker!.close(() => resolve()));
      blocker = null;
    }
    vi.restoreAllMocks();
  });

  it("returns the configured port silently when it is free", async () => {
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    const freePort = await findAvailablePort(HOST);

    const port = await resolveStartupBindPort(freePort, "agent");

    expect(port).toBe(freePort);
    expect(warnSpy).not.toHaveBeenCalled();
  });

  it("falls back with the canonical PORT CONFLICT warning when the port is in use", async () => {
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});

    const port = await resolveStartupBindPort(blockedPort, "agent");

    expect(port).not.toBe(blockedPort);
    expect(port).toBeGreaterThan(0);
    // The fallback port is probed on the same host the server will bind.
    expect(await isPortBindable(port, HOST)).toBe(true);
    expect(warnSpy).toHaveBeenCalledTimes(1);
    const message = String(warnSpy.mock.calls[0][0]);
    expect(message).toContain("PORT CONFLICT");
    expect(message).toContain(String(blockedPort));
    expect(message).toContain(HOST);
  });

  it("auto-assigns for configured port 0 without a conflict warning", async () => {
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    const logSpy = vi.spyOn(console, "log").mockImplementation(() => {});

    const port = await resolveStartupBindPort(0, "service");

    expect(port).toBeGreaterThan(0);
    expect(warnSpy).not.toHaveBeenCalled();
    expect(logSpy).toHaveBeenCalledWith(
      `Auto-assigned port ${port} for service`
    );
  });
});
