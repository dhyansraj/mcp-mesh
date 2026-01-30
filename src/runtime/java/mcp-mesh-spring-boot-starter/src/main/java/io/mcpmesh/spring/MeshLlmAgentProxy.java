package io.mcpmesh.spring;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.mcpmesh.core.MeshEvent;
import io.mcpmesh.types.MeshLlmAgent;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.*;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.concurrent.atomic.AtomicReference;

/**
 * Proxy implementation for LLM agents using mesh delegation.
 *
 * <p>Routes LLM requests to remote LLM provider agents discovered via the mesh.
 * Supports agentic loops with tool calling.
 *
 * <h2>Agentic Loop</h2>
 * <pre>
 * 1. Send prompt to remote LLM provider
 * 2. If response contains tool_calls:
 *    a. Execute each tool via mesh
 *    b. Send tool results back to LLM
 *    c. Repeat until no more tool calls or max iterations
 * 3. Return final text response
 * </pre>
 */
public class MeshLlmAgentProxy implements MeshLlmAgent {

    private static final Logger log = LoggerFactory.getLogger(MeshLlmAgentProxy.class);
    private static final ObjectMapper objectMapper = new ObjectMapper();

    private final String functionId;
    private final List<ToolInfo> availableTools = new CopyOnWriteArrayList<>();
    private final AtomicReference<ProviderEndpoint> providerRef = new AtomicReference<>();

    private volatile String systemPrompt = "";
    private volatile int maxIterations = 1;
    private McpHttpClient mcpClient;
    private MeshDependencyInjector dependencyInjector;

    /**
     * Endpoint info for the LLM provider.
     */
    public record ProviderEndpoint(String endpoint, String functionName, String provider) {
        public boolean isAvailable() {
            return endpoint != null && !endpoint.isBlank();
        }
    }

    public MeshLlmAgentProxy(String functionId) {
        this.functionId = functionId;
    }

    /**
     * Configure the proxy with dependencies.
     */
    public void configure(McpHttpClient mcpClient, MeshDependencyInjector dependencyInjector,
                          String systemPrompt, int maxIterations) {
        this.mcpClient = mcpClient;
        this.dependencyInjector = dependencyInjector;
        this.systemPrompt = systemPrompt != null ? systemPrompt : "";
        this.maxIterations = maxIterations > 0 ? maxIterations : 1;
    }

    /**
     * Update the LLM provider endpoint.
     */
    public void updateProvider(String endpoint, String functionName, String provider) {
        log.info("LLM provider updated for {}: {} at {}", functionId, provider, endpoint);
        providerRef.set(new ProviderEndpoint(endpoint, functionName, provider));
    }

    /**
     * Update available tools from mesh events.
     */
    void updateTools(List<MeshEvent.LlmToolInfo> tools) {
        availableTools.clear();
        for (MeshEvent.LlmToolInfo tool : tools) {
            availableTools.add(new ToolInfo(
                tool.getFunctionName(),
                tool.getDescription(),
                tool.getCapability(),
                tool.getAgentId(),
                tool.getInputSchema()
            ));
        }
        log.debug("Updated {} tools for LLM agent {}", availableTools.size(), functionId);
    }

    void markUnavailable() {
        providerRef.set(null);
    }

    @Override
    public String generate(String prompt) {
        ProviderEndpoint provider = providerRef.get();
        if (provider == null || !provider.isAvailable()) {
            throw new IllegalStateException("LLM provider not available for: " + functionId);
        }

        if (mcpClient == null) {
            throw new IllegalStateException("MCP client not configured for LLM agent: " + functionId);
        }

        log.debug("Generating response via mesh delegation to {}", provider.endpoint());

        return executeAgenticLoop(prompt, provider);
    }

    @Override
    public <T> T generate(String prompt, Class<T> responseType) {
        String response = generate(prompt);

        try {
            // Try to parse as JSON and deserialize to target type
            return objectMapper.readValue(response, responseType);
        } catch (JsonProcessingException e) {
            // If not valid JSON, try to extract JSON from the response
            String jsonContent = extractJsonFromResponse(response);
            if (jsonContent != null) {
                try {
                    return objectMapper.readValue(jsonContent, responseType);
                } catch (JsonProcessingException e2) {
                    log.warn("Failed to parse extracted JSON: {}", e2.getMessage());
                }
            }

            throw new RuntimeException("Failed to parse LLM response as " + responseType.getSimpleName(), e);
        }
    }

    @Override
    public CompletableFuture<String> generateAsync(String prompt) {
        return CompletableFuture.supplyAsync(() -> generate(prompt));
    }

    @Override
    public <T> CompletableFuture<T> generateAsync(String prompt, Class<T> responseType) {
        return CompletableFuture.supplyAsync(() -> generate(prompt, responseType));
    }

    @Override
    public List<ToolInfo> getAvailableTools() {
        return new ArrayList<>(availableTools);
    }

    @Override
    public boolean isAvailable() {
        ProviderEndpoint provider = providerRef.get();
        return provider != null && provider.isAvailable();
    }

    @Override
    public String getProvider() {
        ProviderEndpoint provider = providerRef.get();
        return provider != null ? provider.provider() : null;
    }

    /**
     * Execute the agentic loop with tool calling.
     *
     * <p>Sends prompt to LLM, handles tool calls, and returns final response.
     */
    private String executeAgenticLoop(String userPrompt, ProviderEndpoint provider) {
        List<Map<String, Object>> messages = new ArrayList<>();

        // Add system message if present
        if (!systemPrompt.isBlank()) {
            messages.add(Map.of(
                "role", "system",
                "content", systemPrompt
            ));
        }

        // Add user message
        messages.add(Map.of(
            "role", "user",
            "content", userPrompt
        ));

        // Add tools if available
        List<Map<String, Object>> toolDefs = buildToolDefinitions();

        int iteration = 0;
        while (iteration < maxIterations) {
            iteration++;
            log.debug("Agentic loop iteration {}/{}", iteration, maxIterations);

            // Call LLM provider
            Map<String, Object> params = new LinkedHashMap<>();
            params.put("messages", messages);
            if (!toolDefs.isEmpty()) {
                params.put("tools", toolDefs);
            }

            Map<String, Object> response;
            try {
                response = mcpClient.callTool(provider.endpoint(), provider.functionName(), params);
            } catch (Exception e) {
                log.error("LLM call failed: {}", e.getMessage());
                throw new RuntimeException("LLM call failed", e);
            }

            // Check for tool calls
            List<Map<String, Object>> toolCalls = extractToolCalls(response);

            if (toolCalls.isEmpty()) {
                // No tool calls, return the content
                return extractContent(response);
            }

            // Add assistant message with tool calls
            messages.add(Map.of(
                "role", "assistant",
                "content", extractContent(response),
                "tool_calls", toolCalls
            ));

            // Execute tool calls and add results
            for (Map<String, Object> toolCall : toolCalls) {
                String toolId = (String) toolCall.get("id");
                String toolName = (String) toolCall.get("name");
                @SuppressWarnings("unchecked")
                Map<String, Object> toolArgs = (Map<String, Object>) toolCall.get("arguments");

                log.debug("Executing tool: {} with args: {}", toolName, toolArgs);

                String toolResult = executeToolCall(toolName, toolArgs);

                messages.add(Map.of(
                    "role", "tool",
                    "tool_call_id", toolId,
                    "content", toolResult
                ));
            }
        }

        log.warn("Max iterations ({}) reached for LLM agent {}", maxIterations, functionId);
        // Return last response content
        return extractLastAssistantContent(messages);
    }

    /**
     * Build tool definitions for the LLM from available tools.
     */
    private List<Map<String, Object>> buildToolDefinitions() {
        List<Map<String, Object>> tools = new ArrayList<>();

        for (ToolInfo tool : availableTools) {
            Map<String, Object> functionDef = new LinkedHashMap<String, Object>();
            functionDef.put("name", tool.name());
            functionDef.put("description", tool.description() != null ? tool.description() : "");
            // inputSchema is already a Map, use it directly or provide default
            Map<String, Object> schema = tool.inputSchema();
            if (schema == null || schema.isEmpty()) {
                Map<String, Object> defaultSchema = new LinkedHashMap<String, Object>();
                defaultSchema.put("type", "object");
                defaultSchema.put("properties", new LinkedHashMap<String, Object>());
                schema = defaultSchema;
            }
            functionDef.put("parameters", schema);

            Map<String, Object> toolDef = new LinkedHashMap<String, Object>();
            toolDef.put("type", "function");
            toolDef.put("function", functionDef);
            tools.add(toolDef);
        }

        return tools;
    }

    /**
     * Extract tool calls from LLM response.
     */
    @SuppressWarnings("unchecked")
    private List<Map<String, Object>> extractToolCalls(Map<String, Object> response) {
        Object toolCalls = response.get("tool_calls");
        if (toolCalls instanceof List<?> list) {
            return (List<Map<String, Object>>) list;
        }
        return List.of();
    }

    /**
     * Extract text content from LLM response.
     */
    private String extractContent(Map<String, Object> response) {
        Object content = response.get("content");
        if (content instanceof String s) {
            return s;
        }
        if (content instanceof List<?> list && !list.isEmpty()) {
            // Handle content blocks format
            Object first = list.get(0);
            if (first instanceof Map<?, ?> block) {
                Object text = block.get("text");
                if (text != null) {
                    return text.toString();
                }
            }
        }
        return "";
    }

    /**
     * Execute a tool call via the mesh.
     */
    private String executeToolCall(String toolName, Map<String, Object> args) {
        // Find tool info to get agent endpoint
        ToolInfo toolInfo = findToolByName(toolName);
        if (toolInfo == null) {
            log.warn("Tool not found: {}", toolName);
            return "{\"error\": \"Tool not found: " + toolName + "\"}";
        }

        try {
            // Get proxy for the tool's capability
            var proxy = dependencyInjector.getToolProxy(toolInfo.capability());
            if (proxy == null || !proxy.isAvailable()) {
                log.warn("Tool proxy not available: {}", toolInfo.capability());
                return "{\"error\": \"Tool unavailable: " + toolInfo.capability() + "\"}";
            }

            // Call the tool
            Object result = proxy.call(args);
            return objectMapper.writeValueAsString(result);
        } catch (Exception e) {
            log.error("Tool call failed: {} - {}", toolName, e.getMessage());
            return "{\"error\": \"" + e.getMessage().replace("\"", "'") + "\"}";
        }
    }

    /**
     * Find a tool by name.
     */
    private ToolInfo findToolByName(String name) {
        return availableTools.stream()
            .filter(t -> t.name().equals(name))
            .findFirst()
            .orElse(null);
    }

    /**
     * Extract last assistant content from messages.
     */
    private String extractLastAssistantContent(List<Map<String, Object>> messages) {
        for (int i = messages.size() - 1; i >= 0; i--) {
            Map<String, Object> msg = messages.get(i);
            if ("assistant".equals(msg.get("role"))) {
                Object content = msg.get("content");
                if (content instanceof String s) {
                    return s;
                }
            }
        }
        return "";
    }

    /**
     * Try to extract JSON from a text response.
     */
    private String extractJsonFromResponse(String response) {
        if (response == null) {
            return null;
        }

        // Look for JSON object
        int start = response.indexOf('{');
        int end = response.lastIndexOf('}');
        if (start >= 0 && end > start) {
            return response.substring(start, end + 1);
        }

        // Look for JSON array
        start = response.indexOf('[');
        end = response.lastIndexOf(']');
        if (start >= 0 && end > start) {
            return response.substring(start, end + 1);
        }

        return null;
    }
}
