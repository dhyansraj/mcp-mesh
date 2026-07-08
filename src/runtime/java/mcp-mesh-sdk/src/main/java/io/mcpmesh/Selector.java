package io.mcpmesh;

import java.lang.annotation.ElementType;
import java.lang.annotation.Retention;
import java.lang.annotation.RetentionPolicy;
import java.lang.annotation.Target;

/**
 * Selector for capabilities in the mesh.
 *
 * <p>Used in {@link MeshTool#dependencies()}, {@link MeshLlm#providerSelector()},
 * and {@link MeshLlm#filter()} to specify which capabilities to resolve.
 *
 * <p>Also usable directly on an abstract method of a {@link MeshService}
 * interface (service views): the method binds the one capability named here,
 * and calling it delegates to that capability's resolved proxy. The nested
 * member usage inside the annotations above remains valid.
 *
 * <h2>Tag Syntax</h2>
 * <pre>
 * Syntax          Meaning                         Example
 * ──────────────────────────────────────────────────────────────────
 * tag             Required                        "api"
 * +tag            Preferred (bonus score)         "+fast"
 * -tag            Excluded (hard fail)            "-deprecated"
 * (a|b)           OR alternatives (try in order)  "(python|typescript)"
 * (a|+b)          OR with preference              "(python|+typescript)"
 * </pre>
 *
 * <h2>Schema-Aware Matching (issue #547)</h2>
 *
 * <p>Schema-aware capability matching is an opt-in: leave {@link #expectedType()}
 * at its default ({@code Void.class}) and {@link #schemaMode()} at
 * {@link SchemaMode#NONE} to keep the legacy capability-only behavior. Set
 * {@code expectedType} (and optionally {@code schemaMode}) to filter producers
 * whose published output schema doesn't match the consumer's expected response.
 *
 * <h2>Examples</h2>
 * <pre>{@code
 * // Simple dependency
 * @Selector(capability = "date_service")
 *
 * // With required tag
 * @Selector(capability = "weather_data", tags = {"api"})
 *
 * // With preferences and exclusions
 * @Selector(
 *     capability = "weather_data",
 *     tags = {"api", "+accurate", "-deprecated"}
 * )
 *
 * // With OR alternatives (polyglot)
 * @Selector(
 *     capability = "math_ops",
 *     tags = {"addition", "(python|+typescript)"}
 * )
 *
 * // With version constraint
 * @Selector(
 *     capability = "api_client",
 *     version = ">=2.0.0"
 * )
 *
 * // With schema-aware matching (issue #547)
 * @Selector(
 *     capability = "user_lookup",
 *     expectedType = UserDto.class,
 *     schemaMode = SchemaMode.SUBSET
 * )
 * }</pre>
 */
@Target({ElementType.METHOD})
@Retention(RetentionPolicy.RUNTIME)
public @interface Selector {

    /**
     * Capability name to match.
     */
    String capability() default "";

    /**
     * Tag filters with operators.
     *
     * <p>Supports:
     * <ul>
     *   <li>{@code "tag"} - Required</li>
     *   <li>{@code "+tag"} - Preferred</li>
     *   <li>{@code "-tag"} - Excluded</li>
     *   <li>{@code "(a|b)"} - OR alternatives</li>
     * </ul>
     */
    String[] tags() default {};

    /**
     * Version constraint (e.g., ">=2.0.0").
     */
    String version() default "";

    /**
     * Whether this dependency edge is <b>required</b> (issue #1249).
     *
     * <p>Opt-in strictness, default {@code false} (soft-fail: an unresolved
     * dependency injects a {@code null}/unavailable proxy and the agent still
     * starts and registers). When {@code true}, the registry factors this edge
     * into transitive capability availability — the depending capability is
     * marked unavailable (and that unavailability propagates to <i>its</i>
     * consumers through the existing dependency-update channel) whenever this
     * required dependency's capability is unavailable.
     *
     * <p>Only carried on the wire when {@code true}; {@code false} is omitted
     * from the registration payload to match the optional-field style of
     * {@link #version()}.
     *
     * <p><b>Scope:</b> meaningful only where a {@code Selector} declares a
     * dependency edge (e.g. {@link MeshTool#dependencies()}). It is IGNORED on
     * {@code @MeshLlm} {@code providerSelector} / {@code filter} selectors —
     * those pick an LLM provider / tool-filter set, not a mesh dependency
     * edge, so there is no availability predicate to feed.
     */
    boolean required() default false;

    /**
     * Optional expected response type for schema-aware capability matching (issue #547).
     *
     * <p>Pair with {@link #schemaMode()}. The Java consumer's expected type is
     * normalized via the Rust schema normalizer; only producers whose canonical
     * output schema matches under the chosen mode are wired.
     *
     * <p>Default {@code Void.class} means "not set" — backward-compatible with
     * existing selectors that don't opt in to schema matching.
     */
    Class<?> expectedType() default Void.class;

    /**
     * Schema match mode (issue #547). {@link SchemaMode#NONE} = no schema check
     * (current default). {@link SchemaMode#SUBSET} = consumer's required fields
     * ⊆ producer's output (default when {@code expectedType} is set without an
     * explicit mode). {@link SchemaMode#STRICT} = full hash equality.
     */
    SchemaMode schemaMode() default SchemaMode.NONE;
}
