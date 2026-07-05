package io.mcpmesh.spring;

import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.json.JsonMapper;
import io.mcpmesh.core.MeshObjectMappers;
import io.mcpmesh.MeshAgent;
import io.mcpmesh.Selector;
import io.mcpmesh.core.AgentSpec;
import io.mcpmesh.spring.web.MeshA2AAuthFilter;
import io.mcpmesh.spring.web.MeshA2ABeanPostProcessor;
import io.mcpmesh.spring.web.MeshA2ACardBuilder;
import io.mcpmesh.spring.web.MeshA2ADispatcher;
import io.mcpmesh.spring.web.MeshA2ADispatcherController;
import io.mcpmesh.spring.web.MeshA2APublicUrlCache;
import io.mcpmesh.spring.web.MeshA2ARegistry;
import io.mcpmesh.spring.web.MeshA2ASseDispatcher;
import io.mcpmesh.spring.web.MeshA2ASseHeaderFilter;
import io.mcpmesh.spring.web.MeshA2ATaskStore;
import io.mcpmesh.spring.web.MeshDependency;
import io.mcpmesh.spring.web.MeshDependsOn;
import io.mcpmesh.spring.web.MeshRouteRegistry;
import io.mcpmesh.types.McpMeshTool;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.beans.factory.SmartInitializingSingleton;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.beans.factory.config.ConfigurableListableBeanFactory;
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
import org.springframework.web.servlet.function.RouterFunction;
import org.springframework.web.servlet.function.RouterFunctions;
import org.springframework.web.servlet.function.ServerResponse;

import io.mcpmesh.spring.tracing.TracingFilter;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
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

    private static final String A2A_DEPS_TOOL = "__mesh_a2a_deps";
    private static final String DEPENDS_ON_DEPS_TOOL = "__mesh_depends_on_deps";
    private static final String ROUTE_DEPS_TOOL = "__mesh_route_deps";
    private static final String SERVICE_DEPS_TOOL = "__mesh_service_deps";

    @Autowired
    private ApplicationContext applicationContext;

    private static AgentSpec.ToolSpec syntheticDepsTool(
            String name, String description, List<AgentSpec.DependencySpec> deps) {
        AgentSpec.ToolSpec tool = new AgentSpec.ToolSpec();
        tool.setFunctionName(name);
        tool.setCapability(name);
        tool.setDescription(description);
        tool.setDependencies(deps);
        return tool;
    }

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

    // ─────────────────────────────────────────────────────────────────
    // Issue #932: @MeshA2A producer-side support (Chunk 1A — sync only).
    //
    // Adds five beans:
    //   * MeshA2ARegistry          — collects @MeshA2A surfaces
    //   * MeshA2ABeanPostProcessor — scans beans at boot for @MeshA2A
    //   * MeshA2ATaskStore         — process-local A2A task store (300s eviction)
    //   * MeshA2ACardBuilder       — renders /.well-known/agent.json
    //   * MeshA2ADispatcher        — JSON-RPC entry point dispatcher
    //   * MeshA2ADispatcherController — @RestController mounted at /**
    //   * meshA2AAuthFilter        — bearer-auth gate (filter registration)
    //
    // The dispatcher + card builder + controller depend on a populated
    // MeshA2ARegistry. The bean post-processor is declared as a static
    // factory so it instantiates before user beans (same pattern as the
    // route bean post-processor).
    // ─────────────────────────────────────────────────────────────────

    @Bean
    @ConditionalOnMissingBean
    public static MeshA2ARegistry meshA2ARegistry() {
        return new MeshA2ARegistry();
    }

    @Bean
    @ConditionalOnMissingBean
    public static MeshA2ABeanPostProcessor meshA2ABeanPostProcessor(MeshA2ARegistry registry) {
        return new MeshA2ABeanPostProcessor(registry);
    }

    @Bean
    @ConditionalOnMissingBean
    public MeshA2ATaskStore meshA2ATaskStore() {
        return new MeshA2ATaskStore();
    }

    @Bean
    @ConditionalOnMissingBean
    public MeshA2ACardBuilder meshA2ACardBuilder(
            MeshToolRegistry toolRegistry, ObjectMapper objectMapper) {
        return new MeshA2ACardBuilder(toolRegistry, objectMapper);
    }

    @Bean
    @ConditionalOnMissingBean
    public MeshA2ADispatcher meshA2ADispatcher(
            MeshA2ARegistry registry,
            MeshA2ATaskStore taskStore,
            ObjectMapper objectMapper,
            ObjectProvider<MeshDependencyInjector> injectorProvider,
            ObjectProvider<MeshRuntime> runtimeProvider) {
        // Issue #936: thread the MeshRuntime ObjectProvider through so the
        // dispatcher can auto-inject MeshJobSubmitter parameters on
        // @MeshA2A handlers (long-running producers). The provider is
        // resolved lazily at the first request that actually declares a
        // MeshJobSubmitter parameter — the dispatcher never resolves it at
        // construction time, which keeps it off the bean-creation cycle
        // that #937 fixed.
        return new MeshA2ADispatcher(
            registry, taskStore, objectMapper, injectorProvider, runtimeProvider);
    }

    /**
     * Process-local cache of registry-stamped public URLs (spec §8.2). Populated
     * by {@link MeshEventProcessor} when the Rust core surfaces a
     * {@code surface_updated} event; read by
     * {@link MeshA2ADispatcherController#buildRouterFunction()} at agent-card
     * render time. Empty by default — controller falls back to the local
     * host:port URL form.
     */
    @Bean
    @ConditionalOnMissingBean
    public MeshA2APublicUrlCache meshA2APublicUrlCache() {
        return new MeshA2APublicUrlCache();
    }

    /**
     * Spring-MVC SSE adapter for the dispatcher's framework-agnostic
     * stream-plan (spec §4.6 / §4.7 / §5). The adapter contains the only
     * code that imports Spring MVC's functional SSE API; the dispatcher
     * itself stays unit-testable without a servlet container.
     */
    @Bean
    @ConditionalOnMissingBean
    public MeshA2ASseDispatcher meshA2ASseDispatcher(MeshA2ADispatcher dispatcher) {
        return new MeshA2ASseDispatcher(dispatcher);
    }

    @Bean
    @ConditionalOnMissingBean
    public MeshA2ADispatcherController meshA2ADispatcherController(
            MeshA2ARegistry registry,
            MeshA2ADispatcher dispatcher,
            MeshA2ASseDispatcher sseDispatcher,
            MeshA2ACardBuilder cardBuilder,
            ObjectProvider<MeshProperties> propertiesProvider,
            ObjectProvider<MeshA2APublicUrlCache> publicUrlCacheProvider) {
        return new MeshA2ADispatcherController(
            registry, dispatcher, sseDispatcher, cardBuilder,
            propertiesProvider, publicUrlCacheProvider);
    }

    /**
     * Functional router for every registered {@code @MeshA2A} surface.
     * Spring MVC composes this {@link org.springframework.web.servlet.function.RouterFunction}
     * with annotation-based {@code @RestController} mappings, so user
     * controllers, static-resource serving, and error pages continue to
     * work alongside the A2A producer routes.
     *
     * <h2>Why this returns a lazy wrapper</h2>
     *
     * <p>An earlier revision walked {@code @Component}/{@code @Service}
     * beans eagerly in this factory to force {@link MeshA2ABeanPostProcessor}
     * to populate {@link MeshA2ARegistry} before the router was built. That
     * eager walk caused a bean-creation cycle (issue #937): any user
     * {@code @Component} that autowires {@link MeshRuntime} would re-enter
     * {@code MeshRuntime}'s factory mid-creation and Spring 2.6+ rejects
     * the cycle with {@code BeanCurrentlyInCreationException}.
     *
     * <p>This factory now returns a {@link MeshA2ALazyRouterFunction}: the
     * router-function bean materialises immediately so {@code RouterFunctionMapping}
     * can detect it as a bean, but {@link MeshA2ADispatcherController#buildRouterFunction()}
     * is not invoked until either Spring asks for a route match
     * (per-request {@code route(...)} call) or visits the route tree
     * (e.g. {@code accept(ChangePathPatternParserVisitor)} from
     * {@code RouterFunctionMapping.afterPropertiesSet()}). At those
     * moments the {@link MeshA2ARegistry} is fully populated because
     * {@link MeshA2ABeanPostProcessor} runs as part of each candidate
     * bean's lifecycle — the eager walk is no longer required.
     *
     * <p>To guarantee the inner router exists before the first request,
     * we additionally register a {@link SmartInitializingSingleton} below
     * that proactively materialises it after all singletons have been
     * created (and well before {@link MeshRuntime} starts).
     */
    @Bean
    @ConditionalOnMissingBean(name = "meshA2ARouterFunction")
    public RouterFunction<ServerResponse> meshA2ARouterFunction(
            MeshA2ADispatcherController controller) {
        return new MeshA2ALazyRouterFunction(controller);
    }

    /**
     * Materialises the lazy {@link MeshA2ALazyRouterFunction} once Spring
     * has finished creating all singletons. Running here (instead of
     * inside the {@code meshA2ARouterFunction} factory) keeps the bean
     * factory off the user-{@code @Component} bean-creation path that
     * triggered issue #937, while ensuring the registry-driven route
     * table is built before the first HTTP request can reach the
     * dispatcher.
     *
     * <p>This runs as a {@link SmartInitializingSingleton} — Spring
     * guarantees it fires AFTER every singleton has been instantiated
     * (so every {@code @MeshA2A}-bearing {@code @Component} has been
     * post-processed into the registry) and BEFORE any
     * {@link org.springframework.context.SmartLifecycle#start()} call
     * (so {@link MeshRuntime}'s heartbeat loop sees a fully-built
     * surface set — see {@link #meshA2ASpecFinalizer} which mutates the
     * agent spec in the same phase).
     */
    @Bean
    @ConditionalOnMissingBean(name = "meshA2ARouterFunctionInitializer")
    public SmartInitializingSingleton meshA2ARouterFunctionInitializer(
            @Qualifier("meshA2ARouterFunction")
            RouterFunction<ServerResponse> meshA2ARouterFunction) {
        return () -> {
            if (meshA2ARouterFunction instanceof MeshA2ALazyRouterFunction lazy) {
                lazy.materialise();
            }
        };
    }

    /**
     * Bearer-auth filter (spec §6). Registered at HIGHEST_PRECEDENCE + 10
     * so it runs BEFORE Spring's dispatcher servlet matches the request to
     * the {@link MeshA2ADispatcherController} — rejection short-circuits
     * the chain with HTTP 401 + JSON-RPC -32001 before the dispatcher sees
     * the body. The filter is conditional only on the registry being
     * present; it no-ops on every request that isn't a POST to a registered
     * bearer-protected surface, so it's safe to register unconditionally.
     */
    /**
     * Stamps SSE buffering hints ({@code Cache-Control: no-cache},
     * {@code X-Accel-Buffering: no}, {@code Connection: keep-alive}) on
     * every request that opts into {@code text/event-stream}. Registered at
     * {@code HIGHEST_PRECEDENCE + 6}, just after the bearer-auth filter.
     */
    @Bean
    @ConditionalOnMissingBean(name = "meshA2ASseHeaderFilter")
    public FilterRegistrationBean<MeshA2ASseHeaderFilter> meshA2ASseHeaderFilter() {
        FilterRegistrationBean<MeshA2ASseHeaderFilter> registration = new FilterRegistrationBean<>();
        registration.setFilter(new MeshA2ASseHeaderFilter());
        registration.addUrlPatterns("/*");
        registration.setName("meshA2ASseHeaderFilter");
        registration.setOrder(Ordered.HIGHEST_PRECEDENCE + 6);
        return registration;
    }

    @Bean
    @ConditionalOnMissingBean(name = "meshA2AAuthFilter")
    public FilterRegistrationBean<MeshA2AAuthFilter> meshA2AAuthFilter(MeshA2ARegistry registry) {
        FilterRegistrationBean<MeshA2AAuthFilter> registration = new FilterRegistrationBean<>();
        registration.setFilter(new MeshA2AAuthFilter(registry));
        registration.addUrlPatterns("/*");
        registration.setName("meshA2AAuthFilter");
        // Run AFTER the tracing filter (which is at HIGHEST_PRECEDENCE).
        // Lower precedence = higher numeric order in Spring, so
        // HIGHEST_PRECEDENCE + 5 places auth one step behind tracing —
        // tracing first, auth second — and even rejected requests are
        // still traced for debuggability.
        registration.setOrder(Ordered.HIGHEST_PRECEDENCE + 5);
        return registration;
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
            ObjectMapper objectMapper) {

        // Build the bare agent spec — identity, ports, registry URL.
        // Tools, route/A2A dependencies, and surfaces are folded in by
        // meshAgentSpecFinalizer below, AFTER Spring has finished creating
        // every singleton. Walking @Component beans from this factory
        // (the old behaviour) triggered a bean-creation cycle for any user
        // @Component that autowired MeshRuntime — see issue #937.
        AgentSpec spec = buildBaseAgentSpec(properties, toolRegistry, llmRegistry,
            configResolver);

        // Register MeshJob helper tools (__mesh_job_status / __mesh_job_result /
        // __mesh_job_cancel) and LLM provider tool handlers EAGERLY into the
        // wrapper registry. mcpStatelessServer (see MeshMcpServerConfiguration)
        // snapshots tool handlers at bean-construction time — anything registered
        // later (in a SmartInitializingSingleton) won't be visible to the MCP SDK
        // and every call would hit the upstream "Unknown tool" sentinel. Neither
        // call walks @Component beans, so the bean-cycle that #937 fixed is
        // preserved by keeping the bean-walking work in finalizeAgentSpec().
        try {
            JobsHelperToolsRegistrar.register(toolRegistry, wrapperRegistry, spec.getRegistryUrl());
        } catch (Exception e) {
            log.warn("Failed to register MeshJob helper tools at startup", e);
        }
        registerLlmProviderHandlers(wrapperRegistry);

        log.info("Creating MeshRuntime for agent '{}' (tools/surfaces populated post-init)",
            spec.getName());

        return new MeshRuntime(spec, objectMapper);
    }

    /**
     * Fold tools, route/A2A dependencies, LLM provider tools, and A2A
     * surfaces into the agent spec AFTER every singleton has been
     * instantiated. Runs as a {@link SmartInitializingSingleton} which
     * Spring guarantees fires:
     *
     * <ul>
     *   <li>AFTER every {@code @Component}/{@code @Service}/{@code @RestController}
     *       singleton (so {@link MeshA2ABeanPostProcessor},
     *       {@link MeshToolBeanPostProcessor}, and
     *       {@link io.mcpmesh.spring.web.MeshRouteBeanPostProcessor} have
     *       seen every candidate bean and populated their registries).</li>
     *   <li>BEFORE any {@link org.springframework.context.SmartLifecycle#start()}
     *       call — including {@link MeshRuntime#start()} — so the spec
     *       handed to the native core's heartbeat loop reflects the full
     *       tool/surface set on the very first heartbeat envelope.</li>
     * </ul>
     *
     * <p>This deliberately replaces the previous eager
     * {@code applicationContext.getBeansWithAnnotation(...)} calls inside
     * the {@code meshRuntime} factory; those calls re-entered user
     * {@code @Component} beans that autowired {@code MeshRuntime}, which
     * Spring 2.6+ rejects as {@code BeanCurrentlyInCreationException}
     * (issue #937).
     *
     * <p>The returned bean is a {@link MeshAgentSpecFinalizer} so other
     * post-init beans (in particular {@link #meshCapabilityBeanRegistrar})
     * can call {@link MeshAgentSpecFinalizer#ensureFinalized()} explicitly
     * to guarantee the spec is fully built before they read it. Spring does
     * NOT order {@link SmartInitializingSingleton#afterSingletonsInstantiated()}
     * callbacks across beans (no {@code @DependsOn}/{@code Ordered} honoured
     * there), so the explicit call is the only reliable ordering mechanism —
     * see W2 in PR #1086 review.
     */
    @Bean
    @ConditionalOnMissingBean(name = "meshAgentSpecFinalizer")
    public MeshAgentSpecFinalizer meshAgentSpecFinalizer(
            MeshRuntime runtime,
            MeshToolRegistry toolRegistry,
            MeshLlmRegistry llmRegistry,
            ObjectMapper objectMapper,
            ObjectProvider<MeshRouteRegistry> routeRegistryProvider,
            ObjectProvider<MeshA2ARegistry> a2aRegistryProvider,
            A2AConsumerBeanPostProcessor a2aConsumerBeanPostProcessor,
            ObjectProvider<McpMeshServiceRegistrar> serviceRegistrarProvider) {
        return new MeshAgentSpecFinalizer(() -> finalizeAgentSpec(runtime.getAgentSpec(),
            toolRegistry, llmRegistry, objectMapper, routeRegistryProvider,
            a2aRegistryProvider, a2aConsumerBeanPostProcessor, serviceRegistrarProvider));
    }

    /**
     * Issue #1086: register a singleton {@link McpMeshTool} bean per
     * {@code @MeshDependsOn}-declared capability so Spring-managed beans can
     * inject the proxy by {@code @Qualifier("capability")} from anywhere —
     * services, filters, schedulers, plain {@code @Component}s.
     *
     * <p>This must run BEFORE user singletons are instantiated, otherwise a
     * {@code @Autowired @Qualifier("cap")} field on a user bean blows up
     * with {@code NoSuchBeanDefinitionException} before the late
     * {@link SmartInitializingSingleton} would have had a chance to register
     * anything. We implement it as a {@link MeshCapabilityBeanRegistrar} —
     * a {@code static} factory method ensures the post-processor is
     * instantiated early, like the existing
     * {@code meshToolBeanPostProcessor} / {@code meshA2ABeanPostProcessor}
     * factories.
     *
     * <p>Source coverage: only {@code @MeshDependsOn} capabilities are
     * registered up-front. Capabilities declared via {@code @MeshTool} /
     * {@code @MeshRoute(dependencies=)} / {@code @MeshA2A(dependencies=)}
     * already have direct injection paths ({@code @MeshTool} method
     * parameters, {@code @MeshInject} on controller-method parameters) and
     * don't need a globally-named bean. The late
     * {@link #meshCapabilityBeanRegistrar} fills in any remaining
     * capabilities so the bean factory is complete at runtime, but does NOT
     * participate in the autowire phase.
     *
     * <p>Conflict policy: if a bean name equal to a capability is already
     * registered (user has a {@code @Bean} or {@code @Component} that owns
     * that name), the user's bean wins and we log a WARN.
     */
    @Bean
    @ConditionalOnMissingBean(name = "meshDependsOnBeanRegistrar")
    public static MeshCapabilityBeanRegistrar meshDependsOnBeanRegistrar() {
        return new MeshCapabilityBeanRegistrar();
    }

    /**
     * RFC #1280: register a JDK-proxy facade bean per {@link io.mcpmesh.McpMeshService}
     * service-view interface so consumers can {@code @Autowired} the typed view
     * and have each method delegate to its own per-capability proxy. Like
     * {@link #meshDependsOnBeanRegistrar} this runs as a
     * {@link org.springframework.beans.factory.support.BeanDefinitionRegistryPostProcessor}
     * (via a {@code static} factory method) so the facade beans exist before
     * user singletons are autowired.
     */
    @Bean
    @ConditionalOnMissingBean(name = "mcpMeshServiceRegistrar")
    public static McpMeshServiceRegistrar mcpMeshServiceRegistrar() {
        return new McpMeshServiceRegistrar();
    }

    /**
     * Late-phase complement to {@link #meshDependsOnBeanRegistrar}: walks the
     * fully-built {@link AgentSpec} and registers a singleton
     * {@link McpMeshTool} bean for every capability declared by any of the
     * four sources that wasn't already registered. This keeps the bean
     * factory's view of mesh dependencies complete at runtime, even though
     * autowire-time resolution is handled by the earlier post-processor.
     *
     * <p>Runs as a {@link SmartInitializingSingleton} but does NOT rely on
     * SIS ordering — {@link MeshAgentSpecFinalizer#ensureFinalized()} is
     * invoked explicitly so the spec is fully built before this code reads
     * it. Spring's {@code @DependsOn} only orders bean CREATION, not the
     * {@code afterSingletonsInstantiated()} callbacks themselves, so the
     * earlier {@code @DependsOn("meshAgentSpecFinalizer")} was a no-op for
     * the actual ordering concern here.
     */
    @Bean
    @ConditionalOnMissingBean(name = "meshCapabilityBeanRegistrar")
    public SmartInitializingSingleton meshCapabilityBeanRegistrar(
            MeshDependencyInjector injector,
            ConfigurableListableBeanFactory beanFactory,
            MeshRuntime runtime,
            MeshAgentSpecFinalizer finalizer,
            ObjectProvider<MeshRouteRegistry> routeRegistryProvider,
            ObjectProvider<MeshA2ARegistry> a2aRegistryProvider) {
        return () -> {
            // Idempotent — fires the spec finalization if no other
            // SmartInitializingSingleton has already done so. Whichever
            // callback fires first wins; the other is a no-op.
            finalizer.ensureFinalized();

            // Merge the (capability -> expectedType) views from every source
            // that tracks it. Without this the late-phase path would call
            // injector.getToolProxy(capability) without a return type, and a
            // downstream @Qualifier("cap") McpMeshTool<Foo> consumer would
            // receive an untyped proxy returning Map<String, Object> instead
            // of Foo — even though the source @MeshDependency declared
            // expectedType=Foo.class. @MeshDependsOn already feeds expectedType
            // into the early-phase registrar; this lambda is the symmetric
            // wiring for the @MeshRoute / @MeshA2A cross-source paths.
            Map<String, Class<?>> expectedTypes = new LinkedHashMap<>();
            MeshRouteRegistry routeRegistry = routeRegistryProvider.getIfAvailable();
            if (routeRegistry != null) {
                expectedTypes.putAll(routeRegistry.getExpectedTypesByCapability());
            }
            MeshA2ARegistry a2aRegistry = a2aRegistryProvider.getIfAvailable();
            if (a2aRegistry != null) {
                for (Map.Entry<String, Class<?>> e
                        : a2aRegistry.getExpectedTypesByCapability().entrySet()) {
                    expectedTypes.putIfAbsent(e.getKey(), e.getValue());
                }
            }

            AgentSpec spec = runtime.getAgentSpec();
            // includeProducers=false: don't register McpMeshTool proxy beans
            // for capabilities the agent itself produces — those would be
            // self-loop proxies the agent never consumes through the registry.
            Set<String> capabilities = collectKnownCapabilities(spec.getTools(), false);
            int registered = 0;
            int conflicts = 0;
            for (String capability : capabilities) {
                if (beanFactory.containsBean(capability)) {
                    // Either the user owns that name, or our earlier
                    // post-processor already registered it. Either way: leave it.
                    continue;
                }
                if (beanFactory.containsSingleton(capability)) {
                    continue;
                }
                Class<?> expectedType = expectedTypes.get(capability);
                McpMeshTool<?> proxy = (expectedType != null)
                    ? injector.getToolProxy(capability, expectedType)
                    : injector.getToolProxy(capability);
                try {
                    beanFactory.registerSingleton(capability, proxy);
                    registered++;
                } catch (IllegalStateException e) {
                    log.warn("Skipping McpMeshTool bean registration for capability '{}': {}",
                        capability, e.getMessage());
                    conflicts++;
                }
            }
            if (registered > 0 || conflicts > 0) {
                log.info("Late-phase: registered {} additional McpMeshTool bean(s) "
                    + "(skipped {} due to name conflict)", registered, conflicts);
            }
        };
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
            ApplicationContext applicationContext,
            MeshA2APublicUrlCache publicUrlCache) {

        return new MeshEventProcessor(runtime, injector, wrapperRegistry,
            llmRegistry, mcpHttpClient, proxyFactory, toolInvoker, applicationContext,
            publicUrlCache);
    }

    /**
     * Health endpoint controller — produces a CGLIB-proxied {@link MeshRuntime}
     * via {@link org.springframework.context.annotation.Lazy @Lazy} so the
     * runtime is NOT resolved at controller construction time.
     *
     * <p>Without {@code @Lazy} this factory transitively triggered a
     * bean-creation cycle: {@link #meshA2ARouterFunction} and
     * {@link MeshRuntime#buildAgentSpec}-style eager-touches both walk
     * {@code @Component} beans (which match {@code MeshHealthController}
     * via its {@code @Controller} stereotype). The two touches interleaved
     * so that {@code meshHealthController} was constructed while
     * {@code meshRuntime} was already in creation — at which point
     * {@code getIfAvailable()} could not resolve and Spring rejected the
     * cycle. Using {@code @Lazy} on the direct {@link MeshRuntime} parameter
     * defers resolution to the first {@code /health} request: the
     * controller is fully constructed without touching the real runtime,
     * the cycle is broken, and the runtime is resolved transparently when
     * a probe arrives.
     */
    @Bean
    @ConditionalOnMissingBean
    public MeshHealthController meshHealthController(
            @org.springframework.context.annotation.Lazy MeshRuntime runtime) {
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

    /**
     * Build the bare {@link AgentSpec} — identity, ports, host, namespace,
     * heartbeat interval, registry URL. Does NOT walk {@code @Component}
     * beans or read the tool/route/A2A registries; that work is done by
     * {@link #finalizeAgentSpec} after every singleton has been
     * instantiated.
     *
     * <p>Splitting the spec build into a "metadata-only" phase here and a
     * "tools and surfaces" phase post-singleton-init is the structural
     * fix for issue #937 — the old factory walked
     * {@code @Component}/{@code @Service} beans synchronously, which
     * re-entered any user component that autowired {@link MeshRuntime}
     * and triggered Spring's circular-reference guard.
     */
    private AgentSpec buildBaseAgentSpec(
            MeshProperties properties,
            MeshToolRegistry toolRegistry,
            MeshLlmRegistry llmRegistry,
            MeshConfigResolver configResolver) {

        // Find @MeshAgent annotation
        MeshAgent agentAnnotation = findMeshAgentAnnotation();

        AgentSpec spec = new AgentSpec();

        // Resolve name - either from annotation, properties, or env
        String annotationName = agentAnnotation != null ? agentAnnotation.name() : null;
        String propertiesName = properties.getAgent().getName();
        String paramName = (annotationName != null && !annotationName.isBlank()) ? annotationName : propertiesName;
        String name = configResolver.resolve("agent_name", paramName);

        if (name == null || name.isBlank()) {
            // No agent name configured — fall back to consumer-only mode.
            // We can't yet check MeshRouteRegistry (it's populated by a
            // BeanPostProcessor as @RestController beans are created); we
            // build a consumer-only spec optimistically and the post-init
            // finalizer will populate route deps. If neither @MeshAgent
            // nor any @MeshRoute is present, the finalizer would have
            // nothing to add — in that case the agent has no reason to
            // start. To preserve the previous fail-fast behaviour we
            // re-check inside the finalizer (see finalizeAgentSpec).
            log.info("No agent name configured — provisional consumer-only spec; will validate after singletons init");
            return buildConsumerAgentSpec(properties, configResolver);
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

        // Resolve description (issue #969). Mirror the version-resolution pattern:
        // annotation wins when non-blank, otherwise fall back to mesh.agent.description.
        // We never let it be null (the Rust core's AgentSpec.description is a plain
        // String — null trips Jackson's NON_NULL filter and the field disappears,
        // which the registry would interpret as "no description supplied" and keep
        // a prior value instead of clearing it).
        String description = agentAnnotation != null ? agentAnnotation.description() : null;
        if (description == null || description.isBlank()) {
            String propDescription = properties.getAgent().getDescription();
            if (propDescription != null && !propDescription.isBlank()) {
                description = propDescription;
            }
        }
        spec.setDescription(description != null ? description : "");

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

        // Issue #916 Phase 1: inject the surrounding @MeshAgent name as
        // a tag on every @A2AConsumer-annotated tool. This only mutates
        // ToolSpec metadata captured by the @A2AConsumer post-processor
        // at bean-creation time — no bean walking, no cycle risk.
        try {
            toolRegistry.injectConsumerNameTags(name);
        } catch (Exception e) {
            log.warn("Failed to inject @A2AConsumer auto-tags for agent '{}': {}",
                name, e.getMessage());
        }

        // Start with an empty tools list; finalizeAgentSpec populates it
        // post-singleton-init. We initialise to an empty list (not null)
        // so any callers reading getTools() between now and the finalizer
        // get a stable, non-null reference.
        spec.setTools(new ArrayList<>());
        return spec;
    }

    /**
     * Second-phase agent-spec build: fold tools, route/A2A dependencies,
     * LLM provider tools, MeshJob helper tools, and A2A surfaces into the
     * spec built by {@link #buildBaseAgentSpec}. Called from
     * {@link #meshAgentSpecFinalizer} as a {@link SmartInitializingSingleton}
     * — runs AFTER every bean has been post-processed (so every registry
     * is fully populated) and BEFORE {@link MeshRuntime#start()} fires.
     */
    private void finalizeAgentSpec(
            AgentSpec spec,
            MeshToolRegistry toolRegistry,
            MeshLlmRegistry llmRegistry,
            ObjectMapper objectMapper,
            ObjectProvider<MeshRouteRegistry> routeRegistryProvider,
            ObjectProvider<MeshA2ARegistry> a2aRegistryProvider,
            A2AConsumerBeanPostProcessor a2aConsumerBeanPostProcessor,
            ObjectProvider<McpMeshServiceRegistrar> serviceRegistrarProvider) {

        // Helper tools (MeshJob substrate) and LLM provider handlers are
        // registered eagerly in meshRuntime() — see the comment there. By
        // the time we reach this finalizer the synthetic helper tool specs
        // are already in toolRegistry and the LLM provider handlers are
        // already in wrapperRegistry. We still need to fold the LLM
        // provider tool SPECS into the heartbeat catalog here (they live
        // in the spring-ai processor, not in toolRegistry).

        // Consumer-only fallback validation: if buildBaseAgentSpec
        // produced a consumer-only spec (agent_type="api") because no
        // agent name was configured, surface a clear error when the user
        // also has no @MeshRoute dependencies — otherwise the agent has
        // no reason to start.
        boolean consumerOnly = "api".equals(spec.getAgentType());

        // Add tools from registry (dependencies are embedded in tool specs)
        List<AgentSpec.ToolSpec> allTools = new ArrayList<>(toolRegistry.getToolSpecs());

        // Enrich tools with @MeshLlm provider info for mesh delegation
        enrichToolsWithLlmProvider(allTools, toolRegistry, llmRegistry, objectMapper);

        // Add LLM provider tool specs to the heartbeat (handlers were
        // already registered eagerly in meshRuntime()).
        addLlmProviderToolSpecs(allTools);

        // Add @MeshRoute dependencies as a synthetic tool
        addRouteDependencies(allTools, routeRegistryProvider);

        // Add @MeshA2A dependencies as a synthetic tool so the Rust core
        // resolves them via the registry's dependency mechanism (same
        // pattern as addRouteDependencies). No eager bean-walk needed —
        // MeshA2ABeanPostProcessor populated the registry as each
        // @Component was created during the singleton init phase.
        addA2ADependencies(allTools, a2aRegistryProvider);

        // Issue #1086: 4th dependency source — class-level @MeshDependsOn on
        // arbitrary @Component beans (services, filters, schedulers, etc.).
        // Folds these capabilities into a synthetic __mesh_depends_on_deps
        // tool so the heartbeat path wires proxies the same way it does for
        // @MeshTool / @MeshRoute / @MeshA2A. Dedup is by capability name across
        // all four sources — see collectKnownCapabilities().
        addMeshDependsOnDependencies(allTools, routeRegistryProvider);

        // RFC #1280: 5th dependency source — @McpMeshService service views.
        // Folded LAST so each view method dedupes against every earlier source
        // (@MeshTool / @MeshRoute / @MeshA2A / @MeshDependsOn) and runs through
        // the same cross-source required-wins promotion.
        addMcpMeshServiceDependencies(allTools, serviceRegistrarProvider, routeRegistryProvider,
            a2aRegistryProvider);

        if (consumerOnly) {
            MeshRouteRegistry routeRegistry = routeRegistryProvider.getIfAvailable();
            boolean hasRoutes = routeRegistry != null && routeRegistry.hasRoutes();
            // A @McpMeshService view is a valid mesh consumer surface (#12): an
            // app whose ONLY mesh surface is a service view should start as a
            // consumer without a declared agent name, exactly like a route-only
            // app. hasServiceViews is folded into the gate AND the error message.
            McpMeshServiceRegistrar serviceRegistrar = serviceRegistrarProvider.getIfAvailable();
            boolean hasServiceViews = serviceRegistrar != null
                && !serviceRegistrar.discoveredServices().isEmpty();
            if (!hasRoutes && !hasServiceViews) {
                throw new IllegalStateException(
                    "Agent name is required for a producer agent. Set MCP_MESH_AGENT_NAME, "
                        + "mesh.agent.name, or @MeshAgent(name=...) — or expose a @MeshRoute / "
                        + "@McpMeshService consumer surface to run name-less as a mesh consumer.");
            }
            log.info("Consumer-only mode confirmed: {} route/service consumer surface(s) registered",
                allTools.size());
        }

        spec.setTools(allTools);

        // Flip agent_type to "a2a" and emit a2a_surfaces[] (spec §2 / §8)
        // when at least one @MeshA2A surface is registered. Tools coexist
        // with surfaces — A2A producers may also expose @MeshTool
        // capabilities.
        applyA2ASurfaces(spec, a2aRegistryProvider, objectMapper);

        // Issue #972: stamp the A2A consumer flag from the bean-post-processor's
        // collected bindings. Non-empty means at least one @A2AConsumer method
        // was registered. Producer flag is set inside applyA2ASurfaces above.
        spec.setA2aConsumer(!a2aConsumerBeanPostProcessor.bindings().isEmpty());

        // Flip agent_type to "api" for a NAMED route-only agent. The unnamed
        // path already gets agent_type="api" from buildConsumerAgentSpec, but a
        // named @MeshAgent that only exposes @MeshRoute surfaces (no real
        // @MeshTool capabilities) takes buildBaseAgentSpec and would otherwise
        // stay at the AgentSpec default "mcp_agent" — mislabeling it as an MCP
        // agent in the dashboard. This mirrors Python, whose API pipeline
        // decides agent_type="api" independently of whether a name was set.
        //
        // Guard: only flip when still the default "mcp_agent" so an A2A agent
        // (already flipped to "a2a" above) or any explicit type is preserved.
        // Do NOT rely on the a2a flip having succeeded: applyA2ASurfaces sets
        // "a2a" inside a try block that swallows a serialization exception and
        // leaves agent_type at "mcp_agent". So make a2a precedence explicit by
        // checking the SAME signal applyA2ASurfaces keys on (hasSurfaces()) —
        // an A2A producer is never mislabeled "api" even if that serialize threw.
        // Reuse the same signals the consumer-only path relies on:
        //   - routes: MeshRouteRegistry.hasRoutes()
        //   - a2a surfaces: MeshA2ARegistry.hasSurfaces()
        //   - "no real tools": no ToolSpec whose function name is a genuine user
        //     @MeshTool. Framework job-control tools and synthetic dependency
        //     surfaces all carry the "__mesh_" prefix, so a user tool is any
        //     spec whose functionName does not start with that prefix.
        if ("mcp_agent".equals(spec.getAgentType())) {
            MeshRouteRegistry routeRegistry = routeRegistryProvider.getIfAvailable();
            boolean hasRoutes = routeRegistry != null && routeRegistry.hasRoutes();
            MeshA2ARegistry a2aRegistry = a2aRegistryProvider.getIfAvailable();
            boolean hasA2aSurfaces = a2aRegistry != null && a2aRegistry.hasSurfaces();
            boolean hasRealTools = spec.getTools().stream()
                .map(AgentSpec.ToolSpec::getFunctionName)
                .anyMatch(name -> name != null && !name.startsWith("__mesh_"));
            if (hasRoutes && !hasRealTools && !hasA2aSurfaces) {
                spec.setAgentType("api");
                log.info("@MeshRoute (route-only, named): agent_type=api "
                    + "(no @MeshTool capabilities — matches unnamed consumer path)");
            }
        }

        log.info("Agent spec finalized for '{}' with {} tool(s)",
            spec.getName(), spec.getTools().size());
    }

    /**
     * Add {@code @MeshA2A} dependencies as a synthetic
     * {@code __mesh_a2a_deps} tool. Mirrors {@link #addRouteDependencies}
     * exactly — without this, the registry's dependency resolution
     * mechanism never learns about the capabilities each surface needs,
     * so the {@link MeshDependencyInjector}'s proxy stays stuck in the
     * unavailable state.
     */
    private void addA2ADependencies(List<AgentSpec.ToolSpec> tools,
                                    ObjectProvider<io.mcpmesh.spring.web.MeshA2ARegistry> a2aRegistryProvider) {
        io.mcpmesh.spring.web.MeshA2ARegistry registry = a2aRegistryProvider.getIfAvailable();
        if (registry == null || !registry.hasSurfaces()) {
            return;
        }
        List<AgentSpec.DependencySpec> deps = registry.getUniqueDependencySpecs();
        if (deps.isEmpty()) {
            return;
        }
        tools.add(syntheticDepsTool(A2A_DEPS_TOOL,
            "Synthetic tool for @MeshA2A dependency resolution", deps));
        log.info("Added {} @MeshA2A dependencies to agent registration", deps.size());
    }

    /**
     * Issue #1086: Add class-level {@code @MeshDependsOn} declarations as a
     * synthetic {@code __mesh_depends_on_deps} tool. Mirrors
     * {@link #addRouteDependencies} and {@link #addA2ADependencies} so
     * Spring-managed beans outside {@code @RestController} handler methods
     * (services, filters, schedulers, plain {@code @Component}s) can declare
     * mesh dependencies and have them resolved by the registry's
     * dependency-resolution mechanism.
     *
     * <p>Dedup runs against the capabilities already accumulated on
     * {@code tools} — the same capability declared via {@code @MeshTool} or
     * {@code @MeshRoute(dependencies=)} or {@code @MeshA2A(dependencies=)}
     * wins; {@code @MeshDependsOn} entries are silently dropped when their
     * capability already appears in any prior source. Within
     * {@code @MeshDependsOn} itself the first occurrence wins.
     */
    private void addMeshDependsOnDependencies(List<AgentSpec.ToolSpec> tools,
            ObjectProvider<MeshRouteRegistry> routeRegistryProvider) {
        Map<String, Object> beans = applicationContext.getBeansWithAnnotation(MeshDependsOn.class);
        if (beans.isEmpty()) {
            return;
        }

        // includeProducers=true: a @MeshDependsOn on a capability the agent
        // itself produces (@MeshTool capability=...) is dropped — the agent
        // doesn't need a registry-resolved dependency to call its own tool.
        Set<String> seenCapabilities = collectKnownCapabilities(tools, true);
        List<AgentSpec.DependencySpec> deps = new ArrayList<>();
        var jsonMapper = JsonMapper.builder().build();
        // Issue #547 Phase 4: cluster-wide strict knob promotes WARN→BLOCK on
        // the consumer side too. Same source-of-truth as MeshRouteRegistry.
        boolean clusterStrict = io.mcpmesh.spring.MeshSchemaSupport.clusterStrictEnabled();

        for (Object bean : beans.values()) {
            Class<?> targetClass = org.springframework.aop.support.AopUtils.getTargetClass(bean);
            MeshDependsOn annotation = org.springframework.core.annotation.AnnotationUtils
                .findAnnotation(targetClass, MeshDependsOn.class);
            if (annotation == null) {
                continue;
            }
            for (MeshDependency dep : annotation.value()) {
                String capability = dep.capability();
                if (capability == null || capability.isBlank()) {
                    log.warn("@MeshDependsOn on {} has @MeshDependency with empty capability — skipping",
                        targetClass.getName());
                    continue;
                }
                if (!seenCapabilities.add(capability)) {
                    // Cross-source required-wins (2.8.1, extends #1249): the
                    // capability is already declared by a prior source
                    // (@MeshTool / @MeshRoute / @MeshA2A) OR an earlier
                    // @MeshDependsOn bean. The edge itself is deduped away, but
                    // a required=true @MeshDependsOn must not be silently
                    // downgraded to the prior source's flag — required WINS
                    // across sources, matching the within-source merge in
                    // MeshRouteRegistry.getUniqueDependencySpecs.
                    if (dep.required()) {
                        // Scan BOTH the already-folded tool specs and the
                        // pending `deps` list: a same-source @MeshDependsOn
                        // sibling declared earlier in this loop lives in `deps`
                        // (not yet folded into `tools`), so an order like
                        // {optional bean, required bean} would otherwise drop
                        // the required flag.
                        boolean upgraded =
                            upgradeExistingDependencyToRequired(tools, deps, capability);
                        // The request-time 503 route perimeter reads the route
                        // registry's own DependencySpec, not the AgentSpec copy
                        // upgraded above — promote it too so the perimeter and
                        // the wire advertisement agree (no split-brain).
                        MeshRouteRegistry routeRegistry = routeRegistryProvider.getIfAvailable();
                        if (routeRegistry != null
                                && routeRegistry.promoteCapabilityToRequired(capability)) {
                            upgraded = true;
                        }
                        if (upgraded) {
                            log.info("@MeshDependsOn capability '{}' on {} already declared by another "
                                    + "source — upgrading the deduped dependency to required=true "
                                    + "(required wins across sources)",
                                capability, targetClass.getName());
                            continue;
                        }
                    }
                    log.debug("@MeshDependsOn capability '{}' on {} already declared by another source — skipping",
                        capability, targetClass.getName());
                    continue;
                }
                AgentSpec.DependencySpec agentDep = new AgentSpec.DependencySpec();
                agentDep.setCapability(capability);
                if (dep.tags().length > 0) {
                    // Issue #1158: tags is contractually a JSON-array string
                    // (the Rust core JSON-parses it; a comma-joined string
                    // silently degrades to "no tag constraint").
                    try {
                        agentDep.setTags(jsonMapper.writeValueAsString(dep.tags()));
                    } catch (Exception e) {
                        log.warn("Failed to serialize tags for dependency '{}' — registering with no tag constraint: {}",
                            capability, e.getMessage());
                        agentDep.setTags("[]");
                    }
                }
                if (dep.version() != null && !dep.version().isEmpty()) {
                    agentDep.setVersion(dep.version());
                }
                // Issue #1249: carry the @MeshDependency required flag through
                // to the spec JSON (omitted when false via NON_DEFAULT on the
                // AgentSpec dep). @MeshDependsOn edges participate in the same
                // transitive availability predicate as @MeshRoute / @MeshTool
                // dependencies. The value() array is a user-authored ordered
                // list, so no required-wins merge is needed here (unlike the
                // route/A2A registries' nondeterministic map iteration).
                agentDep.setRequired(dep.required());
                // Issue #547: honour expectedType / schemaMode the same way
                // @MeshRoute does. Default-sentinel (Void.class) means "not
                // set" — same convention as MeshRouteRegistry.DependencySpec
                // (see fromAnnotation).
                Class<?> expectedType = dep.expectedType();
                if (expectedType == Void.class || expectedType == void.class) {
                    expectedType = null;
                }
                MeshRouteRegistry.applySchemaMatching(
                    agentDep, capability, expectedType, dep.schemaMode(), clusterStrict);
                deps.add(agentDep);
            }
        }

        if (deps.isEmpty()) {
            return;
        }

        tools.add(syntheticDepsTool(DEPENDS_ON_DEPS_TOOL,
            "Synthetic tool for @MeshDependsOn dependency resolution", deps));
        log.info("Added {} @MeshDependsOn dependencies to agent registration", deps.size());
    }

    /**
     * RFC #1280: expand every {@link io.mcpmesh.McpMeshService} service view's
     * abstract methods into wire dependency edges under a synthetic
     * {@code __mesh_service_deps} tool. Each method is an ordinary capability
     * dependency — zero wire/registry changes — so the group is a purely
     * consumer-local typed view while the capability remains the atom.
     *
     * <p>Determinism is a hard requirement: {@link McpMeshServiceRegistrar#discoveredServices()}
     * returns views sorted by interface name and each view's bindings are
     * pre-sorted by method name/signature, so the emitted dependency order is
     * reproducible regardless of {@link Class#getMethods()} JVM ordering.
     *
     * <p>Dedup + cross-source required-wins mirror
     * {@link #addMeshDependsOnDependencies} exactly: a capability already
     * declared by an earlier source is deduped away, but a {@code required=true}
     * view method still promotes the surviving edge (AgentSpec + route-registry
     * perimeter) to required.
     */
    private void addMcpMeshServiceDependencies(List<AgentSpec.ToolSpec> tools,
            ObjectProvider<McpMeshServiceRegistrar> serviceRegistrarProvider,
            ObjectProvider<MeshRouteRegistry> routeRegistryProvider,
            ObjectProvider<MeshA2ARegistry> a2aRegistryProvider) {
        McpMeshServiceRegistrar registrar = serviceRegistrarProvider.getIfAvailable();
        if (registrar == null) {
            return;
        }
        List<McpMeshServiceRegistrar.ServiceViewMetadata> views = registrar.discoveredServices();
        if (views.isEmpty()) {
            return;
        }

        // includeProducers=true: a view method binding a capability the agent
        // itself produces is dropped (no self-edge) — same policy as
        // @MeshDependsOn.
        Set<String> seenCapabilities = collectKnownCapabilities(tools, true);
        // Capabilities THIS agent produces (real @MeshTool, not synthetic
        // __mesh_ helper/dep tools). A view method binding a self-produced
        // capability can never resolve through the registry (#6).
        Set<String> producerCapabilities = collectProducerCapabilities(tools);
        // Cross-source resolved-type map (#5): every injector-backed source that
        // stamps a proxy return type for a capability — @MeshRoute / @MeshA2A
        // (expectedType) and @MeshDependsOn (expectedType). A view method
        // binding the same capability to a DIFFERENT resolved type would clobber
        // the shared proxy, so it boot-fails like the existing conflict policy.
        Map<String, Class<?>> otherSourceTypes = collectOtherSourceExpectedTypes(
            routeRegistryProvider, a2aRegistryProvider);
        MeshSettleState settleState = MeshSettleState.getInstance();
        List<AgentSpec.DependencySpec> deps = new ArrayList<>();
        var jsonMapper = JsonMapper.builder().build();
        boolean clusterStrict = io.mcpmesh.spring.MeshSchemaSupport.clusterStrictEnabled();

        for (McpMeshServiceRegistrar.ServiceViewMetadata view : views) {
            for (McpMeshServiceRegistrar.ServiceMethodBinding binding : view.bindings()) {
                String capability = binding.capability();

                // #5: cross-source resolved-type conflict — fail fast, identical
                // types are fine. Skip when either side is untyped (Object).
                Class<?> viewType = binding.resolvedRawType();
                Class<?> otherType = otherSourceTypes.get(capability);
                if (viewType != null && viewType != Object.class
                        && otherType != null && otherType != Object.class
                        && viewType != otherType) {
                    throw new IllegalStateException(String.format(
                        "Capability '%s' is bound with conflicting resolved types across sources: "
                            + "%s (@McpMeshService %s.%s) vs %s (another injector-backed source "
                            + "expectedType). Align the types or split into separate capabilities.",
                        capability, viewType.getName(), view.iface().getName(),
                        binding.method().getName(), otherType.getName()));
                }

                // #6: self-produced capability — the edge is deduped away and can
                // never resolve. Soft-fail per mesh philosophy: WARN + markResolved
                // so the eager-settle latch isn't stranded on a dead key.
                if (producerCapabilities.contains(capability)) {
                    log.warn("@McpMeshService method {}.{} binds capability '{}' produced by this "
                            + "agent — the method will never resolve; call the local bean directly.",
                        view.iface().getName(), binding.method().getName(), capability);
                    settleState.markResolved(capability);
                    seenCapabilities.add(capability);
                    continue;
                }

                if (!seenCapabilities.add(capability)) {
                    // Cross-source required-wins (mirrors addMeshDependsOnDependencies):
                    // the edge is deduped away, but a required view method must
                    // still upgrade the surviving edge rather than inherit the
                    // prior source's flag.
                    if (binding.required()) {
                        boolean upgraded =
                            upgradeExistingDependencyToRequired(tools, deps, capability);
                        MeshRouteRegistry routeRegistry = routeRegistryProvider.getIfAvailable();
                        if (routeRegistry != null
                                && routeRegistry.promoteCapabilityToRequired(capability)) {
                            upgraded = true;
                        }
                        if (upgraded) {
                            log.info("@McpMeshService capability '{}' on {} already declared by another "
                                    + "source — upgrading the deduped dependency to required=true "
                                    + "(required wins across sources)",
                                capability, view.iface().getName());
                            continue;
                        }
                    }
                    log.debug("@McpMeshService capability '{}' on {} already declared by another source — skipping",
                        capability, view.iface().getName());
                    continue;
                }

                AgentSpec.DependencySpec agentDep = new AgentSpec.DependencySpec();
                agentDep.setCapability(capability);
                if (binding.tags().length > 0) {
                    // Issue #1158: tags is contractually a JSON-array string.
                    try {
                        agentDep.setTags(jsonMapper.writeValueAsString(binding.tags()));
                    } catch (Exception e) {
                        log.warn("Failed to serialize tags for dependency '{}' — registering with no tag constraint: {}",
                            capability, e.getMessage());
                        agentDep.setTags("[]");
                    }
                }
                if (binding.version() != null && !binding.version().isEmpty()) {
                    agentDep.setVersion(binding.version());
                }
                agentDep.setRequired(binding.required());
                // Schema matching: expected type is the method return type
                // (or an explicit @Selector.expectedType override), applied only
                // when a schemaMode is requested — resolved in the registrar.
                MeshRouteRegistry.applySchemaMatching(
                    agentDep, capability, binding.schemaExpectedType(),
                    binding.schemaMode(), clusterStrict);
                deps.add(agentDep);
            }
        }

        if (deps.isEmpty()) {
            return;
        }

        tools.add(syntheticDepsTool(SERVICE_DEPS_TOOL,
            "Synthetic tool for @McpMeshService dependency resolution", deps));
        log.info("Added {} @McpMeshService dependencies to agent registration", deps.size());
    }

    /**
     * Capabilities this agent PRODUCES via a real {@code @MeshTool} (function
     * name not carrying the {@code __mesh_} synthetic/helper prefix). Used by
     * {@link #addMcpMeshServiceDependencies} to detect self-produced view edges.
     */
    private static Set<String> collectProducerCapabilities(List<AgentSpec.ToolSpec> tools) {
        Set<String> producers = new LinkedHashSet<>();
        for (AgentSpec.ToolSpec tool : tools) {
            String fn = tool.getFunctionName();
            String cap = tool.getCapability();
            if (fn != null && !fn.startsWith("__mesh_") && cap != null && !cap.isEmpty()) {
                producers.add(cap);
            }
        }
        return producers;
    }

    /**
     * Collect capability → resolved expected-type from every OTHER injector-backed
     * source that stamps a proxy return type: {@code @MeshRoute} / {@code @MeshA2A}
     * (via their registries' {@code getExpectedTypesByCapability}) and
     * {@code @MeshDependsOn} (re-read off the annotations — the AgentSpec
     * dependency only carries the derived schema strings, not the Class).
     */
    private Map<String, Class<?>> collectOtherSourceExpectedTypes(
            ObjectProvider<MeshRouteRegistry> routeRegistryProvider,
            ObjectProvider<MeshA2ARegistry> a2aRegistryProvider) {
        Map<String, Class<?>> types = new LinkedHashMap<>();
        MeshRouteRegistry routeRegistry = routeRegistryProvider.getIfAvailable();
        if (routeRegistry != null) {
            types.putAll(routeRegistry.getExpectedTypesByCapability());
        }
        MeshA2ARegistry a2aRegistry = a2aRegistryProvider.getIfAvailable();
        if (a2aRegistry != null) {
            a2aRegistry.getExpectedTypesByCapability().forEach(types::putIfAbsent);
        }
        for (Object bean : applicationContext.getBeansWithAnnotation(MeshDependsOn.class).values()) {
            Class<?> targetClass = org.springframework.aop.support.AopUtils.getTargetClass(bean);
            MeshDependsOn annotation = org.springframework.core.annotation.AnnotationUtils
                .findAnnotation(targetClass, MeshDependsOn.class);
            if (annotation == null) {
                continue;
            }
            for (MeshDependency dep : annotation.value()) {
                Class<?> expectedType = dep.expectedType();
                if (expectedType == Void.class || expectedType == void.class) {
                    continue;
                }
                if (dep.capability() != null && !dep.capability().isBlank()) {
                    types.putIfAbsent(dep.capability(), expectedType);
                }
            }
        }
        return types;
    }

    /**
     * Issue #1086: collect every capability already declared on the partially
     * built tool list. Used by {@link #addMeshDependsOnDependencies} to skip
     * re-declaring a capability that the user already attached to a
     * {@code @MeshTool}, {@code @MeshRoute}, or {@code @MeshA2A} surface.
     *
     * <p>{@code includeProducers} controls whether the producer side of each
     * tool spec (the {@code @MeshTool} capability name itself) participates
     * in the dedup set. The dependency-folding path
     * ({@link #addMeshDependsOnDependencies}) passes {@code true} so a
     * {@code @MeshDependsOn} on a capability the agent itself produces is
     * silently dropped (re-declaring it as a dependency creates a
     * redundant self-edge). The bean-registration path
     * ({@code meshCapabilityBeanRegistrar}) passes {@code false} so we
     * still register {@code McpMeshTool} proxy beans for every consumed
     * capability without trying to also register one for our own producer
     * capabilities — those would be unused self-loops since the agent
     * dispatches its own producer methods directly, not through a proxy.
     */
    private static Set<String> collectKnownCapabilities(
            List<AgentSpec.ToolSpec> tools, boolean includeProducers) {
        Set<String> seen = new LinkedHashSet<>();
        for (AgentSpec.ToolSpec tool : tools) {
            if (includeProducers && tool.getCapability() != null
                    && !tool.getCapability().isEmpty()) {
                seen.add(tool.getCapability());
            }
            List<AgentSpec.DependencySpec> deps = tool.getDependencies();
            if (deps == null) {
                continue;
            }
            for (AgentSpec.DependencySpec dep : deps) {
                if (dep.getCapability() != null && !dep.getCapability().isEmpty()) {
                    seen.add(dep.getCapability());
                }
            }
        }
        return seen;
    }

    /**
     * Cross-source required-wins helper (2.8.1): promote every existing
     * {@link AgentSpec.DependencySpec} matching {@code capability} to
     * {@code required=true}, scanning BOTH the already-folded {@code tools}
     * specs (prior {@code @MeshTool} / {@code @MeshRoute} / {@code @MeshA2A}
     * sources) and the {@code pendingDeps} list still being accumulated for
     * the synthetic {@code __mesh_depends_on_deps} tool (same-source
     * {@code @MeshDependsOn} siblings declared earlier in the fold loop).
     * Called when a {@code @MeshDependsOn} edge declares {@code required=true}
     * for a capability that is already declared — the dependency edge is
     * deduped away, but the required flag must still win rather than inherit
     * the earlier declaration's (possibly non-required) value.
     *
     * @return {@code true} when at least one matching dependency spec was found
     *         and upgraded; {@code false} when the capability is only present
     *         as a producer surface (no consumable dependency spec to upgrade).
     */
    private static boolean upgradeExistingDependencyToRequired(
            List<AgentSpec.ToolSpec> tools,
            List<AgentSpec.DependencySpec> pendingDeps,
            String capability) {
        boolean upgraded = false;
        for (AgentSpec.ToolSpec tool : tools) {
            List<AgentSpec.DependencySpec> deps = tool.getDependencies();
            if (deps == null) {
                continue;
            }
            for (AgentSpec.DependencySpec dep : deps) {
                if (capability.equals(dep.getCapability())) {
                    dep.setRequired(true);
                    upgraded = true;
                }
            }
        }
        for (AgentSpec.DependencySpec dep : pendingDeps) {
            if (capability.equals(dep.getCapability())) {
                dep.setRequired(true);
                upgraded = true;
            }
        }
        return upgraded;
    }

    /**
     * Apply {@code agent_type="a2a"} + serialized {@code surfaces} JSON onto
     * {@code spec} when at least one {@code @MeshA2A} surface is registered
     * (spec §2 / §8). No-op when the A2A registry is unavailable or empty —
     * the agent falls back to its existing {@code agent_type} (typically
     * {@code mcp_agent}) and omits the surfaces field on the wire.
     */
    private void applyA2ASurfaces(
            AgentSpec spec,
            ObjectProvider<MeshA2ARegistry> a2aRegistryProvider,
            ObjectMapper objectMapper) {
        MeshA2ARegistry a2aRegistry = a2aRegistryProvider.getIfAvailable();
        if (a2aRegistry == null || !a2aRegistry.hasSurfaces()) {
            return;
        }
        List<Map<String, Object>> heartbeatSurfaces = a2aRegistry.buildHeartbeatSurfaces();
        try {
            String surfacesJson = objectMapper.writeValueAsString(heartbeatSurfaces);
            spec.setSurfaces(surfacesJson);
            spec.setAgentType("a2a");
            // Issue #972: this is the producer-side detection point — same
            // branch that flips agent_type to "a2a" also stamps the
            // self-declared producer flag. Default remains false on the spec.
            spec.setA2aProducer(true);
            log.info("@MeshA2A: {} surface(s) registered — agent_type=a2a, surfaces={}",
                heartbeatSurfaces.size(), surfacesJson);
        } catch (Exception e) {
            log.warn("Failed to serialize @MeshA2A surfaces — leaving agent_type unchanged: {}",
                e.getMessage());
        }
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
            MeshConfigResolver configResolver) {

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

        // Tools populated by finalizeAgentSpec (post-singleton-init).
        spec.setTools(new ArrayList<>());

        log.info("Consumer-only AgentSpec (base): name='{}', agentType='api' "
            + "(route deps populated post-init)", spec.getName());

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
        tools.add(syntheticDepsTool(ROUTE_DEPS_TOOL,
            "Synthetic tool for @MeshRoute dependency resolution", routeDeps));

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
    // Package-private static for tests (issue #1164 MED-1) — no instance state used.
    static void enrichToolsWithLlmProvider(
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

            // Build funcId in the format used by MeshLlmRegistry. Use
            // AopUtils.getTargetClass — the same unwrap MeshLlmBeanPostProcessor
            // applies at registration time — so Spring-proxied beans
            // (@Transactional/@Async/@Validated, runtime class Foo$$SpringCGLIB$$0)
            // still resolve their @MeshLlm config (issue #1164 MED-1).
            String funcId = org.springframework.aop.support.AopUtils.getTargetClass(meta.bean()).getName()
                + "." + meta.method().getName();

            // Look up @MeshLlm config
            MeshLlmRegistry.LlmConfig llmConfig = llmRegistry.getByFunctionId(funcId);
            if (llmConfig == null) {
                // Normal for tools without @MeshLlm; a lookup miss for a method
                // that IS annotated means the registration/lookup keys diverged
                // again — surface it loudly instead of silently skipping.
                if (org.springframework.core.annotation.AnnotationUtils
                        .findAnnotation(meta.method(), io.mcpmesh.MeshLlm.class) != null) {
                    log.warn("@MeshLlm config lookup miss for tool '{}' (funcId={}): the method is "
                        + "annotated but no registered config matched — llm_provider enrichment "
                        + "skipped. Registration/lookup key mismatch; report as a bug.",
                        toolSpec.getCapability(), funcId);
                }
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
     * Register LLM provider tool handlers with the wrapper registry if the
     * spring-ai module is available. Called eagerly from {@link #meshRuntime}
     * so the handlers are visible when {@code mcpStatelessServer} snapshots
     * its tool list at bean-construction time.
     *
     * <p>Uses reflection to avoid a hard dependency on mcp-mesh-spring-ai.
     *
     * @param wrapperRegistry Registry to add LLM provider handlers to
     */
    @SuppressWarnings("unchecked")
    private void registerLlmProviderHandlers(MeshToolWrapperRegistry wrapperRegistry) {
        try {
            Class<?> processorClass = Class.forName("io.mcpmesh.ai.MeshLlmProviderProcessor");
            Object processor = applicationContext.getBean(processorClass);

            java.lang.reflect.Method hasProvidersMethod = processorClass.getMethod("hasProviders");
            Boolean hasProviders = (Boolean) hasProvidersMethod.invoke(processor);
            if (!Boolean.TRUE.equals(hasProviders)) {
                return;
            }

            java.lang.reflect.Method createToolWrappersMethod = processorClass.getMethod("createToolWrappers");
            List<?> wrappers = (List<?>) createToolWrappersMethod.invoke(processor);
            int count = 0;
            for (Object wrapper : wrappers) {
                if (wrapper instanceof McpToolHandler handler) {
                    wrapperRegistry.registerHandler(handler);
                    count++;
                }
            }
            log.info("Registered {} LLM provider tool handler(s) with MCP server", count);
        } catch (ClassNotFoundException e) {
            // mcp-mesh-spring-ai not on classpath - this is fine
            log.debug("MeshLlmProviderProcessor not found - LLM provider support not enabled");
        } catch (org.springframework.beans.factory.NoSuchBeanDefinitionException e) {
            log.debug("MeshLlmProviderProcessor not registered as bean");
        } catch (Exception e) {
            log.warn("Failed to register LLM provider handlers: {}", e.getMessage());
        }
    }

    /**
     * Append LLM provider tool specs to the heartbeat catalog if the
     * spring-ai module is available. Called from {@link #finalizeAgentSpec}
     * after every singleton is initialised. Pairs with
     * {@link #registerLlmProviderHandlers} which performs the eager
     * MCP-handler registration earlier in the lifecycle.
     *
     * @param tools List to add LLM provider tool specs to
     */
    @SuppressWarnings("unchecked")
    private void addLlmProviderToolSpecs(List<AgentSpec.ToolSpec> tools) {
        try {
            Class<?> processorClass = Class.forName("io.mcpmesh.ai.MeshLlmProviderProcessor");
            Object processor = applicationContext.getBean(processorClass);

            java.lang.reflect.Method hasProvidersMethod = processorClass.getMethod("hasProviders");
            Boolean hasProviders = (Boolean) hasProvidersMethod.invoke(processor);
            if (!Boolean.TRUE.equals(hasProviders)) {
                return;
            }

            java.lang.reflect.Method getToolSpecsMethod = processorClass.getMethod("getToolSpecs");
            List<AgentSpec.ToolSpec> llmTools = (List<AgentSpec.ToolSpec>) getToolSpecsMethod.invoke(processor);
            tools.addAll(llmTools);
            log.info("Added {} LLM provider tool spec(s) to agent registration", llmTools.size());
        } catch (ClassNotFoundException e) {
            log.debug("MeshLlmProviderProcessor not found - LLM provider support not enabled");
        } catch (org.springframework.beans.factory.NoSuchBeanDefinitionException e) {
            log.debug("MeshLlmProviderProcessor not registered as bean");
        } catch (Exception e) {
            log.warn("Failed to collect LLM provider tool specs: {}", e.getMessage());
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
