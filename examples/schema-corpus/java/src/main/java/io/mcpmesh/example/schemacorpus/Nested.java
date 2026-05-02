package io.mcpmesh.example.schemacorpus;

import jakarta.validation.constraints.NotNull;

/**
 * Pattern 5: Nested — Employee inside Nested.
 *
 * <p>The normalizer inlines {@code $ref} bodies so nested-model shapes converge
 * across runtimes (Pydantic uses {@code $defs}, Zod inlines, Jackson uses
 * {@code $defs}).
 */
public record Nested(@NotNull Employee employee) {

    public record Employee(@NotNull String name, @NotNull String dept) {}
}
