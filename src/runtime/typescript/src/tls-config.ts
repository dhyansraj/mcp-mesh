/**
 * TLS configuration resolved from Rust core (cached).
 */

import { readFileSync } from "node:fs";
import { createRequire } from "node:module";

export interface TlsConfig {
  enabled: boolean;
  mode: string;
  certPath: string | null;
  keyPath: string | null;
  caPath: string | null;
}

let cached: TlsConfig | null = null;

export function getTlsConfigCached(): TlsConfig {
  if (cached) return cached;

  try {
    const require = createRequire(import.meta.url);
    const { getTlsConfig } = require("@mcpmesh/core");
    const raw = JSON.parse(getTlsConfig());
    cached = {
      enabled: raw.enabled,
      mode: raw.mode,
      certPath: raw.cert_path ?? null,
      keyPath: raw.key_path ?? null,
      caPath: raw.ca_path ?? null,
    };
  } catch (err: unknown) {
    // Only swallow module-not-found (native module not available).
    // Other errors (JSON parse, FFI crash) must propagate.
    if (err instanceof Error && err.message.includes("Cannot find module")) {
      cached = { enabled: false, mode: "off", certPath: null, keyPath: null, caPath: null };
    } else {
      throw err;
    }
  }

  if (cached.enabled) {
    console.log(`TLS mode: ${cached.mode}`);
  }

  return cached;
}

/**
 * Resolve TLS credentials early (fetches from Vault if configured).
 * Must be called before getTlsConfigCached()/getTlsOptions() when using non-file providers.
 * Writes secure temp files and caches the result globally in Rust core.
 */
export function prepareTls(agentName: string): void {
  try {
    const require = createRequire(import.meta.url);
    const { prepareTls: nativePrepareTls } = require("@mcpmesh/core");
    const raw = JSON.parse(nativePrepareTls(agentName));
    // Update the local cache too so getTlsConfigCached() returns the resolved config
    cached = {
      enabled: raw.enabled,
      mode: raw.mode,
      certPath: raw.cert_path ?? null,
      keyPath: raw.key_path ?? null,
      caPath: raw.ca_path ?? null,
    };
    if (cached.enabled) {
      console.log(`TLS prepared: mode=${cached.mode} provider=${raw.provider ?? 'file'} cert=${cached.certPath}`);
    }
  } catch (err: unknown) {
    if (err instanceof Error && err.message.includes("Cannot find module")) {
      // Native module not available -- no-op
    } else {
      console.warn(`TLS preparation failed: ${err}`);
    }
  }
}

/**
 * Clean up temporary TLS credential files. Call during agent shutdown.
 */
export function cleanupTls(): void {
  try {
    const require = createRequire(import.meta.url);
    const { cleanupTls: nativeCleanupTls } = require("@mcpmesh/core");
    nativeCleanupTls();
    cached = null;
  } catch {
    // Ignore
  }
}

/**
 * Read TLS files and return options for https.createServer or undici.Agent.
 * Returns null when TLS is disabled. Throws when TLS is enabled but paths are missing.
 */
export function getTlsOptions(): { cert: Buffer; key: Buffer; ca?: Buffer } | null {
  const config = getTlsConfigCached();
  if (!config.enabled) return null;

  if (!config.certPath || !config.keyPath) {
    throw new Error(
      "TLS enabled but certPath or keyPath is missing — check MCP_MESH_TLS_CERT and MCP_MESH_TLS_KEY"
    );
  }

  const opts: { cert: Buffer; key: Buffer; ca?: Buffer } = {
    cert: readFileSync(config.certPath),
    key: readFileSync(config.keyPath),
  };
  if (config.caPath) {
    opts.ca = readFileSync(config.caPath);
  }
  return opts;
}
