/**
 * TLS configuration resolved from Rust core (cached).
 */

import { readFileSync } from "node:fs";

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
    const { getTlsConfig } = require("@mcpmesh/core");
    const raw = JSON.parse(getTlsConfig());
    cached = {
      enabled: raw.enabled,
      mode: raw.mode,
      certPath: raw.cert_path ?? null,
      keyPath: raw.key_path ?? null,
      caPath: raw.ca_path ?? null,
    };
  } catch {
    cached = { enabled: false, mode: "off", certPath: null, keyPath: null, caPath: null };
  }

  if (cached.enabled) {
    console.log(`TLS mode: ${cached.mode}`);
  }

  return cached;
}

/**
 * Read TLS files and return options for https.createServer or undici.Agent.
 * Returns null when TLS is disabled or cert paths are missing.
 */
export function getTlsOptions(): { cert: Buffer; key: Buffer; ca?: Buffer } | null {
  const config = getTlsConfigCached();
  if (!config.enabled || !config.certPath || !config.keyPath) return null;

  const opts: { cert: Buffer; key: Buffer; ca?: Buffer } = {
    cert: readFileSync(config.certPath),
    key: readFileSync(config.keyPath),
  };
  if (config.caPath) {
    opts.ca = readFileSync(config.caPath);
  }
  return opts;
}
