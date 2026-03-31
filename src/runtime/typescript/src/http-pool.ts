/**
 * Module-level HTTP connection pool using undici Agents.
 *
 * Provides pooled dispatchers for HTTP and HTTPS (mTLS) endpoints,
 * replacing the per-call Agent creation that caused connection overhead.
 */

import { Agent } from "undici";
import { getTlsOptions } from "./tls-config.js";

let httpAgent: Agent | null = null;
let httpsAgent: Agent | null = null;

const POOL_CONFIG = {
  keepAliveTimeout: 30_000,
  keepAliveMaxTimeout: 90_000,
  connections: 100,
  pipelining: 1,
};

function getHttpAgent(): Agent {
  if (!httpAgent) {
    httpAgent = new Agent(POOL_CONFIG);
  }
  return httpAgent;
}

function getHttpsAgent(): Agent | null {
  if (!httpsAgent) {
    const tlsOpts = getTlsOptions();
    if (tlsOpts) {
      httpsAgent = new Agent({ ...POOL_CONFIG, connect: tlsOpts });
    }
  }
  return httpsAgent;
}

/**
 * Get a pooled dispatcher for the given URL.
 *
 * Returns an undici Agent with connection pooling:
 * - HTTP endpoints: plain Agent with keep-alive
 * - HTTPS endpoints: Agent with mTLS options (if configured)
 * - Returns undefined if HTTPS but no TLS configured
 */
export function getDispatcher(url: string): Agent | undefined {
  if (url.startsWith("https://")) {
    return getHttpsAgent() ?? undefined;
  }
  return getHttpAgent();
}

/**
 * Close all pooled HTTP agents. Call during application shutdown.
 */
export function closeHttpPool(): void {
  httpAgent?.close();
  httpAgent = null;
  httpsAgent?.close();
  httpsAgent = null;
}
