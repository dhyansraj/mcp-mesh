package io.mcpmesh.spring.web;

import java.lang.annotation.Documented;
import java.lang.annotation.ElementType;
import java.lang.annotation.Retention;
import java.lang.annotation.RetentionPolicy;
import java.lang.annotation.Target;

/**
 * Marks a Spring MVC controller method as a mesh-enabled route with
 * automatic dependency injection of MCP agents.
 *
 * <p>This annotation is the Spring equivalent of Python's {@code @mesh.route}
 * decorator. It enables automatic injection of {@link io.mcpmesh.types.McpMeshTool}
 * proxies into controller methods based on declared dependencies.
 *
 * <h2>Example Usage</h2>
 *
 * <h3>With request attribute access:</h3>
 * <pre>{@code
 * @RestController
 * @RequestMapping("/api")
 * public class ResumeController {
 *
 *     @PostMapping("/upload")
 *     @MeshRoute(dependencies = {
 *         @MeshDependency(capability = "pdf-tool"),
 *         @MeshDependency(capability = "user-service", tags = {"+v2"})
 *     })
 *     public ResponseEntity<String> uploadResume(
 *             @RequestParam("file") MultipartFile file,
 *             HttpServletRequest request) {
 *
 *         Map<String, McpMeshTool> deps = MeshRouteUtils.getDependencies(request);
 *         McpMeshTool pdfTool = deps.get("pdf-tool");
 *
 *         Map<String, Object> result = pdfTool.call(Map.of("content", file.getBytes()));
 *         return ResponseEntity.ok("Processed");
 *     }
 * }
 * }</pre>
 *
 * <h3>With @MeshInject parameter injection:</h3>
 * <pre>{@code
 * @PostMapping("/upload")
 * @MeshRoute(dependencies = {
 *     @MeshDependency(capability = "pdf-tool"),
 *     @MeshDependency(capability = "user-service")
 * })
 * public ResponseEntity<String> uploadResume(
 *         @RequestParam("file") MultipartFile file,
 *         @MeshInject("pdf-tool") McpMeshTool pdfTool,
 *         @MeshInject("user-service") McpMeshTool userService) {
 *
 *     Map<String, Object> result = pdfTool.call(Map.of("content", file.getBytes()));
 *     return ResponseEntity.ok("Processed");
 * }
 * }</pre>
 *
 * <h2>Dependency Resolution</h2>
 *
 * <p>Dependencies are resolved at request time from the mesh registry.
 * If a dependency is unavailable, the proxy will throw an exception
 * when called (fail-fast behavior).
 *
 * <h2>Tracing Integration</h2>
 *
 * <p>When tracing is enabled, routes annotated with {@code @MeshRoute}
 * automatically participate in distributed tracing. Trace context is
 * extracted from incoming request headers and propagated to downstream
 * agent calls.
 *
 * @see MeshDependency
 * @see MeshInject
 * @see MeshRouteUtils
 */
@Target(ElementType.METHOD)
@Retention(RetentionPolicy.RUNTIME)
@Documented
public @interface MeshRoute {

    /**
     * Dependencies to inject into this route.
     *
     * <p>Each dependency is resolved from the mesh by capability.
     * Dependencies are made available via request attributes or
     * {@link MeshInject} parameter injection.
     *
     * @return array of mesh dependencies
     */
    MeshDependency[] dependencies() default {};

    /**
     * Optional description for documentation and debugging.
     *
     * @return route description
     */
    String description() default "";

    /**
     * Whether to fail the request if any dependency is unavailable.
     *
     * <p>If {@code true} (default), the request will return 503 Service
     * Unavailable if any declared dependency cannot be resolved.
     *
     * <p>If {@code false}, the route will execute with unavailable
     * dependencies set to {@code null}.
     *
     * @return true to fail on missing dependencies
     */
    boolean failOnMissingDependency() default true;
}
