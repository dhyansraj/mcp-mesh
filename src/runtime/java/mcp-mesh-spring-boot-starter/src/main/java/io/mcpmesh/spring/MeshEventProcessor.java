package io.mcpmesh.spring;

import tools.jackson.databind.ObjectMapper;
import io.mcpmesh.core.MeshEvent;
import io.mcpmesh.types.MeshLlmAgent;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.context.ApplicationContext;
import org.springframework.context.SmartLifecycle;

import java.lang.reflect.Constructor;
import java.lang.reflect.Method;
import java.util.List;
import java.util.Map;
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
    private final ObjectMapper objectMapper;
    private final ApplicationContext applicationContext; // For optional Spring AI bean lookup
    private final AtomicBoolean running = new AtomicBoolean(false);
    private final ExecutorService executor;

    // Track created LLM agent proxies so we can update their tools later
    // Key: funcId, Value: proxy (we only support one LLM agent per function currently)
    private final Map<String, MeshLlmAgentProxy> llmAgentProxies = new ConcurrentHashMap<>();

    // Cache for tools when wrapper is not found (fallback only)
    // With the new flow, proxy is created immediately when tools arrive, so this
    // is only used when wrapper lookup fails (legacy injection mode).
    // Key: short function name (e.g., "analyze"), Value: tools list
    private final Map<String, List<MeshEvent.LlmToolInfo>> pendingTools = new ConcurrentHashMap<>();

    // Track if direct LLM agents have been initialized
    private final AtomicBoolean directLlmInitialized = new AtomicBoolean(false);

    public MeshEventProcessor(
            MeshRuntime runtime,
            MeshDependencyInjector injector,
            MeshToolWrapperRegistry wrapperRegistry,
            MeshLlmRegistry llmRegistry,
            McpHttpClient mcpClient,
            ObjectMapper objectMapper,
            ApplicationContext applicationContext) {
        this.runtime = runtime;
        this.injector = injector;
        this.wrapperRegistry = wrapperRegistry;
        this.llmRegistry = llmRegistry;
        this.mcpClient = mcpClient;
        this.objectMapper = objectMapper;
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
        log.info("Agent registered with mesh: {}", event.getAgentId());

        // Initialize direct LLM agents (only once)
        initializeDirectLlmAgents();
    }

    /**
     * Initialize direct LLM agents (provider="claude" mode).
     *
     * <p>This is called when the agent registers with the mesh.
     * For direct mode, all configuration is available at startup,
     * so we can create and inject the MeshLlmAgentImpl immediately.
     *
     * <p>This is equivalent to Python's initialize_direct_llm_agents().
     *
     * <p>Uses reflection to avoid compile-time dependency on mcp-mesh-spring-ai.
     */
    private void initializeDirectLlmAgents() {
        if (!directLlmInitialized.compareAndSet(false, true)) {
            return; // Already initialized
        }

        Map<String, MeshLlmRegistry.LlmConfig> allConfigs = llmRegistry.getAllConfigs();
        if (allConfigs.isEmpty()) {
            log.debug("No @MeshLlm configurations found");
            return;
        }

        // Try to get SpringAiLlmProvider bean (optional dependency)
        Object springAiProvider = null;
        try {
            springAiProvider = applicationContext.getBean("springAiLlmProvider");
        } catch (Exception e) {
            log.debug("SpringAiLlmProvider not available (mcp-mesh-spring-ai not on classpath)");
        }

        for (Map.Entry<String, MeshLlmRegistry.LlmConfig> entry : allConfigs.entrySet()) {
            String funcId = entry.getKey();
            MeshLlmRegistry.LlmConfig config = entry.getValue();

            // Only process direct mode (not mesh delegation)
            if (config.isMeshDelegation()) {
                log.debug("Skipping mesh delegation LLM config: {}", funcId);
                continue;
            }

            String provider = config.directProvider();
            log.info("Initializing direct LLM agent for {} (provider={})", funcId, provider);

            // Check if SpringAiLlmProvider is available
            if (springAiProvider == null) {
                log.warn("SpringAiLlmProvider not available for direct LLM mode. " +
                    "Add mcp-mesh-spring-ai dependency for @MeshLlm(provider=\"{}\") to work.", provider);
                continue;
            }

            // Check if the provider is available (API key configured) using reflection
            try {
                Method isAvailableMethod = springAiProvider.getClass().getMethod("isProviderAvailable", String.class);
                Boolean isAvailable = (Boolean) isAvailableMethod.invoke(springAiProvider, provider);
                if (!isAvailable) {
                    log.warn("LLM provider '{}' not available for {}. " +
                        "Check that the API key is configured (e.g., ANTHROPIC_API_KEY).",
                        provider, funcId);
                    continue;
                }
            } catch (Exception e) {
                log.error("Failed to check provider availability: {}", e.getMessage());
                continue;
            }

            // Find the wrapper for this function
            MeshToolWrapper wrapper = wrapperRegistry.getWrapper(funcId);
            if (wrapper == null) {
                log.debug("No wrapper found for funcId: {} (may not have MeshLlmAgent parameter)", funcId);
                continue;
            }

            if (wrapper.getLlmAgentCount() == 0) {
                log.debug("Wrapper {} has no MeshLlmAgent parameters", funcId);
                continue;
            }

            // Create MeshLlmAgentImpl for direct mode using reflection
            try {
                Class<?> agentImplClass = Class.forName("io.mcpmesh.ai.MeshLlmAgentImpl");
                Constructor<?> constructor = agentImplClass.getConstructor(
                    String.class,           // functionId
                    springAiProvider.getClass(), // llmProvider (SpringAiLlmProvider)
                    String.class,           // provider
                    String.class,           // systemPrompt
                    int.class,              // maxIterations
                    int.class,              // maxTokens
                    double.class,           // temperature
                    ObjectMapper.class      // objectMapper
                );

                MeshLlmAgent agent = (MeshLlmAgent) constructor.newInstance(
                    funcId,
                    springAiProvider,
                    provider,
                    config.systemPrompt(),
                    config.maxIterations(),
                    config.maxTokens(),
                    config.temperature(),
                    objectMapper
                );

                // Inject into each LLM agent parameter position in the wrapper
                for (int llmIndex = 0; llmIndex < wrapper.getLlmAgentCount(); llmIndex++) {
                    String compositeKey = MeshToolWrapperRegistry.buildLlmKey(funcId, llmIndex);
                    wrapperRegistry.updateLlmAgent(compositeKey, agent);

                    log.info("Initialized direct LLM agent for {} (provider={}, index={}, available={})",
                        funcId, provider, llmIndex, agent.isAvailable());
                }
            } catch (ClassNotFoundException e) {
                log.warn("MeshLlmAgentImpl not found. Add mcp-mesh-spring-ai dependency for direct LLM mode.");
            } catch (Exception e) {
                log.error("Failed to create direct LLM agent for {}: {}", funcId, e.getMessage(), e);
            }
        }
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
            String wrapperFuncId = null;

            if (proxy == null) {
                // Search by method name suffix (funcId might be just the method name)
                for (Map.Entry<String, MeshLlmAgentProxy> entry : llmAgentProxies.entrySet()) {
                    String key = entry.getKey();
                    // Match if key ends with ".funcId" (full class path) or equals funcId
                    if (key.endsWith("." + funcId) || key.equals(funcId)) {
                        proxy = entry.getValue();
                        wrapperFuncId = key;
                        log.info("Found LLM proxy by method name: {} -> {}", funcId, key);
                        break;
                    }
                }
            }

            if (proxy != null) {
                proxy.updateTools(event.getTools());
                log.info("Updated {} tools on LLM agent proxy for {}", event.getTools().size(), funcId);
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
        // Find wrapper by method name or capability
        MeshToolWrapper wrapper = null;
        for (MeshToolWrapper w : wrapperRegistry.getAllWrappers()) {
            if (w.getMethodName().equals(funcId) || w.getCapability().equals(funcId)) {
                wrapper = w;
                break;
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

            proxy.configure(mcpClient, injector, systemPrompt, contextParam, maxIterations);

            // Apply tools immediately
            proxy.updateTools(tools);

            // Store proxy for later provider updates
            llmAgentProxies.put(wrapperFuncId, proxy);

            // Update the wrapper's LLM agent array
            String compositeKey = MeshToolWrapperRegistry.buildLlmKey(wrapperFuncId, llmIndex);
            wrapperRegistry.updateLlmAgent(compositeKey, proxy);

            log.info("Created LLM agent for {} (index={}, tools={}, provider=pending)",
                wrapperFuncId, llmIndex, tools.size());
        }

        return proxy;
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
            log.info("LLM provider available for {}: {} at {}",
                requestingFuncId, providerInfo.getModel(), providerInfo.getEndpoint());

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
            log.debug("LLM provider event without provider info");
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
        MeshToolWrapper wrapper = wrapperRegistry.getWrapper(funcId);

        // If not found by funcId, try by method name (funcId might be just the function name from registry)
        if (wrapper == null) {
            // Search all wrappers for matching method name
            for (MeshToolWrapper w : wrapperRegistry.getAllWrappers()) {
                if (w.getMethodName().equals(funcId) || w.getCapability().equals(funcId)) {
                    wrapper = w;
                    log.debug("Found wrapper by method name/capability: {} -> {}", funcId, w.getFuncId());
                    break;
                }
            }
        }

        if (wrapper == null) {
            log.debug("No wrapper found for funcId: {} (may be using legacy injection)", funcId);
            return;
        }

        // Use the wrapper's actual funcId for registry lookups and composite keys
        String wrapperFuncId = wrapper.getFuncId();

        if (wrapper.getLlmAgentCount() == 0) {
            log.debug("Wrapper {} has no MeshLlmAgent parameters", wrapperFuncId);
            return;
        }

        // Check if proxy already exists (created by handleLlmToolsUpdated)
        MeshLlmAgentProxy existingProxy = llmAgentProxies.get(wrapperFuncId);

        if (existingProxy != null) {
            // Proxy already exists - just update the provider
            existingProxy.updateProvider(endpoint, functionName, model);
            log.info("Updated provider on existing LLM agent proxy for {} (endpoint={}, model={})",
                wrapperFuncId, endpoint, model);
            return;
        }

        // Get @MeshLlm configuration from registry (using wrapper's full funcId)
        MeshLlmRegistry.LlmConfig config = llmRegistry.getByFunctionId(wrapperFuncId);

        // Create and configure proxy for each LLM agent parameter position
        for (int llmIndex = 0; llmIndex < wrapper.getLlmAgentCount(); llmIndex++) {
            MeshLlmAgentProxy proxy = new MeshLlmAgentProxy(wrapperFuncId);

            // Configure with @MeshLlm settings (or defaults)
            String systemPrompt = config != null ? config.systemPrompt() : "";
            String contextParam = config != null ? config.contextParam() : "ctx";
            int maxIterations = config != null ? config.maxIterations() : 1;

            proxy.configure(mcpClient, injector, systemPrompt, contextParam, maxIterations);

            // Set the provider endpoint
            proxy.updateProvider(endpoint, functionName, model);

            // Store proxy for later tool updates (using wrapper's funcId)
            llmAgentProxies.put(wrapperFuncId, proxy);

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
