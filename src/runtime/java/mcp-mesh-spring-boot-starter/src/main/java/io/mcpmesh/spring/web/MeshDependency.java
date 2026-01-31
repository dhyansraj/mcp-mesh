package io.mcpmesh.spring.web;

import java.lang.annotation.Retention;
import java.lang.annotation.RetentionPolicy;
import java.lang.annotation.Target;

/**
 * Specifies a mesh dependency to be injected into a {@link MeshRoute} handler.
 *
 * <p>Each dependency is resolved from the mesh by capability name and optional
 * tags/version constraints.
 *
 * <h2>Example Usage</h2>
 * <pre>{@code
 * @PostMapping("/upload")
 * @MeshRoute(dependencies = {
 *     @MeshDependency(capability = "pdf-tool"),
 *     @MeshDependency(capability = "user-service", tags = {"+v2", "+premium"})
 * })
 * public ResponseEntity<String> upload(...) { ... }
 * }</pre>
 *
 * @see MeshRoute
 * @see MeshInject
 */
@Target({})
@Retention(RetentionPolicy.RUNTIME)
public @interface MeshDependency {

    /**
     * The capability name to resolve from the mesh.
     *
     * @return capability name
     */
    String capability();

    /**
     * Optional tags for filtering available providers.
     *
     * <p>Tags use the mesh tag syntax:
     * <ul>
     *   <li>{@code "+tag"} - require this tag (AND)</li>
     *   <li>{@code "-tag"} - exclude this tag</li>
     *   <li>{@code "tag1|tag2"} - either tag (OR)</li>
     * </ul>
     *
     * @return array of tag filters
     */
    String[] tags() default {};

    /**
     * Optional version constraint for the dependency.
     *
     * <p>Supports semver-style constraints:
     * <ul>
     *   <li>{@code "1.0.0"} - exact version</li>
     *   <li>{@code "^1.0.0"} - compatible with 1.x.x</li>
     *   <li>{@code ">=1.0.0"} - at least version 1.0.0</li>
     * </ul>
     *
     * @return version constraint string
     */
    String version() default "";

    /**
     * Parameter name to inject the dependency as.
     *
     * <p>If empty, defaults to the capability name with hyphens replaced
     * by camelCase (e.g., "pdf-tool" becomes "pdfTool").
     *
     * @return parameter name for injection
     */
    String name() default "";
}
