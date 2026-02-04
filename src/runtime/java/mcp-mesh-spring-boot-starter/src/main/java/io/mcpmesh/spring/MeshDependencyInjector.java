package io.mcpmesh.spring;

import io.mcpmesh.core.MeshEvent;
import io.mcpmesh.types.McpMeshTool;
import io.mcpmesh.types.MeshLlmAgent;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

/**
 * Manages dependency injection for mesh tools.
 *
 * <p>Creates and maintains proxies for remote tools that are injected
 * into {@code @MeshTool} method parameters.
 */
public class MeshDependencyInjector {

    private static final Logger log = LoggerFactory.getLogger(MeshDependencyInjector.class);

    private final McpHttpClient mcpClient;
    private final McpMeshToolProxyFactory proxyFactory;
    private final ToolInvoker toolInvoker;
    private final Map<String, McpMeshToolProxy> toolProxies = new ConcurrentHashMap<>();
    private final Map<String, MeshLlmAgentProxy> llmProxies = new ConcurrentHashMap<>();

    public MeshDependencyInjector() {
        this.mcpClient = new McpHttpClient();
        this.proxyFactory = new McpMeshToolProxyFactory(this.mcpClient);
        this.toolInvoker = new ToolInvoker(this.proxyFactory);
    }

    public MeshDependencyInjector(McpHttpClient mcpClient, McpMeshToolProxyFactory proxyFactory,
                                   ToolInvoker toolInvoker) {
        this.mcpClient = mcpClient;
        this.proxyFactory = proxyFactory;
        this.toolInvoker = toolInvoker;
    }

    /**
     * Update a tool dependency based on a mesh event.
     *
     * @param capability The capability name
     * @param endpoint   The remote endpoint URL (null if unavailable)
     * @param functionName The function name at the endpoint
     */
    public void updateToolDependency(String capability, String endpoint, String functionName) {
        McpMeshToolProxy proxy = toolProxies.computeIfAbsent(capability,
            cap -> new McpMeshToolProxy(cap));

        if (endpoint != null) {
            log.info("Dependency available: {} at {}", capability, endpoint);
            proxy.updateEndpoint(endpoint, functionName);
        } else {
            log.info("Dependency unavailable: {}", capability);
            proxy.markUnavailable();
        }
    }

    /**
     * Update LLM tools available to an LLM agent.
     *
     * @param functionId The LLM function ID
     * @param tools      Available tools
     */
    public void updateLlmTools(String functionId, java.util.List<MeshEvent.LlmToolInfo> tools) {
        MeshLlmAgentProxy proxy = llmProxies.get(functionId);
        if (proxy != null) {
            log.info("LLM tools updated for {}: {} tools available", functionId, tools.size());
            proxy.updateTools(tools);
        }
    }

    /**
     * Get or create a tool proxy for dependency injection.
     *
     * @param capability The capability name
     * @return The proxy (may not be connected yet)
     */
    public McpMeshTool getToolProxy(String capability) {
        return toolProxies.computeIfAbsent(capability,
            cap -> new McpMeshToolProxy(cap, mcpClient));
    }

    /**
     * Get or create an LLM agent proxy.
     *
     * @param functionId The LLM function ID
     * @return The proxy
     */
    public MeshLlmAgent getLlmProxy(String functionId) {
        return llmProxies.computeIfAbsent(functionId,
            id -> new MeshLlmAgentProxy(id));
    }

    /**
     * Get or create an LLM agent proxy with configuration.
     *
     * @param functionId    The LLM function ID
     * @param systemPrompt  The system prompt for the LLM
     * @param maxIterations Max iterations for agentic loop
     * @return The configured proxy
     */
    public MeshLlmAgent getLlmProxy(String functionId, String systemPrompt, int maxIterations) {
        MeshLlmAgentProxy proxy = llmProxies.computeIfAbsent(functionId,
            id -> new MeshLlmAgentProxy(id));
        proxy.configure(mcpClient, proxyFactory, toolInvoker, this, systemPrompt, maxIterations);
        return proxy;
    }

    /**
     * Update LLM provider endpoint.
     *
     * @param functionId   The LLM function ID
     * @param endpoint     The provider endpoint URL
     * @param functionName The function name at the endpoint
     * @param provider     The provider name (e.g., "claude", "openai")
     */
    public void updateLlmProvider(String functionId, String endpoint, String functionName, String provider) {
        MeshLlmAgentProxy proxy = llmProxies.get(functionId);
        if (proxy != null) {
            log.info("LLM provider updated for {}: {} at {}", functionId, provider, endpoint);
            proxy.updateProvider(endpoint, functionName, provider);
        } else {
            log.warn("No LLM proxy registered for: {}", functionId);
        }
    }

    /**
     * Check if a dependency is currently available.
     *
     * @param capability The capability name
     * @return true if available
     */
    public boolean isDependencyAvailable(String capability) {
        McpMeshToolProxy proxy = toolProxies.get(capability);
        return proxy != null && proxy.isAvailable();
    }
}
