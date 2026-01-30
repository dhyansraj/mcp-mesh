package io.mcpmesh;

import java.lang.annotation.ElementType;
import java.lang.annotation.Retention;
import java.lang.annotation.RetentionPolicy;
import java.lang.annotation.Target;

/**
 * Marks a method parameter as a tool input.
 *
 * <p>Use this annotation on parameters of methods annotated with {@link MeshTool}
 * to provide metadata for JSON schema generation.
 *
 * <h2>Example</h2>
 * <pre>{@code
 * @MeshTool(capability = "greeting")
 * public String greet(
 *     @Param(value = "name", description = "The person's name") String name,
 *     @Param(value = "formal", required = false) boolean formal
 * ) {
 *     return formal ? "Good day, " + name : "Hi, " + name + "!";
 * }
 * }</pre>
 */
@Target(ElementType.PARAMETER)
@Retention(RetentionPolicy.RUNTIME)
public @interface Param {

    /**
     * Parameter name as it appears in the JSON schema.
     */
    String value();

    /**
     * Human-readable description of the parameter.
     */
    String description() default "";

    /**
     * Whether this parameter is required.
     */
    boolean required() default true;
}
