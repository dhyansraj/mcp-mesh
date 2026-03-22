package io.mcpmesh;

import java.lang.annotation.ElementType;
import java.lang.annotation.Retention;
import java.lang.annotation.RetentionPolicy;
import java.lang.annotation.Target;

/**
 * Marks a tool parameter as accepting media URIs.
 *
 * <p>When used alongside {@link Param}, this annotation adds {@code x-media-type}
 * to the parameter's JSON schema, enabling LLMs to pass media URIs through
 * multi-agent call chains.
 *
 * <p>Usage:
 * <pre>{@code
 * @MeshTool(capability = "analyzer")
 * public String analyze(
 *     @Param("question") String question,
 *     @MediaParam("image/*") @Param("image") String imageUri
 * ) {
 *     // imageUri is a media URI string (file://, s3://, etc.)
 * }
 * }</pre>
 *
 * @see Param
 */
@Target(ElementType.PARAMETER)
@Retention(RetentionPolicy.RUNTIME)
public @interface MediaParam {
    /**
     * MIME type pattern that this parameter accepts.
     * Examples: "image/*", "application/pdf", "*&#47;*"
     */
    String value() default "*/*";
}
