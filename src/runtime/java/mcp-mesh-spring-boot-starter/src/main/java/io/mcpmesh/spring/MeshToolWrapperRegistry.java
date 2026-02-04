package io.mcpmesh.spring;

import io.mcpmesh.types.McpMeshTool;
import io.mcpmesh.types.MeshLlmAgent;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.lang.reflect.Type;
import java.util.Collection;
import java.util.Collections;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

/**
 * Registry for MeshToolWrapper and other McpToolHandler instances.
 *
 * <p>Stores wrappers by function ID and handles dependency updates using
 * composite keys (funcId:dep_N format).
 *
 * <p>This registry is the bridge between:
 * <ul>
 *   <li>MCP SDK registration (getAllHandlers)</li>
 *   <li>Heartbeat dependency updates (updateDependency)</li>
 *   <li>Tool invocation (getHandler)</li>
 * </ul>
 *
 * <p>Supports both @MeshTool methods (via MeshToolWrapper) and @MeshLlmProvider
 * classes (via LlmProviderToolWrapper from spring-ai module).
 *
 * @see MeshToolWrapper
 * @see McpToolHandler
 */
public class MeshToolWrapperRegistry {

    private static final Logger log = LoggerFactory.getLogger(MeshToolWrapperRegistry.class);

    private static final String DEP_SEPARATOR = ":dep_";
    private static final String LLM_SEPARATOR = ":llm_";

    // funcId → wrapper (MeshToolWrapper only, for dependency updates)
    private final Map<String, MeshToolWrapper> wrappers = new ConcurrentHashMap<>();

    // methodName → wrapper (for dependency resolution by function name from Rust core)
    private final Map<String, MeshToolWrapper> wrappersByMethodName = new ConcurrentHashMap<>();

    // funcId → handler (all handlers including LLM providers)
    private final Map<String, McpToolHandler> handlers = new ConcurrentHashMap<>();

    // capability → handler (for MCP SDK tool lookup by name)
    private final Map<String, McpToolHandler> handlersByCapability = new ConcurrentHashMap<>();

    // methodName → handler (for MCP tool lookup by method name)
    private final Map<String, McpToolHandler> handlersByMethodName = new ConcurrentHashMap<>();

    private final McpMeshToolProxyFactory proxyFactory;

    public MeshToolWrapperRegistry(McpMeshToolProxyFactory proxyFactory) {
        this.proxyFactory = proxyFactory;
    }

    /**
     * Register a MeshToolWrapper (for @MeshTool methods).
     *
     * @param wrapper The wrapper to register
     */
    public void registerWrapper(MeshToolWrapper wrapper) {
        String funcId = wrapper.getFuncId();
        String capability = wrapper.getCapability();
        String methodName = wrapper.getMethodName();

        // Store in wrapper maps (for dependency updates)
        wrappers.put(funcId, wrapper);
        wrappersByMethodName.put(methodName, wrapper);

        // Store in handler maps (for MCP server)
        handlers.put(funcId, wrapper);
        handlersByCapability.put(capability, wrapper);
        handlersByMethodName.put(methodName, wrapper);

        log.info("Registered wrapper: {} (capability: {}, deps: {}, llm: {})",
            funcId, capability, wrapper.getDependencyCount(), wrapper.getLlmAgentCount());
    }

    /**
     * Register a generic McpToolHandler (for LLM providers, etc.).
     *
     * <p>Use this for handlers that don't need dependency injection.
     *
     * @param handler The handler to register
     */
    public void registerHandler(McpToolHandler handler) {
        String funcId = handler.getFuncId();
        String capability = handler.getCapability();
        String methodName = handler.getMethodName();

        handlers.put(funcId, handler);
        handlersByCapability.put(capability, handler);
        handlersByMethodName.put(methodName, handler);

        log.info("Registered handler: {} (capability: {}, method: {})",
            funcId, capability, methodName);
    }

    /**
     * Get a wrapper by function ID (for dependency updates).
     *
     * @param funcId The function ID
     * @return The wrapper, or null if not found
     */
    public MeshToolWrapper getWrapper(String funcId) {
        return wrappers.get(funcId);
    }

    /**
     * Get a handler by function ID.
     *
     * @param funcId The function ID
     * @return The handler, or null if not found
     */
    public McpToolHandler getHandler(String funcId) {
        return handlers.get(funcId);
    }

    /**
     * Get a handler by capability name.
     *
     * @param capability The capability name
     * @return The handler, or null if not found
     */
    public McpToolHandler getHandlerByCapability(String capability) {
        return handlersByCapability.get(capability);
    }

    /**
     * Get all registered handlers (for MCP server registration).
     *
     * @return Unmodifiable collection of all handlers
     */
    public Collection<McpToolHandler> getAllHandlers() {
        return Collections.unmodifiableCollection(handlers.values());
    }

    /**
     * Get all registered wrappers (MeshToolWrapper only, for backwards compat).
     *
     * @return Unmodifiable collection of MeshToolWrapper instances
     * @deprecated Use {@link #getAllHandlers()} instead
     */
    @Deprecated
    public Collection<MeshToolWrapper> getAllWrappers() {
        return Collections.unmodifiableCollection(wrappers.values());
    }

    /**
     * Get all handlers mapped by capability.
     *
     * @return Unmodifiable map of capability → handler
     */
    public Map<String, McpToolHandler> getHandlersByCapability() {
        return Collections.unmodifiableMap(handlersByCapability);
    }

    /**
     * Update a McpMeshTool dependency using composite key.
     *
     * <p>Composite key format: "funcId:dep_N" where N is the dependency index.
     * Example: "com.example.Calculator.add:dep_0"
     *
     * @param compositeKey The composite key (funcId:dep_N)
     * @param endpoint     The resolved endpoint URL
     * @param functionName The function name at the endpoint
     */
    public void updateDependency(String compositeKey, String endpoint, String functionName) {
        int sepIndex = compositeKey.lastIndexOf(DEP_SEPARATOR);
        if (sepIndex == -1) {
            log.warn("Invalid composite key format (missing {}): {}", DEP_SEPARATOR, compositeKey);
            return;
        }

        String funcId = compositeKey.substring(0, sepIndex);
        int depIndex;
        try {
            depIndex = Integer.parseInt(compositeKey.substring(sepIndex + DEP_SEPARATOR.length()));
        } catch (NumberFormatException e) {
            log.warn("Invalid dependency index in composite key: {}", compositeKey);
            return;
        }

        MeshToolWrapper wrapper = wrappers.get(funcId);
        if (wrapper == null) {
            // Fallback: funcId might be just the method name from Rust core
            wrapper = wrappersByMethodName.get(funcId);
        }
        if (wrapper == null) {
            log.warn("No wrapper found for funcId: {} (also checked method name)", funcId);
            return;
        }

        // Get the expected return type for this dependency (from McpMeshTool<T>)
        Type returnType = wrapper.getDependencyReturnType(depIndex);

        // Get or create typed proxy
        McpMeshTool<?> proxy = proxyFactory.getOrCreateProxy(endpoint, functionName, returnType);

        // Update wrapper's dependency array
        wrapper.updateDependency(depIndex, proxy);

        log.debug("Updated dependency {} for {} → {}:{} (returnType={})",
            depIndex, funcId, endpoint, functionName, returnType);
    }

    /**
     * Mark a dependency as unavailable.
     *
     * @param compositeKey The composite key (funcId:dep_N)
     */
    public void markDependencyUnavailable(String compositeKey) {
        int sepIndex = compositeKey.lastIndexOf(DEP_SEPARATOR);
        if (sepIndex == -1) {
            return;
        }

        String funcId = compositeKey.substring(0, sepIndex);
        int depIndex;
        try {
            depIndex = Integer.parseInt(compositeKey.substring(sepIndex + DEP_SEPARATOR.length()));
        } catch (NumberFormatException e) {
            return;
        }

        MeshToolWrapper wrapper = wrappers.get(funcId);
        if (wrapper == null) {
            // Fallback: funcId might be just the method name from Rust core
            wrapper = wrappersByMethodName.get(funcId);
        }
        if (wrapper != null) {
            wrapper.updateDependency(depIndex, null);
            log.debug("Marked dependency {} unavailable for {}", depIndex, funcId);
        }
    }

    /**
     * Update a MeshLlmAgent using composite key.
     *
     * <p>Composite key format: "funcId:llm_N" where N is the LLM agent index.
     *
     * @param compositeKey The composite key (funcId:llm_N)
     * @param agent        The configured LLM agent proxy
     */
    public void updateLlmAgent(String compositeKey, MeshLlmAgent agent) {
        int sepIndex = compositeKey.lastIndexOf(LLM_SEPARATOR);
        if (sepIndex == -1) {
            log.warn("Invalid LLM composite key format (missing {}): {}", LLM_SEPARATOR, compositeKey);
            return;
        }

        String funcId = compositeKey.substring(0, sepIndex);
        int llmIndex;
        try {
            llmIndex = Integer.parseInt(compositeKey.substring(sepIndex + LLM_SEPARATOR.length()));
        } catch (NumberFormatException e) {
            log.warn("Invalid LLM index in composite key: {}", compositeKey);
            return;
        }

        MeshToolWrapper wrapper = wrappers.get(funcId);
        if (wrapper == null) {
            // Fallback: funcId might be just the method name from Rust core
            wrapper = wrappersByMethodName.get(funcId);
        }
        if (wrapper == null) {
            log.warn("No wrapper found for funcId: {} (also checked method name)", funcId);
            return;
        }

        log.info("updateLlmAgent: compositeKey='{}', funcId='{}', llmIndex={}, agent@{}",
            compositeKey, funcId, llmIndex, agent != null ? System.identityHashCode(agent) : "null");
        wrapper.updateLlmAgent(llmIndex, agent);
        log.debug("Updated LLM agent {} for {}", llmIndex, funcId);
    }

    /**
     * Build a composite key for a dependency.
     *
     * @param funcId   The function ID
     * @param depIndex The dependency index
     * @return The composite key
     */
    public static String buildDependencyKey(String funcId, int depIndex) {
        return funcId + DEP_SEPARATOR + depIndex;
    }

    /**
     * Build a composite key for an LLM agent.
     *
     * @param funcId   The function ID
     * @param llmIndex The LLM agent index
     * @return The composite key
     */
    public static String buildLlmKey(String funcId, int llmIndex) {
        return funcId + LLM_SEPARATOR + llmIndex;
    }

    /**
     * Get the number of registered wrappers.
     */
    public int size() {
        return wrappers.size();
    }

    /**
     * Check if a wrapper exists for the given function ID.
     */
    public boolean hasWrapper(String funcId) {
        return wrappers.containsKey(funcId);
    }

    /**
     * Check if a handler exists for the given capability.
     */
    public boolean hasCapability(String capability) {
        return handlersByCapability.containsKey(capability);
    }
}
