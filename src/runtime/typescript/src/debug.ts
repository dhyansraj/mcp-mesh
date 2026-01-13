/**
 * Debug logging utilities for MCP Mesh SDK.
 *
 * Debug output is controlled by standard MCP Mesh environment variables:
 * - MCP_MESH_LOG_LEVEL=DEBUG - Enable debug output (DEBUG, INFO, WARNING, ERROR, CRITICAL)
 * - MCP_MESH_DEBUG_MODE=true - Force DEBUG level
 *
 * @example
 * ```bash
 * # Enable debug output
 * MCP_MESH_LOG_LEVEL=DEBUG node my-agent.js
 *
 * # Or use debug mode
 * MCP_MESH_DEBUG_MODE=true node my-agent.js
 * ```
 */

type DebugCategory = "llm" | "llm-provider" | "sse" | "template" | "agent" | "registry" | "provider-handler-registry" | "claude-handler" | "openai-handler";

/** Log levels in order of severity */
const LOG_LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] as const;
type LogLevel = (typeof LOG_LEVELS)[number];

/**
 * Get the current log level from environment.
 */
function getLogLevel(): LogLevel {
  // MCP_MESH_DEBUG_MODE forces DEBUG level
  const debugMode = process.env.MCP_MESH_DEBUG_MODE;
  if (debugMode === "true" || debugMode === "1") {
    return "DEBUG";
  }

  // MCP_MESH_LOG_LEVEL sets the level
  const level = process.env.MCP_MESH_LOG_LEVEL?.toUpperCase() as LogLevel | undefined;
  if (level && LOG_LEVELS.includes(level)) {
    return level;
  }

  // Default to INFO
  return "INFO";
}

/**
 * Check if a log level is enabled.
 */
function isLevelEnabled(level: LogLevel): boolean {
  const currentLevel = getLogLevel();
  return LOG_LEVELS.indexOf(level) >= LOG_LEVELS.indexOf(currentLevel);
}

/**
 * Check if debug logging is enabled.
 */
function isDebugEnabled(_category: DebugCategory): boolean {
  return isLevelEnabled("DEBUG");
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
 * // Only logs if MCP_MESH_LOG_LEVEL=DEBUG or MCP_MESH_DEBUG_MODE=true
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
  return isLevelEnabled("DEBUG");
}
