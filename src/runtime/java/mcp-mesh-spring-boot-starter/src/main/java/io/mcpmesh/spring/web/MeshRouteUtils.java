package io.mcpmesh.spring.web;

import io.mcpmesh.types.McpMeshTool;
import jakarta.servlet.http.HttpServletRequest;

import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Utility methods for accessing mesh dependencies in @MeshRoute handlers.
 *
 * <p>This class provides convenient access to dependencies stored in
 * request attributes by {@link MeshRouteHandlerInterceptor}.
 *
 * <h2>Example Usage</h2>
 * <pre>{@code
 * @PostMapping("/process")
 * @MeshRoute(dependencies = {
 *     @MeshDependency(capability = "pdf-tool"),
 *     @MeshDependency(capability = "ocr-service")
 * })
 * public ResponseEntity<String> process(
 *         @RequestBody Request request,
 *         HttpServletRequest httpRequest) {
 *
 *     // Get all dependencies
 *     Map<String, McpMeshTool> deps = MeshRouteUtils.getDependencies(httpRequest);
 *
 *     // Get specific dependency
 *     McpMeshTool pdfTool = MeshRouteUtils.getDependency(httpRequest, "pdf-tool");
 *
 *     // Call the tool
 *     Map<String, Object> result = pdfTool.call(Map.of("data", request.getData()));
 *
 *     return ResponseEntity.ok("Processed");
 * }
 * }</pre>
 */
public final class MeshRouteUtils {

    private MeshRouteUtils() {
        // Utility class
    }

    /**
     * Get all resolved dependencies from the request, keyed by capability.
     *
     * <p><b>This accessor stays capability-keyed under the positional contract
     * (issue #1401), on purpose.</b> Parameter injection is positional because
     * a parameter's name is incidental — nothing ties it to a capability, so
     * matching on it silently misbinds when the declaration list is reordered.
     * Here the capability is typed <i>at the call site</i>
     * ({@code getDependency(request, "pdf-tool")}), so there is no such drift
     * hazard: the caller names the edge it wants and gets exactly that edge or
     * null.
     *
     * <p>The map is rebuilt on each call from the positional list the
     * interceptor stored plus the route metadata, rather than being maintained
     * alongside it — one source of truth, two views. Unavailable dependencies
     * are absent from the map (as before); their slots are null in the
     * positional list.
     *
     * @param request HTTP servlet request
     * @return map of capability name to McpMeshTool, or empty map if no dependencies
     */
    @SuppressWarnings("unchecked")
    public static Map<String, McpMeshTool> getDependencies(HttpServletRequest request) {
        Object attr = request.getAttribute(MeshRouteHandlerInterceptor.MESH_DEPENDENCIES_ATTR);
        if (!(attr instanceof List)) {
            return Collections.emptyMap();
        }
        List<McpMeshTool> resolved = (List<McpMeshTool>) attr;
        MeshRouteRegistry.RouteMetadata metadata = getRouteMetadata(request);
        if (metadata == null) {
            return Collections.emptyMap();
        }
        List<MeshRouteRegistry.DependencySpec> declared = metadata.getDependencies();
        int n = Math.min(resolved.size(), declared.size());

        Map<String, McpMeshTool> byName = new LinkedHashMap<>();
        for (int i = 0; i < n; i++) {
            if (resolved.get(i) != null) {
                byName.put(declared.get(i).getCapability(), resolved.get(i));
            }
        }
        // The @MeshDependency(name = ...) alias is a secondary key, added only
        // where it does not shadow a capability — a capability lookup must
        // never be answered by another dependency's alias.
        for (int i = 0; i < n; i++) {
            String alias = declared.get(i).getParameterName();
            if (resolved.get(i) != null && alias != null && !alias.isEmpty()) {
                byName.putIfAbsent(alias, resolved.get(i));
            }
        }
        return Collections.unmodifiableMap(byName);
    }

    /**
     * Get a resolved dependency by its DECLARATION INDEX — the same index
     * parameter injection uses (issue #1401): index {@code i} is the {@code i}-th
     * entry of {@code dependencies = {...}}.
     *
     * @param request HTTP servlet request
     * @param index   zero-based index into the route's declared dependency list
     * @return the McpMeshTool, or null when the index is out of range or that
     *         dependency is unavailable
     */
    @SuppressWarnings("unchecked")
    public static McpMeshTool getDependency(HttpServletRequest request, int index) {
        Object attr = request.getAttribute(MeshRouteHandlerInterceptor.MESH_DEPENDENCIES_ATTR);
        if (!(attr instanceof List)) {
            return null;
        }
        List<McpMeshTool> resolved = (List<McpMeshTool>) attr;
        if (index < 0 || index >= resolved.size()) {
            return null;
        }
        return resolved.get(index);
    }

    /**
     * Get a specific dependency by capability name.
     *
     * @param request    HTTP servlet request
     * @param capability capability name
     * @return McpMeshTool or null if not found
     */
    public static McpMeshTool getDependency(HttpServletRequest request, String capability) {
        return getDependencies(request).get(capability);
    }

    /**
     * Get a specific dependency by capability name, throwing if not found.
     *
     * @param request    HTTP servlet request
     * @param capability capability name
     * @return McpMeshTool
     * @throws IllegalStateException if dependency not found
     */
    public static McpMeshTool requireDependency(HttpServletRequest request, String capability) {
        McpMeshTool tool = getDependency(request, capability);
        if (tool == null) {
            throw new IllegalStateException(
                "Required dependency '" + capability + "' not found. " +
                "Make sure it's declared in @MeshRoute dependencies.");
        }
        return tool;
    }

    /**
     * Check if a dependency is available.
     *
     * @param request    HTTP servlet request
     * @param capability capability name
     * @return true if dependency exists and is available
     */
    public static boolean hasDependency(HttpServletRequest request, String capability) {
        McpMeshTool tool = getDependency(request, capability);
        return tool != null && tool.isAvailable();
    }

    /**
     * Get the route metadata for the current request.
     *
     * @param request HTTP servlet request
     * @return route metadata or null if not a @MeshRoute
     */
    public static MeshRouteRegistry.RouteMetadata getRouteMetadata(HttpServletRequest request) {
        return (MeshRouteRegistry.RouteMetadata)
            request.getAttribute(MeshRouteHandlerInterceptor.MESH_ROUTE_METADATA_ATTR);
    }
}
