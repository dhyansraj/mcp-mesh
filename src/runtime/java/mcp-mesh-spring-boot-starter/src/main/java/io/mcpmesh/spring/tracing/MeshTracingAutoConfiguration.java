package io.mcpmesh.spring.tracing;

import com.fasterxml.jackson.databind.ObjectMapper;
import io.mcpmesh.spring.McpToolHandler;
import io.mcpmesh.spring.MeshRuntime;
import io.mcpmesh.spring.MeshToolWrapper;
import io.mcpmesh.spring.MeshToolWrapperRegistry;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.autoconfigure.condition.ConditionalOnMissingBean;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.boot.web.servlet.FilterRegistrationBean;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.core.Ordered;

import jakarta.annotation.PostConstruct;
import jakarta.annotation.PreDestroy;

/**
 * Auto-configuration for MCP Mesh distributed tracing.
 *
 * <p>This configuration is enabled when:
 * <ul>
 *   <li>{@code MCP_MESH_DISTRIBUTED_TRACING_ENABLED=true} environment variable is set, OR</li>
 *   <li>{@code mcp.mesh.distributed-tracing-enabled=true} property is set</li>
 * </ul>
 *
 * <p>Components configured:
 * <ul>
 *   <li>{@link TracePublisher} - Async Redis publishing via Rust FFI</li>
 *   <li>{@link AgentContextProvider} - Agent metadata for traces</li>
 *   <li>{@link ExecutionTracer} - Span lifecycle management</li>
 *   <li>{@link TracingFilter} - HTTP header extraction</li>
 * </ul>
 */
@Configuration
@ConditionalOnProperty(
    name = "mcp.mesh.distributed-tracing-enabled",
    havingValue = "true",
    matchIfMissing = false
)
public class MeshTracingAutoConfiguration {

    private static final Logger log = LoggerFactory.getLogger(MeshTracingAutoConfiguration.class);

    @Autowired
    private ObjectProvider<MeshToolWrapperRegistry> wrapperRegistryProvider;

    private TracePublisher tracePublisher;

    @PostConstruct
    public void init() {
        log.info("MCP Mesh distributed tracing: ENABLED");
    }

    @Bean
    @ConditionalOnMissingBean
    public TracePublisher tracePublisher(ObjectMapper objectMapper) {
        this.tracePublisher = new TracePublisher(objectMapper);
        return tracePublisher;
    }

    @Bean
    @ConditionalOnMissingBean
    public AgentContextProvider agentContextProvider(ObjectProvider<MeshRuntime> runtimeProvider) {
        MeshRuntime runtime = runtimeProvider.getIfAvailable();

        String agentId = "unknown";
        String agentName = "unknown";
        String hostname = null;
        int port = 8080;
        String namespace = "default";

        if (runtime != null && runtime.getAgentSpec() != null) {
            // Agent ID is assigned by registry at runtime, use name as initial ID
            agentName = runtime.getAgentSpec().getName();
            agentId = agentName;  // Will be updated when registration event is received
            port = runtime.getAgentSpec().getHttpPort();
            // Get namespace from spec if available
            if (runtime.getAgentSpec().getNamespace() != null) {
                namespace = runtime.getAgentSpec().getNamespace();
            }
        }

        // Try to get from environment
        String envHost = System.getenv("MCP_MESH_HTTP_HOST");
        if (envHost != null && !envHost.isEmpty()) {
            hostname = envHost;
        }
        String envNamespace = System.getenv("MCP_MESH_NAMESPACE");
        if (envNamespace != null && !envNamespace.isEmpty()) {
            namespace = envNamespace;
        }

        return new AgentContextProvider(agentId, agentName, hostname, port, namespace);
    }

    @Bean
    @ConditionalOnMissingBean
    public ExecutionTracer executionTracer(
            TracePublisher publisher,
            AgentContextProvider contextProvider) {
        ExecutionTracer tracer = new ExecutionTracer(publisher, contextProvider);

        // Wire tracer into all existing wrappers
        MeshToolWrapperRegistry registry = wrapperRegistryProvider.getIfAvailable();
        if (registry != null) {
            wireTracerToWrappers(tracer, registry);
        }

        return tracer;
    }

    /**
     * Wire the ExecutionTracer to all registered handlers.
     *
     * <p>This wires tracers to both MeshToolWrapper and LlmProviderToolWrapper instances.
     * Uses reflection for LlmProviderToolWrapper to avoid compile-time dependency on spring-ai.
     */
    private void wireTracerToWrappers(ExecutionTracer tracer, MeshToolWrapperRegistry registry) {
        // Wire to MeshToolWrapper instances
        for (MeshToolWrapper wrapper : registry.getAllWrappers()) {
            wrapper.setTracer(tracer);
            log.debug("Wired tracer to wrapper: {}", wrapper.getFuncId());
        }

        // Wire to other handlers (e.g., LlmProviderToolWrapper) via reflection
        for (McpToolHandler handler : registry.getAllHandlers()) {
            if (handler instanceof MeshToolWrapper) {
                continue; // Already handled above
            }

            // Try to call setTracer via reflection (for LlmProviderToolWrapper)
            try {
                var method = handler.getClass().getMethod("setTracer", ExecutionTracer.class);
                method.invoke(handler, tracer);
                log.debug("Wired tracer to handler: {}", handler.getFuncId());
            } catch (NoSuchMethodException e) {
                // Handler doesn't support tracing, skip
                log.trace("Handler {} doesn't support tracing", handler.getFuncId());
            } catch (Exception e) {
                log.warn("Failed to wire tracer to handler {}: {}", handler.getFuncId(), e.getMessage());
            }
        }
    }

    @Bean
    public FilterRegistrationBean<TracingFilter> tracingFilterRegistration() {
        FilterRegistrationBean<TracingFilter> registration = new FilterRegistrationBean<>();
        registration.setFilter(new TracingFilter());
        registration.addUrlPatterns("/*");
        registration.setOrder(Ordered.HIGHEST_PRECEDENCE);
        registration.setName("meshTracingFilter");
        return registration;
    }

    @PreDestroy
    public void shutdown() {
        if (tracePublisher != null) {
            log.debug("Shutting down TracePublisher");
            tracePublisher.shutdown();
        }
    }
}
