package io.mcpmesh.spring.web;

import io.mcpmesh.spring.MeshDependencyInjector;
import io.mcpmesh.spring.tracing.ExecutionTracer;
import io.mcpmesh.spring.tracing.SpanScope;
import io.mcpmesh.types.McpMeshTool;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.http.HttpStatus;
import org.springframework.web.method.HandlerMethod;
import org.springframework.web.servlet.HandlerInterceptor;

import java.util.LinkedHashMap;
import java.util.Map;
import java.util.concurrent.atomic.AtomicReference;

/**
 * Spring MVC interceptor that resolves mesh dependencies for @MeshRoute endpoints.
 *
 * <p>This interceptor runs before controller methods and:
 * <ol>
 *   <li>Detects @MeshRoute annotated handlers</li>
 *   <li>Resolves declared dependencies from the mesh</li>
 *   <li>Stores resolved dependencies in request attributes</li>
 *   <li>Optionally fails the request if dependencies are unavailable</li>
 * </ol>
 *
 * <p>Dependencies can be accessed in controllers via:
 * <ul>
 *   <li>{@link MeshRouteUtils#getDependencies(HttpServletRequest)}</li>
 *   <li>{@link MeshInject} parameter injection</li>
 * </ul>
 */
public class MeshRouteHandlerInterceptor implements HandlerInterceptor {

    private static final Logger log = LoggerFactory.getLogger(MeshRouteHandlerInterceptor.class);

    /**
     * Request attribute key for resolved dependencies map.
     */
    public static final String MESH_DEPENDENCIES_ATTR = "io.mcpmesh.route.dependencies";

    /**
     * Request attribute key for route metadata.
     */
    public static final String MESH_ROUTE_METADATA_ATTR = "io.mcpmesh.route.metadata";

    /**
     * Request attribute key for the span scope (used to close span in afterCompletion).
     */
    public static final String MESH_SPAN_SCOPE_ATTR = "io.mcpmesh.route.spanScope";

    // Tracing support (set lazily via setter, same pattern as MeshToolWrapper)
    private final AtomicReference<ExecutionTracer> tracerRef = new AtomicReference<>();

    private final MeshRouteRegistry registry;
    private final ObjectProvider<MeshDependencyInjector> injectorProvider;

    public MeshRouteHandlerInterceptor(MeshRouteRegistry registry,
                                        ObjectProvider<MeshDependencyInjector> injectorProvider) {
        this.registry = registry;
        this.injectorProvider = injectorProvider;
    }

    /**
     * Set the ExecutionTracer for this interceptor.
     *
     * @param tracer The tracer to use
     */
    public void setTracer(ExecutionTracer tracer) {
        tracerRef.set(tracer);
    }

    private MeshDependencyInjector getInjector() {
        return injectorProvider.getIfAvailable();
    }

    @Override
    public boolean preHandle(HttpServletRequest request, HttpServletResponse response,
                             Object handler) throws Exception {
        if (!(handler instanceof HandlerMethod handlerMethod)) {
            return true;
        }

        // Look up route metadata by handler method
        String handlerMethodId = handlerMethod.getBeanType().getName() + "." +
            handlerMethod.getMethod().getName();
        MeshRouteRegistry.RouteMetadata metadata = registry.getByHandlerMethodId(handlerMethodId);

        if (metadata == null || metadata.getDependencies().isEmpty()) {
            return true;
        }

        // Start tracing span BEFORE dependency resolution
        ExecutionTracer tracer = tracerRef.get();
        SpanScope spanScope = SpanScope.NOOP;
        if (tracer != null) {
            Map<String, Object> spanMetadata = new LinkedHashMap<>();
            spanMetadata.put("handler", handlerMethod.getMethod().getName());
            spanMetadata.put("http_method", request.getMethod());
            spanMetadata.put("path", request.getRequestURI());
            spanMetadata.put("dependency_count", metadata.getDependencies().size());
            spanScope = tracer.startSpan("route:" + handlerMethod.getMethod().getName(), spanMetadata);
        }

        // Store span scope in request for afterCompletion
        request.setAttribute(MESH_SPAN_SCOPE_ATTR, spanScope);

        // Store metadata in request for later access
        request.setAttribute(MESH_ROUTE_METADATA_ATTR, metadata);

        // Resolve dependencies
        Map<String, McpMeshTool> resolvedDeps = new LinkedHashMap<>();
        boolean allResolved = true;

        for (MeshRouteRegistry.DependencySpec dep : metadata.getDependencies()) {
            try {
                McpMeshTool tool = resolveDependency(dep);
                if (tool != null && tool.isAvailable()) {
                    resolvedDeps.put(dep.getCapability(), tool);
                    // Also store by parameter name for @MeshInject
                    resolvedDeps.put(dep.getParameterName(), tool);
                    log.debug("Resolved dependency '{}' for route", dep.getCapability());
                } else {
                    log.warn("Dependency '{}' not available for route {}",
                        dep.getCapability(), handlerMethodId);
                    allResolved = false;
                }
            } catch (Exception e) {
                log.error("Failed to resolve dependency '{}': {}",
                    dep.getCapability(), e.getMessage());
                allResolved = false;
            }
        }

        // Store resolved dependencies in request
        request.setAttribute(MESH_DEPENDENCIES_ATTR, resolvedDeps);

        // Handle missing dependencies
        if (!allResolved && metadata.isFailOnMissingDependency()) {
            log.error("One or more dependencies unavailable for route: {}", handlerMethodId);
            // CRITICAL: Close span before early return — Spring MVC does NOT call
            // afterCompletion when preHandle returns false
            spanScope.withError(new RuntimeException("Dependencies unavailable"));
            spanScope.close();
            request.removeAttribute(MESH_SPAN_SCOPE_ATTR);
            response.setStatus(HttpStatus.SERVICE_UNAVAILABLE.value());
            response.setContentType("application/json");
            response.getWriter().write(
                "{\"error\":\"Service Unavailable\",\"message\":\"Required mesh dependencies are not available\"}");
            return false;
        }

        return true;
    }

    /**
     * Resolve a single dependency from the mesh.
     *
     * <p>This method uses dynamic discovery to find tool endpoints from the
     * registry if they haven't been pre-registered via dependency events.
     *
     * @param dep dependency specification
     * @return resolved McpMeshTool or null if unavailable
     */
    private McpMeshTool resolveDependency(MeshRouteRegistry.DependencySpec dep) {
        MeshDependencyInjector injector = getInjector();
        if (injector == null) {
            log.warn("MeshDependencyInjector not available");
            return null;
        }

        // Get proxy from injector (populated by DEPENDENCY_AVAILABLE events)
        McpMeshTool proxy;
        if (dep.getReturnType() != null) {
            proxy = injector.getToolProxy(dep.getCapability(), dep.getReturnType());
        } else {
            proxy = injector.getToolProxy(dep.getCapability());
        }

        if (proxy == null) {
            return null;
        }

        // Log tag filtering note
        if (dep.hasTags()) {
            // TODO: Implement tag-based resolution in MeshDependencyInjector
            log.debug("Tag filtering not yet implemented, using capability only: {}",
                dep.getCapability());
        }

        return proxy;
    }

    @Override
    public void afterCompletion(HttpServletRequest request, HttpServletResponse response,
                                Object handler, Exception ex) {
        // Close tracing span
        Object spanObj = request.getAttribute(MESH_SPAN_SCOPE_ATTR);
        if (spanObj instanceof SpanScope spanScope) {
            if (ex != null) {
                spanScope.withError(ex);
            }
            spanScope.close();
        }

        // Clean up request attributes
        request.removeAttribute(MESH_DEPENDENCIES_ATTR);
        request.removeAttribute(MESH_ROUTE_METADATA_ATTR);
        request.removeAttribute(MESH_SPAN_SCOPE_ATTR);
    }
}
