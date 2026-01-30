package io.mcpmesh;

import java.lang.annotation.Retention;
import java.lang.annotation.RetentionPolicy;
import java.lang.annotation.Target;

/**
 * Selector for capabilities in the mesh.
 *
 * <p>Used in {@link MeshTool#dependencies()}, {@link MeshLlm#providerSelector()},
 * and {@link MeshLlm#filter()} to specify which capabilities to resolve.
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
 * }</pre>
 */
@Target({})
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
}
