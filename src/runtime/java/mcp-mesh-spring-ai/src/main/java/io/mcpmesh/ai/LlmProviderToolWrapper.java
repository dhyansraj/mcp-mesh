package io.mcpmesh.ai;

import io.mcpmesh.spring.McpToolHandler;
import io.mcpmesh.spring.tracing.ExecutionTracer;
import io.mcpmesh.spring.tracing.SpanScope;
import io.mcpmesh.spring.tracing.TraceContext;
import io.mcpmesh.spring.tracing.TraceInfo;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicReference;

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

    // Tracing support (set lazily via setter)
    private final AtomicReference<ExecutionTracer> tracerRef = new AtomicReference<>();

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
     * Set the ExecutionTracer for this wrapper.
     *
     * @param tracer The tracer to use
     */
    public void setTracer(ExecutionTracer tracer) {
        tracerRef.set(tracer);
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

        // Extract trace context from arguments and set up TraceContext
        Map<String, Object> cleanArgs = extractAndSetupTraceContext(mcpArgs);

        // Get tracer and start span if tracing is enabled
        ExecutionTracer tracer = tracerRef.get();
        Map<String, Object> spanMetadata = new LinkedHashMap<>();
        spanMetadata.put("capability", capability);
        spanMetadata.put("provider", "llm");

        // Use method name for trace (llm_generate)
        String traceName = getMethodName();
        try (SpanScope span = tracer != null ? tracer.startSpan(traceName, spanMetadata) : SpanScope.NOOP) {
            Object result = processor.handleGenerateRequest(capability, cleanArgs);
            span.withResult(result);
            return result;
        } catch (Exception e) {
            log.error("LLM provider call failed: {}", e.getMessage(), e);
            throw e;
        }
    }

    /**
     * Extract trace context from arguments and set up TraceContext.
     *
     * @param mcpArgs The MCP arguments (may contain _trace_id, _parent_span, and _mesh_headers)
     * @return Clean arguments with trace fields removed
     */
    private Map<String, Object> extractAndSetupTraceContext(Map<String, Object> mcpArgs) {
        if (mcpArgs == null) {
            return new LinkedHashMap<>();
        }

        // Make a mutable copy
        Map<String, Object> cleanArgs = new LinkedHashMap<>(mcpArgs);

        // Extract trace context from arguments
        String traceId = null;
        String parentSpan = null;

        Object traceIdObj = cleanArgs.remove("_trace_id");
        Object parentSpanObj = cleanArgs.remove("_parent_span");

        if (traceIdObj instanceof String) {
            traceId = (String) traceIdObj;
        }
        if (parentSpanObj instanceof String) {
            parentSpan = (String) parentSpanObj;
        }

        // Set trace context from arguments
        if (traceId != null && !traceId.isEmpty()) {
            TraceInfo traceInfo = TraceInfo.fromHeaders(traceId, parentSpan);
            TraceContext.set(traceInfo);
            log.trace("Set trace context from arguments: trace={}, parent={}",
                traceId.substring(0, Math.min(8, traceId.length())),
                parentSpan != null ? parentSpan.substring(0, Math.min(8, parentSpan.length())) : "null");
        }

        // Extract _mesh_headers from arguments and set propagated headers context
        Object meshHeadersObj = cleanArgs.remove("_mesh_headers");
        if (meshHeadersObj instanceof Map) {
            @SuppressWarnings("unchecked")
            Map<String, Object> meshHeaders = (Map<String, Object>) meshHeadersObj;
            if (!TraceContext.getPropagateHeaderNames().isEmpty()) {
                Map<String, String> filtered = new HashMap<>();
                for (Map.Entry<String, Object> entry : meshHeaders.entrySet()) {
                    if (entry.getValue() instanceof String
                        && TraceContext.matchesPropagateHeader(entry.getKey())) {
                        filtered.put(entry.getKey().toLowerCase(), (String) entry.getValue());
                    }
                }
                if (!filtered.isEmpty()) {
                    // Merge with any headers already captured by TracingFilter
                    Map<String, String> existing = TraceContext.getPropagatedHeaders();
                    if (!existing.isEmpty()) {
                        Map<String, String> merged = new HashMap<>(existing);
                        // Args headers fill in gaps but don't override HTTP headers
                        for (Map.Entry<String, String> e : filtered.entrySet()) {
                            merged.putIfAbsent(e.getKey(), e.getValue());
                        }
                        filtered = merged;
                    }
                    TraceContext.setPropagatedHeaders(filtered);
                    log.trace("Set {} propagated headers from _mesh_headers args", filtered.size());
                }
            }
        }

        return cleanArgs;
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
