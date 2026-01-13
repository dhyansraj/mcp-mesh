/**
 * mesh.llm() - LLM-powered tool wrapper for MCP Mesh.
 *
 * Creates a tool that uses an LLM with agentic capabilities,
 * including access to other mesh tools and structured output.
 *
 * @example
 * ```typescript
 * import { FastMCP } from "fastmcp";
 * import { mesh } from "@mcpmesh/sdk";
 * import { z } from "zod";
 *
 * const server = new FastMCP({ name: "Smart Assistant", version: "1.0.0" });
 *
 * const AssistResponse = z.object({
 *   answer: z.string(),
 *   confidence: z.number(),
 * });
 *
 * server.addTool(mesh.llm({
 *   name: "assist",
 *   capability: "smart_assistant",
 *   provider: "claude",
 *   systemPrompt: "file://prompts/assistant.hbs",
 *   filter: [{ capability: "calculator" }],
 *   returns: AssistResponse,
 *   parameters: z.object({ message: z.string() }),
 *   execute: async ({ message }, { llm }) => llm(message),
 * }));
 *
 * const agent = mesh(server, { name: "smart-assistant", port: 9003 });
 * ```
 */

import type { z, ZodType } from "zod";
import { zodToJsonSchema } from "zod-to-json-schema";
import type {
  MeshLlmConfig,
  LlmProviderSpec,
  LlmFilterSpec,
  LlmFilterMode,
  LlmAgent,
  LlmToolProxy,
  LlmOutputMode,
} from "./types.js";
import { MeshLlmAgent, createLlmToolProxy } from "./llm-agent.js";
import { debug } from "./debug.js";

/**
 * Registry for LLM tools - stores configuration and resolved dependencies.
 */
export class LlmToolRegistry {
  private static instance: LlmToolRegistry | null = null;

  /** LLM tool configurations by function ID */
  private configs: Map<string, LlmToolConfig> = new Map();

  /** Resolved tools for each LLM function (from llm_tools_updated events) */
  private resolvedTools: Map<string, LlmToolProxy[]> = new Map();

  /** Resolved providers for each LLM function (from llm_provider_available events) */
  private resolvedProviders: Map<string, ResolvedProvider> = new Map();

  private constructor() {}

  static getInstance(): LlmToolRegistry {
    if (!LlmToolRegistry.instance) {
      LlmToolRegistry.instance = new LlmToolRegistry();
    }
    return LlmToolRegistry.instance;
  }

  /**
   * Reset the registry (for testing).
   */
  static reset(): void {
    LlmToolRegistry.instance = null;
  }

  /**
   * Register an LLM tool configuration.
   */
  register(functionId: string, config: LlmToolConfig): void {
    this.configs.set(functionId, config);
  }

  /**
   * Get an LLM tool configuration.
   */
  getConfig(functionId: string): LlmToolConfig | undefined {
    return this.configs.get(functionId);
  }

  /**
   * Get all registered LLM tool configurations.
   */
  getAllConfigs(): Map<string, LlmToolConfig> {
    return new Map(this.configs);
  }

  /**
   * Update resolved tools for an LLM function.
   */
  setResolvedTools(functionId: string, tools: LlmToolProxy[]): void {
    this.resolvedTools.set(functionId, tools);
    debug.llm(`Tools updated for ${functionId}: ${tools.length} tools available`);
  }

  /**
   * Get resolved tools for an LLM function.
   */
  getResolvedTools(functionId: string): LlmToolProxy[] {
    return this.resolvedTools.get(functionId) ?? [];
  }

  /**
   * Update resolved provider for an LLM function.
   */
  setResolvedProvider(functionId: string, provider: ResolvedProvider): void {
    this.resolvedProviders.set(functionId, provider);
    debug.llm(`Provider available for ${functionId}: ${provider.endpoint}`);
  }

  /**
   * Remove resolved provider for an LLM function.
   */
  removeResolvedProvider(functionId: string): void {
    this.resolvedProviders.delete(functionId);
    debug.llm(`Provider unavailable for ${functionId}`);
  }

  /**
   * Get resolved provider for an LLM function.
   */
  getResolvedProvider(functionId: string): ResolvedProvider | undefined {
    return this.resolvedProviders.get(functionId);
  }

  /**
   * Clear all resolved dependencies.
   */
  clearAllResolved(): void {
    this.resolvedTools.clear();
    this.resolvedProviders.clear();
  }
}

/**
 * Internal LLM tool configuration.
 */
export interface LlmToolConfig {
  functionId: string;
  name: string;
  capability: string;
  description: string;
  version: string;
  tags: string[];
  provider: LlmProviderSpec;
  model?: string;
  maxIterations: number;
  systemPrompt?: string;
  contextParam?: string;
  filter?: LlmFilterSpec[];
  filterMode: LlmFilterMode;
  maxTokens?: number;
  temperature?: number;
  topP?: number;
  stop?: string[];
  inputSchema: string;
  returnSchema?: ZodType;
  outputMode?: LlmOutputMode;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  execute: (args: any, context: { llm: LlmAgent<any> }) => Promise<any>;
}

/**
 * Resolved mesh provider info.
 */
export interface ResolvedProvider {
  endpoint: string;
  functionName: string;
  model?: string;
  agentId: string;
}

/**
 * Tool definition returned by mesh.llm() for fastmcp.
 */
export interface FastMcpToolDef {
  name: string;
  description?: string;
  parameters: ZodType;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  execute: (args: any) => Promise<string>;
}

/**
 * Create an LLM-powered tool definition.
 *
 * This function returns a fastmcp-compatible tool definition that can be
 * passed to server.addTool(). The tool will use an LLM with agentic capabilities.
 *
 * @param config - LLM tool configuration
 * @returns fastmcp tool definition
 */
export function llm<
  TParams extends ZodType,
  TReturns extends ZodType | undefined = undefined
>(
  config: MeshLlmConfig<TParams, TReturns>
): FastMcpToolDef & { _meshLlmConfig: LlmToolConfig } {
  const registry = LlmToolRegistry.getInstance();

  // Generate function ID
  const functionId = config.name;

  // Normalize configuration
  const llmConfig: LlmToolConfig = {
    functionId,
    name: config.name,
    capability: config.capability ?? config.name,
    description: config.description ?? "",
    version: config.version ?? "1.0.0",
    tags: config.tags ?? [],
    provider: config.provider,
    model: config.model,
    maxIterations: config.maxIterations ?? 10,
    systemPrompt: config.systemPrompt,
    contextParam: config.contextParam,
    filter: config.filter,
    filterMode: config.filterMode ?? "all",
    maxTokens: config.maxTokens,
    temperature: config.temperature,
    topP: config.topP,
    stop: config.stop,
    inputSchema: JSON.stringify(zodToJsonSchema(config.parameters, { $refStrategy: "none" })),
    returnSchema: config.returns,
    outputMode: config.outputMode ?? "hint",
    execute: config.execute as LlmToolConfig["execute"],
  };

  // Register with LLM tool registry
  registry.register(functionId, llmConfig);

  // Create MeshLlmAgent once (cached for reuse)
  const agent = new MeshLlmAgent({
    functionId,
    provider: llmConfig.provider,
    model: llmConfig.model,
    systemPrompt: llmConfig.systemPrompt,
    contextParam: llmConfig.contextParam,
    maxIterations: llmConfig.maxIterations,
    maxTokens: llmConfig.maxTokens,
    temperature: llmConfig.temperature,
    topP: llmConfig.topP,
    stop: llmConfig.stop,
    returnSchema: llmConfig.returnSchema,
    outputMode: llmConfig.outputMode,
  });

  // Create the execute wrapper
  const wrappedExecute = async (args: z.infer<TParams>): Promise<string> => {
    try {
      debug.llm(`Executing ${functionId} with args:`, JSON.stringify(args));

      // Get resolved tools and provider
      const tools = registry.getResolvedTools(functionId);
      const meshProvider = registry.getResolvedProvider(functionId);
      debug.llm(`Tools: ${tools.length}, Provider:`, meshProvider ? meshProvider.endpoint : "none");

      // Extract template context from args if contextParam is specified
      let templateContext: Record<string, unknown> = {};
      if (llmConfig.contextParam && args && typeof args === "object") {
        const argsObj = args as Record<string, unknown>;
        if (argsObj[llmConfig.contextParam]) {
          templateContext = argsObj[llmConfig.contextParam] as Record<string, unknown>;
        }
      }

      // Create callable LLM agent
      const llmCallable = agent.createCallable({
        tools,
        meshProvider: meshProvider
          ? {
              endpoint: meshProvider.endpoint,
              functionName: meshProvider.functionName,
              model: meshProvider.model,
            }
          : undefined,
        templateContext,
      });

      // Call user's execute handler
      debug.llm(`Calling user execute handler`);
      const result = await llmConfig.execute(args, { llm: llmCallable as LlmAgent<TReturns extends ZodType ? z.infer<TReturns> : string> });
      debug.llm(`Execute completed successfully`);

      // Convert result to string for MCP
      if (typeof result === "string") {
        return result;
      }
      return JSON.stringify(result);
    } catch (error) {
      debug.llm(`Error in ${functionId}:`, error);
      throw error;
    }
  };

  // Return fastmcp-compatible tool definition with mesh metadata
  return {
    name: config.name,
    description: config.description,
    parameters: config.parameters,
    execute: wrappedExecute,
    _meshLlmConfig: llmConfig,
  };
}

/**
 * Build JsLlmAgentSpec for Rust core from LLM tool configs.
 */
export function buildLlmAgentSpecs(): Array<{
  functionId: string;
  provider: string;
  filter?: string;
  filterMode: string;
  maxIterations: number;
}> {
  const registry = LlmToolRegistry.getInstance();
  const specs: Array<{
    functionId: string;
    provider: string;
    filter?: string;
    filterMode: string;
    maxIterations: number;
  }> = [];

  for (const [, config] of registry.getAllConfigs()) {
    // Serialize provider to JSON
    const providerJson =
      typeof config.provider === "string"
        ? JSON.stringify({ direct: config.provider })
        : JSON.stringify(config.provider);

    // Serialize filter to JSON if present
    const filterJson = config.filter ? JSON.stringify(config.filter) : undefined;

    specs.push({
      functionId: config.functionId,
      provider: providerJson,
      filter: filterJson,
      filterMode: config.filterMode,
      maxIterations: config.maxIterations,
    });
  }

  return specs;
}

/**
 * Handle llm_tools_updated event from Rust core.
 */
export function handleLlmToolsUpdated(
  functionId: string,
  tools: Array<{
    functionName: string;
    capability: string;
    endpoint: string;
    agentId: string;
    inputSchema?: string;
  }>
): void {
  const registry = LlmToolRegistry.getInstance();

  // Create tool proxies
  const proxies = tools.map((tool) => createLlmToolProxy(tool));

  // Update registry
  registry.setResolvedTools(functionId, proxies);
}

/**
 * Handle llm_provider_available event from Rust core.
 */
export function handleLlmProviderAvailable(
  functionId: string,
  providerInfo: {
    agentId: string;
    endpoint: string;
    functionName: string;
    model?: string;
  }
): void {
  debug.llm(`Provider available for ${functionId}: ${providerInfo.endpoint}/${providerInfo.functionName}`);
  const registry = LlmToolRegistry.getInstance();

  registry.setResolvedProvider(functionId, {
    endpoint: providerInfo.endpoint,
    functionName: providerInfo.functionName,
    model: providerInfo.model,
    agentId: providerInfo.agentId,
  });
  debug.llm(`Provider stored for ${functionId}`);
}

/**
 * Handle llm_provider_unavailable event from Rust core.
 */
export function handleLlmProviderUnavailable(functionId: string): void {
  const registry = LlmToolRegistry.getInstance();
  registry.removeResolvedProvider(functionId);
}

/**
 * Get LLM tool metadata for JsToolSpec.
 */
export function getLlmToolMetadata(toolName: string): {
  llmFilter?: string;
  llmProvider?: string;
} | null {
  const registry = LlmToolRegistry.getInstance();
  const config = registry.getConfig(toolName);

  if (!config) {
    return null;
  }

  return {
    llmFilter: config.filter ? JSON.stringify(config.filter) : undefined,
    llmProvider:
      typeof config.provider === "string"
        ? config.provider
        : JSON.stringify(config.provider),
  };
}

/**
 * Check if a tool is an LLM tool.
 */
export function isLlmTool(toolDef: unknown): toolDef is FastMcpToolDef & { _meshLlmConfig: LlmToolConfig } {
  return (
    typeof toolDef === "object" &&
    toolDef !== null &&
    "_meshLlmConfig" in toolDef
  );
}
