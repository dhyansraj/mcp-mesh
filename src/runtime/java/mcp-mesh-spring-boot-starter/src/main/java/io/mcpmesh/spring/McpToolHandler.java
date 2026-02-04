package io.mcpmesh.spring;

import java.util.Map;

/**
 * Interface for handlers that can process MCP tool calls.
 *
 * <p>Implemented by:
 * <ul>
 *   <li>{@link MeshToolWrapper} - For @MeshTool annotated methods</li>
 *   <li>LlmProviderToolWrapper (in spring-ai module) - For @MeshLlmProvider annotated classes</li>
 * </ul>
 *
 * <p>This interface defines the contract used by {@link MeshMcpServerConfiguration}
 * to register and invoke tools via the MCP protocol.
 */
public interface McpToolHandler {

    /**
     * Get the unique function identifier.
     *
     * @return Function ID (e.g., "com.example.Calc.add" or "llm_provider:llm")
     */
    String getFuncId();

    /**
     * Get the capability name for mesh discovery.
     *
     * @return Capability name
     */
    String getCapability();

    /**
     * Get the method/tool name for MCP registration.
     *
     * @return Tool name (used in MCP tool listing)
     */
    String getMethodName();

    /**
     * Get the tool description.
     *
     * @return Human-readable description
     */
    String getDescription();

    /**
     * Get the input schema for the tool.
     *
     * @return JSON Schema as a Map
     */
    Map<String, Object> getInputSchema();

    /**
     * Invoke the tool with MCP arguments.
     *
     * @param mcpArgs Arguments from MCP call (Map of parameter name → value)
     * @return The result object (will be serialized to JSON)
     * @throws Exception if invocation fails
     */
    Object invoke(Map<String, Object> mcpArgs) throws Exception;

    /**
     * Get the number of mesh tool dependencies.
     *
     * @return Dependency count (0 for LLM providers)
     */
    int getDependencyCount();

    /**
     * Get the number of LLM agent dependencies.
     *
     * @return LLM agent count (0 for LLM providers)
     */
    int getLlmAgentCount();
}
