package io.mcpmesh.spring;

import io.mcpmesh.types.McpMeshTool;
import io.mcpmesh.types.MeshLlmAgent.ToolInfo;
import io.mcpmesh.types.MeshToolCallException;
import io.mcpmesh.types.MeshToolUnavailableException;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.lang.reflect.Type;
import java.util.Map;

/**
 * Unified tool invocation utility for both local and remote tool calls.
 *
 * <p>This utility provides a single point for tool invocation logic, supporting:
 * <ul>
 *   <li>Remote invocation via cached {@link McpMeshToolProxy}</li>
 *   <li>Local invocation for self-dependencies (same agent)</li>
 *   <li>Smart invocation that auto-detects local vs remote</li>
 * </ul>
 *
 * <p>Benefits of using this utility:
 * <ul>
 *   <li>Consistent proxy caching for remote calls</li>
 *   <li>Self-dependency optimization (avoids HTTP roundtrip)</li>
 *   <li>Unified error handling</li>
 *   <li>Single point for tracing/metrics integration</li>
 * </ul>
 *
 * <h2>Usage Examples</h2>
 * <pre>{@code
 * // Remote invocation
 * Object result = toolInvoker.invokeRemote(endpoint, functionName, args, String.class);
 *
 * // Local invocation (self-dependency)
 * Object result = toolInvoker.invokeLocal("greet", args);
 *
 * // Smart invocation (auto-detects)
 * Object result = toolInvoker.invoke(toolInfo, args);
 * }</pre>
 *
 * @see McpMeshToolProxyFactory
 * @see MeshToolWrapperRegistry
 */
public class ToolInvoker {

    private static final Logger log = LoggerFactory.getLogger(ToolInvoker.class);

    private final McpMeshToolProxyFactory proxyFactory;
    private final MeshToolWrapperRegistry wrapperRegistry;
    private final String currentAgentId;

    /**
     * Create a ToolInvoker with all dependencies.
     *
     * @param proxyFactory    Factory for cached remote proxies
     * @param wrapperRegistry Registry for local tool handlers
     * @param currentAgentId  The current agent's ID (for self-dependency detection)
     */
    public ToolInvoker(McpMeshToolProxyFactory proxyFactory,
                       MeshToolWrapperRegistry wrapperRegistry,
                       String currentAgentId) {
        this.proxyFactory = proxyFactory;
        this.wrapperRegistry = wrapperRegistry;
        this.currentAgentId = currentAgentId;
    }

    /**
     * Create a ToolInvoker for remote-only invocation.
     *
     * <p>Use this when local invocation is not needed (no wrapperRegistry or agentId).
     *
     * @param proxyFactory Factory for cached remote proxies
     */
    public ToolInvoker(McpMeshToolProxyFactory proxyFactory) {
        this(proxyFactory, null, null);
    }

    /**
     * Invoke a tool remotely via cached proxy.
     *
     * <p>Uses {@link McpMeshToolProxyFactory} to get or create a cached proxy,
     * then calls the tool with the provided arguments.
     *
     * @param endpoint     The tool's HTTP endpoint URL
     * @param functionName The function name to call
     * @param args         Arguments to pass to the tool
     * @param returnType   Expected return type for deserialization (null defaults to Object.class)
     * @return The result from the remote tool
     * @throws MeshToolUnavailableException if the tool/agent is unavailable
     * @throws MeshToolCallException        if the call fails
     */
    public Object invokeRemote(String endpoint, String functionName,
                               Map<String, Object> args, Type returnType) {
        if (endpoint == null || endpoint.isBlank()) {
            throw new MeshToolUnavailableException(
                "Tool endpoint is null or blank: " + functionName);
        }

        log.debug("Invoking remote tool: {} at {} (returnType={})",
            functionName, endpoint, returnType);

        McpMeshTool<?> proxy = proxyFactory.getOrCreateProxy(
            endpoint, functionName, returnType != null ? returnType : Object.class);
        return proxy.call(args);
    }

    /**
     * Invoke a local tool handler by capability.
     *
     * <p>Looks up the handler in {@link MeshToolWrapperRegistry} and invokes it
     * directly, avoiding any network overhead.
     *
     * @param capability The tool capability name
     * @param args       Arguments to pass to the tool
     * @return The result from the local handler
     * @throws MeshToolUnavailableException if local invocation is not available
     *                                       or the capability is not found
     * @throws MeshToolCallException        if the invocation fails
     */
    public Object invokeLocal(String capability, Map<String, Object> args) {
        if (wrapperRegistry == null) {
            throw new MeshToolUnavailableException(
                "Local invocation not available: wrapperRegistry is null");
        }

        McpToolHandler handler = wrapperRegistry.getHandlerByCapability(capability);
        if (handler == null) {
            throw new MeshToolUnavailableException(
                "No local handler found for capability: " + capability);
        }

        log.debug("Invoking local tool: {} (funcId={})", capability, handler.getFuncId());

        try {
            return handler.invoke(args);
        } catch (Exception e) {
            throw new MeshToolCallException(capability, handler.getMethodName(), e);
        }
    }

    /**
     * Smart tool invocation - chooses local or remote based on agentId.
     *
     * <p>If the tool's agentId matches the current agent, invokes locally.
     * Otherwise, invokes remotely via cached proxy.
     *
     * @param toolInfo The tool information (from LLM tools or mesh discovery)
     * @param args     Arguments to pass to the tool
     * @return The result from the tool
     * @throws MeshToolUnavailableException if the tool is unavailable
     * @throws MeshToolCallException        if the call fails
     */
    public Object invoke(ToolInfo toolInfo, Map<String, Object> args) {
        if (toolInfo == null) {
            throw new MeshToolUnavailableException("Tool info is null");
        }

        if (!toolInfo.isAvailable()) {
            throw new MeshToolUnavailableException(
                "Tool is not available: " + toolInfo.name());
        }

        // Check for self-dependency (local invocation)
        if (isSelfDependency(toolInfo)) {
            log.debug("Self-dependency detected for tool: {} (agentId={})",
                toolInfo.name(), toolInfo.agentId());
            return invokeLocal(toolInfo.capability(), args);
        }

        // Remote invocation
        return invokeRemote(
            toolInfo.endpoint(),
            toolInfo.name(),
            args,
            toolInfo.getReturnTypeOrDefault()
        );
    }

    /**
     * Check if a tool is a self-dependency (same agent).
     *
     * @param toolInfo The tool information
     * @return true if the tool is on the same agent
     */
    public boolean isSelfDependency(ToolInfo toolInfo) {
        if (currentAgentId == null || toolInfo == null) {
            return false;
        }
        return currentAgentId.equals(toolInfo.agentId());
    }

    /**
     * Check if local invocation is available.
     *
     * @return true if wrapperRegistry and currentAgentId are configured
     */
    public boolean isLocalInvocationAvailable() {
        return wrapperRegistry != null && currentAgentId != null;
    }

    /**
     * Get the current agent's ID.
     *
     * @return The agent ID, or null if not configured
     */
    public String getCurrentAgentId() {
        return currentAgentId;
    }
}
