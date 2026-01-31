package io.mcpmesh.spring.web;

import io.mcpmesh.types.McpMeshTool;
import jakarta.servlet.http.HttpServletRequest;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.core.MethodParameter;
import org.springframework.web.bind.support.WebDataBinderFactory;
import org.springframework.web.context.request.NativeWebRequest;
import org.springframework.web.method.support.HandlerMethodArgumentResolver;
import org.springframework.web.method.support.ModelAndViewContainer;

import java.util.Map;

/**
 * Resolves {@link McpMeshTool} controller method parameters for @MeshRoute handlers.
 *
 * <p>This argument resolver enables clean dependency injection in two styles:
 *
 * <h3>Style 1: Plain McpMeshTool (recommended, matches @MeshTool pattern)</h3>
 * <pre>{@code
 * @PostMapping("/process")
 * @MeshRoute(dependencies = {
 *     @MeshDependency(capability = "pdf-tool")
 * })
 * public ResponseEntity<String> process(
 *         @RequestBody Request request,
 *         McpMeshTool<String> pdfTool) {  // Matches by parameter name
 *
 *     pdfTool.call(Map.of("data", request.getData()));
 * }
 * }</pre>
 *
 * <h3>Style 2: With @MeshInject annotation (explicit capability)</h3>
 * <pre>{@code
 * @PostMapping("/process")
 * @MeshRoute(dependencies = {
 *     @MeshDependency(capability = "pdf-tool")
 * })
 * public ResponseEntity<String> process(
 *         @RequestBody Request request,
 *         @MeshInject("pdf-tool") McpMeshTool<String> tool) {  // Explicit capability
 *
 *     tool.call(Map.of("data", request.getData()));
 * }
 * }</pre>
 *
 * <p>The resolver retrieves dependencies from request attributes populated
 * by {@link MeshRouteHandlerInterceptor}.
 */
public class MeshInjectArgumentResolver implements HandlerMethodArgumentResolver {

    private static final Logger log = LoggerFactory.getLogger(MeshInjectArgumentResolver.class);

    @Override
    public boolean supportsParameter(MethodParameter parameter) {
        // Support McpMeshTool parameters - with or without @MeshInject
        return McpMeshTool.class.isAssignableFrom(parameter.getParameterType());
    }

    @Override
    @SuppressWarnings("unchecked")
    public Object resolveArgument(MethodParameter parameter, ModelAndViewContainer mavContainer,
                                  NativeWebRequest webRequest, WebDataBinderFactory binderFactory) {

        // Determine capability name from annotation or parameter name
        String capability = null;

        MeshInject annotation = parameter.getParameterAnnotation(MeshInject.class);
        if (annotation != null && !annotation.value().isEmpty()) {
            capability = annotation.value();
        }

        if (capability == null) {
            // Fall back to parameter name (requires -parameters compiler flag)
            capability = parameter.getParameterName();
            if (capability == null) {
                log.error("Cannot determine capability name for McpMeshTool parameter. " +
                    "Either use @MeshInject(\"capability\") or compile with -parameters flag.");
                return null;
            }
        }

        // Get the HttpServletRequest
        HttpServletRequest request = webRequest.getNativeRequest(HttpServletRequest.class);
        if (request == null) {
            log.error("Could not get HttpServletRequest for McpMeshTool resolution");
            return null;
        }

        // Retrieve dependencies from request attributes
        Object depsAttr = request.getAttribute(MeshRouteHandlerInterceptor.MESH_DEPENDENCIES_ATTR);
        if (depsAttr == null) {
            log.debug("No mesh dependencies in request - not a @MeshRoute handler");
            return null;
        }

        Map<String, McpMeshTool> dependencies = (Map<String, McpMeshTool>) depsAttr;

        // Look up by capability name or parameter name
        McpMeshTool tool = dependencies.get(capability);
        if (tool == null) {
            log.warn("Dependency '{}' not found in resolved dependencies. " +
                "Make sure it's declared in @MeshRoute dependencies.", capability);
        }

        return tool;
    }
}
