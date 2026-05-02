package io.mcpmesh.example.schema.producergood;

import jakarta.validation.constraints.NotNull;

/**
 * Canonical Employee shape — must match Python (Pydantic) and TypeScript (Zod)
 * counterparts to produce identical canonical hash:
 * sha256:48882e31915113ed70ee620b2245bfcf856e4e146e2eb6e37700809d7338e732.
 *
 * <p>{@code @NotNull} on String fields aligns nullability with the non-null
 * Python/TS equivalents. {@code double} (primitive) is always required and
 * non-null in the schema generator.
 */
public record Employee(
    @NotNull String name,
    @NotNull String dept,
    double salary
) {}
