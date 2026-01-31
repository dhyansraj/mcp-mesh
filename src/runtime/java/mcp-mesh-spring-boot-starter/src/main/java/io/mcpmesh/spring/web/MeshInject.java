package io.mcpmesh.spring.web;

import java.lang.annotation.Documented;
import java.lang.annotation.ElementType;
import java.lang.annotation.Retention;
import java.lang.annotation.RetentionPolicy;
import java.lang.annotation.Target;

/**
 * Injects a mesh dependency directly into a controller method parameter.
 *
 * <p>This annotation provides a cleaner alternative to accessing dependencies
 * via request attributes. It works in conjunction with {@link MeshRoute} to
 * inject resolved {@link io.mcpmesh.types.McpMeshTool} proxies.
 *
 * <h2>Example Usage</h2>
 * <pre>{@code
 * @PostMapping("/process")
 * @MeshRoute(dependencies = {
 *     @MeshDependency(capability = "pdf-tool"),
 *     @MeshDependency(capability = "ocr-service")
 * })
 * public ResponseEntity<Result> processDocument(
 *         @RequestBody DocumentRequest request,
 *         @MeshInject("pdf-tool") McpMeshTool pdfTool,
 *         @MeshInject("ocr-service") McpMeshTool ocrService) {
 *
 *     // Use the injected tools directly
 *     Map<String, Object> text = pdfTool.call(Map.of("url", request.getUrl()));
 *     Map<String, Object> extracted = ocrService.call(Map.of("image", text.get("image")));
 *
 *     return ResponseEntity.ok(new Result(extracted));
 * }
 * }</pre>
 *
 * <h2>Parameter Naming</h2>
 *
 * <p>The {@link #value()} specifies which capability to inject. This must
 * match a capability declared in the method's {@link MeshRoute#dependencies()}.
 *
 * <p>If {@code value} is empty, the parameter name is used as the capability
 * name (requires compilation with {@code -parameters} flag).
 *
 * <h2>Type Requirements</h2>
 *
 * <p>The parameter type must be assignable from {@link io.mcpmesh.types.McpMeshTool}.
 *
 * @see MeshRoute
 * @see MeshDependency
 */
@Target(ElementType.PARAMETER)
@Retention(RetentionPolicy.RUNTIME)
@Documented
public @interface MeshInject {

    /**
     * The capability name to inject.
     *
     * <p>Must match a capability declared in {@link MeshRoute#dependencies()}.
     * If empty, the parameter name is used.
     *
     * @return capability name
     */
    String value() default "";
}
