package io.mcpmesh.spring.web;

import io.mcpmesh.core.MeshObjectMappers;
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
import tools.jackson.databind.ObjectMapper;

import java.util.ArrayList;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
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

    /** Serializes the issue #1249 perimeter 503 body as real JSON (safe for
     * any characters a capability name might carry). */
    private static final ObjectMapper JSON = MeshObjectMappers.create();

    /**
     * Request attribute key for the resolved dependencies.
     *
     * <p><b>The value is a {@code List<McpMeshTool>} positionally aligned with
     * {@code RouteMetadata.getDependencies()}</b> — index {@code i} holds the
     * proxy for declared dependency {@code i}, or {@code null} when that
     * dependency is unavailable. The list is pre-sized to the declared count and
     * assigned by index, never appended to: an unavailable dependency in the
     * middle of the list must leave every later slot where it is (issue #1390,
     * the whole point of #1401's positional contract).
     *
     * <p>Before 3.4 this held a capability-keyed {@code Map}. Code that wants
     * capability-keyed access should call
     * {@link MeshRouteUtils#getDependencies(HttpServletRequest)}, which rebuilds
     * that view from this list plus {@link #MESH_ROUTE_METADATA_ATTR} — one
     * source of truth, two views.
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
    @SuppressWarnings("deprecation")  // getByHandlerMethodId: compatibility fallback only
    public boolean preHandle(HttpServletRequest request, HttpServletResponse response,
                             Object handler) throws Exception {
        if (!(handler instanceof HandlerMethod handlerMethod)) {
            return true;
        }

        // Look up route metadata by the handler METHOD (issue #1437).
        //
        // The method is the handler's identity; "ClassName.methodName" is not —
        // it omits parameter types, so two overloaded @MeshRoute handlers share
        // one id and this lookup served both of them whichever registered last.
        // The injected dependency list is built from what comes back and is
        // POSITIONAL (#1401), so the swap was invisible in the result's shape.
        //
        // The id is kept for log lines below, where the ambiguity is harmless
        // and it reads better than Method.toString().
        //
        // It is built by RouteMetadata's own helper so it matches what
        // registration indexed. Deriving it from the BEAN TYPE instead diverged
        // for a handler inherited from a base class (declaring class = base,
        // bean type = concrete controller) and the fallback silently missed.
        MeshRouteRegistry.RouteMetadata metadata =
            registry.getByHandlerMethod(handlerMethod.getMethod());
        String handlerMethodId = MeshRouteRegistry.RouteMetadata.buildHandlerMethodId(
            handlerMethod.getMethod());
        if (metadata == null) {
            // Compatibility fallback for metadata registered without a Method
            // identity, and for the exotic proxying arrangements where the
            // method Spring MVC resolves is not the one the bean post-processor
            // scanned. Refused by the registry when the id is ambiguous, so it
            // can never resolve one overload to another's dependencies.
            metadata = registry.getByHandlerMethodId(handlerMethodId);
        }

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

        // Resolve dependencies.
        //
        // POSITIONAL (issue #1401): the list is PRE-SIZED to the declared count
        // and null-padded, and every store below is an indexed set(). It is
        // never built with add() — an unavailable dependency must leave its own
        // slot null and every later slot exactly where it is. Appending only
        // the available ones would shift each subsequent parameter onto the
        // wrong proxy, which is the #1390 defect this contract exists to
        // prevent.
        List<MeshRouteRegistry.DependencySpec> declared = metadata.getDependencies();
        List<McpMeshTool> resolvedDeps =
            new ArrayList<>(Collections.nCopies(declared.size(), (McpMeshTool) null));
        boolean allResolved = true;
        // Issue #1249 perimeter: capability of the first UNAVAILABLE dependency
        // declared required=true. When non-null after resolution, the route
        // returns 503 (naming the capability) before user code — regardless of
        // failOnMissingDependency. External HTTP callers don't traverse mesh
        // proxies, so the required predicate is evaluated here at the boundary
        // from the proxy state the agent already holds locally.
        String firstUnavailableRequiredCap = null;

        io.mcpmesh.spring.MeshSettleState settleState =
            io.mcpmesh.spring.MeshSettleState.getInstance();
        for (int depIndex = 0; depIndex < declared.size(); depIndex++) {
            MeshRouteRegistry.DependencySpec dep = declared.get(depIndex);
            try {
                McpMeshTool tool = resolveDependency(dep);
                // Settling-window grace (#1193): while the agent is still
                // settling, block — bounded by the remaining settle budget —
                // on the per-capability latch, then re-resolve. CAPABILITY
                // keying is deliberate (unlike the tool wrappers' per-slot
                // composite keys): routes resolve through the injector's
                // SHARED per-capability proxy, which updateToolDependency
                // makes live BEFORE counting this latch down — a woken
                // request re-reads a live proxy regardless of which
                // consumer's event fired, so there is no wrong-consumer
                // hazard here. Java route proxies typically
                // exist-but-unavailable rather than null, so the wait is
                // keyed on AVAILABILITY. No-op (single latch check) once
                // settled. Blocking is fine on the servlet request thread.
                if ((tool == null || !tool.isAvailable()) && !settleState.isSettled()) {
                    settleState.awaitDependency(dep.getCapability(), dep.getCapability());
                    tool = resolveDependency(dep);
                }
                if (tool != null && tool.isAvailable()) {
                    // Indexed assignment — see the pre-sizing note above.
                    resolvedDeps.set(depIndex, tool);
                    log.debug("Resolved dependency[{}] '{}' for route",
                        depIndex, dep.getCapability());
                } else {
                    log.warn("Dependency '{}' not available for route {}",
                        dep.getCapability(), handlerMethodId);
                    allResolved = false;
                    if (dep.isRequired() && firstUnavailableRequiredCap == null) {
                        firstUnavailableRequiredCap = dep.getCapability();
                    }
                }
            } catch (Exception e) {
                log.error("Failed to resolve dependency '{}': {}",
                    dep.getCapability(), e.getMessage());
                allResolved = false;
                // Fail-closed: a resolution exception on a required dep counts
                // as unavailable and intentionally trips the perimeter 503 —
                // never let a required edge fall through on error.
                if (dep.isRequired() && firstUnavailableRequiredCap == null) {
                    firstUnavailableRequiredCap = dep.getCapability();
                }
            }
        }

        // Store resolved dependencies in request, positionally
        request.setAttribute(MESH_DEPENDENCIES_ATTR, Collections.unmodifiableList(resolvedDeps));

        // Issue #1249 perimeter 503: a dependency declared required=true is
        // unavailable at call time — return 503 with the capability reason
        // BEFORE user code runs. Mirrors the Python route wrapper's
        // {"error":"dependency_unavailable","capability":...} contract and takes
        // precedence over the coarse failOnMissingDependency backstop below.
        if (firstUnavailableRequiredCap != null) {
            log.warn("Route '{}': required dependency '{}' unavailable — returning 503",
                handlerMethodId, firstUnavailableRequiredCap);
            spanScope.withError(new RuntimeException(
                "Required dependency unavailable: " + firstUnavailableRequiredCap));
            spanScope.close();
            request.removeAttribute(MESH_SPAN_SCOPE_ATTR);
            response.setStatus(HttpStatus.SERVICE_UNAVAILABLE.value());
            response.setContentType("application/json");
            // Build the body through Jackson (insertion-ordered map) so a
            // capability name containing e.g. a quote can't corrupt the JSON.
            // Shape is identical to the Python contract:
            //   {"error":"dependency_unavailable","capability":"<cap>"}
            Map<String, String> errorBody = new LinkedHashMap<>();
            errorBody.put("error", "dependency_unavailable");
            errorBody.put("capability", firstUnavailableRequiredCap);
            response.getWriter().write(JSON.writeValueAsString(errorBody));
            return false;
        }

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
