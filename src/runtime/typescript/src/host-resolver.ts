/**
 * Host resolution utilities for MCP Mesh agents.
 *
 * Provides auto-detection of external IP addresses for registry advertisement.
 */

import { networkInterfaces } from "os";

/**
 * Auto-detect external IP from network interfaces.
 * Returns the first non-internal IPv4 address found.
 */
export function autoDetectExternalIp(): string {
  try {
    const nets = networkInterfaces();
    for (const name of Object.keys(nets)) {
      const netList = nets[name];
      if (!netList) continue;

      for (const net of netList) {
        // Skip internal (loopback) and IPv6 addresses
        if (!net.internal && net.family === "IPv4") {
          return net.address;
        }
      }
    }
  } catch {
    // Fall through to localhost
  }
  return "localhost";
}

/**
 * Resolve external host for registry advertisement.
 * Priority: MCP_MESH_HTTP_HOST env > config.host > auto-detect
 */
export function resolveExternalHost(configHost?: string): string {
  // Priority 1: Environment variable
  const envHost = process.env.MCP_MESH_HTTP_HOST;
  if (envHost) {
    return envHost;
  }

  // Priority 2: Config value (if not "localhost")
  if (configHost && configHost !== "localhost") {
    return configHost;
  }

  // Priority 3: Auto-detect
  return autoDetectExternalIp();
}
