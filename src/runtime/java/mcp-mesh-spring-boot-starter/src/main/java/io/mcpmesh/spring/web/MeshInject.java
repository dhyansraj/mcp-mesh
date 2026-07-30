package io.mcpmesh.spring.web;

import java.lang.annotation.Documented;
import java.lang.annotation.ElementType;
import java.lang.annotation.Retention;
import java.lang.annotation.RetentionPolicy;
import java.lang.annotation.Target;

/**
 * Asserts which mesh dependency a handler parameter is expected to receive.
 *
 * <p><b>{@code @MeshInject} no longer selects a dependency; it asserts the one
 * positional pairing assigns</b> (issue #1401). Dependencies bind by position at
 * every mesh injection site: the Nth declared {@code @MeshDependency} /
 * {@code @Selector} goes to the Nth injectable parameter in signature order, and
 * parameter names are never consulted. This annotation states which capability
 * the author believes lands on a parameter, and the framework <b>fails the
 * boot</b> if position says otherwise.
 *
 * <p>It is optional. Adding it to a correctly-ordered handler changes nothing at
 * runtime and costs nothing per request; removing it changes nothing either.
 * Its value is as a safety net on handlers with several same-typed slots, where
 * an accidental reorder is otherwise type-compatible and silent.
 *
 * <h2>Example Usage</h2>
 * <pre>{@code
 * @PostMapping("/process")
 * @MeshRoute(dependencies = {
 *     @MeshDependency(capability = "pdf-tool"),      // slot 0
 *     @MeshDependency(capability = "ocr-service")    // slot 1
 * })
 * public ResponseEntity<Result> processDocument(
 *         @RequestBody DocumentRequest request,               // not a slot
 *         @MeshInject("pdf-tool") McpMeshTool pdfTool,        // slot 0 — asserted
 *         @MeshInject("ocr-service") McpMeshTool ocrService) { // slot 1 — asserted
 *
 *     // Use the injected tools directly
 *     Map<String, Object> text = pdfTool.call(Map.of("url", request.getUrl()));
 *     Map<String, Object> extracted = ocrService.call(Map.of("image", text.get("image")));
 *
 *     return ResponseEntity.ok(new Result(extracted));
 * }
 * }</pre>
 *
 * <p>Swapping the two {@code @MeshInject} values without swapping the
 * {@code @MeshDependency} entries no longer swaps the proxies — it fails
 * startup, naming both orderings.
 *
 * <h2>Where it applies</h2>
 *
 * <p>{@code @MeshRoute}, {@code @MeshA2A} and {@code @MeshTool}, with the same
 * meaning at all three. On the {@code @MeshA2A} path the annotation additionally
 * marks a parameter as a dependency slot even when its type is not
 * {@link io.mcpmesh.types.McpMeshTool} — the dispatcher owns the whole argument
 * array there, so the annotation is an unambiguous statement of intent.
 *
 * <h2>Type Requirements</h2>
 *
 * <p>On {@code @MeshRoute} and {@code @MeshTool} the parameter type must be
 * assignable from {@link io.mcpmesh.types.McpMeshTool}.
 *
 * @see MeshRoute
 * @see MeshDependency
 */
@Target(ElementType.PARAMETER)
@Retention(RetentionPolicy.RUNTIME)
@Documented
public @interface MeshInject {

    /**
     * The capability this parameter is expected to receive.
     *
     * <p>Must name the dependency that positional pairing assigns to this
     * parameter — the declared entry at the parameter's injectable-slot index.
     * The {@link MeshDependency#name()} alias of that same entry is accepted as
     * a second spelling. Anything else fails startup.
     *
     * <p>Empty (the default) asserts nothing; the parameter still binds by
     * position.
     *
     * @return capability name
     */
    String value() default "";
}
