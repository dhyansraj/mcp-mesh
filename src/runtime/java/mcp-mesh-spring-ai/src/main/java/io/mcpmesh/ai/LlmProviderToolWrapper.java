package io.mcpmesh.ai;

import io.mcpmesh.spring.McpToolHandler;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Wrapper for LLM provider tool that handles MCP calls.
 *
 * <p>This wrapper adapts the {@link MeshLlmProviderProcessor} to the interface
 * expected by the MCP server configuration.
 *
 * <p>When an MCP call comes in for the LLM tool, this wrapper delegates to
 * {@link MeshLlmProviderProcessor#handleGenerateRequest(String, Map)}.
 *
 * @see McpToolHandler
 */
public class LlmProviderToolWrapper implements McpToolHandler {

    private static final Logger log = LoggerFactory.getLogger(LlmProviderToolWrapper.class);

    private final String funcId;
    private final String capability;
    private final String description;
    private final String version;
    private final List<String> tags;
    private final MeshLlmProviderProcessor processor;

    /**
     * Create a wrapper for an LLM provider.
     *
     * @param capability  The capability name (e.g., "llm")
     * @param description Description for the tool
     * @param version     Version string
     * @param tags        Tags for filtering
     * @param processor   The processor that handles requests
     */
    public LlmProviderToolWrapper(
            String capability,
            String description,
            String version,
            List<String> tags,
            MeshLlmProviderProcessor processor) {

        this.funcId = "llm_provider:" + capability;
        this.capability = capability;
        this.description = description;
        this.version = version;
        this.tags = tags;
        this.processor = processor;
    }

    /**
     * Invoke the LLM provider with MCP arguments.
     *
     * @param mcpArgs Arguments from MCP call
     * @return The response map
     * @throws Exception if invocation fails
     */
    public Object invoke(Map<String, Object> mcpArgs) throws Exception {
        log.debug("LLM provider invoked with args: {}", mcpArgs);

        try {
            return processor.handleGenerateRequest(capability, mcpArgs);
        } catch (Exception e) {
            log.error("LLM provider call failed: {}", e.getMessage(), e);
            throw e;
        }
    }

    // =========================================================================
    // Interface methods matching MeshToolWrapper (for MeshMcpServerConfiguration)
    // =========================================================================

    public String getFuncId() {
        return funcId;
    }

    public String getCapability() {
        return capability;
    }

    /**
     * Get the method name (tool name for MCP).
     */
    public String getMethodName() {
        return MeshLlmProviderProcessor.LLM_TOOL_NAME;
    }

    public String getDescription() {
        return description;
    }

    public Map<String, Object> getInputSchema() {
        Map<String, Object> schema = new LinkedHashMap<>();
        schema.put("type", "object");

        Map<String, Object> properties = new LinkedHashMap<>();

        // messages parameter (required)
        Map<String, Object> messagesSchema = new LinkedHashMap<>();
        messagesSchema.put("type", "array");
        messagesSchema.put("description", "Conversation messages");
        Map<String, Object> messageItem = new LinkedHashMap<>();
        messageItem.put("type", "object");
        Map<String, Object> messageProps = new LinkedHashMap<>();
        messageProps.put("role", Map.of("type", "string", "enum", List.of("system", "user", "assistant", "tool")));
        messageProps.put("content", Map.of("type", "string"));
        messageItem.put("properties", messageProps);
        messageItem.put("required", List.of("role", "content"));
        messagesSchema.put("items", messageItem);
        properties.put("messages", messagesSchema);

        // tools parameter (optional)
        Map<String, Object> toolsSchema = new LinkedHashMap<>();
        toolsSchema.put("type", "array");
        toolsSchema.put("description", "Available tools (optional)");
        properties.put("tools", toolsSchema);

        // max_tokens parameter
        properties.put("max_tokens", Map.of("type", "integer", "default", 4096, "description", "Maximum tokens to generate"));

        // temperature parameter
        properties.put("temperature", Map.of("type", "number", "default", 0.7, "description", "Sampling temperature"));

        schema.put("properties", properties);
        schema.put("required", List.of("messages"));

        return schema;
    }

    /**
     * LLM providers have no dependencies.
     */
    public int getDependencyCount() {
        return 0;
    }

    /**
     * LLM providers don't have LLM agents (they ARE the provider).
     */
    public int getLlmAgentCount() {
        return 0;
    }
}
