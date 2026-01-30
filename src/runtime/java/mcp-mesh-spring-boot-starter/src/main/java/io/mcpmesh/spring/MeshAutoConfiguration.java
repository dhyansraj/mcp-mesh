package io.mcpmesh.spring;

import com.fasterxml.jackson.databind.ObjectMapper;
import io.mcpmesh.MeshAgent;
import io.mcpmesh.core.AgentSpec;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.autoconfigure.condition.ConditionalOnClass;
import org.springframework.boot.autoconfigure.condition.ConditionalOnMissingBean;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.ApplicationContext;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

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
    public static ObjectMapper meshObjectMapper() {
        return new ObjectMapper();
    }

    @Bean
    @ConditionalOnMissingBean
    public static MeshToolBeanPostProcessor meshToolBeanPostProcessor(
            MeshToolRegistry registry,
            MeshToolWrapperRegistry wrapperRegistry,
            ObjectMapper objectMapper) {
        return new MeshToolBeanPostProcessor(registry, wrapperRegistry, objectMapper);
    }

    @Bean
    @ConditionalOnMissingBean
    public MeshDependencyInjector meshDependencyInjector() {
        return new MeshDependencyInjector();
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
            MeshConfigResolver configResolver) {

        AgentSpec spec = buildAgentSpec(properties, toolRegistry, wrapperRegistry, configResolver);
        log.info("Creating MeshRuntime for agent '{}' with {} tools",
            spec.getName(), spec.getTools().size());

        return new MeshRuntime(spec);
    }

    @Bean
    @ConditionalOnMissingBean
    public MeshEventProcessor meshEventProcessor(
            MeshRuntime runtime,
            MeshDependencyInjector injector,
            MeshToolWrapperRegistry wrapperRegistry) {

        return new MeshEventProcessor(runtime, injector, wrapperRegistry);
    }

    private AgentSpec buildAgentSpec(
            MeshProperties properties,
            MeshToolRegistry toolRegistry,
            MeshToolWrapperRegistry wrapperRegistry,
            MeshConfigResolver configResolver) {

        // Find @MeshAgent annotation
        MeshAgent agentAnnotation = findMeshAgentAnnotation();

        AgentSpec spec = new AgentSpec();

        // Resolve name (required) - use new API with correct Rust key names
        String annotationName = agentAnnotation != null ? agentAnnotation.name() : null;
        String propertiesName = properties.getAgent().getName();
        String paramName = (annotationName != null && !annotationName.isBlank()) ? annotationName : propertiesName;
        String name = configResolver.resolve("agent_name", paramName);
        if (name == null || name.isBlank()) {
            throw new IllegalStateException(
                "Agent name is required. Set MCP_MESH_AGENT_NAME, mesh.agent.name, or @MeshAgent(name=...)");
        }
        // Append UUID suffix like Python/TypeScript SDKs: {name}-{8char_uuid}
        String uuidSuffix = UUID.randomUUID().toString().replace("-", "").substring(0, 8);
        String agentId = name + "-" + uuidSuffix;
        spec.setName(agentId);

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
        spec.setHttpPort(configResolver.resolveInt("http_port", paramPort > 0 ? paramPort : -1));

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

        // Add tools from registry (dependencies are embedded in tool specs)
        List<AgentSpec.ToolSpec> allTools = new ArrayList<>(toolRegistry.getToolSpecs());

        // Add LLM provider tools if mcp-mesh-spring-ai is on classpath
        addLlmProviderTools(allTools, wrapperRegistry);

        spec.setTools(allTools);

        return spec;
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
