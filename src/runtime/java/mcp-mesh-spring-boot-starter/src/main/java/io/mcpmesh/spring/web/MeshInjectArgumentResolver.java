package io.mcpmesh.spring.web;

import io.mcpmesh.spring.MeshPositionalBinder;
import io.mcpmesh.types.McpMeshTool;
import jakarta.servlet.http.HttpServletRequest;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.core.MethodParameter;
import org.springframework.web.bind.support.WebDataBinderFactory;
import org.springframework.web.context.request.NativeWebRequest;
import org.springframework.web.method.support.HandlerMethodArgumentResolver;
import org.springframework.web.method.support.ModelAndViewContainer;

import java.lang.reflect.Method;
import java.util.Arrays;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

/**
 * Resolves {@link McpMeshTool} controller method parameters for @MeshRoute handlers.
 *
 * <h2>Binding is positional (issue #1401)</h2>
 *
 * <p>The Nth {@code McpMeshTool} parameter, in signature order, receives the Nth
 * entry of {@code dependencies = {...}}. <b>Parameter names are never
 * consulted.</b> This is the same contract as {@code @MeshTool}, and as every
 * Python and TypeScript injection site.
 *
 * <pre>{@code
 * @PostMapping("/process")
 * @MeshRoute(dependencies = {
 *     @MeshDependency(capability = "pdf-tool"),      // -> pdfTool
 *     @MeshDependency(capability = "ocr-service")    // -> ocrService
 * })
 * public ResponseEntity<String> process(
 *         @RequestBody Request request,              // not an injectable slot
 *         McpMeshTool<String> pdfTool,               // slot 0
 *         McpMeshTool<String> ocrService) {          // slot 1
 *
 *     pdfTool.call(Map.of("data", request.getData()));
 * }
 * }</pre>
 *
 * <p>Reordering {@code dependencies = {...}} reorders the parameters it feeds.
 * Renaming a parameter changes nothing.
 *
 * <h2>{@link MeshInject} is an assertion, not a selector</h2>
 *
 * <p>Annotating a parameter {@code @MeshInject("pdf-tool")} does not choose the
 * dependency — position already did. It states which one the author expects, and
 * {@link MeshLegacyBindingDetector} fails the boot if the two disagree. It is
 * optional, costs nothing at request time, and is worth adding to a handler with
 * several same-typed slots.
 *
 * <p>The resolver retrieves dependencies from the positional list request
 * attribute populated by {@link MeshRouteHandlerInterceptor}; capability-keyed
 * access remains available through {@link MeshRouteUtils}.
 */
public class MeshInjectArgumentResolver implements HandlerMethodArgumentResolver {

    private static final Logger log = LoggerFactory.getLogger(MeshInjectArgumentResolver.class);

    /**
     * Per-handler map from signature position to injectable slot ordinal (-1
     * for a parameter that is not a slot). Derived from
     * {@link MeshInjectableSlots#routeSlots}, so it cannot disagree with what
     * the boot-time checks enumerated; cached because Spring MVC calls this
     * resolver once per matching parameter per request.
     */
    private final Map<Method, int[]> slotOrdinals = new ConcurrentHashMap<>();

    @Override
    public boolean supportsParameter(MethodParameter parameter) {
        // Support McpMeshTool parameters - with or without @MeshInject.
        // The predicate lives in MeshInjectableSlots (issue #1401) so the
        // boot-time binding checks classify parameters exactly the way this
        // resolver does, rather than re-deriving the rule.
        return MeshInjectableSlots.isRouteInjectable(parameter.getParameterType());
    }

    @Override
    @SuppressWarnings("unchecked")
    public Object resolveArgument(MethodParameter parameter, ModelAndViewContainer mavContainer,
                                  NativeWebRequest webRequest, WebDataBinderFactory binderFactory) {

        Method method = parameter.getMethod();
        if (method == null) {
            log.error("McpMeshTool injection is only supported on handler METHOD parameters");
            return null;
        }

        // Which injectable slot is this parameter? That ordinal — not the
        // parameter's name — is the declared-dependency index it binds to.
        int ordinal = slotOrdinals
            .computeIfAbsent(method, MeshInjectArgumentResolver::slotOrdinalsOf)
            [parameter.getParameterIndex()];
        if (ordinal < 0) {
            // supportsParameter and MeshInjectableSlots agree by construction,
            // so this is unreachable; fail loudly rather than silently if a
            // future change breaks that.
            log.error("McpMeshTool parameter {} of {} is not an injectable slot",
                parameter.getParameterIndex(), method.getName());
            return null;
        }

        // Get the HttpServletRequest
        HttpServletRequest request = webRequest.getNativeRequest(HttpServletRequest.class);
        if (request == null) {
            log.error("Could not get HttpServletRequest for McpMeshTool resolution");
            return null;
        }

        // Retrieve dependencies from request attributes
        Object depsAttr = request.getAttribute(MeshRouteHandlerInterceptor.MESH_DEPENDENCIES_ATTR);
        if (!(depsAttr instanceof List)) {
            log.debug("No mesh dependencies in request - not a @MeshRoute handler");
            return null;
        }

        List<McpMeshTool> dependencies = (List<McpMeshTool>) depsAttr;
        if (ordinal >= dependencies.size()) {
            log.warn("@MeshRoute {}.{}: parameter {} is injectable slot {}, but only {} "
                    + "dependenc{} declared — injecting null. Declare one @MeshDependency per "
                    + "injectable parameter; dependencies[i] binds to the i-th one.",
                method.getDeclaringClass().getSimpleName(), method.getName(),
                parameter.getParameterIndex(), ordinal, dependencies.size(),
                dependencies.size() == 1 ? "y is" : "ies are");
            return null;
        }

        McpMeshTool tool = dependencies.get(ordinal);
        if (tool == null) {
            log.warn("@MeshRoute {}.{}: dependency at index {} is unavailable — injecting null "
                    + "into parameter {}. Every other parameter keeps its own dependency.",
                method.getDeclaringClass().getSimpleName(), method.getName(), ordinal,
                parameter.getParameterIndex());
        }
        return tool;
    }

    private static int[] slotOrdinalsOf(Method method) {
        int[] ordinals = new int[method.getParameterCount()];
        Arrays.fill(ordinals, -1);
        List<MeshPositionalBinder.Slot> slots = MeshInjectableSlots.routeSlots(method);
        for (int k = 0; k < slots.size(); k++) {
            ordinals[slots.get(k).parameterPosition()] = k;
        }
        return ordinals;
    }
}
