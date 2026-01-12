/**
 * Debug logging utilities for MCP Mesh SDK.
 *
 * Debug output is controlled by the MESH_DEBUG environment variable:
 * - MESH_DEBUG=1 or MESH_DEBUG=true - Enable all debug output
 * - MESH_DEBUG=llm - Enable only LLM-related debug output
 * - MESH_DEBUG=llm,sse - Enable multiple categories (comma-separated)
 *
 * @example
 * ```bash
 * # Enable all debug output
 * MESH_DEBUG=1 node my-agent.js
 *
 * # Enable only LLM debug output
 * MESH_DEBUG=llm node my-agent.js
 * ```
 */

type DebugCategory = "llm" | "sse" | "template" | "agent" | "registry";

/**
 * Check if debug logging is enabled for a category.
 */
function isDebugEnabled(category: DebugCategory): boolean {
  const debugEnv = process.env.MESH_DEBUG;

  if (!debugEnv) {
    return false;
  }

  // Enable all if "1", "true", or "*"
  if (debugEnv === "1" || debugEnv === "true" || debugEnv === "*") {
    return true;
  }

  // Check for specific category
  const categories = debugEnv.split(",").map((c) => c.trim().toLowerCase());
  return categories.includes(category) || categories.includes("all");
}

/**
 * Create a debug logger for a specific category.
 *
 * @param category - Debug category (e.g., "llm", "sse", "template")
 * @returns Debug function that only logs when category is enabled
 *
 * @example
 * ```typescript
 * const debug = createDebug("llm");
 * debug("Executing tool", { name: "add" });
 * // Only logs if MESH_DEBUG=llm or MESH_DEBUG=1
 * ```
 */
export function createDebug(category: DebugCategory): (...args: unknown[]) => void {
  const prefix = `[mesh.${category}]`;

  return (...args: unknown[]) => {
    if (isDebugEnabled(category)) {
      console.log(prefix, ...args);
    }
  };
}

/**
 * Pre-configured debug loggers for common categories.
 */
export const debug = {
  llm: createDebug("llm"),
  sse: createDebug("sse"),
  template: createDebug("template"),
  agent: createDebug("agent"),
  registry: createDebug("registry"),
};

/**
 * Check if any debug logging is enabled.
 */
export function isAnyDebugEnabled(): boolean {
  const debugEnv = process.env.MESH_DEBUG;
  return !!debugEnv && debugEnv !== "0" && debugEnv !== "false";
}
