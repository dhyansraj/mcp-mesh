package io.mcpmesh.spring.web;

import io.mcpmesh.SchemaMode;

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

    /**
     * Whether this route dependency is <b>required</b> (issue #1249).
     *
     * <p>Opt-in strictness, default {@code false} (soft-fail). When
     * {@code true}, the framework's own route wrapper returns HTTP
     * <b>503</b> with body
     * {@code {"error":"dependency_unavailable","capability":"<cap>"}} — before
     * user code runs — whenever this dependency's proxy is unavailable at
     * call time (after the settling window). This is the perimeter backstop:
     * external HTTP callers don't go through mesh proxies, so the required
     * predicate is evaluated at the route boundary from the proxy state the
     * agent already holds locally.
     *
     * <p>Only carried on the wire when {@code true}; {@code false} is omitted
     * from the registration payload.
     *
     * @return true to mark this dependency required (perimeter 503 when
     *         unavailable)
     */
    boolean required() default false;

    /**
     * Optional expected response type for schema-aware capability matching (issue #547).
     *
     * <p>When set together with {@link #schemaMode()}, the resolver filters out
     * candidate producers whose published {@code outputSchema} doesn't satisfy
     * this expected type under the chosen mode. The Java SDK runs this class
     * through victools/jsonschema-generator, normalizes via the Rust normalizer,
     * and ships the canonical schema + hash to the registry.
     *
     * <p>Default {@code Void.class} means "not set" — backward-compatible with
     * existing dependencies that don't opt in to schema matching.
     *
     * <p>Pair with {@link #schemaMode()} = {@link SchemaMode#SUBSET} for most
     * use cases. If {@code expectedType} is set but {@code schemaMode} is
     * {@link SchemaMode#NONE}, the SDK defaults the mode to SUBSET (parity
     * with Python).
     */
    Class<?> expectedType() default Void.class;

    /**
     * Schema match mode (issue #547).
     *
     * <p>{@link SchemaMode#NONE} (default) means no schema check. Pair with
     * {@link #expectedType()} to opt into either {@link SchemaMode#SUBSET} or
     * {@link SchemaMode#STRICT} matching.
     */
    SchemaMode schemaMode() default SchemaMode.NONE;
}
