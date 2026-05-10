package io.mcpmesh.spring;

import tools.jackson.databind.ObjectMapper;
import io.mcpmesh.core.MeshObjectMappers;
import io.mcpmesh.MeshAgent;
import io.mcpmesh.Selector;
import io.mcpmesh.core.AgentSpec;
import io.mcpmesh.spring.web.MeshRouteRegistry;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.autoconfigure.condition.ConditionalOnClass;
import org.springframework.boot.autoconfigure.condition.ConditionalOnMissingBean;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.boot.web.server.context.WebServerInitializedEvent;
import org.springframework.boot.web.servlet.FilterRegistrationBean;
import org.springframework.core.Ordered;
import org.springframework.context.ApplicationContext;
import org.springframework.context.ApplicationListener;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

import io.mcpmesh.spring.tracing.TracingFilter;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.UUID;

/**
 * Spring Boot auto-configuration for MCP Mesh.
 *
 * <p>This configuration is automatically applied when the MCP Mesh SDK
 * is on the classpath and a class annotated with {@link MeshAgent} is found.
 *
 * <h2>Bean Order</h2>
 * <ol>
 *   <li>{@link MeshToolRegistry} - Collects tool metadata</li>
 *   <li>{@link MeshToolBeanPostProcessor} - Scans beans for @MeshTool</li>
 *   <li>{@link MeshDependencyInjector} - Creates dependency proxies</li>
 *   <li>{@link MeshRuntime} - Manages Rust core lifecycle</li>
 *   <li>{@link MeshEventProcessor} - Handles mesh events</li>
 * </ol>
 */
@Configuration
@ConditionalOnClass(MeshAgent.class)
@EnableConfigurationProperties(MeshProperties.class)
public class MeshAutoConfiguration {

    private static final Logger log = LoggerFactory.getLogger(MeshAutoConfiguration.class);

    @Autowired
    private ApplicationContext applicationContext;

    @Bean
    @ConditionalOnMissingBean
    public static MeshToolRegistry meshToolRegistry() {
        return new MeshToolRegistry();
    }

    @Bean
    @ConditionalOnMissingBean
    public static McpMeshToolProxyFactory mcpMeshToolProxyFactory() {
        return new McpMeshToolProxyFactory();
    }

    @Bean
    @ConditionalOnMissingBean
    public static MeshToolWrapperRegistry meshToolWrapperRegistry(McpMeshToolProxyFactory proxyFactory) {
        return new MeshToolWrapperRegistry(proxyFactory);
    }

    @Bean
    @ConditionalOnMissingBean
    public ToolInvoker toolInvoker(
            McpMeshToolProxyFactory proxyFactory,
            MeshToolWrapperRegistry wrapperRegistry,
            MeshRuntime runtime) {
        // Full ToolInvoker with self-dependency optimization support.
        // Uses the unique per-replica agent ID so dependency events (which carry
        // full agent IDs) can be compared directly against currentAgentId.
        String agentId = runtime.getAgentSpec().getAgentId();
        return new ToolInvoker(proxyFactory, wrapperRegistry, agentId);
    }

    @Bean
    @ConditionalOnMissingBean
    public static ObjectMapper meshObjectMapper() {
        return MeshObjectMappers.create();
    }

    @Bean
    @ConditionalOnMissingBean
    public static MeshToolBeanPostProcessor meshToolBeanPostProcessor(
            MeshToolRegistry registry,
            MeshToolWrapperRegistry wrapperRegistry,
            ObjectMapper objectMapper,
            A2AConsumerBeanPostProcessor a2aConsumerBeanPostProcessor) {
        return new MeshToolBeanPostProcessor(registry, wrapperRegistry, objectMapper,
            a2aConsumerBeanPostProcessor);
    }

    /**
     * Issue #923: scans @A2AConsumer methods at boot, constructs an
     * A2AClient per unique (url, skillId, auth, timeout) tuple, and
     * exposes a per-method binding for MeshToolWrapper to inject the
     * cached client at the A2AClient parameter slot at invoke time.
     *
     * <p>Static factory so this processor is instantiated before user
     * beans are created — the same pattern as MeshToolBeanPostProcessor.
     */
    @Bean
    @ConditionalOnMissingBean
    public static A2AConsumerBeanPostProcessor a2aConsumerBeanPostProcessor(
            org.springframework.core.env.Environment environment) {
        return new A2AConsumerBeanPostProcessor(environment);
    }

    @Bean
    @ConditionalOnMissingBean
    public static MeshLlmRegistry meshLlmRegistry() {
        return new MeshLlmRegistry();
    }

    @Bean
    @ConditionalOnMissingBean
    public static PromptTemplateRenderer promptTemplateRenderer() {
        return new PromptTemplateRenderer();
    }

    @Bean
    @ConditionalOnMissingBean
    public static MeshLlmBeanPostProcessor meshLlmBeanPostProcessor(MeshLlmRegistry llmRegistry) {
        return new MeshLlmBeanPostProcessor(llmRegistry);
    }

    @Bean
    @ConditionalOnMissingBean
    public MeshDependencyInjector meshDependencyInjector(
            McpHttpClient mcpHttpClient,
            McpMeshToolProxyFactory proxyFactory,
            ToolInvoker toolInvoker) {
        return new MeshDependencyInjector(mcpHttpClient, proxyFactory, toolInvoker);
    }

    @Bean
    @ConditionalOnMissingBean
    public MeshConfigResolver meshConfigResolver() {
        return new MeshConfigResolver();
    }

    @Bean
    @ConditionalOnMissingBean
    public MeshRuntime meshRuntime(
            MeshProperties properties,
            MeshToolRegistry toolRegistry,
            MeshToolWrapperRegistry wrapperRegistry,
            MeshLlmRegistry llmRegistry,
            MeshConfigResolver configResolver,
            ObjectMapper objectMapper,
            ObjectProvider<MeshRouteRegistry> routeRegistryProvider) {

        AgentSpec spec = buildAgentSpec(properties, toolRegistry, wrapperRegistry, llmRegistry, configResolver, objectMapper, routeRegistryProvider);
        log.info("Creating MeshRuntime for agent '{}' with {} tools",
            spec.getName(), spec.getTools().size());

        return new MeshRuntime(spec, objectMapper);
    }

    @Bean
    @ConditionalOnMissingBean(name = "meshPortUpdater")
    public ApplicationListener<WebServerInitializedEvent> meshPortUpdater(MeshRuntime runtime) {
        return event -> {
            int actualPort = event.getWebServer().getPort();
            int specPort = runtime.getAgentSpec().getHttpPort();
            if (specPort == 0 || specPort != actualPort) {
                log.info("Web server started on port {}. Updating mesh registry (spec port was {})",
                    actualPort, specPort);
                runtime.updatePort(actualPort);
            }
        };
    }

    @Bean
    @ConditionalOnMissingBean(name = "meshTracingFilter")
    public FilterRegistrationBean<TracingFilter> tracingFilterRegistration() {
        FilterRegistrationBean<TracingFilter> registration = new FilterRegistrationBean<>();
        registration.setFilter(new TracingFilter());
        registration.addUrlPatterns("/*");
        registration.setOrder(Ordered.HIGHEST_PRECEDENCE);
        registration.setName("meshTracingFilter");
        return registration;
    }

    @Bean
    @ConditionalOnMissingBean
    public McpHttpClient mcpHttpClient(ObjectMapper objectMapper) {
        return new McpHttpClient(objectMapper);
    }

    @Bean
    @ConditionalOnMissingBean
    public MeshEventProcessor meshEventProcessor(
            MeshRuntime runtime,
            MeshDependencyInjector injector,
            MeshToolWrapperRegistry wrapperRegistry,
            MeshLlmRegistry llmRegistry,
            McpHttpClient mcpHttpClient,
            McpMeshToolProxyFactory proxyFactory,
            ToolInvoker toolInvoker,
            ApplicationContext applicationContext) {

        return new MeshEventProcessor(runtime, injector, wrapperRegistry,
            llmRegistry, mcpHttpClient, proxyFactory, toolInvoker, applicationContext);
    }

    @Bean
    @ConditionalOnMissingBean
    public MeshHealthController meshHealthController(ObjectProvider<MeshRuntime> runtimeProvider) {
        MeshRuntime runtime = runtimeProvider.getIfAvailable();
        return new MeshHealthController(runtime);
    }

    /**
     * Phase B MeshJob substrate: cancel route handler. Mounted on every
     * mesh agent so the registry can forward cancel signals to owner
     * replicas. Safe to register unconditionally — Spring MVC only
     * invokes the handler on POST /jobs/{jobId}/cancel matches.
     */
    @Bean
    @ConditionalOnMissingBean
    public JobCancelController jobCancelController() {
        return new JobCancelController();
    }

    /**
     * Phase B MeshJob substrate: orchestrator that wires producers,
     * consumers, and helper tools together once the mesh runtime is up.
     * SmartLifecycle phase ensures it starts AFTER MeshRuntime and stops
     * BEFORE it (so dispatchers drain in-flight handlers cleanly).
     */
    @Bean
    @ConditionalOnMissingBean
    public JobsRuntimeManager jobsRuntimeManager(
            MeshRuntime runtime,
            MeshToolRegistry toolRegistry,
            MeshToolWrapperRegistry wrapperRegistry,
            A2AConsumerBeanPostProcessor a2aConsumerBeanPostProcessor) {
        return new JobsRuntimeManager(runtime, toolRegistry, wrapperRegistry,
            a2aConsumerBeanPostProcessor);
    }

    private AgentSpec buildAgentSpec(
            MeshProperties properties,
            MeshToolRegistry toolRegistry,
            MeshToolWrapperRegistry wrapperRegistry,
            MeshLlmRegistry llmRegistry,
            MeshConfigResolver configResolver,
            ObjectMapper objectMapper,
            ObjectProvider<MeshRouteRegistry> routeRegistryProvider) {

        // Find @MeshAgent annotation
        MeshAgent agentAnnotation = findMeshAgentAnnotation();

        AgentSpec spec = new AgentSpec();

        // Resolve name - either from annotation, properties, or env
        String annotationName = agentAnnotation != null ? agentAnnotation.name() : null;
        String propertiesName = properties.getAgent().getName();
        String paramName = (annotationName != null && !annotationName.isBlank()) ? annotationName : propertiesName;
        String name = configResolver.resolve("agent_name", paramName);

        if (name == null || name.isBlank()) {
            // No agent name configured — check if this is consumer-only mode.
            // Force RestController beans to be created first so MeshRouteBeanPostProcessor
            // populates MeshRouteRegistry before we check it.
            applicationContext.getBeansWithAnnotation(
                org.springframework.web.bind.annotation.RestController.class);
            MeshRouteRegistry routeRegistry = routeRegistryProvider.getIfAvailable();
            if (routeRegistry != null && routeRegistry.hasRoutes()) {
                log.info("No @MeshAgent found, but @MeshRoute dependencies detected — starting in consumer-only mode");
                return buildConsumerAgentSpec(properties, configResolver, routeRegistryProvider);
            }
            throw new IllegalStateException(
                "Agent name is required. Set MCP_MESH_AGENT_NAME, mesh.agent.name, or @MeshAgent(name=...)");
        }

        // Append UUID suffix like Python/TypeScript SDKs: {name}-{8char_uuid}.
        // `name` stays as the base (shared across replicas); `agentId` is the
        // unique per-replica identifier.
        String uuidSuffix = UUID.randomUUID().toString().replace("-", "").substring(0, 8);
        String agentId = name + "-" + uuidSuffix;
        spec.setName(name);
        spec.setAgentId(agentId);

        // Resolve version (not a Rust config key, use annotation/properties directly)
        String version = agentAnnotation != null ? agentAnnotation.version() : null;
        if (version == null || version.isBlank()) {
            version = properties.getAgent().getVersion();
        }
        spec.setVersion(version);

        // Resolve port
        int annotationPort = agentAnnotation != null ? agentAnnotation.port() : 0;
        int propertiesPort = properties.getAgent().getPort();
        int paramPort = annotationPort > 0 ? annotationPort : propertiesPort;
        spec.setHttpPort(configResolver.resolveInt("http_port", paramPort > 0 ? paramPort : 0));

        // Resolve host (Rust auto-detects IP if null/empty)
        String annotationHost = agentAnnotation != null ? agentAnnotation.host() : null;
        String propertiesHost = properties.getAgent().getHost();
        String paramHost = (annotationHost != null && !annotationHost.isBlank()) ? annotationHost : propertiesHost;
        spec.setHttpHost(configResolver.resolve("http_host", paramHost));

        // Resolve namespace
        String annotationNamespace = agentAnnotation != null ? agentAnnotation.namespace() : null;
        String propertiesNamespace = properties.getAgent().getNamespace();
        String paramNamespace = (annotationNamespace != null && !annotationNamespace.isBlank()) ? annotationNamespace : propertiesNamespace;
        spec.setNamespace(configResolver.resolve("namespace", paramNamespace));

        // Resolve heartbeat interval (Rust key is "health_interval")
        int annotationHeartbeat = agentAnnotation != null ? agentAnnotation.heartbeatInterval() : 0;
        int propertiesHeartbeat = properties.getAgent().getHeartbeatInterval();
        int paramHeartbeat = annotationHeartbeat > 0 ? annotationHeartbeat : propertiesHeartbeat;
        int heartbeat = configResolver.resolveInt("health_interval", paramHeartbeat > 0 ? paramHeartbeat : -1);
        spec.setHeartbeatInterval(heartbeat > 0 ? heartbeat : 5);  // Default to 5 if unset

        // Registry URL
        String propertiesRegistryUrl = properties.getRegistry().getUrl();
        spec.setRegistryUrl(configResolver.resolve("registry_url", propertiesRegistryUrl));

        // Phase B MeshJob substrate: register the three helper tools as
        // synthetic specs BEFORE getToolSpecs() is read into the
        // heartbeat catalog. Without this the registry never learns the
        // helpers exist (they were registered too late in JobsRuntimeManager).
        // Also registers the wrapper-side handlers so MCP tools/call
        // requests for the helper names dispatch correctly. Skips
        // gracefully when no registry URL is configured.
        String resolvedRegistryUrl = configResolver.resolve("registry_url",
            properties.getRegistry().getUrl());
        try {
            JobsHelperToolsRegistrar.register(toolRegistry, wrapperRegistry, resolvedRegistryUrl);
        } catch (Exception e) {
            log.warn("Failed to register MeshJob helper tools at startup", e);
        }

        // Issue #916 Phase 1: inject the surrounding @MeshAgent name as
        // a tag on every @A2AConsumer-annotated tool BEFORE
        // toolRegistry.getToolSpecs() snapshots the catalog. Mirrors
        // Python's _resolve_pending_consumer_self_tags substitution —
        // makes a bridged capability distinguishable from sibling
        // consumers in the registry, so downstream dependencies can
        // pin a specific bridge by tag and untagged dependencies still
        // auto-fail-over when one bridge dies.
        try {
            toolRegistry.injectConsumerNameTags(name);
        } catch (Exception e) {
            log.warn("Failed to inject @A2AConsumer auto-tags for agent '{}': {}",
                name, e.getMessage());
        }

        // Add tools from registry (dependencies are embedded in tool specs)
        List<AgentSpec.ToolSpec> allTools = new ArrayList<>(toolRegistry.getToolSpecs());

        // Enrich tools with @MeshLlm provider info for mesh delegation
        enrichToolsWithLlmProvider(allTools, toolRegistry, llmRegistry, objectMapper);

        // Add LLM provider tools if mcp-mesh-spring-ai is on classpath
        addLlmProviderTools(allTools, wrapperRegistry);

        // Add @MeshRoute dependencies as a synthetic tool
        addRouteDependencies(allTools, routeRegistryProvider);

        spec.setTools(allTools);

        return spec;
    }

    /**
     * Build a consumer-only AgentSpec for apps that use @MeshRoute without @MeshAgent.
     *
     * <p>Consumer-only mode creates a lightweight mesh client that resolves dependencies
     * from the registry without registering as a full MCP agent. The agent type is set
     * to "api" which tells the Rust core this is a consumer-only client.
     *
     * @param properties            Mesh configuration properties
     * @param configResolver        Environment variable resolver
     * @param routeRegistryProvider Provider for MeshRouteRegistry
     * @return AgentSpec configured for consumer-only mode
     */
    private AgentSpec buildConsumerAgentSpec(
            MeshProperties properties,
            MeshConfigResolver configResolver,
            ObjectProvider<MeshRouteRegistry> routeRegistryProvider) {

        AgentSpec spec = new AgentSpec();

        // Derive an app-specific base name so unrelated Spring apps in consumer-only
        // mode don't collapse together in the topology as replicas of "api".
        // Priority: MCP_MESH_AGENT_NAME env/property (via configResolver) >
        //           spring.application.name > "api" fallback.
        String appName = configResolver.resolve("agent_name", null);
        if (appName == null || appName.isBlank()) {
            appName = applicationContext.getEnvironment().getProperty("spring.application.name");
        }
        if (appName == null || appName.isBlank()) {
            appName = "api";
        }

        // Auto-generated ID: {appName}-{8char_uuid} (matches Python's pattern).
        // Base name is shared across replicas; full ID includes the UUID suffix.
        String uuidSuffix = UUID.randomUUID().toString().replace("-", "").substring(0, 8);
        spec.setName(appName);
        spec.setAgentId(appName + "-" + uuidSuffix);

        // Consumer-only agent type
        spec.setAgentType("api");

        // Port 0 — updated by meshPortUpdater when Tomcat starts
        spec.setHttpPort(0);

        // Host — auto-detected via Rust core, or from property/env
        String propertiesHost = properties.getAgent().getHost();
        spec.setHttpHost(configResolver.resolve("http_host", propertiesHost));

        // Namespace
        String propertiesNamespace = properties.getAgent().getNamespace();
        spec.setNamespace(configResolver.resolve("namespace", propertiesNamespace));

        // Heartbeat interval
        int propertiesHeartbeat = properties.getAgent().getHeartbeatInterval();
        int heartbeat = configResolver.resolveInt("health_interval", propertiesHeartbeat > 0 ? propertiesHeartbeat : -1);
        spec.setHeartbeatInterval(heartbeat > 0 ? heartbeat : 5);

        // Registry URL
        String propertiesRegistryUrl = properties.getRegistry().getUrl();
        spec.setRegistryUrl(configResolver.resolve("registry_url", propertiesRegistryUrl));

        // No tools or LLM agents — only route dependencies
        List<AgentSpec.ToolSpec> tools = new ArrayList<>();
        addRouteDependencies(tools, routeRegistryProvider);
        spec.setTools(tools);

        log.info("Consumer-only AgentSpec: name='{}', agentType='api', dependencies={}",
            spec.getName(), tools.size());

        return spec;
    }

    /**
     * Add @MeshRoute dependencies as a synthetic tool for registry resolution.
     *
     * <p>Route dependencies are not part of any @MeshTool, so we create a
     * synthetic tool called "__mesh_route_deps" that declares all unique
     * route dependencies. This allows the Rust core to resolve them via
     * the registry's dependency resolution mechanism.
     *
     * @param tools                 List to add the synthetic tool to
     * @param routeRegistryProvider Provider for MeshRouteRegistry
     */
    private void addRouteDependencies(List<AgentSpec.ToolSpec> tools,
                                      ObjectProvider<MeshRouteRegistry> routeRegistryProvider) {
        MeshRouteRegistry routeRegistry = routeRegistryProvider.getIfAvailable();
        if (routeRegistry == null || !routeRegistry.hasRoutes()) {
            return;
        }

        List<AgentSpec.DependencySpec> routeDeps = routeRegistry.getUniqueDependencySpecs();
        if (routeDeps.isEmpty()) {
            log.debug("No @MeshRoute dependencies to register");
            return;
        }

        // Create synthetic tool for route dependencies
        AgentSpec.ToolSpec routeDepsTool = new AgentSpec.ToolSpec();
        routeDepsTool.setFunctionName("__mesh_route_deps");
        routeDepsTool.setCapability("__mesh_route_deps");
        routeDepsTool.setDescription("Synthetic tool for @MeshRoute dependency resolution");
        routeDepsTool.setDependencies(routeDeps);

        tools.add(routeDepsTool);

        log.info("Added {} @MeshRoute dependencies to agent registration", routeDeps.size());
    }

    /**
     * Enrich tool specs with @MeshLlm provider selector info for mesh delegation.
     *
     * <p>For each tool with a corresponding @MeshLlm annotation that uses mesh delegation
     * (providerSelector), this sets the llmProvider field on the ToolSpec so the registry
     * knows to discover and route LLM calls for this tool.
     *
     * @param tools        List of tool specs to enrich
     * @param toolRegistry Tool registry to get method info
     * @param llmRegistry  LLM registry with @MeshLlm configs
     * @param objectMapper Jackson ObjectMapper for JSON serialization
     */
    private void enrichToolsWithLlmProvider(
            List<AgentSpec.ToolSpec> tools,
            MeshToolRegistry toolRegistry,
            MeshLlmRegistry llmRegistry,
            ObjectMapper objectMapper) {

        for (AgentSpec.ToolSpec toolSpec : tools) {
            // Look up the tool metadata to get the full funcId
            MeshToolRegistry.ToolMetadata meta = toolRegistry.getTool(toolSpec.getCapability());
            if (meta == null) {
                continue;
            }

            // Build funcId in the format used by MeshLlmRegistry
            String funcId = meta.bean().getClass().getName() + "." + meta.method().getName();

            // Look up @MeshLlm config
            MeshLlmRegistry.LlmConfig llmConfig = llmRegistry.getByFunctionId(funcId);
            if (llmConfig == null) {
                continue;
            }

            // Set llmProvider for mesh delegation. After v2, MeshLlmRegistry
            // rejects @MeshLlm with an empty providerSelector at register-time,
            // so this branch should always succeed; the null/empty guard stays
            // as defense-in-depth in case of future code paths that bypass
            // registration validation.
            Selector selector = llmConfig.providerSelector();
            if (selector == null || selector.capability() == null || selector.capability().isEmpty()) {
                log.warn("@MeshLlm on tool '{}' has empty providerSelector — skipping llmProvider enrichment "
                    + "(this should be unreachable after v2; report as a bug)", toolSpec.getCapability());
            } else {
                try {
                    // Build llmProvider JSON: {"capability": "llm", "tags": ["+claude", "+anthropic"]}
                    java.util.Map<String, Object> providerMap = new java.util.LinkedHashMap<>();
                    providerMap.put("capability", selector.capability());
                    providerMap.put("tags", java.util.Arrays.asList(selector.tags()));
                    if (!selector.version().isEmpty()) {
                        providerMap.put("version", selector.version());
                    }

                    String llmProviderJson = objectMapper.writeValueAsString(providerMap);
                    toolSpec.setLlmProvider(llmProviderJson);

                    log.debug("Set llmProvider on tool '{}': {}", toolSpec.getCapability(), llmProviderJson);
                } catch (Exception e) {
                    log.warn("Failed to serialize llmProvider for tool '{}': {}",
                        toolSpec.getCapability(), e.getMessage());
                }
            }

            // Set llmFilter if configured
            // Registry expects: {"filter": [...], "filter_mode": "all"|"best_match"|"wildcard"}
            Selector[] filters = llmConfig.filters();
            if (filters != null && filters.length > 0) {
                try {
                    // Build filter array (supports multiple selectors)
                    java.util.List<java.util.Map<String, Object>> filterArray = new java.util.ArrayList<>();
                    for (Selector filter : filters) {
                        java.util.Map<String, Object> selectorMap = new java.util.LinkedHashMap<>();
                        if (!filter.capability().isEmpty()) {
                            selectorMap.put("capability", filter.capability());
                        }
                        if (filter.tags().length > 0) {
                            selectorMap.put("tags", java.util.Arrays.asList(filter.tags()));
                        }
                        if (!filter.version().isEmpty()) {
                            selectorMap.put("version", filter.version());
                        }
                        filterArray.add(selectorMap);
                    }

                    // Build llmFilter with filter array and filter_mode
                    java.util.Map<String, Object> llmFilterMap = new java.util.LinkedHashMap<>();
                    llmFilterMap.put("filter", filterArray);

                    // Convert filterMode ordinal to string
                    String filterModeStr = switch (llmConfig.filterMode()) {
                        case 0 -> "all";
                        case 1 -> "best_match";
                        case 2 -> "wildcard";
                        default -> "all";
                    };
                    llmFilterMap.put("filter_mode", filterModeStr);

                    String llmFilterJson = objectMapper.writeValueAsString(llmFilterMap);
                    toolSpec.setLlmFilter(llmFilterJson);

                    log.debug("Set llmFilter on tool '{}': {}", toolSpec.getCapability(), llmFilterJson);
                } catch (Exception e) {
                    log.warn("Failed to serialize llmFilter for tool '{}': {}",
                        toolSpec.getCapability(), e.getMessage());
                }
            }
        }
    }

    /**
     * Add LLM provider tool specs and register handlers if spring-ai module is available.
     *
     * <p>This method uses reflection to avoid hard dependency on mcp-mesh-spring-ai.
     * If the module is present and has registered providers:
     * <ol>
     *   <li>Tool specs are added to agent registration (for heartbeat)</li>
     *   <li>Tool wrappers are registered with wrapper registry (for MCP calls)</li>
     * </ol>
     *
     * @param tools           List to add LLM provider tools to
     * @param wrapperRegistry Registry to add LLM provider handlers to
     */
    @SuppressWarnings("unchecked")
    private void addLlmProviderTools(List<AgentSpec.ToolSpec> tools, MeshToolWrapperRegistry wrapperRegistry) {
        try {
            // Check if MeshLlmProviderProcessor class exists (spring-ai module)
            Class<?> processorClass = Class.forName("io.mcpmesh.ai.MeshLlmProviderProcessor");

            // Try to get the bean from application context
            Object processor = applicationContext.getBean(processorClass);

            // Check if it has providers
            java.lang.reflect.Method hasProvidersMethod = processorClass.getMethod("hasProviders");
            Boolean hasProviders = (Boolean) hasProvidersMethod.invoke(processor);

            if (Boolean.TRUE.equals(hasProviders)) {
                // Get tool specs from the processor (for heartbeat)
                java.lang.reflect.Method getToolSpecsMethod = processorClass.getMethod("getToolSpecs");
                List<AgentSpec.ToolSpec> llmTools = (List<AgentSpec.ToolSpec>) getToolSpecsMethod.invoke(processor);
                tools.addAll(llmTools);

                // Get tool wrappers from the processor (for MCP calls)
                java.lang.reflect.Method createToolWrappersMethod = processorClass.getMethod("createToolWrappers");
                List<?> wrappers = (List<?>) createToolWrappersMethod.invoke(processor);

                // Register each wrapper with the registry
                for (Object wrapper : wrappers) {
                    // Cast to McpToolHandler (LlmProviderToolWrapper implements it)
                    if (wrapper instanceof McpToolHandler handler) {
                        wrapperRegistry.registerHandler(handler);
                    }
                }

                log.info("Added {} LLM provider tool(s) to agent registration and MCP server",
                    llmTools.size());
            }
        } catch (ClassNotFoundException e) {
            // mcp-mesh-spring-ai not on classpath - this is fine
            log.debug("MeshLlmProviderProcessor not found - LLM provider support not enabled");
        } catch (org.springframework.beans.factory.NoSuchBeanDefinitionException e) {
            // Processor class exists but no bean registered
            log.debug("MeshLlmProviderProcessor not registered as bean");
        } catch (Exception e) {
            log.warn("Failed to check for LLM provider tools: {}", e.getMessage());
        }
    }

    private MeshAgent findMeshAgentAnnotation() {
        Map<String, Object> beans = applicationContext.getBeansWithAnnotation(MeshAgent.class);
        if (!beans.isEmpty()) {
            Object firstBean = beans.values().iterator().next();
            // Get the target class (unwrap CGLIB proxies)
            Class<?> targetClass = org.springframework.aop.support.AopUtils.getTargetClass(firstBean);
            return org.springframework.core.annotation.AnnotationUtils.findAnnotation(targetClass, MeshAgent.class);
        }
        return null;
    }
}
