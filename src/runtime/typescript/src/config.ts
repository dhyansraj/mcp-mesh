/**
 * Configuration utilities for MCP Mesh agents.
 *
 * All configuration resolution is delegated to Rust core for consistency
 * across all language SDKs. Priority: ENV > config > defaults
 *
 * Defaults are also sourced from Rust core to ensure single source of truth.
 */

import { randomBytes } from "crypto";
import { createServer } from "net";
import type { AgentConfig, ResolvedAgentConfig } from "./types.js";
import {
  resolveConfig as rustResolveConfig,
  resolveConfigInt,
  getDefault,
} from "@mcpmesh/core";

/**
 * Hard cap on the exponential backoff between `nextEvent()` retries in
 * the mesh event loops (MeshAgent, ApiRuntime, MeshExpress).
 */
export const NEXT_EVENT_BACKOFF_CAP_MS = 5_000;

/**
 * Consecutive `nextEvent()` failure ceiling for the mesh event loops.
 *
 * The backoff ramps 100ms → 3.2s over the first 6 failures (~6.3s of
 * sleep), then sits at the 5s cap; terminating on failure #18 means
 * 11 more sleeps at the cap (~55s), so the loop tolerates roughly
 * 60 seconds of CONTINUOUS failure before giving up. A permanently
 * broken handle must not retry forever — the ref'd backoff timers
 * would keep an otherwise-finished process alive indefinitely.
 */
export const MAX_CONSECUTIVE_NEXT_EVENT_FAILURES = 18;

/**
 * Find an available port by binding to port 0 and getting the OS-assigned port.
 * This is used when port=0 is specified to auto-assign a port.
 *
 * `host` must be the host the caller will actually bind — a port that is
 * free on loopback is not necessarily bindable on `0.0.0.0` (issue #1194).
 */
export async function findAvailablePort(
  host: string = "127.0.0.1"
): Promise<number> {
  return new Promise((resolve, reject) => {
    const server = createServer();
    server.listen(0, host, () => {
      const address = server.address();
      if (address && typeof address === "object") {
        const port = address.port;
        server.close(() => resolve(port));
      } else {
        server.close(() => reject(new Error("Failed to get server address")));
      }
    });
    server.on("error", reject);
  });
}

/**
 * Check whether a TCP port can be bound on the given host.
 *
 * Issue #1194: used to surface bind conflicts BEFORE the HTTP server and
 * the registry heartbeat start, so a configured-but-unbindable port never
 * reaches registration (phantom endpoint).
 *
 * Resolves `false` ONLY for a genuine address-in-use conflict
 * (`EADDRINUSE`) — the one condition the auto-assign fallback can adapt
 * to. Any other bind failure (`EACCES` privileged port, `EADDRNOTAVAIL` /
 * host misconfiguration, ...) REJECTS with the underlying error: falling
 * back there would mask a real problem behind a misleading "port in use"
 * warning, and the real server's own bind would hit the same error anyway.
 */
export async function isPortBindable(
  port: number,
  host: string
): Promise<boolean> {
  return new Promise((resolve, reject) => {
    const server = createServer();
    server.once("error", (err: NodeJS.ErrnoException) => {
      if (err.code === "EADDRINUSE") {
        resolve(false);
      } else {
        reject(err);
      }
    });
    server.listen(port, host, () => {
      server.close(() => resolve(true));
    });
  });
}

/**
 * Resolve the port the HTTP server should bind (issue #1194: adapt, don't crash).
 *
 * - `configuredPort === 0`: auto-assign via the OS (existing port-0 path).
 * - configured port bindable: use it as-is.
 * - configured port in use (`EADDRINUSE`): fall back to an OS-assigned port
 *   and report `fellBack: true` so the caller can log a prominent warning.
 *   The caller MUST propagate the returned port into its config before
 *   starting the heartbeat — the registry must only ever see the
 *   actually-bound port.
 * - any other bind failure (`EACCES`, host errors, ...): the probe's
 *   rejection propagates — adapt only to genuine conflicts, surface
 *   everything else loudly.
 *
 * Every probe — including the auto-assign and fallback paths — binds on
 * `host`, the host the server will actually bind. Probing loopback for a
 * server that binds `0.0.0.0` could hand back a port owned by another
 * process on a non-loopback interface.
 */
export async function resolveBindPort(
  configuredPort: number,
  host: string
): Promise<{ port: number; fellBack: boolean }> {
  if (configuredPort === 0) {
    return { port: await findAvailablePort(host), fellBack: false };
  }
  if (await isPortBindable(configuredPort, host)) {
    return { port: configuredPort, fellBack: false };
  }
  return { port: await findAvailablePort(host), fellBack: true };
}

/**
 * Resolve the startup bind port and emit the canonical conflict warning.
 *
 * Shared by `MeshAgent._autoStart()` and `MeshExpress.start()` so the
 * resolve-and-warn behavior (and the warning text) cannot drift between
 * the two entry points. The caller MUST write the returned port back into
 * the config its heartbeat reads BEFORE starting tracing/server/heartbeat
 * — registration must always carry the ACTUAL bound port (issue #1194).
 *
 * The PORT CONFLICT warning is emitted only for a genuine `EADDRINUSE`
 * fallback; non-conflict bind failures (`EACCES`, host errors, ...)
 * propagate to the caller as rejections instead of being mislabeled as
 * conflicts.
 */
export async function resolveStartupBindPort(
  configuredPort: number,
  label: string
): Promise<number> {
  const bindHost = process.env.HOST ?? "0.0.0.0";
  const resolved = await resolveBindPort(configuredPort, bindHost);
  if (resolved.fellBack) {
    console.warn(
      `PORT CONFLICT: configured HTTP port ${configuredPort} on ${bindHost} ` +
        `is already in use. Falling back to auto-assigned port ${resolved.port} — ` +
        `the registry will be given the ACTUAL bound port. Another process ` +
        `likely owns port ${configuredPort}; fix the port assignment to ` +
        `silence this warning.`
    );
  } else if (resolved.port !== configuredPort) {
    console.log(`Auto-assigned port ${resolved.port} for ${label}`);
  }
  return resolved.port;
}

// TypeScript-specific defaults (not in Rust core)
const TS_DEFAULTS = {
  version: "1.0.0",
  description: "",
} as const;

/**
 * Generate a short UUID suffix (8 hex chars) for agent IDs.
 */
export function generateAgentIdSuffix(): string {
  return randomBytes(4).toString("hex");
}

/**
 * Resolve configuration with environment variable precedence via Rust core.
 *
 * All resolution is delegated to Rust core to ensure consistent behavior
 * across Python and TypeScript SDKs.
 *
 * Priority (handled by Rust): ENV > config > defaults
 *
 * Environment variables:
 * - MCP_MESH_AGENT_NAME: Override agent name
 * - MCP_MESH_HTTP_HOST: Override host (auto-detected if not set)
 * - MCP_MESH_HTTP_PORT: Override port
 * - MCP_MESH_NAMESPACE: Override namespace
 * - MCP_MESH_REGISTRY_URL: Override registry URL
 * - MCP_MESH_HEALTH_INTERVAL: Override heartbeat interval
 */
export function resolveConfig(config: AgentConfig): ResolvedAgentConfig {
  // All config resolution via Rust core - ensures consistent ENV > param > default
  const resolvedName = rustResolveConfig("agent_name", config.name);
  const resolvedPort = resolveConfigInt("http_port", config.httpPort) ?? config.httpPort;
  const resolvedHost = rustResolveConfig("http_host", config.httpHost ?? null);
  const resolvedNamespace = rustResolveConfig(
    "namespace",
    config.namespace ?? null
  );
  // Registry URL only from env var MCP_MESH_REGISTRY_URL, default: http://localhost:8000
  const resolvedRegistryUrl = rustResolveConfig("registry_url", null);

  // Get heartbeat interval with fallback to Rust core default
  const healthIntervalDefault = parseInt(getDefault("health_interval") ?? "5", 10);
  const resolvedHeartbeatInterval =
    resolveConfigInt("health_interval", config.heartbeatInterval ?? null) ??
    healthIntervalDefault;

  return {
    name: resolvedName,
    version: config.version ?? TS_DEFAULTS.version,
    description: config.description ?? TS_DEFAULTS.description,
    httpPort: resolvedPort,
    httpHost: resolvedHost,
    namespace: resolvedNamespace,
    registryUrl: resolvedRegistryUrl,
    heartbeatInterval: resolvedHeartbeatInterval,
  };
}

/**
 * Resolve all media-related configuration keys at once.
 *
 * Environment variables (via Rust core):
 * - MCP_MESH_MEDIA_STORAGE: "local" (default) or "s3"
 * - MCP_MESH_MEDIA_STORAGE_PATH: local base path (default: /tmp/mcp-mesh-media)
 * - MCP_MESH_MEDIA_STORAGE_BUCKET: S3 bucket name
 * - MCP_MESH_MEDIA_STORAGE_ENDPOINT: S3-compatible endpoint URL
 * - MCP_MESH_MEDIA_STORAGE_PREFIX: key prefix inside the store (default: "media/")
 */
export function resolveMediaConfig(): {
  storage: string;
  storagePath: string;
  storageBucket: string | undefined;
  storageEndpoint: string | undefined;
  storagePrefix: string;
} {
  return {
    storage: rustResolveConfig("media_storage", null) || "local",
    storagePath: rustResolveConfig("media_storage_path", null) || "/tmp/mcp-mesh-media",
    storageBucket: rustResolveConfig("media_storage_bucket", null) || undefined,
    storageEndpoint: rustResolveConfig("media_storage_endpoint", null) || undefined,
    storagePrefix: rustResolveConfig("media_storage_prefix", null) || "media/",
  };
}
