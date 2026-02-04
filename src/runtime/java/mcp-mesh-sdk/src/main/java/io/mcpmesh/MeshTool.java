package io.mcpmesh;

import java.lang.annotation.ElementType;
import java.lang.annotation.Retention;
import java.lang.annotation.RetentionPolicy;
import java.lang.annotation.Target;

/**
 * Marks a method as an MCP Mesh tool/capability.
 *
 * <p>Methods annotated with {@code @MeshTool} are registered as capabilities
 * with the mesh registry and can be called by other agents in the mesh.
 *
 * <h2>Basic Example</h2>
 * <pre>{@code
 * @MeshTool(
 *     capability = "greeting",
 *     description = "Greet a user by name"
 * )
 * public String greet(@Param("name") String name) {
 *     return "Hello, " + name + "!";
 * }
 * }</pre>
 *
 * <h2>With Dependencies</h2>
 * <pre>{@code
 * @MeshTool(
 *     capability = "smart_greeting",
 *     description = "Enhanced greeting with current date",
 *     dependencies = @Selector(capability = "date_service")
 * )
 * public String smartGreet(
 *     @Param("name") String name,
 *     McpMeshTool dateService  // Injected by mesh
 * ) {
 *     if (dateService != null) {
 *         String today = dateService.call("format", "long");
 *         return String.format("Hello, %s! Today is %s", name, today);
 *     }
 *     return String.format("Hello, %s!", name);
 * }
 * }</pre>
 *
 * <h2>With OR Tag Alternatives (Polyglot)</h2>
 * <pre>{@code
 * @MeshTool(
 *     capability = "calculator",
 *     tags = {"math", "calculator"},
 *     dependencies = @Selector(
 *         capability = "math_ops",
 *         tags = {"addition", "(python|+typescript)"}  // Try Python, prefer TypeScript
 *     )
 * )
 * public int calculate(int a, int b, McpMeshTool mathOps) {
 *     return mathOps.call("a", a, "b", b);
 * }
 * }</pre>
 */
@Target(ElementType.METHOD)
@Retention(RetentionPolicy.RUNTIME)
public @interface MeshTool {

    /**
     * Capability name for discovery.
     *
     * <p>This is the name other agents use to find and depend on this tool.
     */
    String capability();

    /**
     * Human-readable description of the tool.
     */
    String description() default "";

    /**
     * Capability version (semver format).
     */
    String version() default "1.0.0";

    /**
     * Tags for filtering.
     *
     * <p>Supports tag operators:
     * <ul>
     *   <li>{@code "tag"} - Required tag</li>
     *   <li>{@code "+tag"} - Preferred tag (bonus score)</li>
     *   <li>{@code "-tag"} - Excluded tag (hard fail)</li>
     *   <li>{@code "(a|b)"} - OR alternatives (try in order)</li>
     *   <li>{@code "(a|+b)"} - OR with preference</li>
     * </ul>
     */
    String[] tags() default {};

    /**
     * Dependencies required by this tool.
     *
     * <p>Each dependency is resolved at runtime and injected as a
     * {@code McpMeshTool} parameter. If a dependency is unavailable,
     * the parameter will be {@code null} (graceful degradation).
     */
    Selector[] dependencies() default {};
}
