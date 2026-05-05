package io.mcpmesh.spring;

import io.mcpmesh.core.MeshEvent;
import io.mcpmesh.spring.media.MediaStore;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.BeansException;
import org.springframework.context.ApplicationContext;
import org.springframework.context.SmartLifecycle;

import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;

/**
 * Processes events from the Rust core runtime.
 *
 * <p>Runs an event loop that polls for events and dispatches them
 * to the appropriate handlers (dependency updates, LLM tool updates, etc.).
 *
 * <p>For dependency events, this processor updates both:
 * <ul>
 *   <li>Legacy {@link MeshDependencyInjector} for backward compatibility</li>
 *   <li>{@link MeshToolWrapperRegistry} for MCP SDK wrapper-based injection</li>
 * </ul>
 *
 * @see MeshToolWrapperRegistry
 */
public class MeshEventProcessor implements SmartLifecycle {

    private static final Logger log = LoggerFactory.getLogger(MeshEventProcessor.class);
    private static final int LIFECYCLE_PHASE = Integer.MAX_VALUE - 50; // After MeshRuntime
    private static final long EVENT_POLL_TIMEOUT_MS = 5000;

    private final MeshRuntime runtime;
    private final MeshDependencyInjector injector;
    private final MeshToolWrapperRegistry wrapperRegistry;
    private final MeshLlmRegistry llmRegistry;
    private final McpHttpClient mcpClient;
    private final McpMeshToolProxyFactory proxyFactory;
    private final ToolInvoker toolInvoker;
    private final ApplicationContext applicationContext; // For MediaStore bean lookup
    private final AtomicBoolean running = new AtomicBoolean(false);
    private final ExecutorService executor;

    // Track created LLM agent proxies so we can update their tools later
    // Key: funcId (full class path), Value: proxy (we only support one LLM agent per function currently)
    private final Map<String, MeshLlmAgentProxy> llmAgentProxies = new ConcurrentHashMap<>();

    // Reverse lookup: short method name -> set of full funcId keys in llmAgentProxies
    // Populated when proxies are stored, enabling O(1) lookup by method name
    // Uses a set to handle collisions when multiple classes have methods with the same name
    private final Map<String, Set<String>> methodNameToFuncIds = new ConcurrentHashMap<>();

    // Cache for tools when wrapper is not found (fallback only)
    // With the new flow, proxy is created immediately when tools arrive, so this
    // is only used when wrapper lookup fails (legacy injection mode).
    // Key: short function name (e.g., "analyze"), Value: tools list
    private final Map<String, List<MeshEvent.LlmToolInfo>> pendingTools = new ConcurrentHashMap<>();

    public MeshEventProcessor(
            MeshRuntime runtime,
            MeshDependencyInjector injector,
            MeshToolWrapperRegistry wrapperRegistry,
            MeshLlmRegistry llmRegistry,
            McpHttpClient mcpClient,
            McpMeshToolProxyFactory proxyFactory,
            ToolInvoker toolInvoker,
            ApplicationContext applicationContext) {
        this.runtime = runtime;
        this.injector = injector;
        this.wrapperRegistry = wrapperRegistry;
        this.llmRegistry = llmRegistry;
        this.mcpClient = mcpClient;
        this.proxyFactory = proxyFactory;
        this.toolInvoker = toolInvoker;
        this.applicationContext = applicationContext;
        this.executor = Executors.newSingleThreadExecutor(r -> {
            Thread t = new Thread(r, "mesh-event-processor");
            t.setDaemon(true);
            return t;
        });
    }

    @Override
    public void start() {
        if (running.compareAndSet(false, true)) {
            log.info("Starting mesh event processor");
            executor.submit(this::eventLoop);
        }
    }

    @Override
    public void stop() {
        if (running.compareAndSet(true, false)) {
            log.info("Stopping mesh event processor");
            executor.shutdown();
            try {
                if (!executor.awaitTermination(5, TimeUnit.SECONDS)) {
                    executor.shutdownNow();
                }
            } catch (InterruptedException e) {
                executor.shutdownNow();
                Thread.currentThread().interrupt();
            }
        }
    }

    @Override
    public boolean isRunning() {
        return running.get();
    }

    @Override
    public int getPhase() {
        return LIFECYCLE_PHASE;
    }

    private void eventLoop() {
        log.debug("Event loop started");

        while (running.get() && runtime.isRunning()) {
            try {
                MeshEvent event = runtime.nextEvent(EVENT_POLL_TIMEOUT_MS);
                if (event != null) {
                    processEvent(event);
                }
            } catch (Exception e) {
                if (running.get()) {
                    log.error("Error processing mesh event", e);
                }
            }
        }

        log.debug("Event loop stopped");
    }

    private void processEvent(MeshEvent event) {
        log.debug("Processing event: {}", event.getEventType());

        switch (event.getEventType()) {
            case AGENT_REGISTERED -> handleAgentRegistered(event);
            case DEPENDENCY_AVAILABLE -> handleDependencyAvailable(event);
            case DEPENDENCY_UNAVAILABLE -> handleDependencyUnavailable(event);
            case DEPENDENCY_CHANGED -> handleDependencyChanged(event);
            case LLM_TOOLS_UPDATED -> handleLlmToolsUpdated(event);
            case LLM_PROVIDER_AVAILABLE -> handleLlmProviderAvailable(event);
            case SHUTDOWN -> handleShutdown(event);
            case REGISTRATION_FAILED -> handleRegistrationFailed(event);
            default -> log.debug("Unhandled event type: {}", event.getEventType());
        }
    }

    private void handleAgentRegistered(MeshEvent event) {
        // no-op since v2; kept for log signal in DEBUG builds. Direct-LLM
        // init was removed in #859.
        log.info("Agent registered with mesh: {}", event.getAgentId());
    }

    private void handleDependencyAvailable(MeshEvent event) {
        log.info("Dependency available: {} at {} (requestingFunction={}, depIndex={})",
            event.getCapability(), event.getEndpoint(),
            event.getRequestingFunction(), event.getDepIndex());

        // Update legacy injector
        injector.updateToolDependency(
            event.getCapability(),
            event.getEndpoint(),
            event.getFunctionName()
        );

        // Update wrapper registry with composite key
        if (event.getRequestingFunction() != null && event.getDepIndex() != null) {
            String compositeKey = MeshToolWrapperRegistry.buildDependencyKey(
                event.getRequestingFunction(),
                event.getDepIndex()
            );
            wrapperRegistry.updateDependency(
                compositeKey,
                event.getEndpoint(),
                event.getFunctionName()
            );
        }
    }

    private void handleDependencyUnavailable(MeshEvent event) {
        log.info("Dependency unavailable: {} (requestingFunction={}, depIndex={})",
            event.getCapability(), event.getRequestingFunction(), event.getDepIndex());

        // Update legacy injector
        injector.updateToolDependency(
            event.getCapability(),
            null,
            null
        );

        // Mark wrapper dependency as unavailable
        if (event.getRequestingFunction() != null && event.getDepIndex() != null) {
            String compositeKey = MeshToolWrapperRegistry.buildDependencyKey(
                event.getRequestingFunction(),
                event.getDepIndex()
            );
            wrapperRegistry.markDependencyUnavailable(compositeKey);
        }
    }

    private void handleLlmToolsUpdated(MeshEvent event) {
        String funcId = event.getFunctionId();
        log.info("LLM tools updated for function: {} ({} tools)",
            funcId, event.getTools() != null ? event.getTools().size() : 0);

        if (event.getTools() != null) {
            // Log all tool names for debugging
            for (MeshEvent.LlmToolInfo tool : event.getTools()) {
                log.debug("  Tool: {} (capability: {})", tool.getFunctionName(), tool.getCapability());
            }

            // Update legacy injector
            injector.updateLlmTools(funcId, event.getTools());

            // Log current proxy state
            log.debug("Current llmAgentProxies keys: {}", llmAgentProxies.keySet());

            // Update wrapper's LLM agent proxy if exists
            // Registry uses short function name (e.g., "analyze"), but proxy is stored
            // with full Java ID (e.g., "com.example.Class.analyze"). Try both.
            MeshLlmAgentProxy proxy = llmAgentProxies.get(funcId);

            if (proxy == null) {
                // O(1) reverse lookup by short method name
                Set<String> mappedFuncIds = methodNameToFuncIds.get(funcId);
                if (mappedFuncIds != null) {
                    if (mappedFuncIds.size() == 1) {
                        String mappedFuncId = mappedFuncIds.iterator().next();
                        proxy = llmAgentProxies.get(mappedFuncId);
                        if (proxy != null) {
                            log.info("Found LLM proxy by method name map: {} -> {} (proxy@{})",
                                funcId, mappedFuncId, System.identityHashCode(proxy));
                        }
                    } else {
                        log.warn("Ambiguous method name '{}' maps to {} funcIds: {} — skipping reverse lookup",
                            funcId, mappedFuncIds.size(), mappedFuncIds);
                    }
                }
            }

            if (proxy != null) {
                proxy.updateTools(event.getTools());
                log.info("Updated {} tools on LLM agent proxy@{} for {} (isAvailable={})",
                    event.getTools().size(), System.identityHashCode(proxy), funcId, proxy.isAvailable());
            } else {
                // Proxy doesn't exist yet - create it now (don't wait for provider)
                // This matches Python behavior where agent is created when tools arrive
                proxy = createLlmProxyForTools(funcId, event.getTools());
                if (proxy != null) {
                    log.info("Created LLM agent proxy with {} tools for {} (provider pending)",
                        event.getTools().size(), funcId);
                } else {
                    // Fallback: cache tools for later (e.g., wrapper not found)
                    pendingTools.put(funcId, event.getTools());
                    log.info("Cached {} pending tools for {} (wrapper not found)", event.getTools().size(), funcId);
                }
            }
        }
    }

    /**
     * Create MeshLlmAgentProxy when tools arrive (before provider is available).
     *
     * <p>This matches Python SDK behavior where the LLM agent is created when tools
     * are discovered, and the provider is added later when available. The agent
     * can still be used (returns isAvailable=false until provider connects).
     *
     * @param funcId The function ID from the event (method name)
     * @param tools  The discovered tools
     * @return The created proxy, or null if wrapper not found
     */
    private MeshLlmAgentProxy createLlmProxyForTools(String funcId, List<MeshEvent.LlmToolInfo> tools) {
        // Find wrapper by direct lookup, then by method name, then by capability
        MeshToolWrapper wrapper = wrapperRegistry.getWrapper(funcId);
        if (wrapper == null) {
            wrapper = wrapperRegistry.getWrapperByMethodName(funcId);
        }
        if (wrapper == null) {
            McpToolHandler handler = wrapperRegistry.getHandlerByCapability(funcId);
            if (handler instanceof MeshToolWrapper w) {
                wrapper = w;
            }
        }

        if (wrapper == null) {
            log.debug("No wrapper found for funcId: {} (may be using legacy injection)", funcId);
            return null;
        }

        if (wrapper.getLlmAgentCount() == 0) {
            log.debug("Wrapper {} has no MeshLlmAgent parameters", wrapper.getFuncId());
            return null;
        }

        String wrapperFuncId = wrapper.getFuncId();

        // Get @MeshLlm configuration from registry
        MeshLlmRegistry.LlmConfig config = llmRegistry.getByFunctionId(wrapperFuncId);

        // Create proxy for each LLM agent parameter position
        MeshLlmAgentProxy proxy = null;
        for (int llmIndex = 0; llmIndex < wrapper.getLlmAgentCount(); llmIndex++) {
            proxy = new MeshLlmAgentProxy(wrapperFuncId);

            // Configure with @MeshLlm settings (or defaults)
            String systemPrompt = config != null ? config.systemPrompt() : "";
            String contextParam = config != null ? config.contextParam() : "ctx";
            int maxIterations = config != null ? config.maxIterations() : 1;
            boolean parallelToolCalls = config != null && config.parallelToolCalls();

            proxy.configure(mcpClient, proxyFactory, toolInvoker, injector, systemPrompt, contextParam, maxIterations, parallelToolCalls);

            // Wire MediaStore for multimodal support
            wireMediaStore(proxy);

            // Apply tools immediately
            proxy.updateTools(tools);

            // Store proxy for later provider updates
            storeProxyWithReverseLookup(wrapperFuncId, proxy);
            String shortName = wrapperFuncId.contains(".")
                ? wrapperFuncId.substring(wrapperFuncId.lastIndexOf('.') + 1)
                : wrapperFuncId;
            log.info("Stored proxy@{} in llmAgentProxies with key '{}' (methodName='{}')",
                System.identityHashCode(proxy), wrapperFuncId, shortName);

            // Update the wrapper's LLM agent array
            String compositeKey = MeshToolWrapperRegistry.buildLlmKey(wrapperFuncId, llmIndex);
            wrapperRegistry.updateLlmAgent(compositeKey, proxy);

            log.info("Created LLM agent proxy@{} for {} (index={}, tools={}, provider=pending, isAvailable={})",
                System.identityHashCode(proxy), wrapperFuncId, llmIndex, tools.size(), proxy.isAvailable());
        }

        return proxy;
    }

    /**
     * Wire MediaStore into a proxy for multimodal media support.
     *
     * <p>Looks up the MediaStore Spring bean. If not configured (no media storage),
     * the proxy will log a warning if media URIs are used.
     */
    private void wireMediaStore(MeshLlmAgentProxy proxy) {
        try {
            MediaStore store = applicationContext.getBean(MediaStore.class);
            proxy.setMediaStore(store);
        } catch (BeansException e) {
            log.debug("MediaStore not available — multimodal media support disabled for LLM proxy");
        }
    }

    private void storeProxyWithReverseLookup(String funcId, MeshLlmAgentProxy proxy) {
        llmAgentProxies.put(funcId, proxy);
        String shortName = funcId.contains(".")
            ? funcId.substring(funcId.lastIndexOf('.') + 1)
            : funcId;
        methodNameToFuncIds.computeIfAbsent(shortName, k -> ConcurrentHashMap.newKeySet()).add(funcId);
    }

    private void handleDependencyChanged(MeshEvent event) {
        log.debug("Dependency changed: {}", event.getCapability());
        // Re-fetch endpoint info
        if (event.getEndpoint() != null) {
            handleDependencyAvailable(event);
        } else {
            handleDependencyUnavailable(event);
        }
    }

    private void handleLlmProviderAvailable(MeshEvent event) {
        MeshEvent.LlmProviderInfo providerInfo = event.getProviderInfo();
        if (providerInfo != null) {
            String requestingFuncId = providerInfo.getFunctionId();
            log.info("🔌 LLM_PROVIDER_AVAILABLE event received:");
            log.info("  - functionId (consumer): {}", requestingFuncId);
            log.info("  - functionName (provider tool): {}", providerInfo.getFunctionName());
            log.info("  - endpoint: {}", providerInfo.getEndpoint());
            log.info("  - model: {}", providerInfo.getModel());
            log.info("  - agentId: {}", providerInfo.getAgentId());

            // Update the legacy LLM proxy with provider endpoint
            injector.updateLlmProvider(
                requestingFuncId,
                providerInfo.getEndpoint(),
                providerInfo.getFunctionName(),
                providerInfo.getModel()
            );

            // Update wrapper registry with configured MeshLlmAgentProxy
            // The requestingFuncId tells us which function needs the LLM agent
            updateWrapperLlmAgent(
                requestingFuncId,
                providerInfo.getEndpoint(),
                providerInfo.getFunctionName(),
                providerInfo.getModel()
            );
        } else {
            log.warn("⚠️ LLM provider event received but provider_info is NULL - event: {}", event);
        }
    }

    /**
     * Update or create MeshLlmAgentProxy with provider information.
     *
     * <p>If proxy already exists (created by handleLlmToolsUpdated), just updates
     * the provider endpoint. Otherwise creates a new proxy with provider.
     *
     * <p>Uses @MeshLlm configuration from MeshLlmRegistry to set up the proxy
     * with the correct system prompt, max iterations, etc.
     *
     * @param funcId       The requesting function ID (consumer)
     * @param endpoint     The provider endpoint URL
     * @param functionName The provider function name
     * @param model        The model name
     */
    private void updateWrapperLlmAgent(String funcId, String endpoint, String functionName, String model) {
        log.info("🔍 updateWrapperLlmAgent called with funcId='{}', endpoint='{}', functionName='{}', model='{}'",
            funcId, endpoint, functionName, model);

        // Log all registered wrappers for debugging
        log.info("  Registered wrappers ({}):", wrapperRegistry.size());
        for (MeshToolWrapper w : wrapperRegistry.getAllWrappers()) {
            log.info("    - funcId='{}', methodName='{}', capability='{}'",
                w.getFuncId(), w.getMethodName(), w.getCapability());
        }

        MeshToolWrapper wrapper = wrapperRegistry.getWrapper(funcId);
        log.info("  Direct lookup by funcId '{}': {}", funcId, wrapper != null ? "FOUND" : "NOT FOUND");

        // If not found by funcId, try by method name or capability (O(1) lookups)
        if (wrapper == null) {
            wrapper = wrapperRegistry.getWrapperByMethodName(funcId);
            if (wrapper != null) {
                log.info("  Found wrapper by method name: {} -> {}", funcId, wrapper.getFuncId());
            } else {
                McpToolHandler handler = wrapperRegistry.getHandlerByCapability(funcId);
                if (handler instanceof MeshToolWrapper w) {
                    wrapper = w;
                    log.info("  Found wrapper by capability: {} -> {}", funcId, w.getFuncId());
                }
            }
        }

        if (wrapper == null) {
            log.warn("❌ No wrapper found for funcId: {} (checked {} wrappers)", funcId, wrapperRegistry.size());
            return;
        }

        // Use the wrapper's actual funcId for registry lookups and composite keys
        String wrapperFuncId = wrapper.getFuncId();

        if (wrapper.getLlmAgentCount() == 0) {
            log.debug("Wrapper {} has no MeshLlmAgent parameters", wrapperFuncId);
            return;
        }

        // Check if proxy already exists (created by handleLlmToolsUpdated)
        log.info("  Current llmAgentProxies keys: {}", llmAgentProxies.keySet());
        MeshLlmAgentProxy existingProxy = llmAgentProxies.get(wrapperFuncId);
        log.info("  Lookup proxy by wrapperFuncId '{}': {}", wrapperFuncId, existingProxy != null ? "FOUND" : "NOT FOUND");

        if (existingProxy != null) {
            // Proxy already exists - just update the provider
            log.info("✅ Updating existing proxy (proxy@{}) with provider: endpoint={}, functionName={}, model={}",
                System.identityHashCode(existingProxy), endpoint, functionName, model);
            existingProxy.updateProvider(endpoint, functionName, model);
            log.info("  Proxy isAvailable after update: {} (providerRef set)", existingProxy.isAvailable());
            return;
        }

        // Get @MeshLlm configuration from registry (using wrapper's full funcId)
        MeshLlmRegistry.LlmConfig config = llmRegistry.getByFunctionId(wrapperFuncId);
        log.info("  Creating NEW proxy (no existing proxy found). LlmConfig: {}", config != null ? "found" : "NOT FOUND");

        // Create and configure proxy for each LLM agent parameter position
        for (int llmIndex = 0; llmIndex < wrapper.getLlmAgentCount(); llmIndex++) {
            MeshLlmAgentProxy proxy = new MeshLlmAgentProxy(wrapperFuncId);
            log.info("  Created new proxy@{} for {} (llmIndex={})",
                System.identityHashCode(proxy), wrapperFuncId, llmIndex);

            // Configure with @MeshLlm settings (or defaults)
            String systemPrompt = config != null ? config.systemPrompt() : "";
            String contextParam = config != null ? config.contextParam() : "ctx";
            int maxIterations = config != null ? config.maxIterations() : 1;
            boolean parallelToolCalls = config != null && config.parallelToolCalls();

            proxy.configure(mcpClient, proxyFactory, toolInvoker, injector, systemPrompt, contextParam, maxIterations, parallelToolCalls);

            // Wire MediaStore for multimodal support
            wireMediaStore(proxy);

            // Set the provider endpoint
            proxy.updateProvider(endpoint, functionName, model);

            // Store proxy for later tool updates (using wrapper's funcId)
            storeProxyWithReverseLookup(wrapperFuncId, proxy);

            // Update the wrapper's LLM agent array (using wrapper's funcId for composite key)
            String compositeKey = MeshToolWrapperRegistry.buildLlmKey(wrapperFuncId, llmIndex);
            wrapperRegistry.updateLlmAgent(compositeKey, proxy);

            // Apply any pending tools that arrived before the proxy was created
            // Check both short funcId and method name extracted from wrapperFuncId
            String methodName = wrapperFuncId.contains(".")
                ? wrapperFuncId.substring(wrapperFuncId.lastIndexOf('.') + 1)
                : wrapperFuncId;

            log.info("Looking for pending tools with keys: methodName='{}', funcId='{}' (pendingTools keys: {})",
                methodName, funcId, pendingTools.keySet());

            List<MeshEvent.LlmToolInfo> tools = pendingTools.remove(methodName);
            if (tools == null) {
                tools = pendingTools.remove(funcId);
            }
            if (tools != null) {
                proxy.updateTools(tools);
                log.info("Applied {} pending tools to LLM agent proxy for {}", tools.size(), wrapperFuncId);
            } else {
                log.debug("No pending tools found for {} (methodName={}, funcId={})", wrapperFuncId, methodName, funcId);
            }

            log.info("Updated LLM agent for {} (index={}, systemPrompt={}, maxIterations={})",
                wrapperFuncId, llmIndex, systemPrompt.isEmpty() ? "<none>" : "<configured>", maxIterations);
        }
    }

    private void handleShutdown(MeshEvent event) {
        log.info("Shutdown event received: {}", event.getReason());
        running.set(false);
    }

    private void handleRegistrationFailed(MeshEvent event) {
        log.error("Registration failed: {}", event.getError());
    }
}
