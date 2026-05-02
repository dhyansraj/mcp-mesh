package io.mcpmesh.example.schemacorpus;

import jakarta.validation.constraints.NotNull;

/**
 * Pattern 1: Primitives — string + int + bool + double.
 *
 * <p>{@code @NotNull} on String aligns nullability with Pydantic's {@code id: str}
 * (non-Optional). Java primitives are always required and non-null in the
 * schema generator (see {@code MeshSchemaSupport.withRequiredCheck}).
 */
public record Primitives(
    @NotNull String id,
    int age,
    boolean active,
    double score
) {}
