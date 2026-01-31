package io.mcpmesh.spring.web;

import io.mcpmesh.types.McpMeshTool;
import jakarta.servlet.http.HttpServletRequest;

import java.util.Collections;
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
     * Get all resolved dependencies from the request.
     *
     * @param request HTTP servlet request
     * @return map of capability name to McpMeshTool, or empty map if no dependencies
     */
    @SuppressWarnings("unchecked")
    public static Map<String, McpMeshTool> getDependencies(HttpServletRequest request) {
        Object deps = request.getAttribute(MeshRouteHandlerInterceptor.MESH_DEPENDENCIES_ATTR);
        if (deps instanceof Map) {
            return (Map<String, McpMeshTool>) deps;
        }
        return Collections.emptyMap();
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
