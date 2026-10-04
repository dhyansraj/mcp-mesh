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
    // Per capability: the untyped proxy, which owns the endpoint state.
    private final Map<String, McpMeshToolProxy> toolProxies = new ConcurrentHashMap<>();
    // Per capability, per declared return type: typed views sharing that
    // capability's endpoint state (issue #1568). Never updated directly — an
    // update to the untyped proxy is an update to every view.
    // Keyed by the Type itself (value equality for Class / ParameterizedType),
    // not its rendered name, so distinct types can never share a view.
    private final Map<String, Map<java.lang.reflect.Type, McpMeshToolProxy<?>>> typedProxies =
        new ConcurrentHashMap<>();
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
            cap -> new McpMeshToolProxy(cap, mcpClient));

        if (endpoint != null) {
            log.info("Dependency available: {} at {}", capability, endpoint);
            proxy.updateEndpoint(endpoint, functionName);
            // Settling-window grace (#1193): this is the ROUTE funnel —
            // @MeshRoute requests wait on capability keys because every
            // route resolves through THIS injector's per-capability endpoint
            // state (shared by every typed view), which the updateEndpoint
            // above makes live before the countdown — a woken route request re-reads a live proxy
            // regardless of which consumer's event fired. Tool wrappers do
            // NOT use this key: their waits are per-consumer-slot
            // composites counted down inside MeshToolWrapper
            // .updateDependency (after that wrapper's slot is written).
            MeshSettleState.getInstance().markResolved(capability);
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
     * Get or create a tool proxy with a specific return type for dependency injection.
     *
     * <p>Used by {@code @MeshRoute}, {@code @MeshA2A}, the capability-bean
     * registrars and {@code @MeshService} views when the generic type is known
     * (e.g., {@code McpMeshTool<GreetResponse>}).
     *
     * <p>Each distinct return type gets its own proxy, cached and stable, so a
     * consumer's declared type always governs its own calls — mirroring the
     * per-type split in {@link McpMeshToolProxyFactory} (issue #1568). All of a
     * capability's typed proxies share the untyped proxy's endpoint state, so
     * {@link #updateToolDependency} reaches every one of them. {@code null} and
     * {@code Object.class} both deserialize dynamically and return the untyped
     * proxy.
     *
     * @param capability The capability name
     * @param returnType The expected return type for deserialization
     * @return The proxy (may not be connected yet)
     */
    public McpMeshTool getToolProxy(String capability, java.lang.reflect.Type returnType) {
        McpMeshToolProxy base = (McpMeshToolProxy) getToolProxy(capability);
        if (returnType == null || returnType == Object.class
                || returnType instanceof java.lang.reflect.TypeVariable<?>
                || returnType instanceof java.lang.reflect.WildcardType) {
            // An unresolved variable/wildcard carries no usable target — and
            // two unrelated "T"s must never share a typed view. Callers resolve
            // these first (MeshInjectableSlots.proxyTypeArgument); this is the
            // backstop.
            return base;
        }
        return typedProxies
            .computeIfAbsent(capability, cap -> new ConcurrentHashMap<>())
            .computeIfAbsent(returnType, key -> base.typedView(returnType));
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
