package io.mcpmesh;

/**
 * Schema match mode for dependency declarations (issue #547).
 *
 * <p>Determines how a consumer's expected response schema is matched against a
 * producer's published output schema during dependency resolution. Used by both
 * the SDK-level {@link Selector} (inside {@code @MeshTool(dependencies=...)})
 * and the Spring Boot starter's {@code @MeshDependency}.
 *
 * <ul>
 *   <li>{@link #NONE} — no schema check (backward-compatible default)</li>
 *   <li>{@link #SUBSET} — consumer's required fields must be a subset of the
 *       producer's output. Most permissive opt-in.</li>
 *   <li>{@link #STRICT} — full content-hash equality. Fails if the producer
 *       publishes any extra field, or any difference in nullability, types, or
 *       ordering after canonicalization.</li>
 * </ul>
 */
public enum SchemaMode {
    /** No schema check (default). */
    NONE,

    /** Consumer required fields ⊆ producer's output. */
    SUBSET,

    /** Full content-hash equality. */
    STRICT
}
